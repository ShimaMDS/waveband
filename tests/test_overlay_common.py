import unittest
from unittest import mock

from wwmeter import hotkeys, overlay_common
from wwmeter.config import Config
from wwmeter.overlay_common import Controls, HotkeySet, Item, move_script, on_a_screen


class FakeUser32:
    """RegisterHotKey and UnregisterHotKey, with keys another program holds."""

    def __init__(self, taken=()):
        self.taken = set(taken)  # virtual key codes another program has
        self.held: dict[int, tuple] = {}

    def RegisterHotKey(self, hwnd, hotkey_id, modifiers, key):  # noqa: N802 - Win32 naming
        if key in self.taken:
            return 0
        self.held[hotkey_id] = (hwnd, modifiers, key)
        return 1

    def UnregisterHotKey(self, hwnd, hotkey_id):  # noqa: N802 - Win32 naming
        self.held.pop(hotkey_id, None)
        return 1


class HotkeySetTest(unittest.TestCase):
    def setUp(self):
        self.done: list[str] = []
        self.taken: list[list[str]] = []

    def make(self, keys, user32, hwnd=None):
        return HotkeySet(keys, self.done.append, self.taken.append, hwnd=hwnd, user32=user32)

    def test_held_only_while_active(self):
        user32 = FakeUser32()
        keys = self.make({"toggle": "Alt+F8", "reset": "Alt+F10"}, user32, hwnd=1234)
        self.assertEqual(user32.held, {})
        keys.set_active(True)
        self.assertEqual(len(user32.held), 2)
        self.assertTrue(all(hwnd == 1234 for hwnd, _, _ in user32.held.values()))
        # no repeats while a key is held down
        self.assertTrue(all(mods & 0x4000 for _, mods, _ in user32.held.values()))
        keys.set_active(False)
        self.assertEqual(user32.held, {})

    def test_a_hotkey_does_its_action(self):
        keys = self.make({"toggle": "Alt+F8", "reset": "Alt+F10"}, FakeUser32())
        keys.set_active(True)
        self.assertTrue(keys.handle(2))
        self.assertFalse(keys.handle(99))
        self.assertEqual(self.done, ["reset"])

    def test_keys_another_program_holds_are_said(self):
        user32 = FakeUser32(taken={hotkeys.parse("Alt+F10")[1]})
        keys = self.make({"toggle": "Alt+F8", "reset": "Alt+F10"}, user32)
        keys.set_active(True)
        self.assertEqual(self.taken, [["Alt+F10"]])
        self.assertEqual(len(user32.held), 1)

    def test_rebind_while_active(self):
        user32 = FakeUser32()
        keys = self.make({"toggle": "Alt+F8"}, user32)
        keys.set_active(True)
        keys.rebind({"toggle": "Ctrl+Alt+M"})
        self.assertEqual([key for _, _, key in user32.held.values()], [ord("M")])
        self.assertEqual(self.taken[-2], [])  # what was said about the old keys is taken back

    def test_refused_keys_are_kept_until_rebound(self):
        user32 = FakeUser32(taken={hotkeys.parse("Alt+F11")[1]})
        keys = self.make({"toggle": "Alt+F8", "move": "Alt+F11"}, user32)
        self.assertEqual(keys.refused, [])
        keys.set_active(True)
        self.assertEqual(keys.refused, ["Alt+F11"])
        keys.set_active(False)
        self.assertEqual(keys.refused, ["Alt+F11"])  # still another program's while the game is away
        keys.rebind({"toggle": "Alt+F8", "move": "Ctrl+Alt+M"})
        self.assertEqual(keys.refused, [])

    def test_unparsable_and_empty_keys_are_left_out(self):
        user32 = FakeUser32()
        keys = self.make({"toggle": "", "reset": "Banana", "move": "Alt+F11"}, user32)
        keys.set_active(True)
        self.assertEqual(len(user32.held), 1)


class ScreenTest(unittest.TestCase):
    SCREENS = [(0, 0, 2560, 1440), (2560, 0, 4480, 1080)]

    def test_on_a_screen(self):
        self.assertTrue(on_a_screen(40, 400, 424, 380, self.SCREENS))
        self.assertTrue(on_a_screen(3000, 100, 424, 380, self.SCREENS))  # the second monitor
        self.assertTrue(on_a_screen(2500, 100, 424, 380, self.SCREENS))  # over the seam

    def test_off_every_screen(self):
        self.assertFalse(on_a_screen(200, 6000, 424, 380, self.SCREENS))
        self.assertFalse(on_a_screen(-1000, 100, 424, 380, self.SCREENS))
        self.assertFalse(on_a_screen(2500, 1420, 424, 380, self.SCREENS))  # 20 px showing: not enough


class FromQtPixelsTest(unittest.TestCase):
    # as Qt 6.12 placed windows, measured 2026-11-24 (QT_SCREEN_SCALE_FACTORS="1.5;1.25"): each
    # monitor's top-left stays where Windows has it, the rest is divided by its scale
    MONITORS = [((0, 0, 2560, 1440), 1.5), ((-2560, 0, 0, 1440), 1.25)]

    def test_places_on_scaled_monitors(self):
        self.assertEqual(overlay_common.from_qt_pixels(1000, 600, self.MONITORS), (1500, 900))
        self.assertEqual(overlay_common.from_qt_pixels(100, 100, self.MONITORS), (150, 150))
        self.assertEqual(overlay_common.from_qt_pixels(-2000, 300, self.MONITORS), (-1860, 375))

    def test_at_100_percent_nothing_moves(self):
        self.assertEqual(overlay_common.from_qt_pixels(1000, 600, [((0, 0, 2560, 1440), 1.0)]), (1000, 600))

    def test_a_place_on_no_monitor_stays(self):
        # beyond the 150% monitor's 1707 Qt pixels: left for on_a_screen to judge
        self.assertEqual(overlay_common.from_qt_pixels(2000, 600, self.MONITORS), (2000, 600))


class GameInFrontTest(unittest.TestCase):
    GAME, OVERLAY, OTHER = 100, 200, 300

    def check(self, foreground, process=""):
        cfg = Config(log_dir="")
        with mock.patch("wwmeter.capture.find_game_window", return_value=self.GAME), \
                mock.patch("win32gui.GetForegroundWindow", return_value=foreground), \
                mock.patch.object(overlay_common, "process_name", return_value=process):
            return overlay_common.game_in_front(cfg)

    def test_the_game_in_front(self):
        self.assertTrue(self.check(self.GAME))

    def test_the_overlay_itself_is_not_the_game(self):
        # the tray menu brings the overlay's window to the front: it must not show the meter
        self.assertFalse(self.check(self.OVERLAY, "waveband.exe"))

    def test_nothing_in_front_is_not_the_game(self):
        # found in the 0.3.2 audit: "0 in (game, 0)" once read as the game in front
        self.assertFalse(self.check(0))

    def test_a_screenshot_tool_keeps_it_up(self):
        self.assertTrue(self.check(self.OTHER, "snippingtool.exe"))
        self.assertFalse(self.check(self.OTHER, "chrome.exe"))


class FakeOverlay:
    def __init__(self):
        self.moving = False
        self.wanted = True

    def set_moving(self, moving):
        self.moving = moving

    def toggle_wanted(self):
        self.wanted = not self.wanted

    def set_hidden_from_capture(self, hidden):
        self.hidden = hidden


class ControlsTest(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(log_dir="")
        self.overlay = FakeOverlay()
        self.said: list[str] = []
        self.calls: list = []
        self.saved = mock.patch.object(overlay_common.config_mod, "save").start()
        self.addCleanup(mock.patch.stopall)
        self.controls = Controls(
            cfg=self.cfg, overlay=self.overlay, notify=lambda text, ms: self.said.append(text),
            quit=lambda: self.calls.append("quit"), on_reset=lambda: self.calls.append("reset"),
            dashboard_url="http://127.0.0.1:5055/?view=full",
            on_view=self.calls.append, on_copy=lambda: self.calls.append("copy"),
            list_sessions=lambda: [{"file": "a.json", "label": "Monday", "fights": 1, "last": "Crownless"}],
            open_session=lambda chosen: self.calls.append(("open", chosen)),
            themes=lambda: ["wuwa", "classic"], theme_label=str.title,
        )

    def find(self, items, text):
        return next(item for item in items if item.text == text)

    def test_actions(self):
        self.controls.dispatch("older")
        self.controls.dispatch("newer")
        self.controls.dispatch("reset")
        self.controls.dispatch("copy")
        self.assertEqual(self.calls, [-1, 1, "reset", "copy"])
        self.controls.dispatch("move")
        self.assertTrue(self.overlay.moving)
        self.controls.dispatch("toggle")
        self.assertFalse(self.overlay.wanted)

    def test_switches_are_saved(self):
        self.controls.dispatch("unit")
        self.controls.dispatch("compact")
        self.assertEqual(self.cfg.display_unit, "percent")
        self.assertTrue(self.cfg.compact)
        self.assertEqual(self.saved.call_count, 2)

    def test_capture_says_what_it_did(self):
        self.controls.dispatch("capture")
        self.assertTrue(self.overlay.hidden)
        self.assertEqual(len(self.said), 1)

    def test_menu_shows_keys_and_ticks(self):
        self.cfg.hide_between_fights = True
        self.cfg.hotkeys = dict(self.cfg.hotkeys, rest="Ctrl+Alt+H")
        items = self.controls.items()
        rest = self.find(items, "Hide the meter between fights")
        self.assertTrue(rest.checked)
        self.assertEqual(rest.key, "Ctrl+Alt+H")
        self.assertEqual(items[-1].text, "Quit")
        self.assertTrue(items[-2].separator)
        rest.action()
        self.assertFalse(self.cfg.hide_between_fights)

    def test_the_short_menu(self):
        # owner, 2026-11-18: what has a key or a place in the dashboard stays out
        texts = [item.text for item in self.controls.items() if not item.separator]
        self.assertEqual(texts, [
            "Copy this fight's summary", "Earlier sessions", "Hide the meter between fights",
            "Hide from screenshots and streams", "Show the keybinds on the meter", "Theme",
            "Open the dashboard in a browser", "Settings: keybinds, colours, log folder", "Quit",
        ])

    def test_moving_is_listed_when_it_has_no_key_or_to_lock(self):
        listed = lambda: any(i.text == "Move or resize the overlay" for i in self.controls.items())  # noqa: E731
        self.assertFalse(listed())
        self.overlay.moving = True
        self.assertTrue(listed())  # to lock it again
        self.overlay.moving = False
        self.cfg.hotkeys = dict(self.cfg.hotkeys, move="")
        self.assertTrue(listed())

    def test_moving_is_listed_when_its_key_does_not_work(self):
        # a key set but refused (another program holds it) or kept from the meter by the game
        listed = lambda: any(i.text == "Move or resize the overlay" for i in self.controls.items())  # noqa: E731
        works = {"Alt+F11": True}
        self.controls.key_works = lambda name: works.get(name, True)
        self.assertFalse(listed())
        works["Alt+F11"] = False
        self.assertTrue(listed())

    def test_submenus_are_made_when_opened(self):
        items = self.controls.items()
        themes = self.find(items, "Theme").children()
        self.assertEqual([(t.text, t.checked) for t in themes], [("Wuwa", True), ("Classic", False)])
        themes[1].action()
        self.assertEqual(self.cfg.theme, "classic")
        sessions = self.find(items, "Earlier sessions").children()
        self.assertEqual(sessions[0].text, "Back to this session")
        self.assertIn("Monday", sessions[2].text)
        sessions[2].action()
        self.assertEqual(self.calls[-1], ("open", "a.json"))

    def test_update_entry_names_the_version(self):
        self.controls.app_actions = {"available": lambda: "0.3.2", "install": lambda: "Downloading",
                                     "check": lambda: "Looking", "said": lambda: None}
        entry = next(item for item in self.controls.items() if item.text.startswith("Install update"))
        self.assertEqual(entry.text, "Install update (0.3.2)")
        entry.action()
        self.assertEqual(self.said, ["Downloading"])

    def test_poll_says_each_thing_once(self):
        said = ["Boss HP tables updated."]
        self.controls.update_finished = lambda: said.pop(0) if said else None
        self.controls.poll()
        self.controls.poll()
        self.assertEqual(self.said, ["Boss HP tables updated."])


class MoveScriptTest(unittest.TestCase):
    def test_names_the_lock_key(self):
        cfg = Config(log_dir="")
        script = move_script(cfg, True)
        self.assertIn(f"{hotkeys.bindings(cfg.hotkeys)['move']} locks it.", script)
        self.assertIn("toggle('moving', true)", script)

    def test_without_a_move_key(self):
        cfg = Config(log_dir="")
        cfg.hotkeys = dict(cfg.hotkeys, move="")
        self.assertIn("Lock it from the tray menu.", move_script(cfg, False))


class ItemTest(unittest.TestCase):
    def test_separator(self):
        self.assertTrue(Item().separator)
        self.assertFalse(Item("None yet", enabled=False).separator)


if __name__ == "__main__":
    unittest.main()
