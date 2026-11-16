"""``wwmeter update``: fetching the game's tables and rebuilding data\\enemy_hp.json, without the
network: the repository is a dictionary of made-up files here."""

import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
from unittest import mock

from enemy_fixture import TABLES, enemy_data

from wwmeter import update
from wwmeter.gamedata import EnemyData
from wwmeter.roster import Roster

README = "# dump\n> Game Version: 9.1.0\n> Resource Version: 9.1.3\n"


def _template(entry_id, blueprint, prop, name_key):
    return {
        "Id": entry_id, "BlueprintType": blueprint,
        "ComponentsData": {
            "BaseInfoComponent": {"Category": {"MainType": "Monster"}, "TidName": name_key},
            "AttributeComponent": {"PropertyId": prop},
        },
    }


def repository(english_name="Rider", japanese_name="炎騎", types=2):
    """The files of one branch of the dump, by their path there."""
    templates = [_template(9001, "MonsterA", 100, "Name_A"), _template(9002, "MonsterB", 200, "Name_B")]
    files = {
        "README.md": README,
        "BinData/template/templateconfig.json": templates[:types],
        "BinData/level_entity/levelentityconfig_1.json": [
            {"MapId": 50, "EntityId": 7, "BlueprintType": "MonsterA",
             "ComponentsData": {"AttributeComponent": {"Level": 80}}},
        ],
        "BinData/property/baseproperty.json": [{"Id": 100, "LifeMax": 690}, {"Id": 200, "LifeMax": 4680}],
        "BinData/property/monsterpropertygrowth.json": [
            {"CurveId": 0, "Level": level, "LifeMaxRatio": 10000 * level} for level in range(1, 101)
        ],
        "BinData/prefab/prefabconfig.json": [],
        "BinData/instance_dungeon/instancedungeon.json": [{"Id": 3927, "MapConfigId": 50, "EntityLevel": 0}],
        "Textmaps/en/multi_text/MultiText.json": [
            {"Id": "Name_A", "Content": english_name}, {"Id": "Name_B", "Content": "Heron"},
            {"Id": "RoleInfo_1107_Name", "Content": "Carlotta"},
            {"Id": "RoleInfo_1999_Name", "Content": "Newcomer"},
        ],
        "Textmaps/ja/multi_text/MultiText.json": [
            {"Id": "Name_A", "Content": japanese_name}, {"Id": "Name_B", "Content": "鷺"},
            {"Id": "RoleInfo_1107_Name", "Content": "カルロッタ"},
        ],
        "BinData/role/roleinfo.json": [
            {"Id": 1107, "RoleType": 1, "ElementId": 2},
            {"Id": 1999, "RoleType": 1, "ElementId": 6},
            {"Id": 9100, "RoleType": 2, "ElementId": 1},  # not a playable character
        ],
    }
    return {path: (data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)) for path, data in files.items()}


class _Response(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


def serving(files, asked=None):
    """A stand-in for update._get that answers from ``files``."""

    def get(branch, path):
        if asked is not None:
            asked.append((branch, path))
        if branch != "9.1" or path not in files:
            raise urllib.error.HTTPError(f"{update.RAW}/{branch}/{path}", 404, "Not Found", {}, None)
        return _Response(files[path].encode("utf-8"))

    return get


class Folders:
    """A game folder whose launcher says 9.1.0, a cache and an output file in a temp folder."""

    def __init__(self, version="9.1.0"):
        self.temp = tempfile.TemporaryDirectory()
        root = self.temp.name
        game = os.path.join(root, "Wuthering Waves Game")
        self.log_dir = os.path.join(game, "Client", "Saved", "Logs")
        os.makedirs(self.log_dir)
        if version:
            with open(os.path.join(game, "launcherDownloadConfig.json"), "w", encoding="utf-8") as fh:
                json.dump({"version": version, "other": 1}, fh)
        self.cache = os.path.join(root, "cache")
        self.out = os.path.join(root, "enemy_hp.json")

    def run(self, files, **options):
        options.setdefault("cache", self.cache)
        with mock.patch.object(update, "_get", serving(files)):
            return update.run(self.log_dir, out=self.out, say=lambda _text: None, **options)

    def built(self):
        with open(self.out, encoding="utf-8") as fh:
            return json.load(fh)


class VersionTest(unittest.TestCase):
    def test_the_branch_is_the_major_and_minor_version(self):
        self.assertEqual(update.branch_of("3.8.0"), "3.8")
        self.assertEqual(update.branch_of("10.12"), "10.12")
        self.assertEqual(update.branch_of(""), "")
        self.assertEqual(update.branch_of(None), "")

    def test_tables_are_out_of_date_only_for_another_minor_version(self):
        self.assertTrue(update.out_of_date("3.9.0", "3.8.0"))
        self.assertFalse(update.out_of_date("3.8.2", "3.8.0"))
        self.assertFalse(update.out_of_date(None, "3.8.0"))  # not known: say nothing
        self.assertFalse(update.out_of_date("3.9.0", ""))

    def test_the_installed_version_is_read_from_the_launcher_beside_the_client(self):
        folders = Folders("9.1.0")
        self.addCleanup(folders.temp.cleanup)
        self.assertEqual(update.installed_version(folders.log_dir), "9.1.0")
        missing = Folders(None)
        self.addCleanup(missing.temp.cleanup)
        self.assertIsNone(update.installed_version(missing.log_dir))

    def test_languages_fetched_are_english_the_games_and_the_settings(self):
        self.assertEqual(update.wanted_languages("nowhere", "ja"), ["en", "ja"])
        self.assertEqual(update.wanted_languages("nowhere", "pt-BR", "ko"), ["en", "ko"])
        self.assertEqual(update.wanted_languages("nowhere", "", "all"), list(update.LANGUAGES))
        self.assertEqual(update.wanted_languages("nowhere", "zh-TW"), ["en", "zh-Hant"])


class RunTest(unittest.TestCase):
    def setUp(self):
        self.folders = Folders()
        self.addCleanup(self.folders.temp.cleanup)

    def test_it_builds_the_file_the_meter_reads(self):
        done = self.folders.run(repository(), languages="en,ja")
        self.assertIn("9.1.0", done)
        built = self.folders.built()
        self.assertEqual((built["game_version"], built["resource_version"]), ("9.1.0", "9.1.3"))
        self.assertEqual(built["elements"], {"1107": "fusion", "1999": "havoc"})
        data = EnemyData(self.folders.out, "ja")
        rider = data.find("Level", 7, 0, 3927)
        self.assertEqual(rider.name, "炎騎")
        self.assertEqual(data.hp(rider), 690 * 800000 // 10000)
        self.assertEqual(data.character_name(1107), "カルロッタ")
        self.assertEqual(data.element(1999), "havoc")
        self.assertEqual(data.version, "9.1.0")

    def test_the_downloads_are_deleted_unless_asked_to_keep_them(self):
        self.folders.run(repository(), languages="en")
        self.assertTrue(os.path.isfile(os.path.join(self.folders.cache, "templateconfig.json")))  # a cache named is kept
        kept_aside = os.path.join(self.folders.temp.name, "tmp")
        os.makedirs(kept_aside)
        with mock.patch.object(update.tempfile, "gettempdir", return_value=kept_aside):
            own = os.path.join(kept_aside, "wwmeter-gamedata", "9.1")
            os.makedirs(own)
            with open(os.path.join(own, "notes.txt"), "w") as fh:
                fh.write("not the update's")
            self.folders.run(repository(), cache="", force=True)
            self.assertEqual(os.listdir(own), ["notes.txt"])  # only its own files are deleted
            os.remove(os.path.join(own, "notes.txt"))
            self.folders.run(repository(), cache="", force=True)
            self.assertFalse(os.path.exists(os.path.join(kept_aside, "wwmeter-gamedata")))

    def test_languages_not_fetched_keep_the_names_they_had(self):
        self.folders.run(repository(), languages="en,ja")
        # a patch renames the boss in English; Japanese is not fetched this time
        self.folders.run(
            repository(english_name="Rider II", japanese_name="別名"), languages="en", force=True,
            cache=os.path.join(self.folders.temp.name, "fresh"),
        )
        data = EnemyData(self.folders.out, "ja")
        self.assertEqual(data.find("Level", 7, 0, 3927).name, "炎騎")
        self.assertEqual(data.character_name(1107), "カルロッタ")
        data.set_language("en")
        self.assertEqual(data.find("Level", 7, 0, 3927).name, "Rider II")
        self.assertEqual(list(self.folders.built()["text"]), ["en", "ja"])

    def test_an_up_to_date_file_is_left_alone(self):
        self.folders.run(repository(), languages="en")
        before = os.stat(self.folders.out).st_mtime_ns
        done = self.folders.run(repository(), languages="en")
        self.assertIn("already up to date", done)
        self.assertEqual(os.stat(self.folders.out).st_mtime_ns, before)
        # a language the file does not have yet is a reason to build it again
        self.assertNotIn("already", self.folders.run(repository(), languages="en,ja"))

    def test_a_version_not_published_yet_changes_nothing(self):
        self.folders.run(repository(), languages="en")
        before = self.folders.built()
        later = Folders("9.2.0")
        self.addCleanup(later.temp.cleanup)
        later.out = self.folders.out
        with self.assertRaises(update.Failed) as said:
            later.run(repository())
        self.assertIn("not published yet", str(said.exception))
        self.assertEqual(self.folders.built(), before)

    def test_tables_that_lost_most_enemies_are_not_trusted(self):
        files = repository()
        self.folders.run(files, languages="en")
        before = self.folders.built()
        broken = repository(types=0)
        broken["BinData/template/templateconfig.json"] = json.dumps([])
        with self.assertRaises(update.Failed):
            self.folders.run(broken, force=True, cache=os.path.join(self.folders.temp.name, "fresh"))
        self.assertEqual(self.folders.built(), before)

    def test_no_connection_changes_nothing(self):
        def offline(branch, path):
            raise urllib.error.URLError("no route to host")

        with mock.patch.object(update, "_get", offline), self.assertRaises(update.Failed) as said:
            update.run(self.folders.log_dir, out=self.folders.out, cache=self.folders.cache, say=lambda _t: None)
        self.assertIn("Nothing was changed", str(said.exception))
        self.assertFalse(os.path.exists(self.folders.out))

    def test_a_download_cut_off_leaves_no_file_behind(self):
        files = repository()

        class Cut(_Response):
            def read(self, size=-1):
                raise TimeoutError("timed out")

        def get(branch, path):
            if path == "BinData/property/baseproperty.json":
                return Cut(b"")
            return serving(files)(branch, path)

        with mock.patch.object(update, "_get", get), self.assertRaises(update.Failed):
            update.run(self.folders.log_dir, out=self.folders.out, cache=self.folders.cache, say=lambda _t: None)
        self.assertFalse(any(name.startswith("baseproperty") for name in os.listdir(self.folders.cache)))

    def test_a_cache_with_the_same_stamp_is_used_as_it_is(self):
        self.folders.run(repository(), languages="en", keep=True)
        asked = []
        with mock.patch.object(update, "_get", serving(repository(), asked)):
            update.run(self.folders.log_dir, out=self.folders.out, cache=self.folders.cache,
                       force=True, say=lambda _t: None)
        # the stamp, and what the first run found missing (no bestiary or language numbers, and
        # no second part of the level-entity table: that is how the parts are counted)
        missing = {update.BESTIARY, update.LANGUAGE_IDS, update.LEVEL_ENTITIES.format(n=2)}
        self.assertEqual({path for _, path in asked} - missing, {"README.md"})

    def test_downloads_of_an_older_state_of_the_branch_are_fetched_again(self):
        self.folders.run(repository(), languages="en", keep=True)
        files = repository(english_name="Rider II")
        files["README.md"] = README.replace("9.1.3", "9.1.4")
        self.folders.run(files, languages="en")
        data = EnemyData(self.folders.out, "en")
        self.assertEqual(data.find("Level", 7, 0, 3927).name, "Rider II")
        self.assertEqual(self.folders.built()["resource_version"], "9.1.4")


class ReloadTest(unittest.TestCase):
    def test_reloaded_tables_keep_the_language_and_name_enemies_afresh(self):
        data = enemy_data("ja")
        path = data._path  # noqa: SLF001 - the fixture's file
        version = data.names_version
        changed = json.loads(json.dumps(TABLES))
        changed["game_version"] = "newer"
        self.addCleanup(os.remove, path)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(changed, fh, ensure_ascii=False)
        data.reload()
        self.assertEqual((data.version, data.language), ("newer", "ja"))
        self.assertGreater(data.names_version, version)
        self.assertEqual(data.character_name(1107), "カルロッタ")

    def test_a_character_new_with_a_patch_gets_its_element_from_the_tables(self):
        tables = json.loads(json.dumps(TABLES))
        tables["elements"] = {"1999": "havoc", "1107": "aero"}
        data = enemy_data("en", tables)
        roster = Roster(game_name=data.character_name, game_element=data.element)
        self.assertEqual(roster.role_id_of("1999051"), 1999)
        self.assertEqual(roster.lookup("BP_Unknown", 1999), ("Newcomer", "havoc"))
        # the meter's own list still decides for the characters it has
        self.assertEqual(roster.lookup("BP_Carlotta", 1107)[1], "glacio")


class UpdaterTest(unittest.TestCase):
    def test_it_follows_the_update_and_says_how_it_ended(self):
        ended = threading.Event()
        result = []

        def done(ok, line):
            result.append((ok, line))
            ended.set()

        updater = update.Updater(done)
        script = (
            "import sys, time; open(sys.argv[1], 'w').write('Downloading x: 5 MB'); time.sleep(0.8); "
            "open(sys.argv[1], 'w').write('Boss HP tables are now for game 9.1.0.')"
        )
        with mock.patch.object(update.Updater, "_command", staticmethod(lambda status: [sys.executable, "-c", script, status])):
            self.assertTrue(updater.start())
            self.assertFalse(updater.start())  # one at a time
            self.assertTrue(ended.wait(20))
        self.assertEqual(result, [(True, "Boss HP tables are now for game 9.1.0.")])
        self.assertFalse(updater.running)
        self.assertEqual(updater.line, "")

    def test_a_failed_update_says_why(self):
        ended = threading.Event()
        result = []
        updater = update.Updater(lambda ok, line: (result.append((ok, line)), ended.set()))
        script = "import sys; open(sys.argv[1], 'w').write('Couldn't reach GitHub. Nothing was changed.'); sys.exit(1)"
        script = script.replace("Couldn't", "Could not")
        with mock.patch.object(update.Updater, "_command", staticmethod(lambda status: [sys.executable, "-c", script, status])):
            updater.start()
            self.assertTrue(ended.wait(20))
        self.assertEqual(result, [(False, "Could not reach GitHub. Nothing was changed.")])


if __name__ == "__main__":
    unittest.main()
