# What changed

The newest version is first. The first time a newer version of the meter starts, it says so on
the meter and marks the part of this list that is new to you ("What changed" in the tray menu).

## 0.3.0 (not released yet)

- Beta updates: under Settings, The game, "Updates to take" can be Stable (the default) or Beta.
  Beta gets test versions of the next release first (0.3.0-beta.1, beta.2, ...) and still moves
  on to each stable version.

## 0.2.0 (2026-11-16)

- The meter has a name, Waveband, and an icon of its own. The program is `Waveband.exe` now and its log file is
  `waveband.log`. To keep your settings and earlier fights, copy `config.json` and the
  `sessions` folder from the old meter's folder into the new one before starting it.
- An installer, and updates. Waveband now comes as an installer as well as a zip. It asks for
  a newer version when it starts, and an installed copy updates itself from the tray menu
  ("Install update"), then starts again. Updates are only installed when they carry Waveband's
  own signature. "Install updates at start without asking" is there too, off unless you turn
  it on. The installer can bring your settings and fights over from a 0.1 folder.
- A settings page: "Settings: keys, colours, log folder" in the tray menu. Change a key by
  pressing it, give each element a colour of your own, pick the language of the names, point
  the meter at the game's log folder, and copy all your settings as one line of text. Nothing
  needs config.json opened any more.
- The dashboard is three pages now, picked at its top: Fights, Settings and What changed. Fights
  lists the sessions down its left side and the fights of the one you pick beside them, with
  the skills used and the signal check underneath.
- Names in the game's language. Enemies and characters are named from the game's own tables, in
  the language the game is set to, and they follow it when you switch. Ten languages.
- Fights are kept. Each start of the meter is a session with a file of its own, and an earlier
  session can be read again from the tray menu or the dashboard.
- Earlier fights on the meter itself: F7 shows the fight before, Shift+F7 the one after.
- A one-line meter (Shift+F8): only the fight clock and the total per second.
- "Hide the meter between fights" in the tray menu.
- "Copy this fight's summary" in the tray menu and on the dashboard: a few lines of text to
  paste into a chat.
- The meter says so when another program holds one of its keys.
- Bosses measured off the HP bar: each drop of the bar is credited to whoever was on field when
  it landed, and what an ultimate deals during its cutscene goes to the character that used it
  even though the bar only shows it once you have switched. A boss's second bar is counted in
  full when the first jumps straight to it, and when the boss dies only a moment after its
  next bar appears (Inferno Rider at the lowest hologram difficulty), a kill
  the game reports late is counted, and a fight stays open through a lull while the game still
  says combat is on.
- After a kill the meter says "Target defeated" where it used to show a rate with a minus sign,
  and per-second figures are written short (15.38k).
- The dashboard and the live feed are answered only to the meter's own pages, now that they
  carry the settings.
- Choose what each character's row shows, and in what order, in the settings page: damage per
  second, total damage, share, and two new figures, time on field and damage per second on
  field. Also how many decimals a figure is written with.
- A few more bosses show damage where they showed percent of HP: where the game's data gives
  no HP for a boss, the meter works it out from one of the boss's breakable parts when it knows
  what share of the HP that part is (Inferno Rider, Impermanence Heron and Nameless Explorer to
  begin with; it learns others as you fight them). The dashboard says when a fight's HP was
  worked out this way.
- Damage over time the game's log leaves out (Spectro Frazzle, for one) is counted from the HP
  bar on small bosses too, in the "Over time" row. A stretch of ticks worth more than 3% of
  the bar used to make the meter stop reading the bar for the rest of the fight. At a kill,
  what the log never reported no longer goes to whoever landed the last hit.
- After a game patch, "Update boss HP tables" in the tray menu (or under Settings, The game)
  fetches the game's data for the new version and rebuilds the meter's boss HP and names,
  without a new download of the meter: about 260 MB, deleted again afterwards. The meter says
  when the game is newer than its tables. A character new with a patch gets its element colour
  from the same data.
- A smaller download: the zip is about 215 MB, down from 277 MB, and 527 MB unpacked instead of
  670 MB. The installer is 148 MB.
- This list, and a line on the meter the first time a newer version starts.

## 0.1.0 (2026-11-15)

- The first version handed to testers.
