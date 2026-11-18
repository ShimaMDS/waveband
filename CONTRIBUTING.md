# Contributing to Waveband

Thanks for wanting to help. Bug reports, ideas and pull requests are all welcome.

## Reporting a problem

Open [a new issue](../../issues/new/choose) and attach the `selftest.txt` that *Waveband
self-test* (Start menu) or `selftest.bat` (in the zip) makes. Say what you were fighting, your
screen resolution, and what the meter showed against what you expected.

## Branches

- **`main`** is where the next version is worked on. **Pull requests go to `main`.**
- **`beta`** holds each version first, as a test (`0.3.1-beta.1`), before it goes to `stable`.
- **`stable`** is what the latest release was built from, and what GitHub shows first. It only
  changes when a release goes out, so please don't open pull requests against it.

## Setting up

```powershell
git clone https://github.com/ShimaMDS/waveband.git
cd waveband
run.bat                                                       # sets up .venv, starts the meter
.venv\Scripts\python -m pip install -r requirements-dev.txt   # for the tests and tools\
.venv\Scripts\python tools\make_webview2_com.py               # WebView2's loader: the overlay needs it
.venv\Scripts\python -m wwmeter run --demo                    # a made-up fight, no game needed
```

[How it works](docs/HOW-IT-WORKS.md) explains the log, the HP bar, how damage is credited, and
what every file and tool is for.

## Before you open a pull request

- **The tests pass:** `.venv\Scripts\python -m unittest discover -s tests`. A change to how
  fights are read or counted comes with a test that shows it.
- **Keys are tested as players run Waveband.** The game runs as administrator, and Windows then
  passes a program that isn't only keys held with Ctrl or Alt. Started from an administrator
  terminal, Waveband gets every key and hides that, so try a change to the keys with Waveband
  started normally (`run.bat` from Explorer). `tools\key_reach.py` shows which keys get through.
- **Waveband stays passive.** It reads the log file the game writes and looks at the screen.
  It doesn't read or write the game's memory, inject anything into the game, press keys for
  you, or touch the game's files. Changes that do any of these won't be merged.
- **Nothing from the game's files.** No extracted assets, fonts, icons, music or decompiled
  code. Boss HP and names come from the game's published data tables through
  `tools\build_enemy_hp.py`; nothing else from the game goes in.
- **Nothing personal.** Screenshots, recordings and test data shouldn't show your user name,
  player ID, install path or anything else that's yours.
- **Keep changes focused.** One fix or feature per pull request is easier to review.
- **Write for players.** Text that players see (the meter, the dashboard, `CHANGELOG.md`) is
  short, plain and free of jargon. A change players will notice gets a line in the changelog's
  top section.

## License

Waveband is free software under the [GNU AGPL, version 3 or later](LICENSE). By sending a
pull request you agree that your contribution is shared under the same license.
