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


class WebView2LoaderTest(unittest.TestCase):
    def test_the_fetched_loader_is_the_pinned_one(self):
        folder = os.path.join(build_release.ROOT, "lib", "webview2")
        if not os.path.isdir(folder):
            self.skipTest("lib\webview2 not fetched (tools\make_webview2_com.py)")
        for name, digest in build_release.WEBVIEW2_FILES.items():
            self.assertEqual(build_release.sha256(os.path.join(folder, name)), digest, name)


class SourceTest(unittest.TestCase):
    def test_only_what_git_keeps_goes_into_the_source(self):
        # seen 2026-11-19: a script held back from the repository went into a build
        with tempfile.TemporaryDirectory() as folder:
            import subprocess

            tools = os.path.join(folder, "tools")
            os.makedirs(tools)
            for name in ("kept.py", "held_back.py", "steps.js", "notes.txt"):
                with open(os.path.join(tools, name), "w") as fh:
                    fh.write("# x\n")
            subprocess.run(["git", "init", "-q"], cwd=folder, check=True)
            subprocess.run(["git", "add", "tools/kept.py", "tools/steps.js", "tools/notes.txt"], cwd=folder, check=True)
            target = os.path.join(folder, "out")
            build_release.copy_python(tools, target)
            self.assertEqual(sorted(os.listdir(target)), ["kept.py", "steps.js"])

    def test_this_checkout_has_its_tools_tracked(self):
        names = build_release.tracked(os.path.join(build_release.ROOT, "tools"))
        self.assertIn("build_release.py", names)


class NoQtTest(unittest.TestCase):
    def test_qt_in_a_build_is_found(self):
        with tempfile.TemporaryDirectory() as release:
            internal = os.path.join(release, "_internal")
            os.makedirs(os.path.join(internal, "numpy"))
            self.assertEqual(build_release.qt_inside(release), [])
            os.makedirs(os.path.join(internal, "PySide6"))
            open(os.path.join(internal, "Qt6Core.dll"), "wb").close()
            self.assertEqual(sorted(build_release.qt_inside(release)),
                             [os.path.join("_internal", "PySide6"), os.path.join("_internal", "Qt6Core.dll")])
