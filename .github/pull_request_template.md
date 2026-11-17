<!--
Thanks for the pull request. Please open it against `main`, not `stable`.
CONTRIBUTING.md has the details behind the checklist below.
-->

## What this changes

<!-- What was wrong or missing, and what this does about it. Link the issue if there is one: "Fixes #12". -->

## How you checked it

<!-- The fight, recording or steps you used, and what the meter showed before and after. -->

## Checklist

- [ ] The tests pass: `.venv\Scripts\python -m unittest discover -s tests`
- [ ] A change to how fights are read or counted comes with a test
- [ ] Waveband stays passive: no reading or writing the game's memory, no injecting, no pressing keys, no touching the game's files
- [ ] Nothing from the game's files (assets, fonts, icons, music, decompiled code)
- [ ] Nothing personal in screenshots, recordings or test data (user name, player ID, install path)
- [ ] A change players will notice has a line in `CHANGELOG.md`
