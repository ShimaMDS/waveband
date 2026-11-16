"""Waveband's own updates: is there a newer version, and install it.

Each release on GitHub carries the installer (``Waveband-<version>-setup.exe``), the portable
zip, ``SHA256SUMS.txt`` with the SHA-256 of both, and ``SHA256SUMS.txt.sig``, that file's
signature by the release key (``signing.py``). A checksum alone only shows the download arrived
whole: whoever can upload the installer can upload its checksum too. The signature is made with
a key that never leaves the builder's PC, so an update is installed only when it checks out
against the public key built into this copy; one that does not is not run. Waveband asks GitHub's releases API for the
newest release when it starts and once a day after (``check_updates`` in the settings), and says
so when there is a newer one. Installing it downloads the installer to the temp folder, checks
it against the signed ``SHA256SUMS.txt``, starts it without its windows and closes Waveband; the installer
puts the new version over the old one, which keeps the settings and fights beside it, and starts
it again. With ``auto_update`` this happens at start without asking.

Only an installed copy (one with the installer's uninstaller beside it) installs updates. The
portable zip and a copy run from source are told where the new version is instead.

The request names Waveband and its version and nothing else; nothing is sent about the player.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from . import __version__, signing
from .changelog import key as version_key
from .config import NAME, ROOT

# The repository the releases are published in, as "owner/name". Empty until it exists: the
# check then does nothing and says so.
REPO = os.environ.get("WAVEBAND_UPDATE_REPO", "ShimaMDS/waveband")
# The API's address; a test points this at a server of its own.
API = os.environ.get("WAVEBAND_UPDATE_API", "https://api.github.com")
SUMS = "SHA256SUMS.txt"
SIGNATURE = SUMS + ".sig"
_SETUP = re.compile(r"^Waveband-[\w.]+-setup\.exe$", re.IGNORECASE)
_TIMEOUT = 30.0
EVERY = 24 * 3600.0  # seconds between checks while running
_FIRST = 8.0  # seconds after start before the first, so the start is not slowed


class Failed(Exception):
    """The check or the download did not work. The message is for the user."""


@dataclass(frozen=True)
class Release:
    version: str  # "0.2.1"
    page: str  # the release's page, for reading or downloading by hand
    setup_url: str
    setup_name: str
    setup_size: int
    sums_url: str
    signature_url: str = ""


def installed() -> bool:
    """True for a copy the installer put in place: the packaged program with its uninstaller."""
    return bool(getattr(sys, "frozen", False)) and os.path.isfile(os.path.join(ROOT, "unins000.exe"))


def _get(url: str):
    request = urllib.request.Request(url, headers={
        "User-Agent": f"{NAME}/{__version__}", "Accept": "application/vnd.github+json",
    })
    return urllib.request.urlopen(request, timeout=_TIMEOUT)


def latest(repo: str = "") -> Release | None:
    """The newest release, or None when the repository has none (or none with an installer)."""
    repo = repo or REPO
    if not repo:
        raise Failed("Update checks are not set up in this build.")
    try:
        with _get(f"{API}/repos/{repo}/releases/latest") as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise Failed(f"GitHub answered {exc.code}. Try again later.") from exc
    except (OSError, ValueError) as exc:
        raise Failed(f"Couldn't reach GitHub ({getattr(exc, 'reason', None) or exc}).") from exc
    version = str(data.get("tag_name") or "").lstrip("vV")
    assets = {str(a.get("name")): a for a in data.get("assets") or [] if isinstance(a, dict)}
    setup = next((a for name, a in assets.items() if _SETUP.match(name)), None)
    sums = assets.get(SUMS)
    if not version or setup is None or sums is None:
        return None
    return Release(
        version=version,
        page=str(data.get("html_url") or f"https://github.com/{repo}/releases/latest"),
        setup_url=str(setup.get("browser_download_url")),
        setup_name=str(setup.get("name")),
        setup_size=int(setup.get("size") or 0),
        sums_url=str(sums.get("browser_download_url")),
        signature_url=str((assets.get(SIGNATURE) or {}).get("browser_download_url") or ""),
    )


def newer(release: Release | None, current: str = __version__) -> bool:
    return release is not None and version_key(release.version) > version_key(current)


def _fetch(url: str, what: str) -> bytes:
    try:
        with _get(url) as response:
            return response.read(1 << 16)
    except OSError as exc:
        raise Failed(f"Couldn't download {what}: {getattr(exc, 'reason', None) or exc}") from exc


def _expected_hash(release: Release) -> str:
    """The installer's SHA-256 from the release's checksums, once their signature checks out."""
    if not signing.RELEASE_KEY:
        raise Failed("This build has no release key, so it does not install updates itself. "
                     f"Download {release.version} from {release.page}")
    if not release.signature_url:
        raise Failed(f"Release {release.version} is not signed, so it was not installed.")
    data = _fetch(release.sums_url, "the checksums")
    try:
        signature = bytes.fromhex(_fetch(release.signature_url, "the signature").decode("ascii").strip())
    except (UnicodeDecodeError, ValueError):
        signature = b""
    if not signing.verify(bytes.fromhex(signing.RELEASE_KEY), data, signature):
        raise Failed(f"Release {release.version} is not signed with Waveband's release key, so it was "
                     "not installed. Report this on the project's page.")
    text = data.decode("utf-8", errors="replace")
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[1].lstrip("*") == release.setup_name and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            return parts[0].lower()
    raise Failed(f"The release lists no checksum for {release.setup_name}, so it was not installed.")


def download(release: Release, say: Callable[[str], None], folder: str = "") -> str:
    """The release's installer, checked against its published SHA-256. Returns its path."""
    expected = _expected_hash(release)
    folder = folder or tempfile.gettempdir()
    target = os.path.join(folder, release.setup_name)
    digest, size, told = hashlib.sha256(), 0, 0.0
    try:
        with _get(release.setup_url) as response, open(target + ".part", "wb") as out:
            total = int(response.headers.get("Content-Length") or release.setup_size or 0)
            while True:
                block = response.read(1 << 18)
                if not block:
                    break
                out.write(block)
                digest.update(block)
                size += len(block)
                if time.monotonic() - told >= 0.5:
                    told = time.monotonic()
                    of = f" of {total / 1e6:.0f}" if total else ""
                    say(f"Downloading {NAME} {release.version}: {size / 1e6:.0f}{of} MB")
    except OSError as exc:
        _discard(target + ".part")
        raise Failed(f"The download stopped: {getattr(exc, 'reason', None) or exc}") from exc
    if digest.hexdigest() != expected:
        _discard(target + ".part")
        raise Failed("The downloaded installer does not match its published checksum, so it was not run.")
    os.replace(target + ".part", target)
    return target


def _discard(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def run_installer(path: str) -> None:
    """Start the installer on its own, without its windows; it closes this copy and starts the new
    one when done. The caller quits straight after."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        [path, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/UPDATE"],
        close_fds=True, creationflags=flags,
    )


class Updates:
    """Checks now and then, and installs on request, in threads of its own. ``state`` is what the
    meter, the tray and the settings page show."""

    def __init__(self, enabled: Callable[[], bool], auto: Callable[[], bool], quit_app: Callable[[], None],
                 tell: Callable[[str], None]) -> None:
        self._enabled, self._auto, self._quit, self._tell = enabled, auto, quit_app, tell
        self._lock = threading.Lock()
        self._busy = False
        self._stop = threading.Event()
        self.release: Release | None = None
        self.status = "idle"  # idle | checking | latest | available | downloading | error | off
        self.line = ""  # what to say about it now
        self.checked_at = 0.0

    def state(self) -> dict:
        release = self.release
        return {
            "status": self.status, "line": self.line, "current": __version__,
            "latest": release.version if release else "", "page": release.page if release else "",
            "installs": installed(), "checked_at": self.checked_at, "set_up": bool(REPO),
        }

    def start(self) -> None:
        threading.Thread(target=self._loop, name="update-check", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        if self._stop.wait(_FIRST):
            return
        first = True
        while not self._stop.is_set():
            if self._enabled():
                self.check(first=first)
            first = False
            if self._stop.wait(EVERY):
                return

    def check(self, first: bool = False) -> None:
        """Ask for the newest release. Run in the caller's thread; quick."""
        with self._lock:
            if self._busy:
                return
            self._busy = True
        try:
            self.status, self.line = "checking", "Looking for a newer version"
            try:
                release = latest()
            except Failed as why:
                self.status, self.line = "error", str(why)
                return
            self.checked_at = time.time()
            if not newer(release):
                self.release, self.status, self.line = None, "latest", f"{NAME} {__version__} is the newest version."
                return
            told = self.release is None or self.release.version != release.version
            self.release, self.status = release, "available"
            self.line = (f"{NAME} {release.version} is available. Tray menu: Install update."
                         if installed() else f"{NAME} {release.version} is available: {release.page}")
            if told:
                self._tell(self.line)
        finally:
            with self._lock:
                self._busy = False
        if first and self._auto() and installed() and self.status == "available":
            self.install()

    def install(self) -> bool:
        """Download and run the installer of the newest release, in a thread. False when there is
        nothing to install or this copy cannot install it itself."""
        release = self.release
        if release is None or not installed():
            return False
        with self._lock:
            if self._busy:
                return False
            self._busy = True
        threading.Thread(target=self._install, args=(release,), name="update-install", daemon=True).start()
        return True

    def _install(self, release: Release) -> None:
        try:
            self.status = "downloading"

            def say(text: str) -> None:
                self.line = text

            say(f"Downloading {NAME} {release.version}")
            try:
                path = download(release, say)
            except Failed as why:
                self.status, self.line = "error", str(why)
                self._tell(self.line)
                return
            self.line = f"Installing {NAME} {release.version}. It starts again by itself."
            self._tell(self.line)
            try:
                run_installer(path)
            except OSError as exc:
                self.status, self.line = "error", f"Couldn't start the installer: {exc}"
                self._tell(self.line)
                return
            time.sleep(1.0)  # let the message show
            self._quit()
        finally:
            with self._lock:
                self._busy = False
