# Making a release

How a Waveband release is built, signed and published. The checklist at the end says what has
to hold before one goes out.

1. Set the version in `wwmeter\__init__.py` (between releases it is the next one with `.dev0`
   on the end, which the meter treats as that version). Head the top section of `CHANGELOG.md`
   with the version alone (`## 0.3.0`, no date) in place of "not released yet", or
   `## 0.3.0 (beta)` for a beta; its notes are what users are shown after the update, so they
   are written for users. Run the tests (one fails when the top section is not
   for the version in the source), and bring this file and `tools\START HERE.txt` (the
   testers' one-page guide) up to date.
2. Once per clone, `run.bat` (or `.venv\Scripts\python tools\make_webview2_com.py --loader-only`) fetches WebView2's loader
   into `lib\webview2\` (the build stops without it). Then, in a fresh environment, outside this
   folder:
   `python -m venv build-env`, then
   `build-env\Scripts\python -m pip install -r requirements.txt pyinstaller`, then
   `build-env\Scripts\python tools\build_release.py --out <a folder outside this one>`.
   It builds `Waveband.exe` with PyInstaller, with version information (product, version,
   description; antivirus engines that score files by machine learning flag an exe without
   it), leaves Qt out (only some tools use it; up to 0.3.1 it drew the overlay and was 300 MB
   of the build), checks WebView2's loader against its pinned SHA-256, unpacks
   PyInstaller's `base_library.zip` into a folder of the same name (Nexus Mods rejects an
   upload with an archive inside it; the build stops if any is left), adds
   `ui\`, WebView2's loader and its licence (`lib\webview2\`), the data files (the boss HP tables, names, characters, part shares and the text
   reader's model in `data\ocr`), the guide, `README.md`, `CHANGELOG.md`, the `docs\` folder,
   `selftest.bat`, `LICENSE` and the source (only what git keeps: the build has to run in a
   clone, and a file never committed stays out), and zips it. It stops before PyInstaller when
   anything it ships (`wwmeter\`, `tools\`, `ui\`, `requirements.txt`, `run.bat`) differs from
   the commit, so the exe and its source are the same code; an `--unsigned` test build only
   says so. Then it compiles the installer,
   `Waveband-<version>-setup.exe`, from `tools\installer\waveband.iss` with Inno Setup 6.7 or
   newer (`winget install JRSoftware.InnoSetup`; it is found where that puts it, or give
   `--iscc`), writes `SHA256SUMS.txt` with the SHA-256 of the zip and the setup, and signs that
   file with the release key into `SHA256SUMS.txt.sig`. Without the key it says so and fails
   (`--unsigned` for a test build): installed copies would not install the release.
3. `.venv\Scripts\python tools\test_exe.py <out>\Waveband-<version>` runs the packaged self-test
   and a demo (the overlay in the screen's bottom right corner for a few seconds, then quit as
   the tray menu quits it), and saves a picture of the overlay to look at.
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
| `main` | Day-to-day work toward the next version | that version with `.dev0` (0.3.1.dev0) | nothing |
| `beta` | Each version first, as a test | 0.3.1-beta.1, 0.3.1-beta.2, ... | GitHub pre-releases |
| `stable` | The same version once its beta holds | 0.3.1, then 0.3.2, ... then 0.4.0 | ordinary GitHub releases |

**Every version goes out twice** (owner, 2026-11-17): as a beta first and then as a stable
release of the same number. 0.3.1-beta.1 (and beta.2 and so on if it needs fixing), then 0.3.1;
then 0.3.2-beta.1, 0.3.2; and so on up to 0.4.0-beta.1, 0.4.0. Waveband counts only a
`-beta.N` version as a beta (`selfupdate.is_beta`): a copy on one follows the Beta channel until
its user picks a channel, any other copy Stable.

Work happens on `main`. Do the release steps in separate working copies
(`git worktree add <folder> beta`), so the folder the meter runs from is never switched.

**A beta (0.3.1-beta.1):** merge `main` into `beta`; set `__version__ = "0.3.1-beta.1"` and head
the changelog's top section `## 0.3.1 (beta)`; commit "Waveband 0.3.1-beta.1"; build from `beta`
(steps 2 and 3 above), sign, tag `v0.3.1-beta.1` there, push `beta` and the tag, and publish with
`gh release create v0.3.1-beta.1 --prerelease --verify-tag ...`. A fix found in it goes on `main`
and out as `0.3.1-beta.2` the same way.

**The stable release of it (0.3.1):** once a beta has held for a few days, set
`__version__ = "0.3.1"` on `beta` with the plain heading `## 0.3.1`; commit "Waveband 0.3.1";
merge `beta` into `stable` (`git merge -X theirs beta` if `stable` has commits of its own, then
`git diff beta` must be empty); fast-forward `beta` to that commit; build from `stable`, sign, tag
`v0.3.1`, push `stable`, `beta` and the tag (`stable` is protected: pull requests only, but the
owner's account may push past that), and publish with `gh release create v0.3.1 --latest
--verify-tag ...`. Then fast-forward `main` to `stable`, set it to the next `.dev0`
(`0.3.2.dev0`) with an empty `## 0.3.2 (not released yet)` section (the changelog test allows an
empty top section only on a `.dev` version), and push `main`.

Installed copies on the Stable channel only see ordinary releases; on Beta (Settings, Game,
"Updates to take") they see pre-releases too, and still move on to each stable version. GitHub
never treats a pre-release as the latest release. The repository's history starts at 0.2.0.

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
`.venv\Scripts\python tools\release_key.py sign <out>\SHA256SUMS.txt`. Or drag `SHA256SUMS.txt`
onto `tools\sign_release.bat`: it shows the file, asks for the passphrase, signs and checks the
signature against the public key in the code.

## Checklist

Before publishing a release, every line should hold:

- Tests pass, and `tools\check_enemy_hp.py` shows no row that differs on the current patch.
- `README.md`, `docs\HOW-IT-WORKS.md`, this file and `tools\START HERE.txt` say what the build
  does, and the README's pictures are of this version (`tools\screenshots.py`).
- The version in `wwmeter\__init__.py` has lost its `.dev0` (`0.3.1-beta.1` for a beta, `0.3.1`
  for its stable release), and the top section of `CHANGELOG.md` is headed `## 0.3.1 (beta)` or
  `## 0.3.1` (no date) and reads right to someone who only uses the meter.
- `Waveband.exe` carries version information (Properties, Details); without it, machine-learning
  antivirus engines flag it (found on VirusTotal, 2026-11-17). Before a stable release, the
  owner checks the zip, the setup and `Waveband.exe` on VirusTotal.
- Built with `tools\build_release.py` in a fresh environment; `tools\test_exe.py` passes and the
  overlay picture looks right.
- The zip holds no `config.json`, logs, recordings or number samples, and no user name or
  install path.
- `SHA256SUMS.txt.sig` checks out (`tools\release_key.py verify <out>\SHA256SUMS.txt`), and the
  release has the setup, the zip, the checksums and the signature, tagged `v<version>`.
- `REPO` in `wwmeter\selfupdate.py` names the repository the release goes to.
- Published from the right branch: a beta (`x.y.z-beta.N`) from `beta` as a pre-release, its
  stable release (`x.y.z`) from `stable` as an ordinary release, marked latest.
