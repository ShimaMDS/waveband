"""The in-game overlay: a transparent, click-through, always-on-top window showing the web UI.

It never takes focus and passes every click to whatever is underneath. "Move mode" (tray menu or
its hotkey, F11 unless changed) makes it grabbable: drag to move, scroll to resize, then lock it
again.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import time
import webbrowser
from collections.abc import Callable

import win32gui
import win32process
from PySide6.QtCore import QAbstractNativeEventFilter, QEvent, QObject, QPoint, QRect, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import __version__
from . import config as config_mod
from . import hotkeys as hotkey_names
from .capture import client_rect_on_screen, find_game_window, set_dpi_aware
from .settings import ZOOM, available_themes, theme_label

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_WDA_NONE = 0x0
_WDA_EXCLUDEFROMCAPTURE = 0x11
_WM_HOTKEY = 0x0312
_MOD_NOREPEAT = 0x4000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_BASE_SIZE = (424, 380)  # UI at zoom 1.0, in pixels
_HIDE_AFTER = 1.0  # seconds the game must be out of focus before the overlay hides
# The hint is an element of its own, not ``.meter::after``: the themes draw with that (the wuwa
# theme's diamond), and the hint was squeezed into it, out of sight.
_MOVE_STYLE = """
(() => {
  let s = document.getElementById('move-style');
  if (!s) {
    s = document.createElement('style');
    s.id = 'move-style';
    s.textContent = `body.moving .meter{outline:2px dashed #f2b544;outline-offset:2px;cursor:move}
      #move-hint{display:none}
      body.moving #move-hint{display:block;padding:6px 12px 8px;font-size:.84rem;color:#f2b544;
      border-top:1px solid rgba(236,230,216,.12);text-transform:none;letter-spacing:normal}`;
    document.head.appendChild(s);
  }
  const meter = document.querySelector('.meter');
  let hint = document.getElementById('move-hint');
  if (meter && !hint) {
    hint = document.createElement('div');
    hint.id = 'move-hint';
    meter.appendChild(hint);
  }
  if (hint) hint.textContent = 'Drag to move. Scroll to resize. __LOCK__';
  document.body.classList.toggle('moving', %s);
})();
"""


def _process_name(hwnd: int) -> str:
    """Executable name of the process owning a window, lower case. '' when it can't be read.

    Only ever called for the foreground window when that window is not the game.
    """
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
    except Exception:  # noqa: BLE001 - window vanished between calls
        return ""
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = ctypes.wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return os.path.basename(buffer.value).lower()
    finally:
        _kernel32.CloseHandle(handle)


class _HotkeyFilter(QAbstractNativeEventFilter):
    """System-wide hotkeys, held only while the game is in front.

    A registered hotkey is taken from every other program, and the defaults are bare function
    keys, so they are given back the moment the game loses focus: F9 in a browser stays F9.
    """

    def __init__(
        self, keys: dict[str, str], dispatch: Callable[[str], None],
        on_taken: Callable[[list[str]], None] | None = None,
    ) -> None:
        super().__init__()
        self._dispatch = dispatch
        self._on_taken = on_taken  # told which keys another program is holding
        self._keys: dict[int, tuple[int, int, str]] = {}  # hotkey ID -> (modifiers, key, action)
        self._names: dict[int, str] = {}  # hotkey ID -> the key as written, "F9"
        self._held: list[int] = []
        self._active = False  # whether the keys are wanted now: the game is in front
        self._load(keys)

    def _load(self, keys: dict[str, str]) -> None:
        self._keys, self._names = {}, {}
        for hotkey_id, (action, name) in enumerate(keys.items(), start=1):
            parsed = hotkey_names.parse(name)
            if parsed is not None:
                self._keys[hotkey_id] = (*parsed, action)
                self._names[hotkey_id] = name

    def rebind(self, keys: dict[str, str]) -> None:
        """Other keys, chosen on the settings page while the meter runs."""
        active = self._active
        self.set_active(False)
        self._load(keys)
        if self._on_taken is not None:
            self._on_taken([])  # what was said about the old keys no longer holds
        self.set_active(active)

    def set_active(self, active: bool) -> None:
        self._active = active
        if active == bool(self._held) or not self._keys:
            return
        if active:
            refused = []
            for hotkey_id, (modifiers, key, _) in self._keys.items():
                if _user32.RegisterHotKey(None, hotkey_id, modifiers | _MOD_NOREPEAT, key):
                    self._held.append(hotkey_id)
                else:
                    refused.append(self._names[hotkey_id])
            # A key Windows will not give is one another program holds. It would do nothing
            # here and say nothing, so the meter is told and says it.
            if self._on_taken is not None:
                self._on_taken(refused)
            if not self._held:
                self._keys = {}  # every key is taken by another program: stop retrying
        else:
            for hotkey_id in self._held:
                _user32.UnregisterHotKey(None, hotkey_id)
            self._held = []

    def nativeEventFilter(self, event_type, message):  # noqa: N802 - Qt naming
        if event_type == b"windows_generic_MSG":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == _WM_HOTKEY and msg.wParam in self._keys:
                self._dispatch(self._keys[msg.wParam][2])
                return True, 0
        return False, 0


class _DragFilter(QObject):
    """Turns a press anywhere on the page into a native window move while in move mode."""

    def __init__(self, window: "OverlayWindow") -> None:
        super().__init__(window)
        self._window = window

    def eventFilter(self, _obj, event):  # noqa: N802 - Qt naming
        if not self._window.moving:
            return False
        kind = event.type()
        if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None:
                handle.startSystemMove()
            return True
        if kind == QEvent.Wheel:
            self._window.nudge_zoom(0.05 if event.angleDelta().y() > 0 else -0.05)
            return True
        return False


class OverlayWindow(QWebEngineView):
    def __init__(self, url: str, cfg: config_mod.Config) -> None:
        super().__init__()
        self._cfg = cfg
        self.moving = False
        self.on_front: Callable[[bool], None] | None = None  # told whether the game is in front
        self._wanted = True  # user's show/hide choice
        self._last_in_front = time.monotonic()
        self._zoom = self._zoom_wanted()
        # the settings this window was last made to match; see take_settings
        self._placed = (cfg.overlay_x, cfg.overlay_y, cfg.overlay_zoom)
        self._hidden_from_capture = cfg.hide_from_capture
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.page().setBackgroundColor(Qt.transparent)
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self._drag = _DragFilter(self)
        self.loadFinished.connect(self._on_loaded)
        self._apply_flags()
        self._apply_geometry(initial=True)
        self.setUrl(QUrl(url))

        self._watch = QTimer(self)
        self._watch.timeout.connect(self._follow_game)
        self._watch.start(250)

    # -- window plumbing ----------------------------------------------------------------------

    def _apply_flags(self) -> None:
        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        if not self.moving:
            flags |= Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
        self.setWindowFlags(flags)

    def _apply_affinity(self) -> None:
        self._hidden_from_capture = bool(self._cfg.hide_from_capture)
        affinity = _WDA_EXCLUDEFROMCAPTURE if self._hidden_from_capture else _WDA_NONE
        _user32.SetWindowDisplayAffinity(int(self.winId()), affinity)

    def _zoom_wanted(self) -> float:
        try:
            return max(ZOOM[0], min(ZOOM[1], float(self._cfg.overlay_zoom)))
        except (TypeError, ValueError):
            return 1.0

    def _move_script(self) -> str:
        lock_key = hotkey_names.bindings(self._cfg.hotkeys)["move"]
        lock_hint = f"{lock_key} locks it." if lock_key else "Lock it from the tray menu."
        return _MOVE_STYLE.replace("__LOCK__", lock_hint) % ("true" if self.moving else "false")

    def _apply_geometry(self, initial: bool = False) -> None:
        """Size the window for its zoom. ``initial`` also puts it where the settings say."""
        width, height = (round(v * self._zoom) for v in _BASE_SIZE)
        self.setZoomFactor(self._zoom)
        if initial:
            x, y = self._cfg.overlay_x, self._cfg.overlay_y
            # Settings brought from another PC, or a monitor since unplugged, can name a place
            # no screen shows. The meter would be running and nowhere to be seen.
            if not isinstance(x, int) or not isinstance(y, int) or not _on_a_screen(x, y, width, height):
                x, y = self._default_position()
            self.setGeometry(x, y, width, height)
        else:
            self.resize(width, height)

    @staticmethod
    def _default_position() -> tuple[int, int]:
        hwnd = find_game_window()
        if hwnd is None:
            return 40, 400
        left, top, _, bottom = client_rect_on_screen(hwnd)
        return left + 28, top + round((bottom - top) * 0.42)

    def _on_loaded(self, _ok: bool) -> None:
        proxy = self.focusProxy()
        if proxy is not None:
            proxy.installEventFilter(self._drag)
        self.setZoomFactor(self._zoom)
        self.page().runJavaScript(self._move_script())

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        self._apply_affinity()

    # -- behaviour ----------------------------------------------------------------------------

    def _game_in_front(self) -> bool:
        """True while the game, this overlay or a screenshot tool has focus."""
        game = find_game_window()
        if game is None:
            return False
        foreground = win32gui.GetForegroundWindow()
        if foreground in (game, int(self.winId())):
            return True
        # Taking a screenshot moves focus to the snipping tool; the overlay has to stay up for
        # that or it would vanish from every screenshot.
        if not foreground:
            return False
        tools = {str(name).lower() for name in self._cfg.capture_tools or ()}
        return _process_name(foreground) in tools

    def _follow_game(self) -> None:
        """Show only over the game, with a short grace so brief focus changes don't flicker."""
        now = time.monotonic()
        in_front = self.moving or self._game_in_front()
        if self.on_front is not None:
            self.on_front(in_front)
        if in_front or not self._cfg.only_over_game:
            self._last_in_front = now
        should_show = self._wanted and now - self._last_in_front < _HIDE_AFTER
        if should_show != self.isVisible():
            self.setVisible(should_show)

    def nudge_zoom(self, delta: float) -> None:
        self._zoom = max(ZOOM[0], min(ZOOM[1], round(self._zoom + delta, 2)))
        self._apply_geometry()

    def take_settings(self) -> None:
        """Match settings changed somewhere else while running: the settings page can change
        the size and whether screenshots show the meter, and a line of settings brought from
        another PC can move it."""
        if self._hidden_from_capture != bool(self._cfg.hide_from_capture):
            self._apply_affinity()
        placed = (self._cfg.overlay_x, self._cfg.overlay_y, self._cfg.overlay_zoom)
        if self.moving or placed == self._placed:
            return
        self._placed = placed
        self._zoom = self._zoom_wanted()
        self._apply_geometry(initial=True)

    def set_moving(self, moving: bool) -> None:
        if moving == self.moving:
            return
        self.moving = moving
        position = self.pos()
        self._apply_flags()  # changing flags hides the window and recreates its handle
        self.move(position)
        self.show()
        if moving:
            self.raise_()
        else:
            self._save_placement()
        self.page().runJavaScript(self._move_script())

    def toggle_wanted(self) -> None:
        self._wanted = not self._wanted
        self._follow_game()

    def set_hidden_from_capture(self, hidden: bool) -> None:
        self._cfg.hide_from_capture = hidden
        self._apply_affinity()
        config_mod.save(self._cfg)

    def _save_placement(self) -> None:
        position: QPoint = self.pos()
        self._cfg.overlay_x, self._cfg.overlay_y = position.x(), position.y()
        self._cfg.overlay_zoom = self._zoom
        self._placed = (self._cfg.overlay_x, self._cfg.overlay_y, self._cfg.overlay_zoom)
        config_mod.save(self._cfg)


def _on_a_screen(x: int, y: int, width: int, height: int) -> bool:
    """True when enough of a window there is on some screen to see it and get hold of it."""
    window = QRect(x, y, width, height)
    for screen in QGuiApplication.screens():
        seen = screen.geometry().intersected(window)
        if seen.width() >= 80 and seen.height() >= 40:
            return True
    return False


def _tray_icon() -> QIcon:
    """Waveband's icon (``ui/waveband.png``, drawn by ``tools/make_logo.py``), or a plain one
    drawn here when the file is missing."""
    drawn = os.path.join(config_mod.ROOT, "ui", "waveband.png")
    if os.path.isfile(drawn):
        icon = QIcon(drawn)
        if not icon.isNull():
            return icon
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#0e1118"))
    painter.drawRoundedRect(2, 2, 60, 60, 12, 12)
    painter.setBrush(QColor("#f2b544"))
    for i, half in enumerate((8, 18, 26, 14, 22, 10)):
        painter.drawRect(11 + i * 8, 32 - half, 5, half * 2)
    painter.end()
    return QIcon(pixmap)


def run(
    url: str, cfg: config_mod.Config, on_reset: Callable[[], None], dashboard_url: str,
    on_view: Callable[[int], None] | None = None,
    on_copy: Callable[[], None] | None = None,
    on_keys_taken: Callable[[list[str]], None] | None = None,
    list_sessions: Callable[[], list[dict]] | None = None,
    open_session: Callable[[str | None], None] | None = None,
    update_tables: Callable[[], str] | None = None,
    update_finished: Callable[[], str | None] | None = None,
    app_actions: dict | None = None,
) -> int:
    """Show the overlay and block until the user quits from the tray menu. ``on_view`` steps
    to the fight before (-1) or after (+1) the one on show, ``on_copy`` puts its summary on the
    clipboard, and ``on_keys_taken`` is told which hotkeys another program is holding.
    ``list_sessions`` gives the earlier sessions and ``open_session`` puts one on show (None:
    back to this one). ``update_tables`` starts an update of the boss HP tables and says what to
    tell the user; ``update_finished`` gives, once, what the last update ended with."""
    set_dpi_aware()
    app = QApplication.instance() or QApplication([config_mod.NAME])
    app.setQuitOnLastWindowClosed(False)
    window = OverlayWindow(url, cfg)
    window.show()

    def dispatch(action: str) -> None:
        if action == "move":
            window.set_moving(not window.moving)
            move_action.setChecked(window.moving)
        elif action == "toggle":
            window.toggle_wanted()
        elif action == "reset":
            on_reset()
        elif action in ("older", "newer"):
            if on_view is not None:
                on_view(-1 if action == "older" else 1)
        elif action == "copy":
            if on_copy is not None:
                on_copy()
        elif action == "compact":
            cfg.compact = not cfg.compact
            config_mod.save(cfg)
            compact_action.setChecked(cfg.compact)
        elif action == "rest":
            cfg.hide_between_fights = not cfg.hide_between_fights
            config_mod.save(cfg)
            rest_action.setChecked(cfg.hide_between_fights)
        elif action == "unit":
            cfg.display_unit = "damage" if cfg.display_unit == "percent" else "percent"
            config_mod.save(cfg)
            unit_action.setChecked(cfg.display_unit == "percent")
        elif action == "hints":
            cfg.show_keys = not cfg.show_keys
            config_mod.save(cfg)
            hints_action.setChecked(cfg.show_keys)
        elif action == "capture":
            window.set_hidden_from_capture(not cfg.hide_from_capture)
            capture_action.setChecked(cfg.hide_from_capture)
            tray.showMessage(
                config_mod.NAME,
                "Overlay is now hidden from screenshots and streams."
                if cfg.hide_from_capture
                else "Overlay now shows up in screenshots and streams.",
                QSystemTrayIcon.Information,
                2500,
            )

    keys = hotkey_names.bindings(cfg.hotkeys)
    with_key: list[tuple[QAction, str, str]] = []  # menu entries that name their hotkey

    def labelled(text: str, action: str) -> str:
        return f"{text}\t{keys[action]}" if keys[action] else text

    def entry(text: str, action: str, checked: bool | None = None) -> QAction:
        """A menu entry for one of the meter's actions, with its key beside it."""
        item = QAction(labelled(text, action), menu)
        if checked is not None:
            item.setCheckable(True)
            item.setChecked(checked)
        item.triggered.connect(lambda _checked=False: dispatch(action))
        menu.addAction(item)
        with_key.append((item, text, action))
        return item

    app.setWindowIcon(_tray_icon())
    tray = QSystemTrayIcon(_tray_icon(), app)
    tray.setToolTip(f"{config_mod.NAME} {__version__}")
    menu = QMenu()
    entry("Show or hide the overlay", "toggle")
    unit_action = entry("Show percent of HP instead of damage", "unit", cfg.display_unit == "percent")
    entry("Start a new fight", "reset")
    entry("Show the fight before this one", "older")
    entry("Show the fight after this one", "newer")
    entry("Copy this fight's summary", "copy")
    if list_sessions is not None and open_session is not None:
        # Filled in each time it is opened: sessions are files, and one is added per launch.
        session_menu = menu.addMenu("Earlier sessions")

        def fill_sessions() -> None:
            session_menu.clear()
            session_menu.addAction("Back to this session", lambda: open_session(None))
            session_menu.addSeparator()
            found = list_sessions()
            for item in found[:15]:
                count = f"{item['fights']} fight" + ("" if item["fights"] == 1 else "s")
                text = f"{item['label']}  ({count}, last: {item['last']})"
                session_menu.addAction(text, lambda chosen=item["file"]: open_session(chosen))
            if not found:
                session_menu.addAction("None yet").setEnabled(False)

        session_menu.aboutToShow.connect(fill_sessions)
    menu.addSeparator()
    compact_action = entry("One-line meter", "compact", cfg.compact)
    rest_action = entry("Hide the meter between fights", "rest", cfg.hide_between_fights)
    move_action = entry("Move or resize the overlay", "move", False)
    capture_action = entry("Hide from screenshots and streams", "capture", cfg.hide_from_capture)
    hints_action = entry("Show the keybinds on the meter", "hints", cfg.show_keys)
    theme_menu = menu.addMenu("Theme")
    theme_actions = {}

    def pick_theme(name: str) -> None:
        cfg.theme = name
        config_mod.save(cfg)
        for other, action in theme_actions.items():
            action.setChecked(other == name)

    for name in available_themes():
        action = QAction(theme_label(name), theme_menu, checkable=True)
        action.setChecked(name == cfg.theme)
        action.triggered.connect(lambda _checked=False, chosen=name: pick_theme(chosen))
        theme_menu.addAction(action)
        theme_actions[name] = action
    menu.addSeparator()
    menu.addAction("Open the dashboard in a browser", lambda: webbrowser.open(dashboard_url))
    menu.addAction(
        "Settings: keybinds, colours, log folder", lambda: webbrowser.open(dashboard_url + "#settings")
    )
    menu.addAction("What changed", lambda: webbrowser.open(dashboard_url + "#changes"))
    if update_tables is not None:

        def start_update() -> None:
            tray.showMessage(config_mod.NAME, update_tables(), QSystemTrayIcon.Information, 6000)

        menu.addAction("Update boss HP tables (after a game patch)", start_update)
    app_entry = None
    if app_actions is not None:
        app_actions["set_quit"](app.quit)

        def app_update() -> None:
            text = app_actions["install"]() if app_actions["available"]() else app_actions["check"]()
            tray.showMessage(config_mod.NAME, text, QSystemTrayIcon.Information, 6000)

        app_entry = menu.addAction("Check for Waveband updates", app_update)
    menu.addSeparator()
    menu.addAction("Quit", app.quit)
    tray.setContextMenu(menu)
    tray.show()

    hotkeys = _HotkeyFilter(keys, dispatch, on_keys_taken)
    app.installNativeEventFilter(hotkeys)
    window.on_front = hotkeys.set_active  # the hotkeys exist only while the game is in front

    def take_settings() -> None:
        """Match settings changed on the settings page, which runs in a browser and has only
        the settings themselves to change: the keys, the ticks in this menu, the window."""
        nonlocal keys
        wanted = hotkey_names.bindings(cfg.hotkeys)
        if wanted != keys:
            keys = wanted
            hotkeys.rebind(keys)
            for item, text, action in with_key:
                item.setText(labelled(text, action))
        unit_action.setChecked(cfg.display_unit == "percent")
        compact_action.setChecked(bool(cfg.compact))
        rest_action.setChecked(bool(cfg.hide_between_fights))
        capture_action.setChecked(bool(cfg.hide_from_capture))
        hints_action.setChecked(bool(cfg.show_keys))
        for name, action in theme_actions.items():
            action.setChecked(name == cfg.theme)
        window.take_settings()
        ended = update_finished() if update_finished is not None else None
        if ended:
            tray.showMessage(config_mod.NAME, ended, QSystemTrayIcon.Information, 8000)
        if app_actions is not None:
            newest = app_actions["available"]()
            app_entry.setText(f"Install update ({newest})" if newest else "Check for Waveband updates")
            news_line = app_actions["said"]()
            if news_line:
                tray.showMessage(config_mod.NAME, news_line, QSystemTrayIcon.Information, 8000)

    settings_watch = QTimer(app)
    settings_watch.timeout.connect(take_settings)
    settings_watch.start(500)

    try:
        return app.exec()
    finally:
        settings_watch.stop()
        hotkeys.set_active(False)
        tray.hide()
