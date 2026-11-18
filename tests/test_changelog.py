"""CHANGELOG.md as the meter reads it, and what counts as news after an update."""

import os
import tempfile
import unittest

from wwmeter import __version__, changelog

TEXT = """# What changed

Some words before the first version, with a - dash in them.

## 0.3.0 (not released yet)

- One thing, written
  over two lines.
- Another thing.

Words between items are passed over.

- A third.

## 0.2.0 (2026-12-01)

- Settings page.

### A smaller heading is not a version

## 0.1.0

- The first version.
"""


class ParseTest(unittest.TestCase):
    def test_versions_come_in_the_order_written_with_their_notes(self):
        versions = changelog.parse(TEXT)
        self.assertEqual([v["version"] for v in versions], ["0.3.0", "0.2.0", "0.1.0"])
        self.assertEqual(versions[0]["when"], "not released yet")
        self.assertEqual(versions[1]["when"], "2026-12-01")
        self.assertEqual(versions[2]["when"], "")
        self.assertEqual(
            versions[0]["notes"], ["One thing, written over two lines.", "Another thing.", "A third."]
        )
        self.assertEqual(versions[1]["notes"], ["Settings page."])

    def test_text_that_is_no_changelog_gives_nothing(self):
        self.assertEqual(changelog.parse(""), [])
        self.assertEqual(changelog.parse("- an item under no version\njust words\n"), [])

    def test_windows_line_ends_read_the_same(self):
        self.assertEqual(changelog.parse(TEXT.replace("\n", "\r\n")), changelog.parse(TEXT))

    def test_a_missing_file_gives_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(changelog.read(os.path.join(folder, "CHANGELOG.md")), [])


class VersionTest(unittest.TestCase):
    def test_versions_compare_by_their_numbers(self):
        self.assertLess(changelog.key("0.1.0"), changelog.key("0.2.0"))
        self.assertLess(changelog.key("0.9.0"), changelog.key("0.10.0"))
        self.assertLess(changelog.key("0.2.0"), changelog.key("0.2.1"))
        self.assertEqual(changelog.key("0.2"), changelog.key("0.2.0"))

    def test_a_build_on_the_way_to_a_version_is_that_version(self):
        self.assertEqual(changelog.key("0.2.0.dev0"), changelog.key("0.2.0"))

    def test_what_is_not_a_version_sorts_before_every_version(self):
        for odd in ("", "soon", None, 7, ["0.2.0"]):
            self.assertEqual(changelog.key(odd), ())


class NewsTest(unittest.TestCase):
    def setUp(self):
        self.versions = changelog.parse(TEXT)

    def told(self, seen, had_settings, current):
        before = changelog.last_run(seen, had_settings)
        return [v["version"] for v in changelog.news(self.versions, before, current)]

    def test_settings_from_the_first_version_get_the_notes_since(self):
        # 0.1.0 wrote no version into its settings file
        self.assertEqual(self.told("", True, "0.2.0"), ["0.2.0"])
        self.assertEqual(self.told("", True, "0.3.0"), ["0.3.0", "0.2.0"])

    def test_the_second_start_of_a_version_has_no_news(self):
        self.assertEqual(self.told("0.2.0", True, "0.2.0"), [])

    def test_a_first_start_has_no_news(self):
        self.assertIsNone(changelog.last_run("", False))
        self.assertEqual(self.told("", False, "0.3.0"), [])

    def test_notes_of_versions_after_the_one_running_are_left_out(self):
        self.assertEqual(self.told("0.1.0", True, "0.2.0"), ["0.2.0"])

    def test_an_older_version_started_after_a_newer_one_has_no_news(self):
        self.assertEqual(self.told("0.3.0", True, "0.2.0"), [])

    def test_a_build_on_the_way_shows_its_versions_notes_and_the_release_does_not_repeat_them(self):
        self.assertEqual(self.told("0.2.0", True, "0.3.0.dev0"), ["0.3.0"])
        self.assertEqual(self.told("0.3.0.dev0", True, "0.3.0"), [])

    def test_a_damaged_version_in_the_settings_counts_as_none(self):
        for odd in ("soon", 7, None, {"a": 1}):
            self.assertEqual(changelog.last_run(odd, True), changelog.FIRST_OUT)
            self.assertIsNone(changelog.last_run(odd, False))


class OwnChangelogTest(unittest.TestCase):
    """The file that ships. A version with no notes would be an update that says nothing."""

    def setUp(self):
        self.versions = changelog.read()

    def test_the_newest_notes_are_for_the_version_in_the_source(self):
        self.assertTrue(self.versions, "CHANGELOG.md is missing or has no versions")
        self.assertEqual(changelog.key(self.versions[0]["version"]), changelog.key(__version__))

    def test_versions_are_newest_first_and_each_has_notes(self):
        keys = [changelog.key(v["version"]) for v in self.versions]
        self.assertEqual(keys, sorted(set(keys), reverse=True))
        for place, version in enumerate(self.versions):
            if place == 0 and ".dev" in __version__:
                continue  # the next version's section, on main: empty until its first change
            self.assertTrue(version["notes"], version["version"])

    def test_the_first_version_out_is_in_the_list(self):
        self.assertIn(changelog.FIRST_OUT, [v["version"] for v in self.versions])


if __name__ == "__main__":
    unittest.main()
