import unittest

from wwmeter import hotkeys
from wwmeter.config import Config


class ParseTest(unittest.TestCase):
    def test_function_keys(self):
        self.assertEqual(hotkeys.parse("F1"), (0, 0x70))
        self.assertEqual(hotkeys.parse("f8"), (0, 0x77))
        self.assertEqual(hotkeys.parse(" F11 "), (0, 0x7A))
        self.assertEqual(hotkeys.parse("F24"), (0, 0x87))
        self.assertIsNone(hotkeys.parse("F25"))
        self.assertIsNone(hotkeys.parse("F0"))

    def test_modifiers_and_plain_keys(self):
        ctrl_alt = hotkeys.MOD_CONTROL | hotkeys.MOD_ALT
        self.assertEqual(hotkeys.parse("Ctrl+Alt+M"), (ctrl_alt, ord("M")))
        self.assertEqual(hotkeys.parse("alt + control + m"), (ctrl_alt, ord("M")))
        self.assertEqual(hotkeys.parse("Shift+F9"), (hotkeys.MOD_SHIFT, 0x78))
        self.assertEqual(hotkeys.parse("5"), (0, ord("5")))
        self.assertEqual(hotkeys.parse("Home"), (0, 0x24))

    def test_what_cannot_be_a_hotkey(self):
        for text in ("", None, "Ctrl+", "+F8", "Hyper+F8", "F8+Ctrl", "Banana", "é"):
            self.assertIsNone(hotkeys.parse(text), text)


class SpellTest(unittest.TestCase):
    def test_a_key_is_written_one_way(self):
        self.assertEqual(hotkeys.spell("alt + control + m"), "Ctrl+Alt+M")
        self.assertEqual(hotkeys.spell("shift+ctrl+f9"), "Ctrl+Shift+F9")
        self.assertEqual(hotkeys.spell(" f8 "), "F8")
        self.assertEqual(hotkeys.spell("win+pageup"), "Win+PageUp")
        self.assertEqual(hotkeys.spell("SCROLLLOCK"), "ScrollLock")
        self.assertEqual(hotkeys.spell("5"), "5")

    def test_no_key_and_not_a_key(self):
        for text in ("", "   ", None):
            self.assertEqual(hotkeys.spell(text), "")
        for text in ("Banana", "Ctrl+", "F25", "F8+Ctrl"):
            self.assertIsNone(hotkeys.spell(text), text)

    def test_the_spelling_means_the_same_key(self):
        for text in ("alt + control + m", "shift+f7", "home", "Ctrl+Win+Delete"):
            self.assertEqual(hotkeys.parse(hotkeys.spell(text)), hotkeys.parse(text), text)
        for key in hotkeys.DEFAULTS.values():
            self.assertEqual(hotkeys.spell(key), key)


class BindingsTest(unittest.TestCase):
    def test_defaults_are_function_keys_the_game_leaves_alone(self):
        keys = hotkeys.bindings(None)
        self.assertEqual(
            set(keys),
            {"older", "newer", "toggle", "compact", "unit", "reset", "move", "capture", "hints",
             "rest", "copy"},
        )
        game_keys = {f"F{n}" for n in range(1, 7)}  # F1-F4 open menus, F1-F6 switch menu tabs
        self.assertEqual(keys.pop("capture"), "")  # too easy to trip: tray menu only
        for tray_only in ("hints", "rest", "copy"):  # a key can be given in config.json
            self.assertEqual(keys.pop(tray_only), "")
        shifted = {"newer", "compact"}  # the second use of a key: the same key with Shift
        for action, key in keys.items():
            modifiers = hotkeys.parse(key)[0]
            self.assertEqual(modifiers, hotkeys.MOD_SHIFT if action in shifted else 0, action)
            self.assertNotIn(key.split("+")[-1], game_keys | {"F12"}, action)
        self.assertEqual(len(set(keys.values())), len(keys))

    def test_config_overrides_one_action_and_keeps_the_rest(self):
        keys = hotkeys.bindings({"reset": "Ctrl+Alt+R"})
        self.assertEqual(keys["reset"], "Ctrl+Alt+R")
        self.assertEqual(keys["toggle"], hotkeys.DEFAULTS["toggle"])

    def test_an_empty_or_unreadable_key_leaves_the_action_without_a_hotkey(self):
        keys = hotkeys.bindings({"reset": "", "move": "Banana", "nonsense": "F8", "capture": "Pause"})
        self.assertEqual((keys["reset"], keys["move"], keys["capture"]), ("", "", "Pause"))
        self.assertNotIn("nonsense", keys)

    def test_a_key_given_twice_goes_to_the_first_action_only(self):
        keys = hotkeys.bindings({"unit": "f8"})  # toggle already has F8
        self.assertEqual((keys["toggle"], keys["unit"]), ("F8", ""))

    def test_the_line_of_keys_lists_only_actions_that_have_a_key(self):
        self.assertEqual(
            hotkeys.hints(None),
            [{"key": "F7", "label": "earlier"}, {"key": "F8", "label": "hide"},
             {"key": "F9", "label": "dmg / %"}, {"key": "F10", "label": "new fight"},
             {"key": "F11", "label": "move"}],
        )
        changed = hotkeys.hints({"reset": "", "capture": "Pause", "move": "Ctrl+Alt+M"})
        self.assertEqual([hint["key"] for hint in changed], ["F7", "F8", "F9", "Ctrl+Alt+M", "Pause"])
        self.assertTrue(Config().show_keys)  # shown unless switched off

    def test_the_two_shift_keys_are_left_out_of_the_line_of_keys(self):
        self.assertEqual(hotkeys.bindings(None)["newer"], "Shift+F7")
        self.assertNotIn("Shift+F7", [hint["key"] for hint in hotkeys.hints(None)])

    def test_an_update_does_not_take_a_key_the_user_had_chosen(self):
        # written by 0.1, where F7 was free and the user gave it to "capture"
        old = {"toggle": "F8", "unit": "F9", "reset": "F10", "move": "F11", "capture": "F7", "hints": ""}
        merged = hotkeys.with_new_actions(old)
        self.assertEqual(list(merged), list(hotkeys.DEFAULTS))  # every action is listed
        self.assertEqual((merged["capture"], merged["older"]), ("F7", ""))
        self.assertEqual((merged["newer"], merged["compact"]), ("Shift+F7", "Shift+F8"))
        keys = hotkeys.bindings(merged)
        self.assertEqual((keys["capture"], keys["older"]), ("F7", ""))

    def test_a_key_another_program_holds_is_found(self):
        import ctypes

        user32 = ctypes.windll.user32
        rare = "Ctrl+Alt+Shift+F24"  # nothing uses it, and no keyboard has the key
        self.assertEqual(hotkeys.in_use([rare, "", "Banana"]), [])
        modifiers, key = hotkeys.parse(rare)
        self.assertTrue(user32.RegisterHotKey(None, 0xB7F0, modifiers, key))
        try:
            self.assertEqual(hotkeys.in_use(["Ctrl+Alt+Shift+F23", rare]), [rare])
        finally:
            user32.UnregisterHotKey(None, 0xB7F0)
        self.assertEqual(hotkeys.in_use([rare]), [])  # and the check itself keeps nothing

    def test_a_fresh_config_carries_the_defaults(self):
        self.assertEqual(Config().hotkeys, hotkeys.DEFAULTS)
        self.assertIsNot(Config().hotkeys, hotkeys.DEFAULTS)


if __name__ == "__main__":
    unittest.main()
