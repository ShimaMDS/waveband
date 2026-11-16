# What changed

## 0.3.0 (beta)

- Six new themes, one for each element: Glacio, Fusion, Electro, Aero, Spectro and Havoc. Each
  is the WuWa look in that element's colours, taken from its characters, with its own typeface
  and its own logo in the dashboard (an ice crystal, a flame, a lightning bolt, wind blades, a
  radiant star, a crescent eclipse). WuWa stays the default; pick one from the tray menu's Theme
  entry or Settings, DPS Meter.
- A smaller download: the zip is about 180 MB, down from 215 MB. The boss's name and level are
  now read by the same text recognizer as before, run on its own, without the larger libraries
  that came with it; it reads them the same way, and a little faster.
- Beta updates: under Settings, Game, "Updates to take" can be Stable or Beta. Stable tells you
  about releases (0.3.0, then 0.4.0) only; Beta also about the test versions between them (0.3.1,
  0.3.2, ...) and still moves on to each stable version. Until you pick, a beta of Waveband is on Beta
  and any other version on Stable.
- Clearer names on the settings page: Keys is now Keybinds, Meter is DPS Meter, and Another PC
  is Import / Export.
- "Over time" is more accurate: damage over time the log doesn't report (Frazzle, for one) used
  to end up about 0.8% of the boss's HP short; once the hits stop, it's now counted to within a
  pixel of the HP bar.
- Fixes: in the Classic theme the fight clock no longer sits on the waveform, and on the
  dashboard the big figure no longer counts down through the old fight's number after going
  back from an earlier fight.

## 0.2.0

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

## 0.1.0

- The first version handed to testers.
