"""The release build leaves no archive inside the release (Nexus Mods quarantines those)."""

import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import build_release  # noqa: E402


class ZipFreeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.release = self.tmp.name
        internal = os.path.join(self.release, "_internal")
        os.makedirs(internal)
        with zipfile.ZipFile(os.path.join(internal, "base_library.zip"), "w") as bundle:
            bundle.writestr("os.pyc", b"\x00" * 16)
            bundle.writestr("encodings/__init__.pyc", b"\x00" * 16)

    def test_base_library_becomes_a_folder_of_the_same_name(self):
        self.assertEqual(build_release.archives_inside(self.release), [os.path.join("_internal", "base_library.zip")])
        self.assertEqual(build_release.unzip_base_library(self.release), 2)
        folder = os.path.join(self.release, "_internal", "base_library.zip")
        self.assertTrue(os.path.isdir(folder))
        self.assertTrue(os.path.isfile(os.path.join(folder, "encodings", "__init__.pyc")))
        self.assertEqual(build_release.archives_inside(self.release), [])
        self.assertEqual(build_release.unzip_base_library(self.release), 0)  # already done

    def test_an_archive_under_another_name_is_found(self):
        build_release.unzip_base_library(self.release)
        with zipfile.ZipFile(os.path.join(self.release, "digits.npz"), "w") as bundle:
            bundle.writestr("a.npy", b"x")
        self.assertEqual(build_release.archives_inside(self.release), ["digits.npz"])

    def test_digit_templates_are_not_shipped(self):
        self.assertNotIn("digits.npz", build_release.DATA_FILES)


class VersionInfoTest(unittest.TestCase):
    def test_versions_as_four_numbers(self):
        self.assertEqual(build_release.version_numbers("0.3.0.dev0"), (0, 3, 0, 0))
        self.assertEqual(build_release.version_numbers("0.3.0-beta.2"), (0, 3, 0, 0))
        self.assertEqual(build_release.version_numbers("0.2.1"), (0, 2, 1, 0))
        self.assertEqual(build_release.version_numbers("1.2.3.4.5"), (1, 2, 3, 4))

    def test_the_version_file_names_the_program_and_its_version(self):
        text = build_release.version_info("0.3.0-beta.1")
        for expected in ("filevers=(0, 3, 0, 0)", "'ProductName', 'Waveband'", "'FileVersion', '0.3.0-beta.1'",
                         "'OriginalFilename', 'Waveband.exe'", "AGPL-3.0-or-later"):
            self.assertIn(expected, text)

    def test_pyinstaller_reads_it(self):
        try:
            from PyInstaller.utils.win32 import versioninfo
        except ImportError:
            self.skipTest("PyInstaller is only in the build environment")
        path = os.path.join(self.tmp_dir(), "v.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(build_release.version_info("0.3.0"))
        self.assertEqual(type(versioninfo.load_version_info_from_text_file(path)).__name__, "VSVersionInfo")

    def tmp_dir(self) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return tmp.name


if __name__ == "__main__":
    unittest.main()
