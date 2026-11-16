"""Wire the pieces together: readers -> tracker -> server -> overlay."""

from __future__ import annotations

import json
import os
import time
import zlib
from dataclasses import asdict

from . import __version__, changelog, clipboard, elevation, hotkeys, selfupdate, sessions, settings, update
from . import config as config_mod
from .capture import find_game_window
from .config import ROOT, Config
from .gamedata import LEARNED_PARTS_PATH, PartShares, apply_language, client_language, enemy_data
from .summary import fight_summary
from .roster import Roster
from .server import StateServer
from .tracker import Tracker

UI_DIR = os.path.join(ROOT, "ui")


def run(cfg: Config, demo: bool = False, overlay: bool = True) -> int:
    # Each launch is a session with a file of its own, so the list of fights starts empty and
    # never runs from one day into the next. The demo's made-up fights are not kept.
    session_file = None if demo else sessions.new_path(time.time())
    if not demo:
        sessions.adopt_old_list()  # the single list of an earlier version becomes a session
    tables = enemy_data(cfg)  # enemy HP, and the game's names for enemies and characters
    tracker = Tracker(
        Roster(game_name=tables.character_name, game_element=tables.element),
        timeout=cfg.encounter_timeout, enemies=tables,
        history_path=session_file,
        # the demo's made-up fights teach nothing worth keeping
        parts=PartShares(learned_path=None if demo else LEARNED_PARTS_PATH),
    )
    earlier = {"list": [], "read_at": 0.0}  # earlier sessions, re-read now and then

    def earlier_sessions() -> list[dict]:
        if time.time() - earlier["read_at"] > 15.0:
            earlier.update(list=sessions.listing(skip=session_file or ""), read_at=time.time())
        return earlier["list"]

    def open_session(name: str | None) -> None:
        """Put an earlier session on show for reading, or go back to this one."""
        fights = sessions.read(name) if name else []
        tracker.open_session(fights, sessions.label(name) if fights else "")
        if name and not fights:
            say("That session's file could not be read.")

    said = {"text": "", "until": 0.0}  # a line the meter shows for a few seconds
    keys_taken: list[str] = []  # the meter's hotkeys that another program holds

    def say(text: str, seconds: float = 4.0) -> None:
        said.update(text=text, until=time.time() + seconds)

    def copy_summary() -> None:
        """The fight on show, as text on the clipboard."""
        fight = tracker.snapshot(time.time())["encounter"]
        if fight is None:
            say("No fight to copy yet.")
            return
        try:
            clipboard.copy(fight_summary(fight, __version__))
        except OSError:
            say("Couldn't get at the clipboard. Try again.")
        else:
            say("Fight summary copied. Paste it anywhere.")

    def on_keys_taken(names: list[str]) -> None:
        keys_taken[:] = names

    waveband_elevated = elevation.this_process()

    def keys_need_ctrl_or_alt() -> bool:
        """Whether a key held without Ctrl or Alt won't reach Waveband while the game is in
        front: the game runs as administrator and Waveband does not. Taken to be so while the
        game isn't running, as it runs as administrator unless someone changed that."""
        if waveband_elevated:
            return False
        game = find_game_window()
        return game is None or elevation.window(game) is not False

    # The boss HP tables after a game patch: fetched and rebuilt by a program of their own
    # (``wwmeter update``), then read again here without a restart.
    installed = {"version": None, "read_at": float("-inf")}
    finished: list[str] = []  # what an update ended with, for the tray to say once

    def installed_game() -> str | None:
        """The installed game's version, from the launcher's record; looked at once a minute."""
        if time.monotonic() - installed["read_at"] > 60.0:
            installed.update(version=update.installed_version(cfg.log_dir), read_at=time.monotonic())
        return installed["version"]

    def tables_done(ok: bool, line: str) -> None:
        if ok:
            tracker.reload_tables(lambda: apply_language(tables, cfg))
            languages[:] = list(tables.languages)
            installed["read_at"] = float("-inf")
        say(line, 10.0 if ok else 20.0)
        finished.append(line)

    updater = update.Updater(tables_done)

    def update_tables() -> str:
        """Start an update of the boss HP tables. What to tell the user about it."""
        if demo:
            return "The demo has no game to update the tables for."
        if not updater.start():
            return "The boss HP tables are already being updated."
        return ("Looking for newer boss HP tables. If there are, about 260 MB is downloaded; "
                "the meter keeps working meanwhile, and its line says how far along it is.")

    # Waveband's own updates. Quitting is the overlay's to do; it sets this when it starts.
    quit_app = {"do": None}
    told: list[str] = []  # what the update check has to say in a tray message, once

    def quit_for_update() -> None:
        if quit_app["do"] is not None:
            quit_app["do"]()

    app_updates = selfupdate.Updates(
        enabled=lambda: bool(cfg.check_updates) and not demo,
        auto=lambda: bool(cfg.auto_update),
        channel=lambda: selfupdate.effective_channel(cfg.update_channel),
        quit_app=quit_for_update,
        tell=told.append,
    )

    def install_app() -> str:
        """Install the newer version, or say where it is when this copy cannot."""
        release = app_updates.release
        if release is None:
            return "There is no newer version to install."
        if not selfupdate.installed():
            import webbrowser

            webbrowser.open(release.page)
            return f"Opened the page of {release.version}: download it there."
        if not app_updates.install():
            return "Already busy with an update."
        return f"Downloading {release.version}. Waveband closes and starts again when it is installed."

    def check_app() -> str:
        if not selfupdate.REPO:
            return "This build does not look for updates."
        import threading

        threading.Thread(target=app_updates.check, daemon=True).start()
        return "Looking for a newer version."

    def app_said() -> str | None:
        """What the update check has to say in a tray message, once."""
        return told.pop(0) if told else None

    def update_finished() -> str | None:
        """What the last update ended with, once; None when there is nothing new to say."""
        return finished.pop(0) if finished else None

    def tables_state() -> dict:
        game = None if demo else installed_game()
        return {
            "version": tables.version,
            "built": tables.built,
            "game": game or "",
            "stale": update.out_of_date(game, tables.version),
            "running": updater.running,
            "line": updater.line,
        }

    # What changed since the version that last ran here. Said once: in a line on the meter
    # until a fight starts or the notes are opened, and marked on the dashboard for this run.
    had_settings = os.path.isfile(config_mod.CONFIG_PATH)
    versions = changelog.read()
    ran_before = changelog.last_run(cfg.seen_version, had_settings)
    fresh = [v["version"] for v in changelog.news(versions, ran_before, __version__)]
    news = {"line": f"Updated to {__version__}. What changed: see the tray menu."
            if fresh else ""}
    if cfg.seen_version != __version__:
        cfg.seen_version = __version__
        if had_settings:
            # A first start writes no settings file: the version goes into it with the first
            # setting that changes.
            config_mod.save(cfg)

    themes = settings.available_themes()
    languages = list(tables.languages)

    def settings_reply(said_now: str = "", problems: list[str] | None = None) -> dict:
        """The settings for the settings page, with what there is to say about a change."""
        return {
            "reply": "settings",
            "settings": settings.describe(
                cfg, themes, languages, client_language(cfg.log_dir, tables.language_ids),
                keys_need_ctrl_or_alt(),
            ),
            "said": said_now,
            "problems": problems or [],
        }

    def take_up(changed: set[str]) -> None:
        """Save changed settings and make the running meter use them. The overlay window and
        the tray menu look at the settings themselves a few times a second."""
        if not changed:
            return
        config_mod.save(cfg)
        if changed & {"log_dir", "language"}:
            apply_language(tables, cfg)  # the game's language is read from beside the log folder
        if "encounter_timeout" in changed:
            tracker.set_timeout(cfg.encounter_timeout)

    def change_settings(command: dict) -> dict | None:
        """What the settings page can ask for. Each answer is the settings as they now are."""
        name = command.get("cmd")
        if name == "settings":
            return settings_reply()
        if name == "set":
            wanted = command.get("changes")
            before = hotkeys.bindings(cfg.hotkeys)
            changed, problems = settings.apply(cfg, wanted, themes, languages)
            take_up(changed)
            if "hotkeys" in changed:
                # a key some other program holds would do nothing in the game, and silently
                after = hotkeys.bindings(cfg.hotkeys)
                new = [key for action, key in after.items() if key and key != before.get(action)]
                plain = [key for key in new if hotkeys.needs_ctrl_or_alt(key)]
                if plain and keys_need_ctrl_or_alt():
                    several = len(plain) > 1
                    problems.append(
                        f"{' and '.join(plain)} won't reach Waveband while you play: the game runs "
                        "as administrator, and Windows then passes on only keys held with Ctrl or "
                        f"Alt. Hold Alt with {'them' if several else 'it'}, or run Waveband as "
                        "administrator."
                    )
                held = hotkeys.in_use(new)
                if held:
                    several = len(held) > 1
                    problems.append(
                        f"{' and '.join(held)} {'are' if several else 'is'} in use by another "
                        f"program right now, so {'they' if several else 'it'} may do nothing in "
                        "the game. Close that program, or pick another key."
                    )
            if "log_dir" in changed and not os.path.isfile(cfg.log_path):
                problems.append(
                    "There is no Client.log in that folder yet. The game writes one when it starts."
                )
            return settings_reply("Saved." if changed else "", problems)
        if name == "find_log":
            found = config_mod.find_log_dir()
            if not os.path.isfile(os.path.join(found, "Client.log")):
                return settings_reply(problems=[
                    "Couldn't find the game's log in the usual places. Paste the game's folder here."
                ])
            changed = {"log_dir"} if found != cfg.log_dir else set()
            cfg.log_dir = found
            take_up(changed)
            return settings_reply("Found the game's log." if changed else "That is the folder in use.")
        if name == "import":
            try:
                changed, problems = settings.take_line(cfg, command.get("line"), themes, languages)
            except settings.Refused as why:
                return settings_reply(problems=[str(why)])
            take_up(changed)
            said_now = "Settings taken from the line." if changed else "Those are the settings in use."
            return settings_reply(said_now, problems)
        return None

    def on_command(command: dict) -> dict | None:
        """What the page can ask for: a new fight, a look at an earlier one, a summary, and the
        settings."""
        name = command.get("cmd")
        if name in ("settings", "set", "find_log", "import"):
            return change_settings(command)
        if name == "update_tables":
            say(update_tables(), 8.0)
            return None
        if name == "check_app":
            say(check_app(), 6.0)
            return None
        if name == "install_app":
            say(install_app(), 8.0)
            return None
        if name == "changes":
            if command.get("read") is True:
                news["line"] = ""  # the notes are open in front of the user
            return {
                "reply": "changes", "version": __version__, "before": ran_before or "",
                "versions": versions, "new": fresh,
            }
        if name == "reset":
            tracker.reset()
        elif name == "copy":
            copy_summary()
        elif name == "view":
            fight = command.get("id")
            tracker.view(fight if isinstance(fight, int) else None)
        elif name == "step" and command.get("step") in (-1, 1):
            tracker.view_step(command["step"])
        elif name == "session":
            chosen = command.get("file")
            open_session(chosen if isinstance(chosen, str) else None)
        return None

    def snapshot() -> dict:
        state = tracker.snapshot(time.time())
        keys = hotkeys.bindings(cfg.hotkeys)
        live = bool((state.get("encounter") or {}).get("live"))
        if news["line"] and live:
            news["line"] = ""  # a fight has started: the meter is for the fight now
        game_data = tables_state()
        stale = ""
        if game_data["stale"] and not live and not game_data["running"]:
            stale = (f"The game is {update.branch_of(game_data['game'])} and the boss HP tables "
                     f"are for {update.branch_of(game_data['version'])}. Tray menu: Update boss HP tables.")
        state["ui"] = {
            "version": __version__,
            # the line that says the meter was updated; empty on every start but the first
            "news": news["line"],
            "theme": cfg.theme,
            "unit": cfg.display_unit,
            # the line of keys along the top of the meter; empty when switched off
            "keys": hotkeys.hints(cfg.hotkeys) if cfg.show_keys else [],
            "compact": cfg.compact,
            "hide_between_fights": cfg.hide_between_fights,
            # what a character's row shows, and how finely
            "figures": settings.row_figures(cfg.row_figures),
            "decimals": [settings.decimals(cfg.figure_decimals, 2), settings.decimals(cfg.share_decimals, 0)],
            # named on the meter while an earlier fight is on show
            "older_key": keys["older"],
            "newer_key": keys["newer"],
            # an answer just given; else, while the tables are being updated, how far along
            "said": said["text"] if state["now"] < said["until"] else game_data["line"],
            # the boss HP tables are for another game version than the one installed
            "stale": stale,
            # a newer Waveband is out (said between fights only), and the state of updates
            "app_line": app_updates.line if app_updates.status == "available" and not live else "",
            "app": app_updates.state(),
            "tables": game_data,
            "keys_taken": list(keys_taken),
            # the user's own colours for the elements, laid over the theme's
            "colours": cfg.colours if isinstance(cfg.colours, dict) else {},
            # changes whenever a setting does, wherever it was changed: an open settings page
            # asks for the settings again
            "settings": zlib.crc32(json.dumps(asdict(cfg), sort_keys=True).encode("utf-8")),
        }
        state["sessions"] = earlier_sessions()
        return state

    server = StateServer(cfg.port, snapshot, UI_DIR, on_command)
    server.start()
    app_updates.start()

    if demo:
        from .demo import DemoFeed

        feed = DemoFeed(tracker)
    else:
        from .engine import Engine

        feed = Engine(cfg, tracker)
    feed.start()

    dashboard = server.url + "?view=full"
    print(f"meter running. dashboard: {dashboard}", flush=True)
    print(f"settings: {dashboard}#settings", flush=True)
    try:
        if overlay:
            from . import overlay as overlay_mod

            return overlay_mod.run(
                server.url + "?view=overlay", cfg, tracker.reset, dashboard, tracker.view_step,
                copy_summary, on_keys_taken, earlier_sessions, open_session,
                update_tables, update_finished,
                app_actions={"check": check_app, "install": install_app, "said": app_said,
                             "available": lambda: app_updates.release.version
                             if app_updates.status == "available" and app_updates.release else "",
                             "set_quit": lambda do: quit_app.update(do=do)},
            )
        print("no overlay window; press Ctrl+C to quit", flush=True)
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        return 0
    finally:
        app_updates.stop()
        feed.stop()
        server.stop()
