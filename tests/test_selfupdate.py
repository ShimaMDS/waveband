"""Waveband's own updates, against a stand-in for GitHub's releases API on this PC."""

import hashlib
import http.server
import json
import os
import tempfile
import threading
import unittest
from unittest import mock

from wwmeter import selfupdate, signing

SETUP = b"pretend installer " * 5000
KEY = signing.new_secret()  # the test's own release key
OTHER_KEY = signing.new_secret()


class FakeGitHub:
    """GitHub's releases API and the release's files, served on 127.0.0.1."""

    def __init__(self, version="9.1.0", sums=None, setup=SETUP, status=200, key=KEY, signed=True, others=()):
        self.version, self.setup, self.status, self.signed = version, setup, status, signed
        # more releases, for the beta channel's list: (version, pre-release, draft)
        self.others = list(others)
        self.sums = sums if sums is not None else (
            f"{hashlib.sha256(setup).hexdigest()}  Waveband-{version}-setup.exe\n"
            f"{'0' * 64}  Waveband-{version}.zip\n")
        self.signature = signing.sign(key, self.sums.encode()).hex() + "\n"
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                base = f"http://127.0.0.1:{owner.port}"
                if self.path == "/repos/someone/waveband/releases/latest":
                    if owner.status != 200:
                        self.send_error(owner.status)
                        return
                    body = json.dumps({
                        "tag_name": f"v{owner.version}", "html_url": f"{base}/release",
                        "assets": [
                            {"name": f"Waveband-{owner.version}-setup.exe", "size": len(owner.setup),
                             "browser_download_url": f"{base}/setup"},
                            {"name": f"Waveband-{owner.version}.zip", "size": 1, "browser_download_url": f"{base}/zip"},
                            {"name": "SHA256SUMS.txt", "size": 10, "browser_download_url": f"{base}/sums"},
                        ] + ([{"name": "SHA256SUMS.txt.sig", "size": 129, "browser_download_url": f"{base}/sig"}]
                             if owner.signed else []),
                    }).encode()
                elif self.path == "/repos/someone/waveband/releases?per_page=30":
                    def entry(version, pre, draft):
                        return {"tag_name": f"v{version}", "prerelease": pre, "draft": draft,
                                "html_url": f"{base}/release/{version}", "assets": [
                                    {"name": f"Waveband-{version}-setup.exe", "size": 1, "browser_download_url": f"{base}/setup"},
                                    {"name": "SHA256SUMS.txt", "size": 1, "browser_download_url": f"{base}/sums"}]}
                    body = json.dumps([entry(owner.version, False, False)]
                                      + [entry(*other) for other in owner.others]).encode()
                elif self.path == "/setup":
                    body = owner.setup
                elif self.path == "/sums":
                    body = owner.sums.encode()
                elif self.path == "/sig":
                    body = owner.signature.encode()
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def __enter__(self):
        self._patches = [mock.patch.object(selfupdate, "API", f"http://127.0.0.1:{self.port}"),
                         mock.patch.object(selfupdate, "REPO", "someone/waveband"),
                         mock.patch.object(signing, "RELEASE_KEY", signing.public_key(KEY).hex())]
        for patch in self._patches:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in self._patches:
            patch.stop()
        self.server.shutdown()
        self.server.server_close()


class ReleaseTest(unittest.TestCase):
    def test_the_newest_release_and_its_files(self):
        with FakeGitHub() as github:
            release = selfupdate.latest()
        self.assertEqual(release.version, "9.1.0")
        self.assertEqual(release.setup_name, "Waveband-9.1.0-setup.exe")
        self.assertTrue(release.sums_url.endswith("/sums"))
        self.assertIn(str(github.port), release.page)

    def test_newer_compares_versions_as_numbers(self):
        release = selfupdate.Release("0.10.0", "", "", "", 0, "")
        self.assertTrue(selfupdate.newer(release, "0.9.3"))
        self.assertFalse(selfupdate.newer(release, "0.10.0"))
        self.assertFalse(selfupdate.newer(release, "0.10.0.dev0"))  # a build on the way to it
        self.assertFalse(selfupdate.newer(None, "0.1.0"))

    def test_no_release_yet_is_not_an_error(self):
        with FakeGitHub(status=404):
            self.assertIsNone(selfupdate.latest())

    def test_without_a_repository_it_says_so(self):
        with mock.patch.object(selfupdate, "REPO", ""), self.assertRaises(selfupdate.Failed):
            selfupdate.latest()

    def test_an_unreachable_github_is_a_message_not_a_crash(self):
        with mock.patch.object(selfupdate, "API", "http://127.0.0.1:9"), \
                mock.patch.object(selfupdate, "REPO", "someone/waveband"), self.assertRaises(selfupdate.Failed):
            selfupdate.latest()


class VersionTest(unittest.TestCase):
    def test_betas_are_labelled_and_sort_between_releases(self):
        order = ["0.2.0", "0.2.1", "0.2.2", "0.3.0-beta.1", "0.3.0-beta.2", "0.3.0-beta.10", "0.3.0", "0.3.1"]
        self.assertEqual(sorted(reversed(order), key=selfupdate.version_key), order)

    def test_a_build_on_the_way_to_a_version_is_that_version(self):
        self.assertEqual(selfupdate.version_key("0.3.0.dev0"), selfupdate.version_key("0.3.0"))

    def test_a_beta_installer_is_recognised(self):
        self.assertTrue(selfupdate._SETUP.match("Waveband-0.3.0-beta.1-setup.exe"))


class ChannelTest(unittest.TestCase):
    def test_a_quick_fix_to_stable_reaches_stable(self):
        with FakeGitHub(version="9.1.1", others=[("9.2.0-beta.1", True, False)]):
            release = selfupdate.latest(channel="stable")
        self.assertEqual(release.version, "9.1.1")
        self.assertTrue(selfupdate.newer(release, "9.1.0"))

    def test_beta_takes_the_newest_labelled_beta(self):
        with FakeGitHub(version="9.1.1", others=[("9.2.0-beta.1", True, False), ("9.2.0-beta.2", True, False)]):
            release = selfupdate.latest(channel="beta")
        self.assertEqual(release.version, "9.2.0-beta.2")
        self.assertTrue(selfupdate.newer(release, "9.2.0-beta.1"))
        self.assertFalse(selfupdate.newer(release, "9.2.0"))

    def test_stable_sees_only_the_stable_release(self):
        with FakeGitHub(version="9.1.0", others=[("9.1.3", True, False)]):
            self.assertEqual(selfupdate.latest(channel="stable").version, "9.1.0")

    def test_beta_sees_the_newest_of_both(self):
        with FakeGitHub(version="9.1.0", others=[("9.1.3", True, False), ("9.1.2", True, False)]):
            self.assertEqual(selfupdate.latest(channel="beta").version, "9.1.3")

    def test_beta_moves_on_to_the_next_stable_version(self):
        with FakeGitHub(version="9.2.0", others=[("9.1.9", True, False)]):
            self.assertEqual(selfupdate.latest(channel="beta").version, "9.2.0")

    def test_a_draft_is_never_offered(self):
        with FakeGitHub(version="9.1.0", others=[("9.9.9", True, True)]):
            self.assertEqual(selfupdate.latest(channel="beta").version, "9.1.0")

    def test_a_chosen_channel_is_kept_whatever_the_version(self):
        for version in ("0.3.0", "0.3.0-beta.1", "0.3.0.dev0"):
            self.assertEqual(selfupdate.effective_channel("stable", version), "stable")
            self.assertEqual(selfupdate.effective_channel("beta", version), "beta")

    def test_until_one_is_chosen_a_beta_follows_beta_and_the_rest_stable(self):
        self.assertEqual(selfupdate.effective_channel("", "0.3.0-beta.1"), "beta")
        self.assertEqual(selfupdate.effective_channel("", "0.3.0"), "stable")
        self.assertEqual(selfupdate.effective_channel("", "0.4.0"), "stable")
        self.assertEqual(selfupdate.effective_channel("", "0.3.0.dev0"), "stable")

    def test_each_version_has_a_beta_and_then_a_stable_release(self):
        # the owner's scheme: 0.3.1-beta.1, then 0.3.1; 0.3.2-beta.1, then 0.3.2; ... then 0.4.0
        for version in ("0.3.1-beta.1", "0.3.1-beta.2", "0.3.2-beta.1", "0.4.0-beta.1"):
            self.assertTrue(selfupdate.is_beta(version), version)
            self.assertEqual(selfupdate.effective_channel("", version), "beta")
        for version in ("0.3.0", "0.3.1", "0.3.2", "0.4.0", "0.3.1.dev0"):
            self.assertFalse(selfupdate.is_beta(version), version)
            self.assertEqual(selfupdate.effective_channel("", version), "stable")
        order = ["0.3.0", "0.3.1-beta.1", "0.3.1-beta.2", "0.3.1", "0.3.2-beta.1", "0.3.2", "0.4.0-beta.1", "0.4.0"]
        keys = [selfupdate.version_key(v) for v in order]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(set(keys)), len(keys))
        self.assertEqual(selfupdate.effective_channel("nonsense", "0.3.0-beta.2"), "beta")

    def test_a_beta_on_its_own_hears_of_the_next_beta(self):
        # someone who installed beta.1 from a link and never opened Settings
        with FakeGitHub(version="0.2.0", others=[("0.3.0-beta.2", True, False)]):
            channel = selfupdate.effective_channel("", "0.3.0-beta.1")
            self.assertEqual(selfupdate.latest(channel=channel).version, "0.3.0-beta.2")

    def test_the_checker_asks_the_channel_set(self):
        updates = selfupdate.Updates(enabled=lambda: True, auto=lambda: False, quit_app=lambda: None,
                                     tell=lambda _t: None, channel=lambda: "beta")
        with FakeGitHub(version="0.0.1", others=[("9.1.3", True, False)]):
            updates.check()
        self.assertEqual((updates.status, updates.state()["latest"], updates.state()["channel"]),
                         ("available", "9.1.3", "beta"))


class DownloadTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def test_a_download_that_matches_its_checksum_is_kept(self):
        said = []
        with FakeGitHub():
            path = selfupdate.download(selfupdate.latest(), said.append, self.folder.name)
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), SETUP)
        self.assertTrue(said)

    def test_a_download_that_does_not_match_is_thrown_away(self):
        with FakeGitHub(sums=f"{'1' * 64}  Waveband-9.1.0-setup.exe\n"), self.assertRaises(selfupdate.Failed) as why:
            selfupdate.download(selfupdate.latest(), lambda _t: None, self.folder.name)
        self.assertIn("checksum", str(why.exception))
        self.assertEqual(os.listdir(self.folder.name), [])

    def test_a_release_with_no_checksum_for_the_installer_is_not_installed(self):
        with FakeGitHub(sums=f"{'1' * 64}  something-else.exe\n"), self.assertRaises(selfupdate.Failed):
            selfupdate.download(selfupdate.latest(), lambda _t: None, self.folder.name)
        self.assertEqual(os.listdir(self.folder.name), [])


class SignatureTest(unittest.TestCase):
    """A checksum shows a download arrived whole; the signature shows who made the release."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def refused(self, github, words):
        with github, self.assertRaises(selfupdate.Failed) as why:
            selfupdate.download(selfupdate.latest(), lambda _t: None, self.folder.name)
        self.assertIn(words, str(why.exception))
        self.assertEqual(os.listdir(self.folder.name), [])

    def test_a_release_signed_with_another_key_is_not_installed(self):
        # what someone who got into the GitHub account could publish: their own installer, its
        # right checksum, signed with a key of their own
        evil = b"not waveband " * 100
        self.refused(FakeGitHub(setup=evil, key=OTHER_KEY), "not signed with Waveband's release key")

    def test_an_unsigned_release_is_not_installed(self):
        self.refused(FakeGitHub(signed=False), "not signed")

    def test_a_build_without_a_release_key_does_not_install(self):
        github = FakeGitHub()
        with github, mock.patch.object(signing, "RELEASE_KEY", ""), self.assertRaises(selfupdate.Failed) as why:
            selfupdate.download(selfupdate.latest(), lambda _t: None, self.folder.name)
        self.assertIn("no release key", str(why.exception))


class UpdatesTest(unittest.TestCase):
    def make(self, auto=False):
        told = []
        updates = selfupdate.Updates(enabled=lambda: True, auto=lambda: auto, quit_app=lambda: None, tell=told.append)
        return updates, told

    def test_a_newer_version_is_said_once(self):
        updates, told = self.make()
        with FakeGitHub():
            updates.check()
            updates.check()
        self.assertEqual(updates.status, "available")
        self.assertEqual(len(told), 1)
        self.assertIn("9.1.0", told[0])
        self.assertEqual(updates.state()["latest"], "9.1.0")

    def test_the_newest_version_says_so_quietly(self):
        updates, told = self.make()
        with FakeGitHub(version="0.0.1"):
            updates.check()
        self.assertEqual(updates.status, "latest")
        self.assertEqual(told, [])

    def test_a_copy_that_is_not_installed_does_not_install(self):
        updates, _ = self.make(auto=True)
        with FakeGitHub(), mock.patch.object(selfupdate, "run_installer") as run:
            updates.check(first=True)
            self.assertFalse(updates.install())
        run.assert_not_called()
        self.assertIn("http", updates.line)  # where to download it instead

    def test_an_installed_copy_downloads_checks_runs_and_quits(self):
        quits = threading.Event()
        updates = selfupdate.Updates(enabled=lambda: True, auto=lambda: False, quit_app=quits.set, tell=lambda _t: None)
        with FakeGitHub(), mock.patch.object(selfupdate, "installed", return_value=True), \
                mock.patch.object(selfupdate, "run_installer") as run, mock.patch.object(selfupdate.time, "sleep"):
            updates.check()
            self.assertTrue(updates.install())
            self.assertTrue(quits.wait(10))
        run.assert_called_once()
        with open(run.call_args[0][0], "rb") as fh:
            self.assertEqual(fh.read(), SETUP)
        os.remove(run.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
