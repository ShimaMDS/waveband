# Making a release

How a Waveband release is built, signed and published. The checklist at the end says what has
to hold before one goes out.

1. Set the version in `wwmeter\__init__.py` (between releases it is the next one with `.dev0`
   on the end, which the meter treats as that version). Give the top section of `CHANGELOG.md`
   its date in place of "not released yet"; its notes are what users are shown after the
   update, so they are written for users. Run the tests (one fails when the top section is not
   for the version in the source), and bring this file and `tools\START HERE.txt` (the
   testers' one-page guide) up to date.
2. In a fresh environment, outside this folder:
   `python -m venv build-env`, then
   `build-env\Scripts\python -m pip install -r requirements.txt pyinstaller`, then
   `build-env\Scripts\python tools\build_release.py --out <a folder outside this one>`.
   It builds `Waveband.exe` with PyInstaller, deletes about 310 MB the meter never loads (most
   of it parts of Qt that come along with the web view: Qt Quick's modules, 3D, charts, PDF,
   and every Qt library that nothing left in the folder loads, found by reading the import
   tables with `pefile`), adds
   `ui\`, the four data files, the guide, `README.md`, `CHANGELOG.md`, the `docs\` folder,
   `selftest.bat`, `LICENSE` and the source, and zips it. Then it compiles the installer,
   `Waveband-<version>-setup.exe`, from `tools\installer\waveband.iss` with Inno Setup 6.7 or
   newer (`winget install JRSoftware.InnoSetup`; it is found where that puts it, or give
   `--iscc`), writes `SHA256SUMS.txt` with the SHA-256 of the zip and the setup, and signs that
   file with the release key into `SHA256SUMS.txt.sig`. Without the key it says so and fails
   (`--unsigned` for a test build): installed copies would not install the release.
3. `.venv\Scripts\python tools\test_exe.py <out>\Waveband-<version>` runs the packaged self-test
   and a demo with the overlay parked off-screen, and saves a picture of the overlay to look at.
4. Publish a GitHub release tagged `v<version>` with four files: the setup, the zip,
   `SHA256SUMS.txt` and `SHA256SUMS.txt.sig`, at https://github.com/ShimaMDS/waveband. Installed
   copies find it through `REPO` in `wwmeter\selfupdate.py`. Copy the zip into
   `release\` too.

The zip never contains `config.json`, logs, `recordings\`, `tests\` or
`data\number_samples.pkl`. 0.1.0 was also scanned for the builder's user name and install path
before it went out; do that again for any zip built by other means. The .exe is unsigned, so
Windows shows an "unknown publisher" warning and some antivirus programs flag it.

**Branches and versions.**

| Branch | What it holds | Versions | Published as |
|---|---|---|---|
| `main` | Day-to-day work toward the next version | that version with `.dev0` (0.3.0.dev0) | nothing |
| `beta` | Test versions of the next version | 0.3.0-beta.1, 0.3.0-beta.2, ... | GitHub pre-releases |
| `stable` | What everyone gets, and quick fixes to it | 0.2.0, 0.2.1, 0.2.2, then 0.3.0 | ordinary GitHub releases |

Work happens on `main`. **A beta:** merge `main` into `beta`, set the version to the next beta
(`0.3.0-beta.1`), build and sign from `beta`, tag `v0.3.0-beta.1` there, and publish with
`gh release create v0.3.0-beta.1 --prerelease ...`. Its notes go in the next version's changelog
section ("0.3.0 (beta)"). **A quick fix to stable:** fix it on `stable`, set the version to the
next patch (`0.2.1`), add a changelog section for it (`## 0.2.1`, no date), and publish an ordinary release; then
merge `stable` into `main` so the fix is not lost. **The next stable version:** merge `beta` into
`stable`, set the version to `0.3.0`, make its heading plain `## 0.3.0`, and publish an ordinary release; then set
`main` to the next `.dev0`.

Installed copies on the Stable channel (the default) only see ordinary releases; on Beta (Settings,
The game, "Updates to take") they see pre-releases too, and still move on to each stable version.
GitHub never treats a pre-release as the latest release. The repository's history starts at 0.2.0.

**The release key.** `tools\release_key.py new` made it once (2026-11-16). Its private half is
`%USERPROFILE%\.waveband\release-signing-key.txt`, outside this folder, and its public half is
`RELEASE_KEY` in `wwmeter\signing.py`. Keep a copy of the key file somewhere safe that is not
this PC (a password manager): without it no further update can be signed, and installed copies
would have to be updated by hand once, to a version with a new key. Never commit, upload or
share it. Also keep two-factor login on the GitHub account the releases come from. The
signature means a taken-over account alone cannot ship an update; the key file on this PC is
then what has to stay safe.

The key file is locked with a passphrase (`tools\release_key.py protect` locks a plain one,
`passphrase` changes it): it holds the key XORed with 32 bytes scrypt derives from the
passphrase (128 MB, about half a second a try, random salt), so a copy of the file alone, taken
by a backup service, an upload or a program reading files, cannot sign anything. Keep the
passphrase long and only in the password manager. Because the passphrase is typed in a terminal,
`build_release.py` asks for it when run in one; run anywhere else (by an assistant, say), it
builds everything, says "Not signed" and exits with 1, and the maintainer signs in a terminal:
`.venv\Scripts\python tools\release_key.py sign <out>\SHA256SUMS.txt`.

## Checklist

Before publishing a release, every line should hold:

- Tests pass, and `tools\check_enemy_hp.py` shows no row that differs on the current patch.
- `README.md`, `docs\HOW-IT-WORKS.md`, this file and `tools\START HERE.txt` say what the build
  does, and the README's pictures are of this version (`tools\screenshots.py`).
- The version in `wwmeter\__init__.py` has lost its `.dev0`, and the top section of
  `CHANGELOG.md` is headed with just the version (no date) and reads right to someone who only uses the meter.
- Built with `tools\build_release.py` in a fresh environment; `tools\test_exe.py` passes and the
  overlay picture looks right.
- The zip holds no `config.json`, logs, recordings or number samples, and no user name or
  install path.
- `SHA256SUMS.txt.sig` checks out (`tools\release_key.py verify <out>\SHA256SUMS.txt`), and the
  release has the setup, the zip, the checksums and the signature, tagged `v<version>`.
- `REPO` in `wwmeter\selfupdate.py` names the repository the release goes to.
- Published from the right branch: a beta (`x.y.0-beta.N`) from `beta` as a pre-release, a stable
  version or a fix to one from `stable` as an ordinary release.
