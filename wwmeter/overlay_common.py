"""What the overlay does that needs no window toolkit: shared by the WebView2 overlay
(``overlay_webview2``) and the Qt one (``overlay``), and testable without either.

- ``HotkeySet``: the system-wide keys, held only while the game is in front.
- ``Controls``: what each hotkey and tray menu entry does, and the tray menu itself as plain
  ``Item``s that each overlay draws its own way.
- Where the game is, whether it is in front, whether a place is on a screen.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field

from . import config as config_mod
from . import hotkeys as hotkey_names

BASE_SIZE = (424, 380)  # UI at zoom 1.0, in pixels
HIDE_AFTER = 1.0  # seconds the game must be out of focus before the overlay hides
WM_HOTKEY = 0x0312
_MOD_NOREPEAT = 0x4000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# The hint is an element of its own, not ``.meter::after``: the themes draw with that (the wuwa
# theme's diamond), and the hint was squeezed into it, out of sight.
MOVE_STYLE = """
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


def move_script(cfg: config_mod.Config, moving: bool) -> str:
    """The page's move-mode look: on or off, with the key that locks the meter again."""
    lock_key = hotkey_names.bindings(cfg.hotkeys)["move"]
    lock_hint = f"{lock_key} locks it." if lock_key else "Lock it from the tray menu."
    return MOVE_STYLE.replace("__LOCK__", lock_hint) % ("true" if moving else "false")


def process_name(hwnd: int) -> str:
    """Executable name of the process owning a window, lower case. '' when it can't be read.

    Only ever called for the foreground window when that window is not the game.
    """
    import win32process

    kernel32 = ctypes.windll.kernel32
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
    except Exception:  # noqa: BLE001 - window vanished between calls
        return ""
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = ctypes.wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return os.path.basename(buffer.value).lower()
    finally:
        kernel32.CloseHandle(handle)


def game_in_front(cfg: config_mod.Config, own: int) -> bool:
    """True while the game, the overlay (window ``own``; 0 when the overlay's own window never
    counts) or a screenshot tool has focus."""
    import win32gui

    from .capture import find_game_window

    game = find_game_window()
    if game is None:
        return False
    foreground = win32gui.GetForegroundWindow()
    if not foreground:  # nothing in front (focus changing, the lock screen): not the game
        return False
    if foreground in (game, own):
        return True
    # Taking a screenshot moves focus to the snipping tool; the overlay has to stay up for that
    # or it would vanish from every screenshot.
    tools = {str(name).lower() for name in cfg.capture_tools or ()}
    return process_name(foreground) in tools


def screens() -> list[tuple[int, int, int, int]]:
    """Every monitor's rectangle (left, top, right, bottom), in screen pixels."""
    import win32api

    return [tuple(rect) for _, _, rect in win32api.EnumDisplayMonitors()]


def on_a_screen(x: int, y: int, width: int, height: int,
                rects: list[tuple[int, int, int, int]] | None = None) -> bool:
    """True when enough of a window there is on some screen to see it and get hold of it."""
    for left, top, right, bottom in rects if rects is not None else screens():
        seen_w = min(right, x + width) - max(left, x)
        seen_h = min(bottom, y + height) - max(top, y)
        if seen_w >= 80 and seen_h >= 40:
            return True
    return False


def default_position() -> tuple[int, int]:
    """Left of the game's picture, a little below its middle; or a fixed place without a game."""
    from .capture import client_rect_on_screen, find_game_window

    hwnd = find_game_window()
    if hwnd is None:
        return 40, 400
    left, top, _, bottom = client_rect_on_screen(hwnd)
    return left + 28, top + round((bottom - top) * 0.42)


class HotkeySet:
    """System-wide hotkeys, held only while the game is in front.

    A registered hotkey is taken from every other program, and the defaults are function keys,
    so they are given back the moment the game loses focus: Alt+F8 in a browser stays Alt+F8.
    ``hwnd`` is the window WM_HOTKEY goes to; None sends it to the thread's queue.
    """

    def __init__(
        self, keys: dict[str, str], dispatch: Callable[[str], None],
        on_taken: Callable[[list[str]], None] | None = None, hwnd: int | None = None, user32=None,
    ) -> None:
        self._dispatch = dispatch
        self._on_taken = on_taken  # told which keys another program is holding
        self._hwnd = hwnd
        self._user32 = user32 if user32 is not None else ctypes.windll.user32
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
                if self._user32.RegisterHotKey(self._hwnd, hotkey_id, modifiers | _MOD_NOREPEAT, key):
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
                self._user32.UnregisterHotKey(self._hwnd, hotkey_id)
            self._held = []

    def handle(self, hotkey_id: int) -> bool:
        """Do what a WM_HOTKEY with this ID asks. False when it isn't one of these keys."""
        if hotkey_id not in self._keys:
            return False
        self._dispatch(self._keys[hotkey_id][2])
        return True


@dataclass
class Item:
    """One tray menu entry. No text and no action: a separator."""

    text: str = ""
    action: Callable[[], None] | None = None
    key: str = ""  # its hotkey, shown beside it
    checked: bool | None = None  # None: not a tick box
    enabled: bool = True
    children: Callable[[], list[Item]] | None = None  # a submenu, made when it opens
    radio: bool = False  # ticked as one of a group (the themes)

    @property
    def separator(self) -> bool:
        return not self.text and self.action is None and self.children is None


@dataclass
class Controls:
    """What the hotkeys and the tray menu do. ``overlay`` has ``moving``, ``set_moving(bool)``,
    ``toggle_wanted()`` and ``set_hidden_from_capture(bool)``; ``notify(text, ms)`` shows a tray
    message; ``quit()`` ends the meter."""

    cfg: config_mod.Config
    overlay: object
    notify: Callable[[str, int], None]
    quit: Callable[[], None]
    on_reset: Callable[[], None]
    dashboard_url: str
    on_view: Callable[[int], None] | None = None
    on_copy: Callable[[], None] | None = None
    list_sessions: Callable[[], list[dict]] | None = None
    open_session: Callable[[str | None], None] | None = None
    update_finished: Callable[[], str | None] | None = None
    app_actions: dict | None = None
    themes: Callable[[], list[str]] = field(default=lambda: [])
    theme_label: Callable[[str], str] = field(default=lambda name: name)

    def _save(self) -> None:
        config_mod.save(self.cfg)

    def dispatch(self, action: str) -> None:
        cfg = self.cfg
        if action == "move":
            self.overlay.set_moving(not self.overlay.moving)
        elif action == "toggle":
            self.overlay.toggle_wanted()
        elif action == "reset":
            self.on_reset()
        elif action in ("older", "newer"):
            if self.on_view is not None:
                self.on_view(-1 if action == "older" else 1)
        elif action == "copy":
            if self.on_copy is not None:
                self.on_copy()
        elif action == "compact":
            cfg.compact = not cfg.compact
            self._save()
        elif action == "rest":
            cfg.hide_between_fights = not cfg.hide_between_fights
            self._save()
        elif action == "unit":
            cfg.display_unit = "damage" if cfg.display_unit == "percent" else "percent"
            self._save()
        elif action == "hints":
            cfg.show_keys = not cfg.show_keys
            self._save()
        elif action == "capture":
            self.overlay.set_hidden_from_capture(not cfg.hide_from_capture)
            self.notify(
                "Overlay is now hidden from screenshots and streams."
                if cfg.hide_from_capture
                else "Overlay now shows up in screenshots and streams.",
                2500,
            )

    def pick_theme(self, name: str) -> None:
        self.cfg.theme = name
        self._save()

    def update_app(self) -> None:
        actions = self.app_actions
        text = actions["install"]() if actions["available"]() else actions["check"]()
        self.notify(text, 6000)

    def poll(self) -> None:
        """Run every half second: say what an update of the tables or of Waveband ended with."""
        ended = self.update_finished() if self.update_finished is not None else None
        if ended:
            self.notify(ended, 8000)
        if self.app_actions is not None:
            said = self.app_actions["said"]()
            if said:
                self.notify(said, 8000)

    def items(self) -> list[Item]:
        """The tray menu as it is now: ticks and keys as set this moment.

        Kept short (owner, 2026-11-18). What it leaves out has a hotkey (showing or hiding the
        meter, damage or percent, a new fight, the fight before or after, the one-line meter,
        moving it) or a place in the dashboard (What changed; Settings, The game, Update boss
        HP tables). Moving is listed when it has no key, or to lock it again: without a key it
        could not be reached at all.
        """
        cfg = self.cfg
        keys = hotkey_names.bindings(cfg.hotkeys)

        def entry(text: str, action: str, checked: bool | None = None) -> Item:
            return Item(text, lambda: self.dispatch(action), keys.get(action, ""), checked)

        menu = [entry("Copy this fight's summary", "copy")]
        if self.list_sessions is not None and self.open_session is not None:
            menu.append(Item("Earlier sessions", children=self._sessions))
        menu += [
            Item(),
            entry("Hide the meter between fights", "rest", bool(cfg.hide_between_fights)),
            entry("Hide from screenshots and streams", "capture", bool(cfg.hide_from_capture)),
            entry("Show the keybinds on the meter", "hints", bool(cfg.show_keys)),
        ]
        if self.overlay.moving or not keys.get("move"):
            menu.append(entry("Move or resize the overlay", "move", bool(self.overlay.moving)))
        menu += [
            Item("Theme", children=lambda: [
                Item(self.theme_label(name), lambda chosen=name: self.pick_theme(chosen),
                     checked=name == cfg.theme, radio=True)
                for name in self.themes()
            ]),
            Item(),
            Item("Open the dashboard in a browser", lambda: webbrowser.open(self.dashboard_url)),
            Item("Settings: keybinds, colours, log folder",
                 lambda: webbrowser.open(self.dashboard_url + "#settings")),
        ]
        if self.app_actions is not None:
            newest = self.app_actions["available"]()
            menu.append(Item(f"Install update ({newest})" if newest else "Check for Waveband updates",
                             self.update_app))
        menu += [Item(), Item("Quit", self.quit)]
        return menu

    def _sessions(self) -> list[Item]:
        found = self.list_sessions()
        items = [Item("Back to this session", lambda: self.open_session(None)), Item()]
        for item in found[:15]:
            count = f"{item['fights']} fight" + ("" if item["fights"] == 1 else "s")
            text = f"{item['label']}  ({count}, last: {item['last']})"
            items.append(Item(text, lambda chosen=item["file"]: self.open_session(chosen)))
        if not found:
            items.append(Item("None yet", enabled=False))
        return items
