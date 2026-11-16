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

DATA_FILES = ("characters.json", "names.json", "enemy_hp.json", "part_shares.json", "digits.npz",
              "ocr/ch_PP-OCRv3_rec_infer.onnx", "ocr/NOTICE.txt")
SOURCE_FILES = ("requirements.txt", "run.bat")
SOURCE_NOTE = (
    "This is the source Waveband.exe was built from, included so you can read what it does.\n\n"
    "You do not need it to use the meter. To run from source instead of the .exe (Python 3.11 or\n"
    "newer): copy the ui and data folders from the folder above into this one, then double-click\n"
    "run.bat. The first start downloads the libraries listed in requirements.txt.\n"
)
SELFTEST_BAT = '@echo off\r\ncd /d "%~dp0"\r\nstart "" /wait Waveband.exe selftest\r\nif exist selftest.txt start "" notepad selftest.txt\r\n'


def build_exe(work: str) -> str:
    """Run PyInstaller; returns the folder holding Waveband.exe and _internal."""
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", NAME,
        # drawn by tools/make_logo.py
        "--icon", os.path.join(ROOT, "assets", "waveband.ico"),
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
        os.path.join(ROOT, "tools", "exe_entry.py"),
    ]
    subprocess.run(command, check=True)
    return os.path.join(work, "dist", NAME)


def _listed(folder: str, keep=lambda name: False) -> list[str]:
    if not os.path.isdir(folder):
        return []
    return [os.path.join(folder, name) for name in os.listdir(folder) if not keep(name)]


def _imports(path: str) -> set[str]:
    """Lower-case names of the DLLs a program file loads, from its import tables."""
    import pefile  # comes with PyInstaller

    names: set[str] = set()
    try:
        binary = pefile.PE(path, fast_load=True)
    except pefile.PEFormatError:
        return names
    try:
        binary.parse_data_directories(directories=[
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"],
        ])
        for table in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT"):
            for entry in getattr(binary, table, []):
                names.add(entry.dll.decode("ascii", "replace").lower())
    finally:
        binary.close()
    return names


def unused_qt(qt: str) -> list[str]:
    """Qt's own DLLs in the bundled PySide6 folder that nothing left in it loads.

    The web view's hook brings Qt's whole folder of QML modules, and each of those drags in the
    library behind it (Qt Quick 3D, Charts, the virtual keyboard, ...). With the QML folder
    gone, what is still needed is whatever the Python modules, the web view's helper program
    and the remaining plugins load, and whatever those load in turn.
    """
    try:
        import pefile  # noqa: F401
    except ImportError:
        print("pefile is not installed, so unused Qt libraries stay in")
        return []
    here = {name.lower(): os.path.join(qt, name) for name in os.listdir(qt) if os.path.isfile(os.path.join(qt, name))}

    def is_qt(name: str) -> bool:
        return name.startswith("qt6") and name.endswith(".dll")

    waiting = [path for name, path in here.items() if not is_qt(name) and name.endswith((".pyd", ".exe", ".dll"))]
    for folder, _, files in os.walk(os.path.join(qt, "plugins")):
        waiting += [os.path.join(folder, name) for name in files if name.lower().endswith(".dll")]
    needed: set[str] = set()
    while waiting:
        for name in _imports(waiting.pop()):
            if name in here and name not in needed:
                needed.add(name)
                waiting.append(here[name])
    return [path for name, path in here.items() if is_qt(name) and name not in needed]


def trim(release: str) -> float:
    """Delete bundled files the meter never loads. Returns the megabytes saved."""
    internal = os.path.join(release, "_internal")
    qt = os.path.join(internal, "PySide6")
    doomed = []
    resources = os.path.join(qt, "resources")
    # debug copies of the web view's resource packs, and the pack of its developer tools,
    # which the overlay never opens
    doomed += _listed(resources, lambda f: not (f.endswith(".debug.pak") or "devtools" in f))
    # the web view's own menus in 50 languages (the page has no menus), and Qt's translations
    # of dialogs the meter never shows
    doomed += _listed(os.path.join(qt, "translations", "qtwebengine_locales"), lambda f: f == "en-US.pak")
    doomed += _listed(os.path.join(qt, "translations"), lambda f: not f.endswith(".qm"))
    # AVIF pictures are never opened; Pillow goes without when the module is absent
    doomed += _listed(os.path.join(internal, "PIL"), lambda f: not f.startswith("_avif"))
    # a software stand-in for OpenGL: the overlay is drawn through Direct3D
    doomed += _listed(qt, lambda f: f.lower() != "opengl32sw.dll")
    # the PDF picture format would keep the PDF library in
    doomed += _listed(os.path.join(qt, "plugins", "imageformats"), lambda f: not f.lower().startswith("qpdf"))
    saved = 0
    for path in doomed:
        if os.path.isfile(path):
            saved += os.path.getsize(path)
            os.remove(path)
    # Qt Quick's modules and their debugging plugins: the overlay is a web page in a widget
    for folder in (os.path.join(qt, "qml"), os.path.join(qt, "plugins", "qmltooling")):
        if os.path.isdir(folder):
            saved += sum(os.path.getsize(os.path.join(f, n)) for f, _, ns in os.walk(folder) for n in ns)
            shutil.rmtree(folder)
    if os.path.isdir(qt):
        unused = unused_qt(qt)
        for path in unused:
            saved += os.path.getsize(path)
            os.remove(path)
        print(f"{len(unused)} Qt libraries nothing loads: " + ", ".join(sorted(os.path.basename(p)[3:-4] for p in unused)))
    return saved / 1e6


def copy_python(source: str, target: str) -> None:
    """The Python files of a folder, and the steps file drive_page.py is run with."""
    os.makedirs(target, exist_ok=True)
    for name in sorted(os.listdir(source)):
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

    work = os.path.join(out, "work")
    shutil.rmtree(release, ignore_errors=True)
    built = os.path.join(work, "dist", NAME)
    if not (args.keep_work and os.path.isfile(os.path.join(built, NAME + ".exe"))):
        shutil.rmtree(work, ignore_errors=True)
        os.makedirs(out, exist_ok=True)
        built = build_exe(work)
    shutil.copytree(built, release)
    print(f"trimmed {trim(release):.0f} MB of files the meter never loads")

    shutil.copytree(os.path.join(ROOT, "ui"), os.path.join(release, "ui"))
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
