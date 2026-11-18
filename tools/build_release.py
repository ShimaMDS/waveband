"""Build the folder and zip handed to testers: Waveband.exe with everything it needs.

Run it with a Python that has the requirements and PyInstaller installed, ideally a fresh
environment so nothing stray is bundled:

    python -m venv build-env
    build-env\\Scripts\\python -m pip install -r requirements.txt pyinstaller
    build-env\\Scripts\\python tools\\build_release.py --out <folder outside the project>

The result is ``<out>\\Waveband-<version>\\`` and ``<out>\\Waveband-<version>.zip``. Nothing personal
goes in: no config.json, logs, recordings, or number samples cut from someone's screen.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # the other tools

from wwmeter import __version__  # noqa: E402
from wwmeter.config import NAME  # noqa: E402

# digits.npz stays out: it is only for the damage-number reader, which needs OpenCV (not in the
# build), and an .npz is a zip, which Nexus Mods rejects as an archive inside the archive
DATA_FILES = ("characters.json", "names.json", "enemy_hp.json", "part_shares.json",
              "ocr/ch_PP-OCRv3_rec_infer.onnx", "ocr/NOTICE.txt")
SOURCE_FILES = ("requirements.txt", "run.bat")
# fetched by tools/make_webview2_com.py from Microsoft's WebView2 SDK 1.0.4314.35 (the x64
# loader, signed by Microsoft), with their SHA-256: the build ships these files and no others
WEBVIEW2_FILES = {
    "WebView2Loader.dll": "d3fce90bdeecb08596e377dea6a316354dd8949e32ff09b89d51be00c14e21b6",
    "LICENSE.txt": "0af8f1b807512aae39c2ac1aa4d0cae65cabecb6fd554b8439a5162a0d6eca55",
}
SOURCE_NOTE = (
    "This is the source Waveband.exe was built from, included so you can read what it does.\n\n"
    "You do not need it to use the meter. To run from source instead of the .exe (Python 3.11 or\n"
    "newer): copy the ui, data and lib folders from the folder above into this one, then double-click\n"
    "run.bat. The first start downloads the libraries listed in requirements.txt.\n"
)
SELFTEST_BAT = '@echo off\r\ncd /d "%~dp0"\r\nstart "" /wait Waveband.exe selftest\r\nif exist selftest.txt start "" notepad selftest.txt\r\n'


def version_numbers(version: str) -> tuple[int, int, int, int]:
    """A version as the four numbers Windows keeps in a program's file properties: 0.3.0.dev0
    and 0.3.0-beta.2 are 0.3.0.0, 0.2.1 is 0.2.1.0."""
    numbers = []
    for part in version.replace("-", ".").split("."):
        if not part.isdigit():
            break
        numbers.append(int(part))
    return tuple((numbers + [0, 0, 0, 0])[:4])


def version_info(version: str) -> str:
    """Waveband.exe's version information, as PyInstaller's --version-file reads it: what Windows
    shows under the file's Properties, Details. A program with none looks like an anonymous one
    to the antivirus engines that score files by machine learning; every signed library beside
    it has this."""
    numbers = version_numbers(version)
    strings = {
        "CompanyName": "Waveband",
        "FileDescription": "Waveband, a damage meter for Wuthering Waves",
        "FileVersion": version,
        "InternalName": NAME,
        "LegalCopyright": "Copyright (c) Waveband contributors. Free software: AGPL-3.0-or-later.",
        "OriginalFilename": f"{NAME}.exe",
        "ProductName": NAME,
        "ProductVersion": version,
        "Comments": "https://github.com/ShimaMDS/waveband",
    }
    table = ",\n          ".join(f"StringStruct({k!r}, {v!r})" for k, v in strings.items())
    return (
        "VSVersionInfo(\n"
        f"  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags=0x0,\n"
        "                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),\n"
        "  kids=[\n"
        "    StringFileInfo([StringTable('040904B0', [\n"
        f"          {table}])]),\n"
        "    VarFileInfo([VarStruct('Translation', [1033, 1200])]),\n"
        "  ])\n"
    )


def build_exe(work: str) -> str:
    """Run PyInstaller; returns the folder holding Waveband.exe and _internal."""
    os.makedirs(work, exist_ok=True)
    version_file = os.path.join(work, "version-info.txt")
    with open(version_file, "w", encoding="utf-8") as fh:
        fh.write(version_info(__version__))
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", NAME,
        # drawn by tools/make_logo.py
        "--icon", os.path.join(ROOT, "assets", "waveband.ico"),
        "--version-file", version_file,
        "--distpath", os.path.join(work, "dist"),
        "--workpath", os.path.join(work, "build"),
        "--specpath", work,
        "--paths", ROOT,
        "--collect-submodules", "wwmeter",
        # OpenCV is only for the damage-number reader, which is off and stays out of the build
        # (wwmeter/dmgnum.py says so on the meter if it is turned on); the boss-title reader
        # needs ONNX Runtime alone, with its model in data\ocr
        "--exclude-module", "cv2",
        "--exclude-module", "tkinter",
        # Qt is only for some tools (requirements-dev.txt), never the meter: kept out even when the
        # build environment has it (it was 300 MB of the 0.3.1 download)
        "--exclude-module", "PySide6",
        "--exclude-module", "shiboken6",
        os.path.join(ROOT, "tools", "exe_entry.py"),
    ]
    subprocess.run(command, check=True)
    return os.path.join(work, "dist", NAME)


def _listed(folder: str, keep=lambda name: False) -> list[str]:
    if not os.path.isdir(folder):
        return []
    return [os.path.join(folder, name) for name in os.listdir(folder) if not keep(name)]


def unzip_base_library(release: str) -> int:
    """Unpack PyInstaller's ``_internal/base_library.zip`` into a folder of the same name.

    It holds the compiled modules of Python's standard library that start the interpreter. Nexus
    Mods quarantines an upload holding another archive, and this is one. PyInstaller's launcher
    puts that exact path on Python's search path, so the name has to stay; as a folder, Python
    reads the modules from it as from any folder (tested: the self-test and a demo run pass).
    Unpacking the modules straight into ``_internal`` works as well (on the search path too, and
    no name clashes), if the folder's name is ever the problem. Returns the number of files."""
    path = os.path.join(release, "_internal", "base_library.zip")
    if not os.path.isfile(path):
        return 0
    unpacked = path + ".unpacked"
    shutil.rmtree(unpacked, ignore_errors=True)
    with zipfile.ZipFile(path) as bundle:
        count = len([n for n in bundle.namelist() if not n.endswith("/")])
        bundle.extractall(unpacked)
    os.remove(path)
    os.rename(unpacked, path)
    return count


# the first bytes of a zip (a file in one, or an empty one) and of a 7z
_ARCHIVE_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"7z\xbc\xaf")


def archives_inside(release: str) -> list[str]:
    """Files in the release that are zips themselves (by their first bytes, whatever the name)."""
    found = []
    for folder, _, files in os.walk(release):
        for file in files:
            path = os.path.join(folder, file)
            with open(path, "rb") as fh:
                if fh.read(4) in _ARCHIVE_MAGIC:
                    found.append(os.path.relpath(path, release))
    return found


def trim(release: str) -> float:
    """Delete bundled files the meter never loads. Returns the megabytes saved."""
    internal = os.path.join(release, "_internal")
    # AVIF pictures are never opened; Pillow goes without when the module is absent
    doomed = _listed(os.path.join(internal, "PIL"), lambda f: not f.startswith("_avif"))
    saved = 0
    for path in doomed:
        if os.path.isfile(path):
            saved += os.path.getsize(path)
            os.remove(path)
    return saved / 1e6


def tracked(folder: str) -> list[str]:
    """The names of the files directly in ``folder`` that git keeps. A file only on this PC (one
    never added, such as a script held back until it may be published) is not among them."""
    out = subprocess.run(["git", "ls-files", "-z", "--", "."], cwd=folder, capture_output=True, check=True)
    names = [name for name in out.stdout.decode("utf-8").split("\0") if name]
    return sorted(name for name in names if "/" not in name)


def copy_python(source: str, target: str) -> None:
    """The Python files of a folder that git keeps, and the steps file drive_page.py is run with.
    Only what git keeps: the source in a release is what was committed, never a file that lies in
    the folder on the PC that built it (seen 2026-11-19: tools\\make_nexus_images.py, held back
    from the repository, went into a build made from the working folder)."""
    os.makedirs(target, exist_ok=True)
    for name in tracked(source):
        if name.endswith((".py", ".js")):
            shutil.copy2(os.path.join(source, name), os.path.join(target, name))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", required=True, help="folder to build in (outside the project)")
    parser.add_argument("--keep-work", action="store_true", help="reuse the PyInstaller output already in --out")
    parser.add_argument("--iscc", default="", help="Inno Setup's ISCC.exe (default: where its installer puts it)")
    parser.add_argument("--no-installer", action="store_true", help="the zip alone is enough")
    parser.add_argument("--unsigned", action="store_true", help="a test build: no release key needed")
    parser.add_argument("--sign", action="store_true", help="ask for the release key's passphrase and sign (in a terminal)")
    args = parser.parse_args(argv)
    out = os.path.abspath(args.out)
    name = f"{NAME}-{__version__}"
    release = os.path.join(out, name)
    inside = os.path.normcase(out + os.sep).startswith(os.path.normcase(ROOT + os.sep))
    if inside:
        print("Pick an --out folder outside the project.")
        return 2
    missing = [f for f in DATA_FILES if not os.path.isfile(os.path.join(ROOT, "data", f))]
    if missing:
        print(f"Missing from data\\: {missing}. Build enemy_hp.json with tools\\build_enemy_hp.py first.")
        return 1
    try:
        tracked(os.path.join(ROOT, "tools"))
    except (OSError, subprocess.CalledProcessError):
        print("Build from a git checkout: the source in the release is what git keeps, and git can't "
              "say here (no git, or this folder isn't a clone).")
        return 1
    missing = [f for f in WEBVIEW2_FILES if not os.path.isfile(os.path.join(ROOT, "lib", "webview2", f))]
    if missing:
        print(f"Missing from lib\\webview2\\: {missing}. Run tools\\make_webview2_com.py first.")
        return 1
    changed = [f for f, digest in WEBVIEW2_FILES.items()
               if sha256(os.path.join(ROOT, "lib", "webview2", f)) != digest]
    if changed:
        print(f"Not the pinned SDK's files in lib\\webview2\\: {changed}. Delete the folder and run "
              "tools\\make_webview2_com.py again (or pin the new SDK's hashes here on purpose).")
        return 1

    work = os.path.join(out, "work")
    shutil.rmtree(release, ignore_errors=True)
    built = os.path.join(work, "dist", NAME)
    if not (args.keep_work and os.path.isfile(os.path.join(built, NAME + ".exe"))):
        shutil.rmtree(work, ignore_errors=True)
        os.makedirs(out, exist_ok=True)
        built = build_exe(work)
    shutil.copytree(built, release)
    print(f"trimmed {trim(release):.0f} MB of files the meter never loads")
    print(f"unpacked base_library.zip into a folder: {unzip_base_library(release)} files")

    shutil.copytree(os.path.join(ROOT, "ui"), os.path.join(release, "ui"))
    # WebView2's loader, which finds the runtime Windows has; its BSD licence goes along
    os.makedirs(os.path.join(release, "lib", "webview2"))
    for file in WEBVIEW2_FILES:
        shutil.copy2(os.path.join(ROOT, "lib", "webview2", file), os.path.join(release, "lib", "webview2", file))
    os.makedirs(os.path.join(release, "data"))
    for file in DATA_FILES:
        os.makedirs(os.path.dirname(os.path.join(release, "data", file)), exist_ok=True)
        shutil.copy2(os.path.join(ROOT, "data", file), os.path.join(release, "data", file))
    # the meter reads the changelog to say what changed; the licence goes with every copy; the
    # README's pictures and the write-ups are in docs
    for document in ("README.md", "CHANGELOG.md", "LICENSE"):
        shutil.copy2(os.path.join(ROOT, document), os.path.join(release, document))
    shutil.copytree(os.path.join(ROOT, "docs"), os.path.join(release, "docs"))
    with open(os.path.join(ROOT, "tools", "START HERE.txt"), encoding="utf-8") as fh:
        notes = fh.read().replace("{version}", __version__)
    with open(os.path.join(release, "START HERE.txt"), "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write(notes)
    with open(os.path.join(release, "selftest.bat"), "w", encoding="ascii", newline="") as fh:
        fh.write(SELFTEST_BAT)

    # The source, so anyone can read what the program does.
    source = os.path.join(release, "source")
    copy_python(os.path.join(ROOT, "wwmeter"), os.path.join(source, "wwmeter"))
    copy_python(os.path.join(ROOT, "tools"), os.path.join(source, "tools"))
    for file in SOURCE_FILES:
        shutil.copy2(os.path.join(ROOT, file), os.path.join(source, file))
    with open(os.path.join(source, "README.txt"), "w", encoding="utf-8", newline="\r\n") as fh:
        fh.write(SOURCE_NOTE)

    nested = archives_inside(release)
    if nested:
        print("Archives inside the release (Nexus Mods would quarantine it):", ", ".join(nested))
        return 1
    archive = os.path.join(out, name + ".zip")
    if os.path.exists(archive):
        os.remove(archive)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for folder, _, files in os.walk(release):
            for file in files:
                path = os.path.join(folder, file)
                bundle.write(path, os.path.join(name, os.path.relpath(path, release)))
    size = sum(os.path.getsize(os.path.join(f, n)) for f, _, ns in os.walk(release) for n in ns)
    print(f"{release}: {size / 1e6:.0f} MB unpacked")
    print(f"{archive}: {os.path.getsize(archive) / 1e6:.0f} MB")

    setup = build_installer(release, out, args.iscc)
    # what Waveband's updater checks a download against, and anyone else can
    sums = os.path.join(out, "SHA256SUMS.txt")
    with open(sums, "w", encoding="ascii", newline="\n") as fh:
        for path in (archive, setup):
            if path:
                fh.write(f"{sha256(path)}  {os.path.basename(path)}\n")
    print(f"{sums}: the SHA-256 of {'both' if setup else 'the zip'}")
    signed = sign_sums(sums, args.sign)
    return 0 if (setup or args.no_installer) and (signed or args.unsigned) else 1


def sign_sums(sums: str, ask: bool = False) -> str:
    """``SHA256SUMS.txt.sig`` with the release key (tools\\release_key.py). '' when there is no
    key here: installed copies then refuse to install this release by themselves."""
    import release_key

    if release_key.is_locked() and not ask:
        # Asking for the passphrase here would hang a build run where nobody can type (seen
        # 2026-11-16: a background shell looked enough like a terminal for getpass to wait).
        print(f"Not signed: the release key is locked. Sign in your own terminal:\n"
              f"    .venv\\Scripts\\python tools\\release_key.py sign \"{sums}\"")
        return ""
    try:
        signature = release_key.sign_file(sums)  # asks for the key's passphrase in the terminal
    except release_key.Locked as why:
        print(f"Not signed: {why}")
        return ""
    print(f"{signature}: signed with the release key")
    return signature


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def find_iscc(given: str = "") -> str:
    """Inno Setup's compiler: the one named, else where its installer puts it."""
    places = [given, os.environ.get("ISCC", ""),
              os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
              os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Inno Setup 6", "ISCC.exe"),
              os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Inno Setup 6", "ISCC.exe")]
    return next((p for p in places if p and os.path.isfile(p)), "")


def build_installer(release: str, out: str, iscc: str = "") -> str:
    """``Waveband-<version>-setup.exe`` in ``out``, from ``tools\\installer\\waveband.iss``. ''
    when Inno Setup is not installed (winget install JRSoftware.InnoSetup)."""
    compiler = find_iscc(iscc)
    if not compiler:
        print("Inno Setup is not installed, so no installer was made: winget install JRSoftware.InnoSetup")
        return ""
    from wwmeter import selfupdate

    repo_url = f"https://github.com/{selfupdate.REPO}" if selfupdate.REPO else ""
    command = [compiler, "/Q", f"/DAppVersion={__version__}", f"/DSourceDir={release}", f"/DOutDir={out}",
               f"/DRepoUrl={repo_url}", os.path.join(ROOT, "tools", "installer", "waveband.iss")]
    subprocess.run(command, check=True)
    setup = os.path.join(out, f"{NAME}-{__version__}-setup.exe")
    print(f"{setup}: {os.path.getsize(setup) / 1e6:.0f} MB")
    return setup


if __name__ == "__main__":
    sys.exit(main())
