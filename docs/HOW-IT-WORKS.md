# How Waveband works

The long version, for players who want the details and for anyone reading the code. The short
version is the [README](../README.md); what changed in each release is in the
[changelog](../CHANGELOG.md); how a release is built is in [RELEASING.md](RELEASING.md).

Waveband is a damage meter that sits on top of Wuthering Waves. It is passive: it reads the log
file the game writes anyway and looks at the screen. It never opens, reads or changes the game
process, and never presses keys. It is an unofficial fan tool, not made or endorsed by Kuro Games.

This describes 0.2.0, built for game version 3.8 and tested at 2560x1440 and 1920x1080. Inside
the code Waveband is still called `wwmeter` (the Python package, `python -m wwmeter`, the
settings line).

- [Using it](#using-it)
- [What it can measure](#what-it-can-measure)
- [How it measures](#how-it-measures)
- [How accurate it is](#how-accurate-it-is)
- [Boss HP after a game patch](#boss-hp-after-a-game-patch)
- [Installing and updates](#installing-and-updates)
- [Settings](#settings)
- [Themes and colours](#themes-and-colours)
- [Reading damage numbers (optional)](#reading-damage-numbers-optional)
- [Commands and tools](#commands-and-tools)
- [If something looks wrong](#if-something-looks-wrong)
- [For developers](#for-developers)

## Using it

**Starting.** With the installer, start Waveband from the Start menu. With the zip, run
`Waveband.exe`. From source, run `run.bat` (Python 3.11 or newer; the first start installs what
`requirements.txt` lists). A tray icon appears, and the meter shows over the game whenever the
game is in front. Quit from the tray icon. The game has to run in Borderless or Windowed mode:
nothing can draw over exclusive fullscreen. Errors go to `waveband.log` beside the program.

**What draws it.** The meter is a web page (`ui\`) shown in a window of its own: since 0.3.2 by
WebView2, the web view Windows 10 and 11 already have, and up to 0.3.1 by Qt's own copy of
Chromium. Qt is kept for one version as a fallback: Settings, DPS Meter, "What draws the meter",
and Waveband uses it by itself when WebView2 is missing or won't start (`waveband.log` says so).
WebView2 keeps a cache in `%LOCALAPPDATA%\Waveband\WebView2`; the uninstaller deletes it.

**Keys.** They work only while the game is in front, so they stay free everywhere else. The game
itself uses F1 to F6.

| Key | What it does |
|---|---|
| Alt+F7 / Alt+Shift+F7 | The fight before / after the one on the meter |
| Alt+F8 / Alt+Shift+F8 | Hide or show the meter / one-line meter |
| Alt+F9 | Damage per second, or percent of the enemy's HP per second |
| Alt+F10 | Start a new fight |
| Alt+F11 | Move mode: drag the meter, scroll to resize, Alt+F11 again to lock |

Why Alt: the game runs as administrator, and while a program that runs as administrator is in
front, Windows passes a program that doesn't only the keys held with Ctrl or Alt. F8 alone, or
Shift+F8, never reaches Waveband; that keeps any program from reading what is typed into an
administrator's window. Up to 0.3.0 the keys were F7 to F11 without Alt and did nothing for
that reason; settings still on those keys move to the Alt ones by themselves. A key without
Ctrl or Alt can still be chosen, for a Waveband run as administrator; the settings page says
when one won't arrive. Holding Alt in the game also brings up the mouse cursor, which move mode
wants anyway.

The keys without Shift are listed along the top of the meter ("Show the keybinds on the meter" turns that
off). Three more actions have no key until you give them one: hiding between fights, copying a
fight's summary, and the line of keys. All of them are also in the tray menu. If another program
already holds one of these keys, Windows won't give it to Waveband; the meter says so ("Alt+F9 is
in use by another program"), and you can pick another key in Settings.

**The tray menu** has every action, a theme picker, and opens the dashboard in your browser. The
dashboard has three pages: Fights, Settings and What changed.

**Sessions and earlier fights.** Each start of Waveband is a session. Finished fights are saved
as they end, one file per session in the `sessions` folder (`sessions\2026-11-15_16-30-05.json`),
and the list starts empty at every start. Alt+F7 steps back through this session's fights on
the meter itself and Alt+Shift+F7 steps forward again; a line on the meter says which fight is shown,
and the meter keeps measuring behind it. When a new fight starts, the meter goes back to it by
itself; stepping back during a fight still works. Earlier sessions open from the tray menu or from the
list on the dashboard's Fights page. They are only read: new fights still go to the current
session, and a new fight closes the earlier session on show. Session files are plain JSON and are never deleted by Waveband.

**Copying a fight.** "Copy this fight's summary" puts the fight on show on the clipboard as a few
lines written in Discord's markdown, ready to paste into a chat:

    ### Fallacy of No Return: Tethys System (Lv 70)
    **10,293 DPS** · 682,649 damage · 1:06 · 100% of its 682,649 HP
    1. **Hiyuki** · 9,080 DPS · 602,165 (88.2%)
    2. **Lynae** · 822 DPS · 54,522 (8.0%)
    3. **Shorekeeper** · 391 DPS · 25,963 (3.8%)
    -# Measured from the boss HP bar and the boss's HP from the game's data. Split by who was on field. Waveband 0.3.1

Discord shows the fight as a small heading, the DPS in bold, the characters as a numbered list
and the last line as small grey text, on a phone too. Pasted somewhere without markdown, the few
marks stay and the text still reads. Nothing is sent anywhere.

**One-line meter, hiding, screenshots.** Alt+Shift+F8 shrinks the meter to the clock and the damage
per second; anything it needs to explain is still shown underneath. "Hide the meter between
fights" takes it off the screen when no fight is on (a finished fight stays up for 12 seconds). A fight
ends when the game says combat is over, or after a few seconds without damage; while the game
still counts you as in combat (an enemy nearby that you haven't fought off) it stays open, for
up to two minutes.
"Hide from screenshots and streams" keeps the meter out of every capture, Win+Shift+S included;
it is off by default, so if the meter is missing from a screenshot, that switch is on.

## What it can measure

Waveband never sees damage directly. It sees how much HP an enemy has lost, so what it can show
depends on what the game reveals about each enemy:

| The enemy... | Examples | Waveband shows |
|---|---|---|
| writes its HP to the log after every hit | Crownless, Chasm Guardian, Havoc Dreadmane | Exact damage and DPS |
| shows only a boss HP bar | Dreamless, Inferno Rider, Impermanence Heron, Nameless Explorer | Damage and DPS: the share of the bar lost, times the boss's real HP from the game's data |
| shows a bar, but its HP can't be worked out | some open-world and quest placements | Percent of HP per second, and the meter says why |
| shows neither | most common enemies | Nothing; the meter names the enemy and says why |

Alt+F9 switches between damage and percent of HP. Figures per second are written short the way the
game writes big numbers (15.38k); the copied summary keeps every digit. Bar-only bosses are as
fine as the bar can be read, about 0.1% of the boss's HP, so single hits aren't told apart there.

Not possible at all: per-skill damage, crit rate, healing. The log doesn't carry them.

## How it measures

### The game's log

After each hit the game writes a line like
`[CombatInfo] [Part] ... UpdatePartInfo [TagName: 怪物.common.弱点][LifeValue: 142929]`. For tags
starting `怪物.common.` the value is the enemy's whole HP, and the first line, written before any
hit, is its full HP. The drop between two lines is the damage. Tags named after the enemy are
breakable parts with pools of their own (a wing, a weak point); those aren't the HP, and neither
are weak points that start from different values.

The log is scrambled byte by byte (even bytes XOR 0xA5, odd bytes XOR 0xEF) and is about 99%
rendering warnings; Waveband unscrambles it and keeps the few kinds of line it needs.

### The boss HP bar

The bar is read off the screen ten times a second. Its position is measured at 2560x1440 and
scaled by the window's height, anchored to the centre, so it works at any 16:9 size and should
on ultrawide. A drop is believed once it has held for 0.6 seconds, which filters out a hit's
white flash. The HUD hides during ultimate cutscenes; the bar's level is remembered across the
gap, so what the ultimate dealt is counted when the bar comes back.

A bar that refills is the boss's next bar. The rest of the old bar is counted as dealt, and the
new bar is counted from its highest reading. With one boss about this holds whatever was left of
the old bar; with two about, only up to 10%, since the bar going up might be the other boss.
A boss that dies a moment after its next bar appears (Inferno Rider at the lowest hologram
difficulty shows its second bar for under two seconds) is still counted as both bars.

### Boss HP from the game's data

The game works out a monster's full HP as `LifeMax x LifeMaxRatio(level) / 10000`, rounded down:
a base row that depends on where the enemy is placed, and a growth curve by level. The same boss
has a different base row in the open world, in each Tactical Hologram difficulty and in the Tower
of Adversity (Crownless: 690, 6,549 and 15,120), which is why a wiki's "base HP" is several times
too low for those modes. `data\enemy_hp.json` holds the game's tables boiled down to what this
needs, and the log supplies the rest:

- When an enemy spawns, the log names its placement:
  `[Entity] ... 实体详细数据。 [CreatureDataId: n][ConfigType: Prefab|Level|Template][EntityType: Monster][PbDataId: n][PrefabId: n]`.
- `[World] [CreatureController.JoinSceneNotify] Begin [InstanceId: n]` names the map the player
  is in, and for tower floors the enemies' level.
- The level comes from the placement or the instance. When neither fixes one, as with open-world
  bosses that follow your world level, the `Lv` read off the boss bar's title is used. The title
  is never preferred over the data: in the hologram it can show a higher level than the one HP
  uses (see below).

The bar is taken to belong to whichever boss-class enemy the log named most recently, within 15
seconds, and each drop is multiplied by that enemy's own HP, so a second boss or a phase with
different HP is counted with its own figure. The meter also reads the spawn lines already in the
log when it starts, so a boss that loaded before Waveband did is still recognised.

Some placements multiply HP by an "extra rate" from a table that isn't in the client's data.
Those are left unknown rather than guessed. Bosses are well covered: about 96% of boss placements
in the 3.8 data get an HP (Tactical Hologram 281 of 282, Tower of Adversity 248 of 255;
`tools\boss_coverage.py` lists the rest).

**HP from a boss's parts.** Where the data gives no HP, Waveband tries the boss's breakable parts.
A part's pool is a fixed share of the boss's full HP wherever it is placed (Inferno Rider's weak
point is 15% and its back 25%, Impermanence Heron's wing 2%, Nameless Explorer's part 17%), so the
pool divided by the share is the full HP. Those three ship in `data\part_shares.json`; Waveband
learns others when it sees a part on a boss whose HP the data does give, and keeps them in
`learned_parts.json`. Only round shares are taken, and a part seen with two different shares is
never used. A fight measured this way says so ("derived") on the dashboard and in the summary.

### Who gets the credit

The game doesn't log who dealt a hit. Damage goes to whoever is on field
(`[Battle] RoleTeam PerformPossess` logs every switch), so off-field damage (outros, coordinated
attacks, lingering effects) counts for the active character.

For bar-only bosses, a drop is credited to whoever was on field when the bar fell, not when the
drop was confirmed 0.6 seconds later. When it fell is worked out from the last two seconds of
readings. Around an ultimate's cutscene, the damage shows up as the bar slides down just after
it returns, often just as the next character comes in; a fall that starts within 0.7 seconds of
the bar's return goes to whoever was on field when it returned.

**Time on field** comes from the same switch lines and adds up to the fight's length. "Damage
per second on field" divides a character's damage by their own time on field. Because off-field
damage counts for whoever is on field, that figure flatters a character who stands on field
while another's skills are running. Both figures are off unless chosen in Settings, Rows.

### Damage over time

The game writes no HP line when a damage-over-time tick lands (Spectro Frazzle, Glacio Chafe), so
on such a team the log comes up short. When an enemy has both a logged HP and a bar, Waveband
compares them. If the bar shows more HP lost than the log, and the two agreed earlier in the
fight, the difference goes in its own row, **Over time**. A hit can reach the log before the bar
shows it, so the comparison is made a second after each hit, and the bar and the log may differ
by 0.8% before anything is booked. A gap that opens by more than 3% at once is believed only with
one boss about, and only after it has lasted two seconds.

The logged HP never catches up with the ticks, so a boss killed that way dies with HP still
logged. The game writes the killing hit's own HP line just after the death line: that hit stays
with the character who landed it, and whatever is still logged goes to Over time.

### When a fight starts and ends

A fight starts at the first HP drop and ends one second after the game logs
`[Battle] NotifyInFight: False`, its own combat flag. When an enemy dies
(`RemoveHatredItem ... [reason: Dead]`), whatever HP it still showed is credited to the fight,
which matters when the killing blow lands in a cutscene; a death reported up to 10 seconds after
the fight closed still counts. Otherwise a fight ends after 8 seconds with no damage and no
skills (30 with a boss bar up, 120 while the game's combat flag is still on, so a long lull
doesn't split one fight in two), or when the same boss comes back at full HP, which is what
restarting a challenge looks like. The clock stops a second after the last hit, so the figures
hold instead of sinking.

### Names

The log uses internal names (`BP_Kmola` is Carlotta). Every skill ID starts with the character's
game ID (skill 1107051 belongs to 1107), so Waveband reads the ID from a character's first skill.
Characters and enemies are named from the game's own text tables, in the language the game is
set to: English, both Chinese scripts, Japanese, Korean, German, Spanish, French, Portuguese or
Thai. The language is read from the game's settings store (`Saved\LocalStorage\LocalStorage.db`,
opened read-only and without locking it) every few seconds, so switching the game's language
switches the names, mid-fight too. Settings, The game can fix one language instead. A name a
language lacks shows in English.

A fight is named after the boss on the bar, or with no bar after the enemy with the most HP, with
the level its bar shows. Elements and weapons come from `data\characters.json`, and for a
character newer than that file, from the game's data.

## How accurate it is

- **Exact where the log has HP.** The first HP value logged matches the HP worked out from the
  game's data to the point, for every enemy checked (13 placements, among them Crownless in the
  tower at 5,510,473 and at three hologram difficulties). `tools\check_enemy_hp.py` repeats this
  on your own logs.
- **Bar-only bosses: within about 1% of the kill.** Kills of Dreamless (99.75%), Impermanence
  Heron (99.62%), Denia (100%), Inferno Rider (two bars, 199.87%) and others. The missing fraction
  is the bar's own resolution: one pixel is 0.13% of the boss's HP at 1440p and 0.18% at 1080p.
- **Bar against log:** on a tower fight with both, the median difference was 0.07% of the boss's
  HP and 99% of readings were within 1%. Measured from the bar alone, the same fight came to
  0.65% over the exact total.
- **Per character on bar-only bosses:** good to a pixel or two at each switch, about 0.25% of the
  boss's HP. On that tower fight each character's damage from the bar was within 4.2% of their
  exact damage (0.8% for one, 2.0% and 4.2% for the others).
- **Parts:** on five hologram Inferno Rider fights, the HP worked out from its parts equalled the
  data's figure exactly.

**The level on screen isn't always the level HP uses.** In the Tactical Hologram, Crownless's bar
shows the difficulty's level while its HP is worked out from a lower one:

| Hologram difficulty | I | II | III | IV | V | VI |
|---|---|---|---|---|---|---|
| Level on the bar | 60 | 65 | 70 | 80 | 90 | 100 |
| Level HP uses | 55 | 60 | 65 | 75 | 80 | 90 |
| HP | 144,681 | 229,768 | 361,512 | 739,406 | 1,024,088 | 1,719,806 |

So the data's level always wins over the one on screen. Every other hologram boss is placed at
the level its difficulty shows, and difficulty VI of Sigillum, Denia and Myriad Snare fixes no
level, so there the level is read off the bar (Denia at VI: "Lv 100", 4,363,915 HP, as the data
predicts). `tools\level_check.py` lists these cases from the data.

**Not checked yet:** 4K and ultrawide screens; game clients in languages other than English,
Korean and Japanese; a boss placement that really has an extra rate (whether its parts are the
same share of the raised HP is assumed).

## Boss HP after a game patch

`data\enemy_hp.json` is built for one game version. When the installed game is a newer version
than the data, the meter says so between fights.

"Update boss HP tables" in the tray menu (also in Settings, The game, and `Waveband.exe update`)
reads the installed version and fetches that version's data from
[Arikatsu/WutheringWaves_Data](https://github.com/Arikatsu/WutheringWaves_Data), a community copy
of the game client's data tables published per version: about 205 MB of tables plus the text of
English, the game's language and the language picked in Settings. Only JSON is fetched and
nothing in it is run. It takes about a minute, the downloads are deleted afterwards, and the
running meter picks up the new data without a restart. If anything goes wrong (no connection,
the new version not published yet, a table missing), nothing is changed. No game file is read or
changed for this.

For developers, after a patch: `tools\build_enemy_hp.py` does the same in every language and keeps
the downloads; then `tools\check_enemy_hp.py` (every row should say `match`) and
`tools\level_check.py` (its first list should still name only Crownless).

## Installing and updates

**The installer** installs for your Windows account only, with no administrator prompt, into
`%LOCALAPPDATA%\Programs\Waveband`, with a Start menu entry (a desktop icon and starting with
Windows are optional). On a first install it can bring settings, fights and learned part shares
over from a folder an older copy was unzipped in. Uninstalling removes the program and leaves
what Waveband wrote beside it: settings, fights and logs. **The zip** works anywhere, with nothing
installed.

**Updates.** Waveband asks GitHub for the newest release when it starts and once a day (turn it
off in Settings, The game). The request names Waveband and its version and nothing about you.
When there's a newer version, the meter says so between fights and the tray menu gets "Install
update". **Stable** only offers stable versions (0.3.0, 0.3.1, ...); **Beta**
also offers the test version each of them gets first (0.3.1-beta.1 before 0.3.1) and still moves
on to each stable version. Choose
under Settings, Game, "Updates to take"; until you do, a beta of Waveband is on Beta and any
other version on Stable. An installed copy then downloads the installer, checks it, runs it quietly and starts
again on the new version; the zip copy just tells you where to download it. "Install updates at
start without asking" is off unless you turn it on.

**How an update is checked.** Every release carries `SHA256SUMS.txt` (the SHA-256 of the
installer and the zip) and `SHA256SUMS.txt.sig`, that file's Ed25519 signature. The signing key
is kept off GitHub, locked with a passphrase, and Waveband carries its public half
(`RELEASE_KEY` in `wwmeter\signing.py`). An update is installed only when the signature checks
out and the installer matches its checksum, so even someone who took over the GitHub account
couldn't ship one. The signature check is the algorithm of RFC 8032 in plain Python, tested
against the RFC's own test vectors.

## Settings

"Settings" in the tray menu opens the settings page of the dashboard
(`http://127.0.0.1:5055/?view=full#settings`). Changes are checked, saved and used at once; only
"What draws the meter" waits for the next start, and no file has to be opened.

- **Keybinds.** Click a keybind, then press the key you want. Function keys, letters, digits and the
  navigation keys work, alone or with Ctrl, Alt or Shift; a letter or digit needs Ctrl or Alt,
  because the game uses those itself. A key another action has is refused. A key without Ctrl or
  Alt is taken, but marked: it won't reach Waveband while the game, run as administrator, is in
  front, unless Waveband runs as administrator too.
- **Colours.** A colour of your own for each element.
- **DPS Meter.** The theme, damage or percent, the size, the switches the tray menu has, and what
  draws the meter (WebView2 or Qt).
- **Rows.** Which figures each character's row shows and in what order (damage per second, total,
  share, time on field, damage per second on field), and how many decimals.
- **Game.** The language of names, the game's log folder ("Find it for me" usually does it), the
  boss HP tables, and Waveband's own updates: Stable or Beta, looking for them, and installing
  them without asking.
- **Import / Export.** All settings as one line of text starting `wwmeter1:`, to paste into Waveband on
  another PC or into a bug report. It leaves out the log folder (its path can contain your
  Windows user name), the port, and what draws the meter (that is about this PC's WebView2).

Settings are kept in `config.json` beside the program, written the first time one changes; the
fields and defaults are in `wwmeter\config.py`. A few are only there, for hand editing with
Waveband closed: `port`, `capture_backend`, `capture_fps`, `capture_tools`, `read_numbers`,
`encounter_timeout` and `boss_bar`. The log folder is found automatically: in Steam's libraries
and the usual install folders on every drive, taking the install whose log was written last.

**Who can reach the dashboard.** The server listens on `127.0.0.1` only, so nothing off this PC
can. A web page open in a browser on this PC could still try to talk to it, so the server only
answers its own pages: the live feed is refused to pages from anywhere else, and requests have to
be addressed to `127.0.0.1` or `localhost`. The overlay, the dashboard and an OBS browser source
pointed at it all work.

**After an update** the meter says "Updated to x.y.z" once, and What changed marks what's new
since the version you last ran.

## Themes and colours

The tray menu's Theme entry (and Settings, DPS Meter) switches the look at once. **WuWa**, the
default, follows the game's own HUD. The six element themes (Glacio, Fusion, Electro, Aero,
Spectro, Havoc) are the WuWa look in that element's colours: the game's own colour for the
element, a second colour from what that element's characters wear, and a ground, hairline,
waveform and dashboard background tinted to match. Each also has its own typeface, one that
Windows ships (Corbel, Franklin Gothic, Bahnschrift semi-condensed, Candara, Constantia and
Cambria; where a face draws old-style digits, the digits come from Calibri or Cambria so numbers
keep an even height), and its own mark and wordmark in the dashboard's top bar, from
`ui\brand\` (drawn by `tools\make_logo.py`). The program's icon, the installer and the GitHub
page keep the default Resonance Halo whatever the theme. **Classic**, the original dark panel, is
there too. Each theme is one stylesheet in `ui\themes` (the element ones are written by
`tools\make_themes.py`); copy one to make your own and it appears in the menu. Add `&theme=havoc`
to the dashboard's address to preview one.

Characters are coloured by element, in the game's own element colours: Glacio `#41AEFB`, Fusion
`#F0744E`, Electro `#B46BFF`, Aero `#55FFB5`, Spectro `#F8E56C`, Havoc `#E649A6`. When two
characters share an element, the second gets a lighter or darker shade.

## Reading damage numbers (optional)

Setting `"read_numbers": true` in `config.json` reads the floating damage numbers off the screen,
for enemies that neither log HP nor show a bar. It is rough and off by default: graded against
exact damage it reads about half of it, with a lot of noise from effects in the same colour and
overlapping numbers. The meter marks such figures "rough".

## Commands and tools

Run from the project folder with `.venv\Scripts\python -m wwmeter <command>`:

| Command | What it does |
|---|---|
| `run` | The meter and overlay (what `run.bat` starts) |
| `run --demo` | A made-up fight, to try things without the game |
| `run --no-overlay` | Dashboard only |
| `update [--branch 3.9] [--languages all]` | Rebuild the boss HP data for the installed game version |
| `selftest` | Check each part Waveband depends on and write `selftest.txt` |
| `record` | Save frames and the log of a fight into `recordings\`, for testing |
| `replay <folder>` | Run a recording through the meter and print the result |
| `decode [file]` | Write a readable copy of a `Client.log` |
| `--version` | Print the version |

Tools, run with `.venv\Scripts\python tools\<name>.py`:

| Tool | What it does |
|---|---|
| `log_report.py [minutes]` | What the log says about recent fights: enemies, placements and their HP, part pools, combat flags, deaths. The first thing to run when the meter and a fight disagree |
| `build_enemy_hp.py` | Rebuild `data\enemy_hp.json` in every language, keeping the downloads |
| `check_enemy_hp.py` | Compare the data's HP with every full HP in your logs |
| `level_check.py` | List placements whose bar shows a different level from the one HP uses, or fixes none |
| `boss_coverage.py [--list MODE]` | Count the boss placements the data gives an HP for, by mode |
| `wiki_hp.py "Enemy" [levels]` | Open-world base HP by level from the Fandom wiki (not used by the meter) |
| `grade_number_reader.py`, `collect_number_samples.py`, `build_digit_templates.py` | Grade and train the optional damage-number reader |
| `build_release.py --out <folder>` | Build `Waveband.exe`, the zip, the installer and the signed checksums. See [RELEASING.md](RELEASING.md) |
| `release_key.py` | The release signing key: make, lock, sign, verify |
| `sign_release.bat` | Drag a release's `SHA256SUMS.txt` onto it: shows the file, asks for the key's passphrase, signs and checks the signature |
| `test_exe.py <folder>` or `--source` | Smoke-test a built `Waveband.exe` (or the source): the self-test, then a demo with each overlay, WebView2's quit as the tray menu quits it |
| `make_webview2_com.py` | Fetch Microsoft's WebView2 SDK (pinned, hash-checked): its loader into `lib\webview2\`, and `wwmeter\webview2_com.py` written from its `WebView2.h`. Run once after cloning |
| `webview2_overlay.py` | Check the WebView2 overlay on this PC against a running meter: transparency, clicks passing, move mode, out of screenshots, memory |
| `render_page.py`, `drive_page.py` | Render or script a page of a running meter, to check the look and the controls without the game; `settings_walk.js` is the `drive_page.py` script that uses every control of the settings page (against a demo meter with settings of its own) |
| `screenshots.py` | Take the README's pictures from the demo meter |
| `memory_steps.py [page]` | Load the meter's parts one after another and say how much memory each adds (commit and working set), ending with the overlay page of a running meter |
| `key_reach.py [key ...]` | Which hotkeys reach a program that isn't run as administrator while the game is in front: run it from an administrator terminal, click into the game, and it taps each key (F13 alone, with Shift, Ctrl, Alt by default) and says which arrived |
| `make_logo.py` | Draw the logo, the icons, the installer's pictures and each element theme's mark and wordmark |
| `make_themes.py` | Write the six element themes from their colours and typefaces |
| `theme_previews.py` | Pictures of every theme's meter and dashboard, drawn twice as sharp, and a grid of them all, in `assets\themes\` (kept out of git) |
| `exe_entry.py` | What `Waveband.exe` runs (used by `build_release.py`) |
| `START HERE.txt` | The testers' one-page guide; `build_release.py` puts it in every release with the version filled in |

## If something looks wrong

- **Not sure what's wrong:** run "Waveband self-test" from the Start menu, `selftest.bat` in the
  zip, or `python -m wwmeter selftest`. It checks each part and writes `selftest.txt`.
- **The meter doesn't show:** the game has to be in front, in Borderless or Windowed mode. If it
  still doesn't, look in `waveband.log` and the self-test's "overlay window" line; switching
  "What draws the meter" to Qt and starting Waveband again gets the old overlay back.
- **The meter is missing from screenshots:** "Hide from screenshots and streams" is on.
- **"Can't find the game's log file":** Settings, The game, "Find it for me", or paste the game's
  folder. The log lives in `...\Wuthering Waves Game\Client\Saved\Logs`.
- **A boss shows percent instead of damage:** its HP isn't known. After a game patch, use "Update
  boss HP tables". Otherwise its placement has an extra rate, or its level isn't fixed and hasn't
  been read off the bar yet (it switches to damage once it has). The dashboard's "Damage from" line
  says which source is in use.
- **The meter names an enemy and says it doesn't report HP:** that enemy logs nothing and has no
  boss bar. `tools\log_report.py` shows what the log had.
- **"Can't make sense of the game's log":** the log's scrambling changed; please report it.
- **Restarting Waveband loses the fight in progress.** Finished fights are kept; restart between
  fights.

If none of that helps, [open an issue](https://github.com/ShimaMDS/waveband/issues/new/choose) with
your `selftest.txt`.

## For developers

The game rotates `Client.log` by renaming it, so the file has to be opened with delete sharing
(`wwmeter\logtail.py`) or the game's rename fails. After some rotations the file starts with an
unscrambled byte-order mark while the text is still scrambled, so only the text is used to detect
the scrambling (`wwmeter\logcodec.py`).

After a game patch, run `tools\log_report.py` and check that these lines still appear:
`UpdatePartInfo ... [LifeValue: n]`, `RoleTeam PerformPossess`, `NotifyInFight`,
`RemoveHatredItem ... [reason: Dead]`, `BeginSkill ... [技能Id: n]`, and the two boss HP needs:
`实体详细数据。 [CreatureDataId: n] ... [ConfigType: ...][EntityType: Monster][PbDataId: n][PrefabId: n]`
and `JoinSceneNotify] Begin [InstanceId: n]`. Then rebuild and check the boss HP data.

| File | What it holds |
|---|---|
| `wwmeter\logcodec.py`, `logtail.py`, `logparse.py` | Unscramble, follow and parse the log |
| `wwmeter\tracker.py` | Fights: sources, credit, start and end, bar against log, bar percent into damage |
| `wwmeter\gamedata.py`, `data\enemy_hp.json`, `data\part_shares.json` | Which placement an enemy is, its full HP and name from the game's data, and the share of a boss's HP each part is |
| `wwmeter\update.py` | `wwmeter update`: fetch the game's data and rebuild `data\enemy_hp.json` |
| `wwmeter\hud.py`, `ocr.py`, `capture.py`, `engine.py` | The boss bar and its title from a frame (`ocr.py` runs PaddleOCR's text recognizer, `data\ocr`, on ONNX Runtime); frames of the game window; the log and screen threads |
| `wwmeter\server.py`, `app.py` | The local server and the wiring |
| `wwmeter\overlay_webview2.py`, `webview2_com.py`, `lib\webview2\` | The overlay window on WebView2 (DirectComposition, click-through, out of screenshots) and the Windows tray icon and menu; the WebView2 COM interfaces (written by `tools\make_webview2_com.py`); WebView2's loader |
| `wwmeter\overlay_common.py`, `overlay.py` | What both overlays share (hotkeys, the tray menu's entries and actions, following the game); the Qt overlay, the fallback |
| `wwmeter\settings.py`, `ui\settings.js` | The settings page and the one-line settings export |
| `wwmeter\selfupdate.py`, `signing.py` | Waveband's own updates, and Ed25519 signatures with the release key's public half |
| `wwmeter\sessions.py`, `summary.py`, `changelog.py` | Session files, the copied summary, What changed |
| `wwmeter\roster.py`, `hotkeys.py`, `elevation.py`, `selftest.py`, `dmgnum.py` | Names and elements, keys and which of them reach Waveband past a game run as administrator, the self-test, the optional number reader |
| `ui\` | The overlay and dashboard page and its themes; `base.css` holds what every theme shares |
| `data\` | Characters, hand-written names, digit templates, part shares, the boss HP data, the text recognizer's model (`data\ocr`) |
| `assets\`, `tools\installer\` | The logo and icons; the Inno Setup installer |
| `docs\` | This file, the release steps and the README's pictures |

Tests: `.venv\Scripts\python -m unittest discover -s tests`, after
`.venv\Scripts\python -m pip install -r requirements-dev.txt` (OpenCV and RapidOCR, for the tests
and the tools; the meter itself needs neither). `.gitignore` keeps out everything a
running copy writes (`config.json`, logs, `sessions\`, `learned_parts.json`) and test recordings.
