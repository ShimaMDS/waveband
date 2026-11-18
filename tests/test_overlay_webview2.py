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


if __name__ == "__main__":
    unittest.main()
