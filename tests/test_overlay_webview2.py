"""The WebView2 overlay's parts that run without a window or WebView2: the tray menu as Windows
builds it (CreatePopupMenu works without showing anything)."""

import ctypes
import unittest
from ctypes import wintypes
from unittest import mock

import win32con
import win32gui

from wwmeter import overlay_common
from wwmeter.config import Config
from wwmeter.overlay_common import Controls, Item
from wwmeter.overlay_webview2 import build_menu


class FakeOverlay:
    moving = False

    def set_moving(self, moving):
        self.moving = moving

    def toggle_wanted(self):
        pass

    def set_hidden_from_capture(self, hidden):
        pass


def texts(menu: int) -> list[str]:
    """Each entry's text as Windows has it (a separator's is "")."""
    get = ctypes.windll.user32.GetMenuStringW
    get.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.LPWSTR, ctypes.c_int, wintypes.UINT]
    found = []
    for i in range(win32gui.GetMenuItemCount(menu)):
        buffer = ctypes.create_unicode_buffer(256)
        get(menu, i, buffer, 256, win32con.MF_BYPOSITION)
        found.append(buffer.value)
    return found


class BuildMenuTest(unittest.TestCase):
    def test_the_whole_tray_menu_is_made(self):
        # found 2026-11-18: the menu never opened, pywin32 refusing None as a separator's text
        mock.patch.object(overlay_common.config_mod, "save").start()
        self.addCleanup(mock.patch.stopall)
        cfg = Config(log_dir="")
        controls = Controls(
            cfg=cfg, overlay=FakeOverlay(), notify=lambda *_: None, quit=lambda: None,
            on_reset=lambda: None, dashboard_url="http://127.0.0.1:5055/?view=full",
            list_sessions=lambda: [{"file": "a.json", "label": "Monday", "fights": 2, "last": "Crownless"}],
            open_session=lambda chosen: None, themes=lambda: ["wuwa", "classic"],
            theme_label=str.title,
            app_actions={"available": lambda: "0.3.2", "install": lambda: "", "check": lambda: "", "said": lambda: None},
        )
        cfg.hotkeys = dict(cfg.hotkeys, copy="Ctrl+Alt+C")
        items = controls.items()
        menu, actions = build_menu(items)
        try:
            shown = texts(menu)
            self.assertEqual(len(shown), len(items))
            self.assertIn("Settings: keybinds, colours, log folder", shown)
            self.assertIn("Install update (0.3.2)", shown)
            self.assertIn("Copy this fight's summary\tCtrl+Alt+C", shown)  # its key beside it
            self.assertIn("Quit", shown)
            sessions = win32gui.GetSubMenu(menu, shown.index("Earlier sessions"))
            self.assertEqual(win32gui.GetMenuItemCount(sessions), 3)  # back, a separator, Monday
            themes = win32gui.GetSubMenu(menu, shown.index("Theme"))
            self.assertEqual(texts(themes), ["Wuwa", "Classic"])
            # every entry with an action has a command, and no submenu or separator has one
            self.assertEqual(len(actions), sum(1 for i in items if i.action) + 2 + 2)
        finally:
            win32gui.DestroyMenu(menu)

    def test_ticks_and_greyed_entries(self):
        menu, actions = build_menu([Item("On", lambda: None, checked=True), Item("None yet", enabled=False)])
        try:
            on = win32gui.GetMenuState(menu, 0, win32con.MF_BYPOSITION)
            off = win32gui.GetMenuState(menu, 1, win32con.MF_BYPOSITION)
            self.assertTrue(on & win32con.MF_CHECKED)
            self.assertTrue(off & win32con.MF_GRAYED)
        finally:
            win32gui.DestroyMenu(menu)

    def test_the_chosen_theme_has_a_bullet(self):
        menu, _ = build_menu([Item("Wuwa", lambda: None, checked=False, radio=True),
                              Item("Classic", lambda: None, checked=True, radio=True),
                              Item("A tick box", lambda: None, checked=True)])
        try:
            kinds = [_menu_type(menu, i) & win32con.MFT_RADIOCHECK for i in range(3)]
            self.assertEqual([bool(kind) for kind in kinds], [False, True, False])
            self.assertTrue(win32gui.GetMenuState(menu, 1, win32con.MF_BYPOSITION) & win32con.MF_CHECKED)
        finally:
            win32gui.DestroyMenu(menu)


def _menu_type(menu: int, position: int) -> int:
    """An entry's fType (MFT_RADIOCHECK and the like), which GetMenuState doesn't give."""
    class MENUITEMINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("fMask", wintypes.UINT), ("fType", wintypes.UINT),
                    ("fState", wintypes.UINT), ("wID", wintypes.UINT), ("hSubMenu", wintypes.HMENU),
                    ("hbmpChecked", wintypes.HBITMAP), ("hbmpUnchecked", wintypes.HBITMAP),
                    ("dwItemData", ctypes.c_size_t), ("dwTypeData", wintypes.LPWSTR),
                    ("cch", wintypes.UINT), ("hbmpItem", wintypes.HBITMAP)]

    info = MENUITEMINFOW(cbSize=ctypes.sizeof(MENUITEMINFOW), fMask=0x100)  # MIIM_FTYPE
    get = ctypes.windll.user32.GetMenuItemInfoW
    get.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.BOOL, ctypes.POINTER(MENUITEMINFOW)]
    if not get(menu, position, True, ctypes.byref(info)):
        raise ctypes.WinError()
    return info.fType


class OldPlaceTest(unittest.TestCase):
    """The meter's place in a settings file from 0.3.1 and before (Qt's scaled pixels)."""

    MONITORS = [((0, 0, 2560, 1440), 1.5)]

    def setUp(self):
        import json
        import os
        import tempfile

        from wwmeter import config

        self.config, self.json = config, json
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = os.path.join(self.folder.name, "config.json")
        mock.patch.object(config, "CONFIG_PATH", self.path).start()
        mock.patch.object(overlay_common, "screen_scales", lambda: self.MONITORS).start()
        self.addCleanup(mock.patch.stopall)

    def load(self, data):
        with open(self.path, "w", encoding="utf-8") as fh:
            self.json.dump(data, fh)
        return self.config.load()

    def test_a_place_from_0_3_1_is_turned_into_screen_pixels_once(self):
        from wwmeter.overlay_webview2 import _take_up_qt_place

        cfg = self.load({"overlay_x": 1000, "overlay_y": 600, "seen_version": "0.3.1"})
        self.assertEqual(cfg.overlay_pixels, "qt")
        _take_up_qt_place(cfg)
        self.assertEqual((cfg.overlay_x, cfg.overlay_y, cfg.overlay_pixels), (1500, 900, "screen"))
        again = self.config.load()  # saved: the next start leaves it where it is
        self.assertEqual((again.overlay_x, again.overlay_y, again.overlay_pixels), (1500, 900, "screen"))
        _take_up_qt_place(again)
        self.assertEqual((again.overlay_x, again.overlay_y), (1500, 900))

    def test_a_file_a_0_3_2_beta_wrote_is_in_screen_pixels(self):
        cfg = self.load({"overlay_x": 1000, "overlay_y": 600, "seen_version": "0.3.2-beta.2"})
        self.assertEqual(cfg.overlay_pixels, "screen")

    def test_a_file_from_before_versions_were_kept_is_qt(self):
        self.assertEqual(self.load({"overlay_x": 10, "overlay_y": 10}).overlay_pixels, "qt")

    def test_no_place_saved_is_left_alone(self):
        from wwmeter.overlay_webview2 import _take_up_qt_place

        cfg = self.load({"seen_version": "0.3.0"})
        _take_up_qt_place(cfg)
        self.assertEqual((cfg.overlay_x, cfg.overlay_y, cfg.overlay_pixels), (None, None, "screen"))

    def test_a_new_file_is_in_screen_pixels(self):
        self.assertEqual(self.config.Config(log_dir="").overlay_pixels, "screen")


if __name__ == "__main__":
    unittest.main()
