import base64
import json
import os
import tempfile
import unittest
import zlib
from unittest import mock

from wwmeter import config as config_mod
from wwmeter import hotkeys, settings
from wwmeter.config import Config

THEMES = ["wuwa", "classic"]
LANGUAGES = ["en", "ja", "ko"]


def apply(cfg, changes):
    return settings.apply(cfg, changes, THEMES, LANGUAGES)


def line_of(data) -> str:
    """A line as ``settings.export`` packs one, of anything."""
    packed = zlib.compress(json.dumps(data).encode("utf-8"), 9)
    return "wwmeter1:" + base64.urlsafe_b64encode(packed).decode("ascii").rstrip("=")


class ApplyTest(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(log_dir=r"C:\nowhere\Logs")

    def test_the_figures_of_a_row_are_a_list_in_order(self):
        self.assertEqual(self.cfg.row_figures, ["dps", "share"])
        wanted = ["field_time", "dps", "field_dps"]
        self.assertEqual(apply(self.cfg, {"row_figures": wanted}), ({"row_figures"}, []))
        self.assertEqual(self.cfg.row_figures, wanted)
        for bad in (["dps", "dps"], ["speed"], "dps", [], [1], None):
            changed, refused = apply(self.cfg, {"row_figures": bad})
            self.assertEqual((changed, len(refused)), (set(), 1), bad)
            self.assertTrue(refused[0].startswith("The figures on a row: "), refused)
        self.assertEqual(self.cfg.row_figures, wanted)

    def test_decimals_are_none_to_two(self):
        changed, refused = apply(self.cfg, {"figure_decimals": 1, "share_decimals": 2.0})
        self.assertEqual((changed, refused), ({"figure_decimals", "share_decimals"}, []))
        self.assertEqual((self.cfg.figure_decimals, self.cfg.share_decimals), (1, 2))
        self.assertEqual(len(apply(self.cfg, {"figure_decimals": 3, "share_decimals": -1})[1]), 2)
        self.assertEqual((self.cfg.figure_decimals, self.cfg.share_decimals), (1, 2))

    def test_nonsense_in_the_file_shows_as_the_usual_figures(self):
        self.cfg.row_figures = ["dps", "nonsense"]
        self.cfg.figure_decimals = "many"
        self.cfg.share_decimals = 7
        shown = settings.describe(self.cfg, ["wuwa"], ["en"])
        self.assertEqual(shown["row_figures"], ["dps", "share"])
        self.assertEqual((shown["figure_decimals"], shown["share_decimals"]), (2, 0))
        self.assertEqual([f["name"] for f in shown["figures"]],
                         ["dps", "damage", "share", "field_time", "field_dps"])
        self.assertIn("off field", shown["figures"][-1]["note"])

    def test_a_change_is_taken_and_named(self):
        changed, refused = apply(self.cfg, {"theme": "classic", "compact": True, "display_unit": "percent"})
        self.assertEqual(changed, {"theme", "compact", "display_unit"})
        self.assertEqual(refused, [])
        self.assertEqual((self.cfg.theme, self.cfg.compact, self.cfg.display_unit), ("classic", True, "percent"))

    def test_a_setting_given_the_value_it_has_did_not_change(self):
        self.assertEqual(apply(self.cfg, {"theme": self.cfg.theme, "compact": False}), (set(), []))

    def test_a_refused_setting_is_left_and_the_rest_are_taken(self):
        changed, refused = apply(self.cfg, {"theme": "neon", "show_keys": False})
        self.assertEqual(changed, {"show_keys"})
        self.assertEqual(refused, ["The theme: has to be one of: wuwa, classic."])
        self.assertEqual(self.cfg.theme, "wuwa")

    def test_what_is_not_a_setting_is_passed_over(self):
        port = self.cfg.port
        self.assertEqual(apply(self.cfg, {"port": 80, "made_up": 1, "log_path": "x"}), (set(), []))
        self.assertEqual(self.cfg.port, port)
        self.assertEqual(apply(self.cfg, ["theme", "classic"]), (set(), ["That is not a set of settings."]))

    def test_a_switch_has_to_be_on_or_off(self):
        for value in (1, "true", None):
            changed, refused = apply(self.cfg, {"hide_from_capture": value})
            self.assertEqual(changed, set())
            self.assertEqual(refused, ["Hiding from screenshots: has to be on or off."])
        self.assertFalse(self.cfg.hide_from_capture)

    def test_the_size_stays_within_what_the_window_allows(self):
        self.assertEqual(apply(self.cfg, {"overlay_zoom": 1.234})[0], {"overlay_zoom"})
        self.assertEqual(self.cfg.overlay_zoom, 1.23)
        for value in (0.1, 9, "big", True, float("nan")):
            changed, refused = apply(self.cfg, {"overlay_zoom": value})
            self.assertEqual(changed, set(), value)
            self.assertEqual(len(refused), 1, value)
        self.assertEqual(self.cfg.overlay_zoom, 1.23)

    def test_names_follow_the_game_or_a_language_the_tables_have(self):
        self.assertEqual(apply(self.cfg, {"language": "ja"})[0], {"language"})
        self.assertEqual(apply(self.cfg, {"language": "tlh"})[0], set())
        self.assertEqual(self.cfg.language, "ja")
        self.assertEqual(apply(self.cfg, {"language": ""})[0], {"language"})

    def test_a_log_folder_that_is_not_there_is_refused(self):
        changed, refused = apply(self.cfg, {"log_dir": r"Q:\no\such\folder"})
        self.assertEqual((changed, refused), (set(), ["The log folder: there is no such folder."]))
        self.assertEqual(self.cfg.log_dir, r"C:\nowhere\Logs")
        self.assertEqual(apply(self.cfg, {"log_dir": 5})[0], set())


class KeysTest(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(log_dir=r"C:\nowhere\Logs")

    def test_a_key_is_written_one_way_and_the_others_are_kept(self):
        changed, refused = apply(self.cfg, {"hotkeys": {"copy": "alt + control + c"}})
        self.assertEqual((changed, refused), ({"hotkeys"}, []))
        self.assertEqual(self.cfg.hotkeys["copy"], "Ctrl+Alt+C")
        self.assertEqual(self.cfg.hotkeys["toggle"], "F8")
        self.assertEqual(set(self.cfg.hotkeys), set(hotkeys.DEFAULTS))

    def test_a_key_another_action_has_is_refused_by_name(self):
        changed, refused = apply(self.cfg, {"hotkeys": {"reset": "f8"}})
        self.assertEqual(changed, set())
        self.assertEqual(refused, ['F8 is already the key for "Show or hide the meter".'])
        self.assertEqual(self.cfg.hotkeys["reset"], "F10")

    def test_two_actions_can_trade_keys_in_one_change(self):
        changed, refused = apply(self.cfg, {"hotkeys": {"toggle": "F10", "reset": "F8"}})
        self.assertEqual((changed, refused), ({"hotkeys"}, []))
        self.assertEqual((self.cfg.hotkeys["toggle"], self.cfg.hotkeys["reset"]), ("F10", "F8"))

    def test_a_freed_key_can_be_given_to_another_action(self):
        apply(self.cfg, {"hotkeys": {"toggle": ""}})
        self.assertEqual(self.cfg.hotkeys["toggle"], "")
        self.assertEqual(apply(self.cfg, {"hotkeys": {"reset": "F8"}}), ({"hotkeys"}, []))

    def test_any_number_of_actions_can_have_no_key(self):
        changed, refused = apply(self.cfg, {"hotkeys": {"toggle": "", "reset": "", "move": ""}})
        self.assertEqual((changed, refused), ({"hotkeys"}, []))

    def test_what_is_not_a_key_is_refused(self):
        for key in ("Banana", "Ctrl+", 7, None):
            changed, refused = apply(self.cfg, {"hotkeys": {"reset": key}})
            self.assertEqual(changed, set(), key)
            self.assertEqual(len(refused), 1, key)
        self.assertEqual(apply(self.cfg, {"hotkeys": "F8"})[0], set())
        self.assertEqual(self.cfg.hotkeys["reset"], "F10")

    def test_an_action_this_version_does_not_have_is_passed_over(self):
        self.assertEqual(apply(self.cfg, {"hotkeys": {"dance": "F12"}}), (set(), []))
        self.assertNotIn("dance", self.cfg.hotkeys)

    def test_back_to_the_usual_keys(self):
        apply(self.cfg, {"hotkeys": {"toggle": "F10", "reset": "F8", "copy": "Ctrl+Alt+C"}})
        self.assertEqual(apply(self.cfg, {"hotkeys": dict(hotkeys.DEFAULTS)}), ({"hotkeys"}, []))
        self.assertEqual(self.cfg.hotkeys, hotkeys.DEFAULTS)

    def test_a_table_from_an_older_version_gets_the_newer_actions(self):
        self.cfg.hotkeys = {"toggle": "F8", "reset": "F10"}
        apply(self.cfg, {"hotkeys": {"reset": "F12"}})
        self.assertEqual(set(self.cfg.hotkeys), set(hotkeys.DEFAULTS))
        self.assertEqual(self.cfg.hotkeys["older"], "F7")


class ColoursTest(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(log_dir=r"C:\nowhere\Logs")

    def test_a_colour_is_kept_per_element(self):
        self.assertEqual(apply(self.cfg, {"colours": {"glacio": "#12ABef"}}), ({"colours"}, []))
        apply(self.cfg, {"colours": {"havoc": "#000000"}})
        self.assertEqual(self.cfg.colours, {"glacio": "#12abef", "havoc": "#000000"})

    def test_an_empty_colour_gives_the_element_back_the_themes(self):
        apply(self.cfg, {"colours": {"glacio": "#12abef", "havoc": "#000000"}})
        self.assertEqual(apply(self.cfg, {"colours": {"glacio": ""}})[0], {"colours"})
        self.assertEqual(self.cfg.colours, {"havoc": "#000000"})

    def test_what_is_not_a_colour_is_refused(self):
        for colour in ("red", "#fff", "#12abeg", "url(http://example.invalid/)", 5):
            changed, refused = apply(self.cfg, {"colours": {"glacio": colour}})
            self.assertEqual(changed, set(), colour)
            self.assertEqual(len(refused), 1, colour)
        self.assertEqual(self.cfg.colours, {})

    def test_only_the_six_elements_have_colours(self):
        self.assertEqual(apply(self.cfg, {"colours": {"wave-rgb": "#ffffff"}}), (set(), []))
        self.cfg.colours = {"bone": "#ffffff", "aero": "#00ff00"}  # a file edited by hand
        apply(self.cfg, {"colours": {"fusion": "#ff0000"}})
        self.assertEqual(self.cfg.colours, {"aero": "#00ff00", "fusion": "#ff0000"})


class LogFolderTest(unittest.TestCase):
    def test_the_folder_is_found_from_what_people_paste(self):
        with tempfile.TemporaryDirectory() as folder:
            launcher = os.path.join(folder, "Wuthering Waves")
            game = os.path.join(launcher, "Wuthering Waves Game")
            logs = os.path.join(game, "Client", "Saved", "Logs")
            os.makedirs(logs)
            log = os.path.join(logs, "Client.log")
            open(log, "w").close()
            for pasted in (logs, log, game, launcher, f'"{logs}"', f"  {logs}\\ \n", os.path.join(game, "Client")):
                self.assertEqual(settings.log_folder(pasted), logs, pasted)

    def test_a_folder_with_no_log_in_it_yet_is_taken_as_it_is(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(settings.log_folder(folder), os.path.abspath(folder))

    def test_what_is_not_a_folder(self):
        for pasted in ("", "   ", None, r"Q:\no\such\folder", "a\x00b"):
            self.assertIsNone(settings.log_folder(pasted), pasted)

    def test_a_pasted_folder_becomes_the_log_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            logs = os.path.join(folder, "Client", "Saved", "Logs")
            os.makedirs(logs)
            cfg = Config(log_dir=r"C:\nowhere\Logs")
            self.assertEqual(apply(cfg, {"log_dir": folder}), ({"log_dir"}, []))
            self.assertEqual(cfg.log_dir, logs)


class LineTest(unittest.TestCase):
    def changed_config(self) -> Config:
        cfg = Config(log_dir=r"C:\Users\somebody\Wuthering Waves\Client\Saved\Logs", port=6123)
        apply(cfg, {
            "theme": "classic", "display_unit": "percent", "overlay_zoom": 1.4, "compact": True,
            "language": "ja", "hide_between_fights": True,
            "hotkeys": {"copy": "Ctrl+Alt+C", "toggle": "F12"},
            "colours": {"glacio": "#112233", "havoc": "#445566"},
        })
        return cfg

    def test_the_line_leaves_out_what_belongs_to_this_pc(self):
        line = settings.export(self.changed_config())
        self.assertTrue(line.startswith("wwmeter1:"))
        self.assertNotIn("\n", line)
        body = line.split(":", 1)[1]
        raw = zlib.decompress(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))).decode("utf-8")
        self.assertNotIn("somebody", raw)
        self.assertNotIn("6123", raw)
        data = json.loads(raw)
        self.assertNotIn("log_dir", data)
        self.assertNotIn("port", data)
        self.assertNotIn("seen_version", data)
        self.assertEqual(data["theme"], "classic")

    def test_a_line_does_not_change_which_version_this_pc_last_ran(self):
        source = self.changed_config()
        source.seen_version = "0.9.0"
        target = Config(log_dir=r"D:\Games\Logs", seen_version="0.2.0")
        settings.take_line(target, settings.export(source), ["wuwa", "classic"], ["en", "ja"])
        self.assertEqual(target.seen_version, "0.2.0")
        self.assertEqual(apply(target, {"seen_version": "0.1.0"})[0], set())
        self.assertEqual(target.seen_version, "0.2.0")

    def test_a_line_carries_the_settings_to_another_pc(self):
        source = self.changed_config()
        target = Config(log_dir=r"D:\Games\Logs", port=5055)
        changed, refused = settings.take_line(target, settings.export(source), THEMES, LANGUAGES)
        self.assertEqual(refused, [])
        self.assertIn("hotkeys", changed)
        self.assertNotIn("log_dir", changed)
        self.assertEqual((target.log_dir, target.port), (r"D:\Games\Logs", 5055))
        for name in ("theme", "display_unit", "overlay_zoom", "compact", "language",
                     "hide_between_fights", "hotkeys", "colours"):
            self.assertEqual(getattr(target, name), getattr(source, name), name)
        self.assertEqual(settings.take_line(target, settings.export(source), THEMES, LANGUAGES), (set(), []))

    def test_a_line_puts_back_what_it_has_at_the_default(self):
        target = self.changed_config()
        settings.take_line(target, settings.export(Config(log_dir="x")), THEMES, LANGUAGES)
        self.assertEqual(target.hotkeys, hotkeys.DEFAULTS)
        self.assertEqual(target.colours, {})
        self.assertEqual((target.theme, target.compact, target.language), ("wuwa", False, ""))

    def test_a_line_cannot_move_the_log_folder_or_the_port(self):
        target = Config(log_dir=r"D:\Games\Logs", port=5055)
        with tempfile.TemporaryDirectory() as folder:
            line = line_of({"log_dir": folder, "port": 80, "compact": True})
            self.assertEqual(settings.read_line(line), {"compact": True})
            self.assertEqual(settings.take_line(target, line, THEMES, LANGUAGES), ({"compact"}, []))
        self.assertEqual((target.log_dir, target.port), (r"D:\Games\Logs", 5055))

    def test_a_line_is_checked_like_any_other_change(self):
        target = Config(log_dir="x")
        line = line_of({"theme": "neon", "overlay_zoom": 50, "show_keys": False, "colours": {"aero": "red"}})
        changed, refused = settings.take_line(target, line, THEMES, LANGUAGES)
        self.assertEqual(changed, {"show_keys"})
        self.assertEqual(len(refused), 3)
        self.assertEqual((target.theme, target.overlay_zoom, target.colours), ("wuwa", 1.0, {}))

    def test_a_key_the_line_gives_twice_goes_to_the_first_action(self):
        target = Config(log_dir="x")
        line = line_of({"hotkeys": {"toggle": "F8", "reset": "f8", "move": "Banana", "dance": "F12"}})
        changed, refused = settings.take_line(target, line, THEMES, LANGUAGES)
        self.assertEqual((changed, refused), ({"hotkeys"}, []))
        self.assertEqual((target.hotkeys["toggle"], target.hotkeys["reset"], target.hotkeys["move"]), ("F8", "", ""))
        self.assertEqual(target.hotkeys["older"], "F7")  # left out of the line: kept
        self.assertNotIn("dance", target.hotkeys)

    def test_a_line_broken_on_the_way_is_put_together_again(self):
        line = settings.export(self.changed_config())
        broken = "  " + line[:30] + "\r\n" + line[30:80] + " " + line[80:] + "\n"
        self.assertEqual(settings.read_line(broken), settings.read_line(line))

    def test_what_is_not_a_line_of_settings(self):
        for text in ("", None, "hello", "https://example.invalid/", 5):
            with self.assertRaises(settings.Refused) as refused:
                settings.read_line(text)
            self.assertIn("not a line of meter settings", str(refused.exception))

    def test_a_damaged_line_says_so(self):
        line = settings.export(self.changed_config())
        damaged = (
            line[: len(line) // 2],  # cut short
            "wwmeter1:",
            "wwmeter1:!!!!",
            "wwmeter1:" + base64.urlsafe_b64encode(b"not packed").decode("ascii"),
            line_of(["a", "list"]),
            line_of("a text"),
        )
        for text in damaged:
            with self.assertRaises(settings.Refused, msg=text[:40]) as refused:
                settings.read_line(text)
            self.assertIn("damaged", str(refused.exception))

    def test_words_pasted_after_the_line_do_not_change_what_it_holds(self):
        # the packed settings carry a checksum, so what is read is what was written or nothing
        line = settings.export(self.changed_config())
        self.assertEqual(settings.read_line(line + "AAAA"), settings.read_line(line))

    def test_a_line_that_unpacks_to_far_too_much_is_refused(self):
        with self.assertRaises(settings.Refused):
            settings.read_line(line_of({"theme": "a" * 2_000_000}))  # a few thousand characters packed
        with self.assertRaises(settings.Refused) as refused:
            settings.read_line("wwmeter1:" + "A" * 50_000)
        self.assertIn("too long", str(refused.exception))


class DescribeTest(unittest.TestCase):
    def test_what_the_page_is_given(self):
        cfg = Config(log_dir=r"C:\nowhere\Logs", language="tlh")
        apply(cfg, {"hotkeys": {"copy": "ctrl+alt+c"}, "colours": {"aero": "#00ff00"}})
        shown = settings.describe(cfg, THEMES, LANGUAGES, "ko")
        self.assertEqual([item["action"] for item in shown["hotkeys"]], list(hotkeys.DEFAULTS))
        copy = shown["hotkeys"][-1]
        self.assertEqual((copy["key"], copy["default"], copy["label"]), ("Ctrl+Alt+C", "", "Copy the fight's summary"))
        self.assertEqual(shown["colours"], {"aero": "#00ff00"})
        self.assertEqual(shown["themes"], [{"name": "wuwa", "label": "WuWa"}, {"name": "classic", "label": "Classic"}])
        self.assertEqual(shown["language"], "")  # one the tables do not have is shown as the game's
        self.assertEqual(shown["languages"][1], {"code": "ja", "label": "日本語"})
        self.assertEqual(shown["game_language"], "한국어")
        self.assertFalse(shown["log_found"])
        self.assertEqual(settings.read_line(shown["line"])["theme"], cfg.theme)
        json.dumps(shown)  # it goes to the page as JSON

    def test_every_action_has_words_for_the_page(self):
        self.assertEqual(set(hotkeys.LABELS), set(hotkeys.DEFAULTS))

    def test_the_themes_on_disk_are_offered_with_the_usual_one_first(self):
        themes = settings.available_themes()
        self.assertEqual(themes[0], "wuwa")
        self.assertIn("classic", themes)


class ConfigFileTest(unittest.TestCase):
    def test_settings_are_written_whole_and_read_back(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "config.json")
            with mock.patch.object(config_mod, "CONFIG_PATH", path):
                cfg = Config(log_dir=os.path.join(folder, "ログ"))
                cfg.colours = {"glacio": "#112233"}
                cfg.hotkeys["copy"] = "Ctrl+Alt+C"
                config_mod.save(cfg)
                config_mod.save(cfg)  # over a file that is there
                self.assertEqual(os.listdir(folder), ["config.json"])
                with open(path, encoding="utf-8") as fh:
                    self.assertIn("ログ", fh.read())
                back = config_mod.load()
            self.assertEqual(back, cfg)


if __name__ == "__main__":
    unittest.main()
