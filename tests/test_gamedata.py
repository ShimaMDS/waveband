import copy
import os
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace

from enemy_fixture import TABLES, enemy_data

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import level_check  # noqa: E402

from wwmeter.gamedata import (
    ENEMY_HP_PATH,
    PART_SHARES_PATH,
    ClientLanguage,
    EnemyData,
    PartShares,
    Spawns,
    apply_language,
    client_language,
    game_language,
    pick_language,
)
from wwmeter.logparse import parse_line

_HEAD = "[2026.11.15-09.23.40:100][429][GameThread]Sharphereal: Display: [C#][43718][Info]"


def join_line(instance: int) -> str:
    return f"{_HEAD}[World][LFJW][655727] [CreatureController.JoinSceneNotify] Begin [InstanceId: {instance}]"


def spawn_line(creature: int, config_type: str, pb_data: int, prefab: int = 0, kind: str = "Monster") -> str:
    return (
        f"{_HEAD}[Entity][LFJW][656259] [实体生命周期:创建实体] 实体详细数据。 [CreatureDataId: {creature}]"
        f"[EntityId: 107872257][ConfigType: {config_type}][EntityType: {kind}][PbDataId: {pb_data}]"
        f"[PrefabId: {prefab}][ModelId: 390008][ModelBlueprintPath: ][Visible: True][PlayerId: 1]"
        "[OwnerId: 13972][Location: X=7706.9 Y=-32 Z=-119.9][Rotation: P=0 Y=-180 R=0][Flag: Create, InitData]"
    )


class EnemyDataTest(unittest.TestCase):
    def setUp(self):
        self.data = enemy_data()

    def test_hp_is_the_base_row_times_the_level_curve_rounded_down(self):
        # Crownless, Tactical Hologram difficulty 5: the game logged 1,024,088
        enemy = self.data.find("Level", 7, 0, 3927)
        self.assertEqual((enemy.life_max, enemy.level), (6549, 80))
        self.assertEqual(self.data.hp(enemy), 1_024_088)

    def test_a_prefab_enemy_takes_its_level_from_the_instance(self):
        # Crownless, Tower of Adversity: the game logged 5,510,473
        enemy = self.data.find("Prefab", 1, 400, 20019)
        self.assertEqual(enemy.level, 100)
        self.assertEqual(self.data.hp(enemy), 5_510_473)

    def test_the_same_entity_id_on_another_map_is_another_enemy(self):
        enemy = self.data.find("Level", 7, 0, 3925)
        self.assertEqual((enemy.life_max, enemy.level), (9892, 90))

    def test_without_the_map_an_id_placed_differently_on_two_maps_is_unknown(self):
        self.assertIsNone(self.data.find("Level", 7, 0, None))

    def test_without_the_map_an_id_that_means_one_thing_everywhere_is_found(self):
        enemy = self.data.find("Level", 8, 0, None)
        self.assertEqual((enemy.blueprint, enemy.life_max, enemy.level), ("MonsterA", 690, None))

    def test_a_level_can_be_supplied_when_the_placement_fixes_none(self):
        enemy = self.data.find("Template", 9001, 0, 8)
        self.assertIsNone(self.data.hp(enemy))
        self.assertEqual(self.data.hp(enemy, 90), 690 * 2626059 // 10000)  # 181,198: the wiki's figure
        self.assertIsNone(self.data.hp(enemy, 121))

    def test_an_extra_rate_makes_the_hp_unknown(self):
        enemy = self.data.find("Prefab", 2, 401, 20019)
        self.assertFalse(enemy.exact)
        self.assertIsNone(self.data.hp(enemy))

    def test_a_placement_can_clear_the_extra_rate_and_keeps_the_types_curve(self):
        enemy = self.data.find("Prefab", 3, 402, 20019)
        self.assertTrue(enemy.exact)
        self.assertEqual(self.data.hp(enemy), 4680 * 20000 // 10000)

    def test_unknown_placements_and_a_missing_file_answer_none(self):
        self.assertIsNone(self.data.find("Prefab", 9, 999, 20019))
        self.assertIsNone(self.data.find("Level", 9, 0, 3927))
        self.assertIsNone(self.data.find("Template", 1, 0, None))
        empty = EnemyData("does-not-exist.json")
        self.assertFalse(empty)
        self.assertIsNone(empty.find("Prefab", 1, 400, 20019))
        self.assertIsNone(empty.hp(None))


class EnemyNamesTest(unittest.TestCase):
    def setUp(self):
        self.data = enemy_data()

    def test_a_boss_is_named_by_both_parts_of_the_title_on_its_bar(self):
        self.assertEqual(self.data.find("Prefab", 1, 400, 20019).name, "Crownless: Newborn Desires")
        self.assertEqual(self.data.find("Template", 9001, 0, 8).name, "Crownless: Newborn Desires")

    def test_a_placement_with_a_name_of_its_own_uses_it(self):
        # and its second part, set to a text that is empty, replaces the type's
        self.assertEqual(self.data.find("Prefab", 4, 403, 20019).name, "Cadanto")

    def test_a_second_part_that_repeats_the_name_is_the_whole_title(self):
        self.assertEqual(self.data.find("Template", 9002, 0, 8).name, "The False Sovereign: Dark Serpent")

    def test_an_enemy_the_game_never_named_has_no_name(self):
        self.assertEqual(self.data.find("Prefab", 2, 401, 20019).name, "")

    def test_the_level_the_bar_shows_is_kept_apart_from_the_level_hp_uses(self):
        enemy = self.data.find("Level", 7, 0, 3927)
        self.assertEqual((enemy.level, enemy.shown_level), (80, 90))
        self.assertIsNone(self.data.find("Level", 7, 0, 3925).shown_level)
        # another language writes the digits its own way: the number is taken from the English
        self.assertEqual(enemy_data("ja").find("Level", 7, 0, 3927).shown_level, 90)

    def test_names_are_given_in_the_language_asked_for(self):
        data = enemy_data("JA")
        self.assertEqual(data.language, "ja")
        self.assertEqual(data.find("Prefab", 1, 400, 20019).name, "無冠者・芽生える欲望")
        # a text that language lacks is shown in English
        self.assertEqual(data.find("Prefab", 4, 403, 20019).name, "Cadanto")

    def test_a_language_the_tables_lack_falls_back_to_english(self):
        for wanted in ("ko", "", "nonsense"):
            self.assertEqual(enemy_data(wanted).language, "en")
        self.assertEqual(pick_language(["en", "zh-Hans", "zh-Hant", "pt"], "zh_TW"), "zh-Hant")
        self.assertEqual(pick_language(["en", "zh-Hans", "zh-Hant", "pt"], "zh-CN"), "zh-Hans")
        self.assertEqual(pick_language(["en", "zh-Hans", "zh-Hant", "pt"], "pt-BR"), "pt")
        self.assertEqual(pick_language([], "en"), "")

    def test_an_enemy_with_no_hp_row_still_has_its_name(self):
        enemy = self.data.find("Prefab", 5, 404, 20019)
        self.assertEqual(enemy.name, "Crownless: Newborn Desires")
        self.assertIsNone(self.data.hp(enemy))

    def test_a_file_from_before_names_were_kept_gives_none(self):
        old = {key: value for key, value in TABLES.items() if key not in ("text", "text_keys")}
        old["blueprints"] = [[100], [200, 3001, 77], [100]]
        data = enemy_data(tables=old)
        enemy = data.find("Prefab", 1, 400, 20019)
        self.assertEqual((data.language, enemy.name, enemy.shown_level), ("", "", None))
        self.assertEqual(data.hp(enemy), 5_510_473)


class CharacterNamesTest(unittest.TestCase):
    def test_a_character_is_named_in_the_language_asked_for(self):
        self.assertEqual(enemy_data("en").character_name(1107), "Carlotta")
        self.assertEqual(enemy_data("ja").character_name(1107), "カルロッタ")

    def test_a_name_the_language_lacks_is_given_in_english(self):
        self.assertEqual(enemy_data("ja").character_name(1408), "Rover: Aero")

    def test_a_character_the_tables_do_not_know_has_no_name(self):
        data = enemy_data("ja")
        self.assertEqual(data.character_name(1234), "")
        self.assertEqual(data.character_name(None), "")

    def test_a_change_of_language_changes_the_name(self):
        data = enemy_data("en")
        data.set_language("ja")
        self.assertEqual(data.character_name(1107), "カルロッタ")

    def test_tables_built_before_character_names_give_none(self):
        tables = {key: value for key, value in TABLES.items() if key != "characters"}
        self.assertEqual(enemy_data("ja", tables).character_name(1107), "")


class ClientLanguageTest(unittest.TestCase):
    def settings(self, folder: str, content: bytes) -> str:
        logs = os.path.join(folder, "Saved", "Logs")
        config = os.path.join(folder, "Saved", "Config", "WindowsNoEditor")
        os.makedirs(logs)
        os.makedirs(config)
        with open(os.path.join(config, "GameUserSettings.ini"), "wb") as fh:
            fh.write(content)
        return logs

    def store(self, logs: str, value) -> None:
        """The game's own settings store with a text language in it (None: with none)."""
        folder = os.path.join(os.path.dirname(logs), "LocalStorage")
        os.makedirs(folder, exist_ok=True)
        db = sqlite3.connect(os.path.join(folder, "LocalStorage.db"))
        db.execute("create table if not exists LocalStorage (key text primary key, value text)")
        db.execute("delete from LocalStorage")
        db.execute("insert into LocalStorage values ('VoiceLanguage', '2')")
        if value is not None:
            db.execute("insert into LocalStorage values ('TextLanguage', ?)", (value,))
        db.commit()
        db.close()

    def test_the_language_the_game_saved_last_wins_over_its_settings_file(self):
        # the settings file is only brought up to date when the game closes
        with tempfile.TemporaryDirectory() as folder:
            logs = self.settings(folder, b"Culture=en\r\n")
            self.store(logs, "3")
            self.assertEqual(client_language(logs), "ko")
            self.store(logs, 5)
            self.assertEqual(client_language(logs), "zh-Hant")
            self.assertEqual(client_language(logs, {5: "xx"}), "xx")  # the numbers of another version

    def test_a_store_that_does_not_say_leaves_it_to_the_settings_file(self):
        with tempfile.TemporaryDirectory() as folder:
            logs = self.settings(folder, b"Culture=ja\r\n")
            for value in (None, "99", "korean"):
                self.store(logs, value)
                self.assertEqual(client_language(logs), "ja")
            with open(os.path.join(os.path.dirname(logs), "LocalStorage", "LocalStorage.db"), "wb") as fh:
                fh.write(b"not a database")
            self.assertEqual(client_language(logs), "ja")

    def test_a_switch_of_the_games_language_is_taken_up_while_running(self):
        with tempfile.TemporaryDirectory() as folder:
            logs = self.settings(folder, b"Culture=en\r\n")
            data = enemy_data()
            data.follow(ClientLanguage(logs, every=0.0))
            spawns = Spawns(data)
            spawns.on_event(parse_line(join_line(20019)))
            spawns.on_event(parse_line(spawn_line(13974, "Prefab", 1, 400)))
            self.assertEqual(spawns.enemy(13974).name, "Crownless: Newborn Desires")
            self.assertFalse(spawns.refresh())
            self.store(logs, "2")
            self.assertTrue(spawns.refresh())
            self.assertEqual(data.language, "ja")
            self.assertEqual(spawns.enemy(13974).name, "無冠者・芽生える欲望")
            self.assertFalse(spawns.refresh())

    def test_a_language_chosen_in_the_settings_is_taken_up_while_running(self):
        with tempfile.TemporaryDirectory() as folder:
            logs = self.settings(folder, b"Culture=ja\r\n")
            cfg = SimpleNamespace(language="", log_dir=logs)
            data = enemy_data()
            apply_language(data, cfg)
            spawns = Spawns(data)
            spawns.on_event(parse_line(join_line(20019)))
            spawns.on_event(parse_line(spawn_line(13974, "Prefab", 1, 400)))
            self.assertEqual(spawns.enemy(13974).name, "無冠者・芽生える欲望")
            cfg.language = "en"  # fixed, whatever the game says
            apply_language(data, cfg)
            self.assertTrue(spawns.refresh())
            self.assertEqual(spawns.enemy(13974).name, "Crownless: Newborn Desires")
            self.assertFalse(spawns.refresh())
            cfg.language = ""  # and back to the game's
            apply_language(data, cfg)
            self.assertTrue(spawns.refresh())
            self.assertEqual(spawns.enemy(13974).name, "無冠者・芽生える欲望")

    def test_the_files_are_not_looked_at_more_often_than_asked(self):
        with tempfile.TemporaryDirectory() as folder:
            logs = self.settings(folder, b"Culture=en\r\n")
            client = ClientLanguage(logs, every=3600.0)
            self.assertEqual(client.current(), "en")
            self.store(logs, "2")
            self.assertEqual(client.current(), "en")

    def test_a_language_fixed_in_the_settings_does_not_follow_the_game(self):
        data = enemy_data("ja")
        self.assertFalse(data.refresh())
        self.assertEqual(data.language, "ja")

    def test_the_language_is_read_from_the_settings_file_beside_the_logs(self):
        with tempfile.TemporaryDirectory() as folder:
            logs = self.settings(folder, b"[Internationalization]\r\nbUseVSync=False\r\nCulture=zh-Hans\r\n")
            self.assertEqual(client_language(logs), "zh-Hans")

    def test_a_settings_file_saved_as_utf16_is_read_too(self):
        with tempfile.TemporaryDirectory() as folder:
            logs = self.settings(folder, "[Internationalization]\r\nCulture=ja\r\n".encode("utf-16"))
            self.assertEqual(client_language(logs), "ja")

    def test_no_file_or_no_setting_means_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(client_language(os.path.join(folder, "Saved", "Logs")), "")
            logs = self.settings(folder, b"[ScalabilityGroups]\r\nsg.ShadowQuality=3\r\nCulture=\r\n")
            self.assertEqual(client_language(logs), "")

    def test_the_language_named_in_the_settings_wins_over_the_clients(self):
        class Settings:
            language, log_dir = "en", ""

        with tempfile.TemporaryDirectory() as folder:
            Settings.log_dir = self.settings(folder, b"Culture=ja\r\n")
            self.assertEqual(game_language(Settings), "en")
            Settings.language = ""
            self.assertEqual(game_language(Settings), "ja")


class SpawnsTest(unittest.TestCase):
    def setUp(self):
        self.spawns = Spawns(enemy_data())

    def feed(self, *lines):
        for line in lines:
            self.spawns.on_event(parse_line(line))

    def test_a_spawn_line_names_the_enemy_by_the_id_combat_lines_use(self):
        self.feed(join_line(20019), spawn_line(13974, "Prefab", 1, 400))
        self.assertEqual(self.spawns.data.hp(self.spawns.enemy(13974)), 5_510_473)
        self.assertIsNone(self.spawns.enemy(13975))

    def test_a_level_enemy_is_looked_up_on_the_map_it_spawned_in(self):
        self.feed(join_line(3927), spawn_line(5, "Level", 7), join_line(3925), spawn_line(6, "Level", 7))
        self.assertEqual(self.spawns.enemy(5).level, 80)
        self.assertEqual(self.spawns.enemy(6).level, 90)

    def test_a_reused_id_means_the_newest_spawn(self):
        self.feed(join_line(3927), spawn_line(5, "Level", 7))
        self.assertEqual(self.spawns.enemy(5).level, 80)
        self.feed(join_line(20019), spawn_line(5, "Prefab", 1, 400))
        self.assertEqual(self.spawns.enemy(5).level, 100)

    def test_only_monsters_are_kept(self):
        self.feed(join_line(20019), spawn_line(13974, "Prefab", 1, 400, kind="SceneItem"))
        self.assertIsNone(self.spawns.enemy(13974))


@unittest.skipUnless(os.path.isfile(ENEMY_HP_PATH), "data/enemy_hp.json has not been built")
class LevelCheckTest(unittest.TestCase):
    """tools/level_check.py: the placements whose level wants a second look."""

    def test_every_placement_is_listed_with_what_its_bar_shows(self):
        placed = {(map_id, entity): (enemy, fixed) for map_id, entity, enemy, fixed in enemy_data().placements()}
        self.assertEqual(sorted(placed), [("50", 7), ("51", 7), ("52", 8), ("53", 8)])
        enemy, fixed = placed["50", 7]
        self.assertEqual((enemy.level, enemy.shown_level, enemy.shown_text, fixed), (80, 90, "90", False))
        self.assertEqual((placed["51", 7][0].shown_level, placed["51", 7][0].shown_text), (None, ""))
        self.assertIsNone(placed["52", 8][0].level)

    def test_a_bar_that_shows_another_level_than_hp_uses_is_named(self):
        differs, unreadable, unfixed = level_check.check(enemy_data())
        self.assertEqual(differs, [(50, 7, "Crownless: Newborn Desires", 90, 80, 1_024_088)])
        self.assertEqual((unreadable, unfixed), ([], []))

    def test_a_hidden_level_and_a_difficulty_without_one_are_named(self):
        tables = copy.deepcopy(TABLES)
        tables["text_keys"].append("Level_hidden")
        for words in tables["text"].values():
            words.append("?")
        tables["level"]["52"]["8"] = [0, 101, 70, None, None, None, None, 8]  # its bar shows "?"
        # a boss with a row of difficulties, the last of which fixes no level
        tables["level"]["60"] = {"1": [0, 101, 60], "2": [0, 101, 70], "3": [0, 101, 80], "4": [0, 101]}
        # ordinary enemies, most of them without a level, are not that
        tables["level"]["61"] = {"1": [0, 101, 60], "2": [0, 101, 70], "3": [0, 101, 80], "4": [0], "5": [0],
                                 "6": [0], "7": [0]}
        # and where an instance fixes the level of what is in its map, nothing is missing
        tables["level"]["62"] = dict(tables["level"]["60"])
        tables["instances"]["777"] = [62, 100]
        differs, unreadable, unfixed = level_check.check(enemy_data(tables=tables))
        self.assertEqual(unreadable, [(52, 8, "Crownless: Newborn Desires", "?")])
        self.assertEqual(unfixed, [(60, 4, "Crownless: Newborn Desires", [60, 70, 80])])
        self.assertEqual(len(differs), 1)


class BuiltTablesTest(unittest.TestCase):
    """The file built from the game's tables. These placements are for game version 3.8; if a
    patch moves them, check with tools/check_enemy_hp.py and update the IDs here."""

    @classmethod
    def setUpClass(cls):
        cls.data = EnemyData()

    def test_it_reproduces_the_hp_the_game_logged_for_crownless(self):
        hologram = self.data.find("Level", 244750004, 0, 3927)
        tower = self.data.find("Prefab", 1850002, 405850005, 20019)
        self.assertEqual(self.data.hp(hologram), 1_024_088)
        self.assertEqual(self.data.hp(tower), 5_510_473)

    def test_it_names_playable_characters_in_each_language(self):
        data = EnemyData(language="ko")
        self.assertEqual(data.character_name(1107), "카를로타")
        data.set_language("ja")
        self.assertEqual(data.character_name(1107), "カルロッタ")
        data.set_language("en")
        self.assertEqual(data.character_name(1107), "Carlotta")
        # every character the meter's own list has is named by the game in every language kept
        from wwmeter.roster import Roster

        for language in data.languages:
            data.set_language(language)
            for role_id in Roster()._by_id:  # noqa: SLF001
                self.assertTrue(data.character_name(role_id), (language, role_id))

    def test_it_names_enemies_the_way_the_game_does(self):
        hologram = self.data.find("Level", 244750004, 0, 3927)
        self.assertEqual(hologram.name, "Crownless: Newborn Desires")
        # the hologram's bar shows the difficulty's level, not the one its HP is worked out from
        self.assertEqual((hologram.level, hologram.shown_level), (80, 90))
        self.assertEqual(self.data.find("Level", 244750015, 0, 3927).name, "Inferno Rider: Blazing Guardian")
        self.assertEqual(self.data.find("Prefab", 1750001, 401750028, 20019).name, "Chasm Guardian")
        # its own name is empty in the tables: this one comes from the bestiary
        self.assertEqual(self.data.find("Prefab", 1700002, 401700024, 20016).name, "Fractsidus Milliner")
        japanese = EnemyData(language="ja")
        if japanese.language == "ja":  # the file can be built with fewer languages
            self.assertEqual(japanese.find("Level", 244750015, 0, 3927).name, "燎原の炎騎・焼身止炎")

    def test_only_crownless_shows_a_level_its_hp_does_not_use(self):
        # 3.8: the hologram shows 60 to 100 over HP worked out at 55 to 90. A new name here
        # after a rebuild is a boss to fight once and compare (tools/level_check.py lists them)
        differs, _, unfixed = level_check.check(self.data)
        self.assertEqual({name for _, _, name, *_ in differs}, {"Crownless: Newborn Desires"})
        current = {shown: (level, hp) for map_id, _, _, shown, level, hp in differs if map_id == 3927}
        self.assertEqual(current[90], (80, 1_024_088))
        self.assertEqual(current[100], (90, 1_719_806))
        # difficulty VI of these three fixes no level: the meter has only the one on the screen
        self.assertEqual({name for map_id, _, name, _ in unfixed if map_id in (3924, 3925)},
                         {"Sigillum: Homebound Starfarer", "Denia: Illusory Descent",
                          "Myriad Snare: Rustfire Chassis"})

    def test_part_pools_of_bosses_that_log_no_hp_are_round_shares_of_it(self):
        # Inferno Rider's two weak points logged 198,060 and 330,100: 15% and 25% of its HP
        rider = self.data.hp(self.data.find("Level", 244750015, 0, 3927))
        self.assertAlmostEqual(198_060 / rider, 0.15, places=5)
        self.assertAlmostEqual(330_100 / rider, 0.25, places=5)


RIDER = "BP_ML1QiShiMd00001"
WEAK, BACK = "怪物.common.弱点", "怪物.common.背部弱点"


class PartSharesTest(unittest.TestCase):
    """The figures are the hologram Inferno Rider's as the game logged them: two parts with
    15% and 25% of its HP at every level."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.kept = os.path.join(self.folder.name, "learned_parts.json")

    def test_a_share_is_learned_where_the_hp_is_known_and_gives_the_hp_where_it_is_not(self):
        shares = PartShares(path=None)
        self.assertIsNone(shares.full_hp(RIDER, {WEAK: 142_713.16}))
        self.assertTrue(shares.learn(RIDER, WEAK, 15_891.45, 105_943))  # level 60
        self.assertEqual(shares.share(RIDER, WEAK), 0.15)
        self.assertEqual(shares.full_hp(RIDER, {WEAK: 142_713.16}), 951_421)  # level 90's HP

    def test_the_same_share_seen_again_changes_nothing(self):
        shares = PartShares(path=None)
        shares.learn(RIDER, BACK, 26_485.75, 105_943)
        self.assertFalse(shares.learn(RIDER, BACK, 330_099.75, 1_320_399))
        self.assertEqual(shares.share(RIDER, BACK), 0.25)

    def test_a_pool_that_is_the_whole_hp_is_not_a_part(self):
        shares = PartShares(path=None)
        self.assertFalse(shares.learn("BP_MB1Wuguanzhe00601", WEAK, 1_024_088.0, 1_024_088))
        self.assertIsNone(shares.share("BP_MB1Wuguanzhe00601", WEAK))

    def test_a_share_that_is_not_round_is_not_learned(self):
        # a part first seen after it had been hit
        shares = PartShares(path=None)
        self.assertFalse(shares.learn(RIDER, WEAK, 14_402.0, 105_943))
        self.assertIsNone(shares.share(RIDER, WEAK))

    def test_a_part_seen_with_two_shares_is_never_used(self):
        shares = PartShares(path=None)
        shares.learn(RIDER, WEAK, 15_891.45, 105_943)
        self.assertTrue(shares.learn(RIDER, WEAK, 21_188.6, 105_943))  # 20% this time
        self.assertIsNone(shares.share(RIDER, WEAK))
        self.assertIsNone(shares.full_hp(RIDER, {WEAK: 142_713.16}))
        self.assertFalse(shares.learn(RIDER, WEAK, 15_891.45, 105_943))  # and it stays so
        self.assertIsNone(shares.share(RIDER, WEAK))

    def test_with_several_parts_the_highest_answer_is_the_hp(self):
        shares = PartShares(path=None)
        shares.learn(RIDER, WEAK, 15_891.45, 105_943)
        shares.learn(RIDER, BACK, 26_485.75, 105_943)
        # the weak point was first seen after a hit, the back at its full size
        self.assertEqual(shares.full_hp(RIDER, {WEAK: 100_000.0, BACK: 237_855.25}), 951_421)

    def test_what_is_learned_is_kept_and_read_back(self):
        PartShares(path=None, learned_path=self.kept).learn(RIDER, WEAK, 15_891.45, 105_943)
        again = PartShares(path=None, learned_path=self.kept)
        self.assertEqual(again.share(RIDER, WEAK), 0.15)

    def test_what_this_pc_learned_wins_over_what_came_with_the_meter(self):
        shipped = os.path.join(self.folder.name, "part_shares.json")
        with open(shipped, "w", encoding="utf-8") as fh:
            fh.write('{"shares": {"%s": {"%s": 0.15, "%s": 0.25}}}' % (RIDER, WEAK, BACK))
        first = PartShares(shipped, self.kept)
        self.assertEqual(first.share(RIDER, WEAK), 0.15)
        first.learn(RIDER, WEAK, 21_188.6, 105_943)  # contradicts the shipped share
        again = PartShares(shipped, self.kept)
        self.assertIsNone(again.share(RIDER, WEAK))
        self.assertEqual(again.share(RIDER, BACK), 0.25)

    def test_a_file_that_is_not_a_table_of_shares_is_read_as_empty(self):
        for text in ("", "[1, 2]", '{"shares": 3}', '{"shares": {"a": {"b": "x", "c": 1.5, "d": true}}}'):
            with open(self.kept, "w", encoding="utf-8") as fh:
                fh.write(text)
            shares = PartShares(path=None, learned_path=self.kept)
            self.assertIsNone(shares.full_hp("a", {"b": 10.0, "c": 10.0, "d": 10.0}), text)

    def test_the_shipped_shares_are_the_ones_measured(self):
        shares = PartShares(PART_SHARES_PATH)
        self.assertEqual((shares.share(RIDER, WEAK), shares.share(RIDER, BACK)), (0.15, 0.25))
        # the open-world Rider of 2026-11-15, whose level its placement does not fix: level 85
        self.assertEqual(shares.full_hp(RIDER, {WEAK: 55_706.4, BACK: 92_844.0}), 371_376)
        self.assertEqual(shares.share("BP_ML1WuChangluMd00601", "怪物.ML1WuChangluMd00601.翅膀"), 0.02)
        self.assertEqual(shares.share("BP_ML1WuMingTanSuoZheMd00401", "怪物.c230fb21.b77281b1"), 0.17)


if __name__ == "__main__":
    unittest.main()
