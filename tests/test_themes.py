"""Every theme the meter offers has its stylesheet, and everything a stylesheet points at exists.

A theme renamed or added without its files would otherwise ship with a blank top bar (no mark or
wordmark) or fall back to unstyled text, and nothing else would notice.
"""

import os
import re
import unittest

from wwmeter.config import ROOT
from wwmeter.settings import ELEMENTS, available_themes, theme_label

UI = os.path.join(ROOT, "ui")
THEMES = os.path.join(UI, "themes")
_URL = re.compile(r"""url\(\s*["']?([^"')]+)["']?\s*\)""")


def references(css_path: str) -> list[str]:
    """The local files a stylesheet points at, resolved from its own folder."""
    with open(css_path, encoding="utf-8") as fh:
        text = re.sub(r"/\*.*?\*/", "", fh.read(), flags=re.S)  # not what comments mention
    found = []
    for target in _URL.findall(text):
        if re.match(r"^(data:|https?:|#)", target):
            continue
        found.append(os.path.normpath(os.path.join(os.path.dirname(css_path), target.split("?")[0])))
    return found


class ThemeFilesTest(unittest.TestCase):
    def test_the_meter_offers_wuwa_first_and_every_element(self):
        themes = available_themes()
        self.assertEqual(themes[0], "wuwa")
        for element in ELEMENTS:
            self.assertIn(element, themes)
        self.assertIn("classic", themes)

    def test_every_theme_has_a_label(self):
        for theme in available_themes():
            self.assertTrue(theme_label(theme).strip(), theme)

    def test_everything_the_stylesheets_point_at_exists(self):
        sheets = [os.path.join(UI, "base.css")] + [os.path.join(THEMES, f"{t}.css") for t in available_themes()]
        for sheet in sheets:
            self.assertTrue(os.path.isfile(sheet), sheet)
            for path in references(sheet):
                self.assertTrue(os.path.isfile(path), f"{os.path.relpath(sheet, ROOT)} points at a missing "
                                                      f"{os.path.relpath(path, ROOT)}")

    def test_each_element_theme_shows_its_own_mark_and_wordmark(self):
        for element in ELEMENTS:
            refs = {os.path.relpath(p, UI).replace(os.sep, "/") for p in references(os.path.join(THEMES, f"{element}.css"))}
            for part in ("mark", "wordmark"):
                self.assertIn(f"brand/{element}-{part}.svg", refs, element)

    def test_the_default_mark_and_wordmark_exist(self):
        # WuWa and Classic use these, from base.css
        for part in ("mark", "wordmark"):
            self.assertTrue(os.path.isfile(os.path.join(UI, "brand", f"wuwa-{part}.svg")), part)


if __name__ == "__main__":
    unittest.main()
