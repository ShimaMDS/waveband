"""The in-game overlay on WebView2, the web view Windows 10 and 11 already have (from 0.3.2).

A window with no frame, always on top, never taking focus, passing every click through, that
shows the web UI with the page's own transparency. "Move mode" (tray menu or its hotkey, Alt+F11
unless changed) makes it grabbable: drag to move, scroll to resize, then lock it again. The
tray icon and its menu are Windows' own (pywin32). Up to 0.3.1 Qt drew all of this.

How it is drawn: WebView2 in *visual hosting*. The window has no redirection surface
(``WS_EX_NOREDIRECTIONBITMAP``) and gets a DirectComposition visual tree; WebView2 draws into a
visual in it (``ICoreWebView2CompositionController``) over a transparent default background,
so every pixel's alpha reaches the screen. Clicks pass through because the window is
``WS_EX_LAYERED | WS_EX_TRANSPARENT``; WebView2 in visual hosting gets no mouse input unless the
host forwards it, and the meter never needs it to. ``tools\\webview2_overlay.py`` measures
all of this.

``run`` raises ``Unavailable`` when WebView2 can't be used here (no runtime, no loader, or it
failed to start), before or after showing anything; the caller then says so and stops.
"""

from __future__ import annotations

import ctypes
import os
import tempfile
import time
import traceback
from collections.abc import Callable
from ctypes import HRESULT, wintypes

from . import __version__
from . import config as config_mod
from . import hotkeys as hotkey_names
from .capture import set_dpi_aware
from .overlay_common import (
    BASE_SIZE, HIDE_AFTER, Controls, HotkeySet, Item, default_position, from_qt_pixels, game_in_front,
    move_script, on_a_screen,
)
from .settings import ZOOM, available_themes, theme_label

LOADER = os.path.join(config_mod.ROOT, "lib", "webview2", "WebView2Loader.dll")
RUNTIME_DOWNLOAD = "https://developer.microsoft.com/microsoft-edge/webview2/"


class Unavailable(RuntimeError):
    """WebView2 can't show the overlay on this PC; the message says why."""


# -- Win32 ----------------------------------------------------------------------------------------

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON),
    ]


_user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.DefWindowProcW.restype = LRESULT
_user32.RegisterClassExW.argtypes = [ctypes.POINTER(_WNDCLASSEXW)]
_user32.RegisterClassExW.restype = wintypes.ATOM
_user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, wintypes.UINT]
_user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
_user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
_user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
_user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
_user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
_user32.SetTimer.restype = ctypes.c_size_t
_user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
_user32.GetDpiForWindow.argtypes = [wintypes.HWND]
_user32.GetDpiForWindow.restype = wintypes.UINT
_user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
_user32.LoadCursorW.restype = wintypes.HANDLE
_user32.SetCursor.argtypes = [wintypes.HANDLE]
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.ChangeWindowMessageFilterEx.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.DWORD, ctypes.c_void_p]
_user32.CheckMenuRadioItem.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT, wintypes.UINT, wintypes.UINT]
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE

WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOREDIRECTIONBITMAP = 0x00200000
WS_EX_NOACTIVATE = 0x08000000
GWL_EXSTYLE = -20
LWA_ALPHA = 0x2
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
HWND_TOPMOST = wintypes.HWND(-1)
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x1, 0x2, 0x4, 0x10, 0x20
WM_DESTROY, WM_CLOSE, WM_SETCURSOR, WM_NCHITTEST = 0x0002, 0x0010, 0x0020, 0x0084
WM_TIMER, WM_MOUSEWHEEL, WM_EXITSIZEMOVE, WM_DPICHANGED = 0x0113, 0x020A, 0x0232, 0x02E0
WM_HOTKEY, WM_NULL, WM_APP, WM_QUIT = 0x0312, 0x0000, 0x8000, 0x0012
PM_REMOVE = 0x1
WM_TRAY = WM_APP + 1  # the tray icon's messages
WM_LBUTTONUP, WM_RBUTTONUP, WM_CONTEXTMENU = 0x0202, 0x0205, 0x007B
HTCAPTION, HTTRANSPARENT = 2, -1
IDC_SIZEALL = 32646
WDA_NONE, WDA_EXCLUDEFROMCAPTURE = 0x0, 0x11
MSGFLT_ALLOW = 1
MF_BYCOMMAND = 0x0
TIMER_FOLLOW, TIMER_SETTINGS, TIMER_RELOAD, TIMER_RESTART = 1, 2, 3, 4
RELOAD_AFTER = 2000  # ms before a page that would not load is asked for again
RESTART_AFTER = 500  # ms before WebView2 is started again after its browser process ended
RESTARTS_A_MINUTE = 3  # more than this and it is said and the meter stops
# ICoreWebView2ProcessFailedEventArgs.ProcessFailedKind (COREWEBVIEW2_PROCESS_FAILED_KIND)
PROCESS_FAILED_BROWSER, PROCESS_FAILED_RENDERER, PROCESS_FAILED_UNRESPONSIVE = 0, 1, 2
CLASS_NAME = "WavebandOverlay"


_WINDOWS: dict[int, "OverlayWindow"] = {}  # live overlay windows by handle


def _dispatch(hwnd, msg, wparam, lparam):
    """The class's one window procedure. A class keeps the procedure it was registered with, so
    each window's own is looked up here (messages before it is known go to DefWindowProc)."""
    window = _WINDOWS.get(hwnd)
    if window is None:
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)
    return window._wndproc(hwnd, msg, wparam, lparam)


_PROC = WNDPROC(_dispatch)  # kept for the life of the process: Windows calls it


def _register_class() -> None:
    instance = _kernel32.GetModuleHandleW(None)
    cls = _WNDCLASSEXW(cbSize=ctypes.sizeof(_WNDCLASSEXW), lpfnWndProc=_PROC,
                       hInstance=instance, lpszClassName=CLASS_NAME)
    if not _user32.RegisterClassExW(ctypes.byref(cls)) and ctypes.get_last_error() != 1410:
        # 1410: ERROR_CLASS_ALREADY_EXISTS, from an earlier window: it has the same procedure
        raise Unavailable(f"the overlay's window class: {ctypes.WinError(ctypes.get_last_error())}")


def _hresult(value) -> int:
    """An HRESULT handed to a callback, as an int (it arrives as a ctypes instance)."""
    return int(getattr(value, "value", value)) & 0xFFFFFFFF


# -- COM: WebView2 (generated) and DirectComposition (the four calls made) ------------------------

def _com():
    """comtypes and the interfaces, imported only when the overlay starts, with COM started
    on this thread. comtypes starts COM only on the thread that imports it first, and in the
    meter that is the screen thread (bettercam imports it): seen 2026-11-18 as WebView2's
    environment failing with CO_E_NOTINITIALIZED."""
    hr = ctypes.windll.ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
    if hr not in (0, 1):  # S_OK, or S_FALSE when already started the same way
        raise Unavailable(f"COM would not start on the overlay's thread (0x{hr & 0xFFFFFFFF:08X})")
    import comtypes  # noqa: F401
    from comtypes import COMMETHOD, GUID, COMObject, IUnknown

    from . import webview2_com as wv

    class IDCompositionVisual(IUnknown):
        _iid_ = GUID("{4D93059D-097B-4651-9A60-F0F25116E2F3}")
        _methods_ = []

    class IDCompositionVisual2(IDCompositionVisual):
        _iid_ = GUID("{E8DE1639-4331-4B26-BC5F-6A321D347A85}")
        _methods_ = []

    class IDCompositionTarget(IUnknown):
        _iid_ = GUID("{EACDD04C-117E-4E17-88F4-D1B12B0E3D89}")
        _methods_ = [COMMETHOD([], HRESULT, "SetRoot", (["in"], ctypes.POINTER(IDCompositionVisual), "visual"))]

    unused = ("CreateSurfaceFactory", "CreateSurface", "CreateVirtualSurface", "CreateTranslateTransform",
              "CreateScaleTransform", "CreateRotateTransform", "CreateSkewTransform", "CreateMatrixTransform",
              "CreateTransformGroup", "CreateTranslateTransform3D", "CreateScaleTransform3D",
              "CreateRotateTransform3D", "CreateMatrixTransform3D", "CreateTransform3DGroup",
              "CreateEffectGroup", "CreateRectangleClip", "CreateAnimation")

    class IDCompositionDevice2(IUnknown):  # the vtable order is dcomp.h's
        _iid_ = GUID("{75F6468D-1B8E-447C-9BC6-75FEA80B5B25}")
        _methods_ = [
            COMMETHOD([], HRESULT, "Commit"),
            COMMETHOD([], HRESULT, "WaitForCommitCompletion"),
            COMMETHOD([], HRESULT, "GetFrameStatistics"),  # never called
            COMMETHOD([], HRESULT, "CreateVisual",
                      (["out"], ctypes.POINTER(ctypes.POINTER(IDCompositionVisual2)), "visual")),
        ] + [COMMETHOD([], HRESULT, name) for name in unused]  # never called

    class IDCompositionDesktopDevice(IDCompositionDevice2):
        _iid_ = GUID("{5F4633FE-1E08-4CB8-8C75-CE24333F5602}")
        _methods_ = [
            COMMETHOD([], HRESULT, "CreateTargetForHwnd", (["in"], wintypes.HWND, "hwnd"),
                      (["in"], wintypes.BOOL, "topmost"),
                      (["out"], ctypes.POINTER(ctypes.POINTER(IDCompositionTarget)), "target")),
        ]

    def handler(interface, callback):
        """A COM object implementing one WebView2 handler interface by calling ``callback``."""

        def invoke(self, this, *args):
            try:
                callback(*args)
            except Exception:  # noqa: BLE001 - an exception must not cross into COM
                traceback.print_exc()
            return 0

        cls = type(f"{interface.__name__}Impl", (COMObject,), {
            "_com_interfaces_": [interface], f"{interface.__name__}_Invoke": invoke,
        })
        return cls().QueryInterface(interface)

    return wv, handler, IUnknown, IDCompositionDesktopDevice, IDCompositionVisual


def _loader():
    if not os.path.isfile(LOADER):
        # releases carry it; a git checkout gets it from run.bat or the tool named here
        raise Unavailable(f"{LOADER} is missing; from source, run.bat or "
                          "tools\\make_webview2_com.py --loader-only fetches it")
    try:
        return ctypes.WinDLL(LOADER)
    except OSError as error:
        raise Unavailable(f"{LOADER} would not load: {error}") from error


def runtime_version() -> str:
    """The WebView2 Runtime's version on this PC. Raises Unavailable when there is none."""
    loader = _loader()
    query = loader.GetAvailableCoreWebView2BrowserVersionString
    query.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    query.restype = ctypes.c_long
    text = ctypes.c_void_p()
    hr = query(None, ctypes.byref(text))
    if hr != 0 or not text.value:
        raise Unavailable(f"no WebView2 Runtime installed (0x{hr & 0xFFFFFFFF:08X})")
    try:
        return ctypes.wstring_at(text.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(text)


def data_folder() -> str:
    """Where WebView2 keeps its cache for Waveband: not beside the exe, which may not be writable."""
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return os.path.join(base, config_mod.NAME, "WebView2")


def _take_up_qt_place(cfg: config_mod.Config) -> None:
    """The meter's place as 0.3.1 and before saved it (Qt's scaled pixels) in screen pixels,
    once, so on a scaled display it comes up where the user put it."""
    if cfg.overlay_pixels == "screen":
        return
    if isinstance(cfg.overlay_x, int) and isinstance(cfg.overlay_y, int):
        before = (cfg.overlay_x, cfg.overlay_y)
        cfg.overlay_x, cfg.overlay_y = from_qt_pixels(*before)
        if (cfg.overlay_x, cfg.overlay_y) != before:
            print(f"the meter's place from before 0.3.2, {before}, is {cfg.overlay_x, cfg.overlay_y} "
                  "in screen pixels", flush=True)
    cfg.overlay_pixels = "screen"
    try:
        config_mod.save(cfg)
    except OSError:
        traceback.print_exc()  # converted again next start; the meter is placed right either way


# -- the overlay window ---------------------------------------------------------------------------

class OverlayWindow:
    """The window, its composition visual and the WebView2 drawing into it."""

    def __init__(self, url: str, cfg: config_mod.Config, on_failed: Callable[[str], None]) -> None:
        self._cfg = cfg
        self._url = url
        self._on_failed = on_failed
        self.moving = False
        self.on_front: Callable[[bool], None] | None = None  # told whether the game is in front
        self.messages: dict[int, Callable[[int, int], int | None]] = {}  # more messages, for run()
        self._wanted = True  # user's show/hide choice
        self._visible = False
        self._last_in_front = time.monotonic()
        self._zoom = self._zoom_wanted()
        _take_up_qt_place(cfg)
        self._placed = (cfg.overlay_x, cfg.overlay_y, cfg.overlay_zoom)
        self._hidden_from_capture = bool(cfg.hide_from_capture)
        self._controller = None
        self._webview = None
        self._keep: list = []  # handlers WebView2 holds on to
        self._restarts: list[float] = []  # when WebView2 was started again, the last minute

        self.hwnd = None
        self._wv, self._handler, self._IUnknown, desktop_device, visual_type = _com()
        _register_class()
        ex = (WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_NOREDIRECTIONBITMAP
              | WS_EX_LAYERED | WS_EX_TRANSPARENT)
        x, y = self._start_position()
        hwnd = _user32.CreateWindowExW(ex, CLASS_NAME, config_mod.NAME, WS_POPUP, x, y, 1, 1,
                                       None, None, _kernel32.GetModuleHandleW(None), None)
        if not hwnd:
            raise Unavailable(f"the overlay window could not be made: {ctypes.WinError(ctypes.get_last_error())}")
        self.hwnd = hwnd
        _WINDOWS[hwnd] = self
        try:
            # A layered window shows nothing until told how: fully opaque; the per-pixel alpha
            # comes from the composition visual
            _user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
            self._size_window()
            self._apply_affinity()
            device = ctypes.POINTER(desktop_device)()
            hr = ctypes.windll.dcomp.DCompositionCreateDevice2(None, ctypes.byref(desktop_device._iid_),
                                                               ctypes.byref(device))
            if hr != 0:
                raise Unavailable(f"DirectComposition would not start (0x{hr & 0xFFFFFFFF:08X})")
            self._device = device
            self._target = device.CreateTargetForHwnd(hwnd, True)
            self._visual = device.CreateVisual()
            self._target.SetRoot(self._visual.QueryInterface(visual_type))
            device.Commit()
            self._start_webview()
        except BaseException:
            self.close()  # no half-made window left behind
            raise

    # -- WebView2 ---------------------------------------------------------------------------------

    def _start_webview(self) -> None:
        # transparent from the first frame, before the controller exists to be told so; taken out
        # again once the view exists (_on_controller), so programs Waveband starts don't inherit it
        os.environ["WEBVIEW2_DEFAULT_BACKGROUND_COLOR"] = "00000000"
        loader = _loader()
        create = loader.CreateCoreWebView2EnvironmentWithOptions
        done_type = self._wv.ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler
        create.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(done_type)]
        create.restype = ctypes.c_long
        done = self._handler(done_type, self._on_environment)
        self._keep.append(done)
        hr = create(None, data_folder(), None, done)
        if hr != 0:
            raise Unavailable(f"WebView2 would not start (0x{hr & 0xFFFFFFFF:08X})")

    def _on_environment(self, error, environment) -> None:
        if _hresult(error):
            self._on_failed(f"WebView2's environment failed (0x{_hresult(error):08X})")
            return
        try:
            self._make_view(environment)
        except Exception as fault:  # noqa: BLE001 - without a view there is no overlay: say so
            traceback.print_exc()
            self._on_failed(f"WebView2's view could not be made ({fault!r})")

    def _make_view(self, environment) -> None:
        wv = self._wv
        env = environment.QueryInterface(wv.ICoreWebView2Environment3)
        self._environment = env
        done_type = wv.ICoreWebView2CreateCoreWebView2CompositionControllerCompletedHandler
        done = self._handler(done_type, self._on_controller)
        self._keep.append(done)
        env.CreateCoreWebView2CompositionController(self.hwnd, done)

    def _on_controller(self, error, composition) -> None:
        os.environ.pop("WEBVIEW2_DEFAULT_BACKGROUND_COLOR", None)
        if _hresult(error):
            self._on_failed(f"WebView2's view failed (0x{_hresult(error):08X})")
            return
        try:
            self._show_page(composition)
        except Exception as fault:  # noqa: BLE001 - without the page there is no overlay: say so
            traceback.print_exc()
            self._on_failed(f"WebView2 could not show the meter ({fault!r})")

    def _show_page(self, composition) -> None:
        wv = self._wv
        self._composition = composition
        composition.put_RootVisualTarget(self._visual.QueryInterface(self._IUnknown))
        controller = composition.QueryInterface(wv.ICoreWebView2Controller3)
        self._controller = controller
        controller.put_DefaultBackgroundColor(wv.COREWEBVIEW2_COLOR(0, 0, 0, 0))
        controller.put_ShouldDetectMonitorScaleChanges(False)  # this window says when (WM_DPICHANGED)
        self._apply_scale()
        controller.put_IsVisible(True)
        webview = controller.get_CoreWebView2()
        self._webview = webview
        settings = webview.get_Settings()
        settings.put_AreDefaultContextMenusEnabled(False)
        settings.put_IsStatusBarEnabled(False)
        settings.put_IsZoomControlEnabled(False)
        settings.put_AreDevToolsEnabled(False)
        settings.put_AreDefaultScriptDialogsEnabled(False)
        # Edge's "can't reach this page" is opaque and would sit over the game; without it a page
        # that fails to load leaves the overlay empty (clear) until it loads (_on_loaded)
        settings.put_IsBuiltInErrorPageEnabled(False)
        loaded = self._handler(wv.ICoreWebView2NavigationCompletedEventHandler, self._on_loaded)
        self._keep.append(loaded)
        webview.add_NavigationCompleted(loaded)
        died = self._handler(wv.ICoreWebView2ProcessFailedEventHandler, self._on_process_failed)
        self._keep.append(died)
        webview.add_ProcessFailed(died)
        self._script_done = self._handler(wv.ICoreWebView2ExecuteScriptCompletedHandler, lambda *_: None)
        webview.Navigate(self._url)
        self._device.Commit()

    def _on_loaded(self, _sender, args) -> None:
        if not args.get_IsSuccess():
            print(f"the overlay page did not load ({self._url}); trying again", flush=True)
            _user32.SetTimer(self.hwnd, TIMER_RELOAD, RELOAD_AFTER, None)
            return
        self._run_script(move_script(self._cfg, self.moving))

    def _on_process_failed(self, _sender, args) -> None:
        """WebView2 draws from processes of its own (msedgewebview2.exe), which can end on their
        own: ended in Task Manager, a crash, low memory. Without this the meter would stay empty
        for the rest of the session with nothing saying why."""
        kind = args.get_ProcessFailedKind()
        if kind == PROCESS_FAILED_BROWSER:
            # the view is gone with it: a new browser, view and page, from the message loop
            print("WebView2's browser process ended; starting it again", flush=True)
            self._webview = None
            _user32.SetTimer(self.hwnd, TIMER_RESTART, RESTART_AFTER, None)
        elif kind in (PROCESS_FAILED_RENDERER, PROCESS_FAILED_UNRESPONSIVE):
            print(f"the overlay page's process {'ended' if kind == PROCESS_FAILED_RENDERER else 'hung'}; "
                  "loading the page again", flush=True)
            if self._webview is not None:
                self._webview.Reload()
        else:
            print(f"a WebView2 helper process ended (kind {kind}); WebView2 starts it again", flush=True)

    def _restart_webview(self) -> None:
        now = time.monotonic()
        self._restarts = [t for t in self._restarts if now - t < 60] + [now]
        if len(self._restarts) > RESTARTS_A_MINUTE:
            # it keeps ending as soon as it starts: say so and stop, rather than loop unseen
            self._on_failed("WebView2's browser process keeps ending")
            return
        if self._controller is not None:
            try:
                self._controller.Close()
            except Exception:  # noqa: BLE001 - its browser is gone; nothing left to close
                pass
        self._controller = self._webview = self._composition = self._environment = None
        self._keep = []
        self._start_webview()  # the environment, then the view and the page, as at the start

    def _run_script(self, script: str) -> None:
        if self._webview is not None:
            self._webview.ExecuteScript(script, self._script_done)

    # -- size, place, look ------------------------------------------------------------------------

    def _zoom_wanted(self) -> float:
        try:
            return max(ZOOM[0], min(ZOOM[1], float(self._cfg.overlay_zoom)))
        except (TypeError, ValueError):
            return 1.0

    def _scale(self) -> float:
        return (_user32.GetDpiForWindow(self.hwnd) or 96) / 96 if getattr(self, "hwnd", None) else 1.0

    def _size(self) -> tuple[int, int]:
        scale = self._scale()
        return tuple(round(v * self._zoom * scale) for v in BASE_SIZE)

    def _start_position(self) -> tuple[int, int]:
        x, y = self._cfg.overlay_x, self._cfg.overlay_y
        width, height = (round(v * self._zoom) for v in BASE_SIZE)
        # Settings brought from another PC, or a monitor since unplugged, can name a place no
        # screen shows. The meter would be running and nowhere to be seen.
        if not isinstance(x, int) or not isinstance(y, int) or not on_a_screen(x, y, width, height):
            return default_position()
        return x, y

    def _size_window(self) -> None:
        width, height = self._size()
        _user32.SetWindowPos(self.hwnd, None, 0, 0, width, height, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE)

    def _apply_scale(self) -> None:
        """The page at this zoom on this monitor's scale, filling the window."""
        if self._controller is None:
            return
        width, height = self._size()
        self._controller.put_RasterizationScale(self._scale())
        self._controller.put_ZoomFactor(self._zoom)
        self._controller.put_Bounds(wintypes.RECT(0, 0, width, height))

    def _apply_affinity(self) -> None:
        self._hidden_from_capture = bool(self._cfg.hide_from_capture)
        affinity = WDA_EXCLUDEFROMCAPTURE if self._hidden_from_capture else WDA_NONE
        _user32.SetWindowDisplayAffinity(self.hwnd, affinity)

    def _place(self) -> None:
        """Where the settings say, at their size."""
        self._zoom = self._zoom_wanted()
        x, y = self._start_position()
        width, height = self._size()
        _user32.SetWindowPos(self.hwnd, None, x, y, width, height, SWP_NOZORDER | SWP_NOACTIVATE)
        self._apply_scale()

    def nudge_zoom(self, delta: float) -> None:
        self._zoom = max(ZOOM[0], min(ZOOM[1], round(self._zoom + delta, 2)))
        self._size_window()
        self._apply_scale()

    def _set_visible(self, visible: bool) -> None:
        self._visible = visible
        _user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE if visible else SW_HIDE)
        if visible:
            _user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    # -- behaviour --------------------------------------------------------------------------------

    def follow_game(self) -> None:
        """Show only over the game, with a short grace so brief focus changes don't flicker."""
        now = time.monotonic()
        in_front = self.moving or game_in_front(self._cfg)
        if self.on_front is not None:
            self.on_front(in_front)
        if in_front or not self._cfg.only_over_game:
            self._last_in_front = now
        should_show = self._wanted and now - self._last_in_front < HIDE_AFTER
        if should_show != self._visible:
            self._set_visible(should_show)

    def take_settings(self) -> None:
        """Match settings changed on the settings page or brought from another PC."""
        if self._hidden_from_capture != bool(self._cfg.hide_from_capture):
            self._apply_affinity()
        placed = (self._cfg.overlay_x, self._cfg.overlay_y, self._cfg.overlay_zoom)
        if self.moving or placed == self._placed:
            return
        self._placed = placed
        self._place()

    def set_moving(self, moving: bool) -> None:
        if moving == self.moving:
            return
        self.moving = moving
        ex = _user32.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
        ex = ex & ~WS_EX_TRANSPARENT if moving else ex | WS_EX_TRANSPARENT
        _user32.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, ex)
        _user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                             SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED)
        if not moving:
            self._save_placement()
        self.follow_game()
        self._run_script(move_script(self._cfg, moving))

    def toggle_wanted(self) -> None:
        self._wanted = not self._wanted
        self.follow_game()

    def set_hidden_from_capture(self, hidden: bool) -> None:
        self._cfg.hide_from_capture = hidden
        self._apply_affinity()
        config_mod.save(self._cfg)

    def _save_placement(self) -> None:
        rect = wintypes.RECT()
        _user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
        self._cfg.overlay_x, self._cfg.overlay_y = rect.left, rect.top
        self._cfg.overlay_zoom = self._zoom
        self._placed = (self._cfg.overlay_x, self._cfg.overlay_y, self._cfg.overlay_zoom)
        config_mod.save(self._cfg)

    def run_script_now(self) -> None:
        """The move-mode look again, after the keys changed (its hint names the lock key)."""
        self._run_script(move_script(self._cfg, self.moving))

    # -- messages ---------------------------------------------------------------------------------

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_NCHITTEST:
                # reached only in move mode (otherwise WS_EX_TRANSPARENT): drag it anywhere
                return HTCAPTION if self.moving else HTTRANSPARENT
            if msg == WM_SETCURSOR and self.moving:
                _user32.SetCursor(_user32.LoadCursorW(None, IDC_SIZEALL))
                return 1
            if msg == WM_MOUSEWHEEL and self.moving:
                delta = ctypes.c_short(wparam >> 16 & 0xFFFF).value
                self.nudge_zoom(0.05 if delta > 0 else -0.05)
                return 0
            if msg == WM_TIMER and wparam == TIMER_RELOAD:
                _user32.KillTimer(hwnd, TIMER_RELOAD)
                if self._webview is not None:
                    self._webview.Navigate(self._url)
                return 0
            if msg == WM_TIMER and wparam == TIMER_RESTART:
                _user32.KillTimer(hwnd, TIMER_RESTART)
                try:
                    self._restart_webview()
                except Exception as fault:  # noqa: BLE001 - no view and no way to make one: say so
                    traceback.print_exc()
                    self._on_failed(f"WebView2 would not start again ({fault!r})")
                return 0
            if msg == WM_DPICHANGED:
                self._size_window()
                self._apply_scale()
                return 0
            if msg in self.messages:
                answer = self.messages[msg](wparam, lparam)
                if answer is not None:
                    return answer
            if msg == WM_DESTROY:
                _user32.PostQuitMessage(0)
                return 0
        except Exception:  # noqa: BLE001 - an exception must not cross into Windows
            traceback.print_exc()
            return 0
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def close(self) -> None:
        if self._controller is not None:
            try:
                self._controller.Close()
            except Exception:  # noqa: BLE001 - closing anyway
                traceback.print_exc()
            self._controller = None
            self._webview = None
        if self.hwnd:
            hwnd, self.hwnd = self.hwnd, None
            _user32.KillTimer(hwnd, TIMER_FOLLOW)
            _user32.KillTimer(hwnd, TIMER_SETTINGS)
            _user32.KillTimer(hwnd, TIMER_RELOAD)
            _user32.KillTimer(hwnd, TIMER_RESTART)
            _user32.DestroyWindow(hwnd)  # its WM_DESTROY still reaches this window's procedure
            _WINDOWS.pop(hwnd, None)


# -- the tray icon --------------------------------------------------------------------------------

def _tray_icon_file() -> str:
    """Waveband's icon (``ui/waveband.png``) as an .ico Windows can load, or a plain one drawn
    here when the file is missing."""
    from PIL import Image, ImageDraw

    drawn = os.path.join(config_mod.ROOT, "ui", "waveband.png")
    image = None
    if os.path.isfile(drawn):
        try:
            image = Image.open(drawn).convert("RGBA")
        except OSError:
            image = None
    if image is None:
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((2, 2, 61, 61), 12, fill="#0e1118")
        for i, half in enumerate((8, 18, 26, 14, 22, 10)):
            draw.rectangle((11 + i * 8, 32 - half, 15 + i * 8, 32 + half), fill="#f2b544")
    path = os.path.join(tempfile.gettempdir(), "wwmeter-tray.ico")
    image.save(path, sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (48, 48), (64, 64)])
    return path


class Tray:
    """Waveband's icon by the clock, its menu and its messages."""

    def __init__(self, hwnd: int, tip: str) -> None:
        import win32con
        import win32gui

        self._gui, self._con = win32gui, win32con
        self.hwnd = hwnd
        self.tip = tip
        import win32api

        size = win32api.GetSystemMetrics(win32con.SM_CXSMICON)
        self.icon = win32gui.LoadImage(0, _tray_icon_file(), win32con.IMAGE_ICON, size, size,
                                       win32con.LR_LOADFROMFILE)
        self.taskbar_created = win32gui.RegisterWindowMessage("TaskbarCreated")
        # Explorer broadcasts it from a lower integrity level. Measured 2026-11-24 (Windows 10,
        # Waveband as administrator): a window that already has an icon by the clock gets it
        # anyway, one without (its icon couldn't be added: Waveband started before Explorer
        # did) doesn't, unless the window lets it in.
        _user32.ChangeWindowMessageFilterEx(hwnd, self.taskbar_created, MSGFLT_ALLOW, None)
        self.add()

    def add(self) -> None:
        gui, con = self._gui, self._con
        flags = gui.NIF_ICON | gui.NIF_MESSAGE | gui.NIF_TIP
        try:
            gui.Shell_NotifyIcon(gui.NIM_ADD, (self.hwnd, 1, flags, WM_TRAY, self.icon, self.tip))
        except Exception:  # noqa: BLE001 - Explorer not running yet; TaskbarCreated adds it later
            traceback.print_exc()

    def remove(self) -> None:
        try:
            self._gui.Shell_NotifyIcon(self._gui.NIM_DELETE, (self.hwnd, 1))
        except Exception:  # noqa: BLE001 - already gone with Explorer
            pass

    def notify(self, text: str, ms: int = 4000) -> None:
        gui, con = self._gui, self._con
        try:
            gui.Shell_NotifyIcon(gui.NIM_MODIFY, (self.hwnd, 1, gui.NIF_INFO, WM_TRAY, self.icon,
                                                  self.tip, text[:255], ms, config_mod.NAME, gui.NIIF_INFO))
        except Exception:  # noqa: BLE001 - a message lost is no reason to stop
            traceback.print_exc()

    def show_menu(self, items: list[Item]) -> None:
        """The menu at the mouse; runs what was picked."""
        gui, con = self._gui, self._con
        root, actions = build_menu(items)
        try:
            x, y = gui.GetCursorPos()
            # the menu closes when clicked away from only if its window is in front for it
            try:
                gui.SetForegroundWindow(self.hwnd)
            except Exception:  # noqa: BLE001 - Windows may refuse; the menu still works
                pass
            chosen = gui.TrackPopupMenu(root, con.TPM_RETURNCMD | con.TPM_NONOTIFY | con.TPM_RIGHTBUTTON,
                                        x, y, 0, self.hwnd, None)
            gui.PostMessage(self.hwnd, WM_NULL, 0, 0)
        finally:
            gui.DestroyMenu(root)  # takes its submenus with it
        if chosen and actions.get(chosen) is not None:
            actions[chosen]()


def build_menu(items: list[Item]) -> tuple[int, dict[int, Callable[[], None]]]:
    """A Windows popup menu of ``items``, and the action behind each command ID. The caller
    destroys the menu (its submenus go with it); if making it fails, nothing is left behind."""
    import win32con as con
    import win32gui as gui

    actions: dict[int, Callable[[], None]] = {}

    def build(entries: list[Item]) -> int:
        menu = gui.CreatePopupMenu()
        try:
            for item in entries:
                if item.separator:
                    gui.AppendMenu(menu, con.MF_SEPARATOR, 0, "")  # pywin32 refuses None here
                    continue
                text = f"{item.text}\t{item.key}" if item.key else item.text
                flags = con.MF_STRING
                if item.checked:
                    flags |= con.MF_CHECKED
                if not item.enabled:
                    flags |= con.MF_GRAYED
                if item.children is not None:
                    gui.AppendMenu(menu, flags | con.MF_POPUP, build(item.children()), text)
                    continue
                command = len(actions) + 1
                actions[command] = item.action
                gui.AppendMenu(menu, flags, command, text)
                if item.radio and item.checked:
                    # one of a group: a bullet instead of a tick
                    _user32.CheckMenuRadioItem(int(menu), command, command, command, MF_BYCOMMAND)
        except Exception:
            gui.DestroyMenu(menu)  # and the submenus already in it
            raise
        return menu

    return build(items), actions


# -- running it -----------------------------------------------------------------------------------

def run(
    url: str, cfg: config_mod.Config, on_reset: Callable[[], None], dashboard_url: str,
    on_view: Callable[[int], None] | None = None,
    on_copy: Callable[[], None] | None = None,
    on_keys_taken: Callable[[list[str]], None] | None = None,
    list_sessions: Callable[[], list[dict]] | None = None,
    open_session: Callable[[str | None], None] | None = None,
    update_finished: Callable[[], str | None] | None = None,
    app_actions: dict | None = None,
    keys_need_ctrl_or_alt: Callable[[], bool] | None = None,
) -> int:
    """Show the overlay and block until the user quits from the tray menu. ``on_view`` steps to
    the fight before (-1) or after (+1) the one on show, ``on_copy`` puts its summary on the
    clipboard, ``on_keys_taken`` is told which hotkeys another program is holding,
    ``list_sessions`` gives the earlier sessions and ``open_session`` puts one on show (None:
    back to this one); ``update_finished`` gives, once, what the last update of the boss HP
    tables ended with; ``keys_need_ctrl_or_alt`` says whether a key held without them would
    not reach the meter (the game runs as administrator and Waveband does not). Raises
    Unavailable when WebView2 can't be used here."""
    set_dpi_aware()
    runtime_version()  # no runtime: say so now, before a window or a tray icon exists
    failed: list[str] = []
    window = None
    tray = None
    hotkeys = None

    def on_failed(why: str) -> None:
        failed.append(why)
        _user32.PostQuitMessage(0)

    try:
        window = OverlayWindow(url, cfg, on_failed)
        tray = Tray(window.hwnd, f"{config_mod.NAME} {__version__}")

        hwnd = window.hwnd

        def quit_app() -> None:  # from any thread (the updater's too)
            _user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)

        def key_works(name: str) -> bool:
            if hotkeys is not None and name in hotkeys.refused:
                return False  # another program holds it
            blocked = keys_need_ctrl_or_alt is not None and keys_need_ctrl_or_alt()
            return not (blocked and hotkey_names.needs_ctrl_or_alt(name))

        controls = Controls(
            cfg=cfg, overlay=window, notify=tray.notify, quit=quit_app, on_reset=on_reset,
            dashboard_url=dashboard_url, on_view=on_view, on_copy=on_copy, list_sessions=list_sessions,
            open_session=open_session, update_finished=update_finished,
            app_actions=app_actions, themes=available_themes, theme_label=theme_label,
            key_works=key_works,
        )
        if app_actions is not None:
            app_actions["set_quit"](quit_app)
        keys = hotkey_names.bindings(cfg.hotkeys)
        hotkeys = HotkeySet(keys, controls.dispatch, on_keys_taken, hwnd=window.hwnd)
        window.on_front = hotkeys.set_active  # the hotkeys exist only while the game is in front

        def take_settings() -> None:
            nonlocal keys
            wanted = hotkey_names.bindings(cfg.hotkeys)
            if wanted != keys:
                keys = wanted
                hotkeys.rebind(keys)
                window.run_script_now()
            window.take_settings()
            controls.poll()

        def on_timer(wparam: int, _lparam: int) -> int:
            if wparam == TIMER_FOLLOW:
                window.follow_game()
            elif wparam == TIMER_SETTINGS:
                take_settings()
            return 0

        def on_tray(_wparam: int, lparam: int) -> int:
            if lparam & 0xFFFF in (WM_RBUTTONUP, WM_CONTEXTMENU, WM_LBUTTONUP):
                tray.show_menu(controls.items())
            return 0

        def on_close(_wparam: int, _lparam: int) -> int:
            hotkeys.set_active(False)
            tray.remove()
            window.close()  # the window's WM_DESTROY ends the message loop
            return 0

        window.messages.update({
            WM_TIMER: on_timer,
            WM_HOTKEY: lambda wparam, _: 0 if hotkeys.handle(wparam) else None,
            WM_TRAY: on_tray,
            tray.taskbar_created: lambda *_: (tray.add(), 0)[1],  # Explorer started again
            WM_CLOSE: on_close,
        })
        _user32.SetTimer(window.hwnd, TIMER_FOLLOW, 250, None)
        _user32.SetTimer(window.hwnd, TIMER_SETTINGS, 500, None)
        window.follow_game()

        msg = wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))
    finally:
        if hotkeys is not None:
            hotkeys.set_active(False)
        if tray is not None:
            tray.remove()
        if window is not None:
            window.close()
        # Closing posts a quit (WM_DESTROY), and a failure posted one before: left in the queue,
        # it would end the next message loop on this thread at once
        leftover = wintypes.MSG()
        while _user32.PeekMessageW(ctypes.byref(leftover), None, WM_QUIT, WM_QUIT, PM_REMOVE):
            pass
    if failed:
        raise Unavailable(failed[0])
    return 0
