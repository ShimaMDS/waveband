import json
import os
import tempfile
import time
import unittest

from wwmeter import sessions


def fight(number: int, title: str, ended_at: float, duration: float = 60.0) -> dict:
    return {
        "id": number, "title": title, "duration": duration, "damage": 1_000 * number, "dps": 10,
        "unit": "damage", "players": [], "ended_at": ended_at, "live": False,
    }


class SessionFilesTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = holder.name
        self.folder = os.path.join(self.root, "sessions")

    def write(self, name: str, fights: list[dict]) -> None:
        os.makedirs(self.folder, exist_ok=True)
        with open(os.path.join(self.folder, name), "w", encoding="utf-8") as fh:
            json.dump({"v": 1, "fights": fights}, fh)

    def test_a_session_is_named_after_the_moment_the_meter_started(self):
        started = time.mktime((2026, 11, 15, 16, 30, 5, 0, 0, -1))
        path = sessions.new_path(started, self.folder)
        self.assertEqual(os.path.basename(path), "2026-11-15_16-30-05.json")
        self.assertEqual(sessions.label("2026-11-15_16-30-05.json"), "15 Nov 16:30")
        self.assertFalse(os.path.exists(self.folder))  # nothing is made until a fight ends

    def test_sessions_are_listed_newest_first_and_empty_ones_left_out(self):
        self.write("2026-11-14_20-05-00.json", [fight(2, "Crownless", 2.0), fight(1, "Dreamless", 1.0)])
        self.write("2026-11-15_16-30-05.json", [fight(1, "Lady of the Sea", 3.0)])
        self.write("2026-11-15_18-00-00.json", [])
        self.write("notes.json", [fight(1, "not a session", 1.0)])
        found = sessions.listing(folder=self.folder)
        self.assertEqual(
            found,
            [
                {"file": "2026-11-15_16-30-05.json", "label": "15 Nov 16:30", "fights": 1,
                 "last": "Lady of the Sea"},
                {"file": "2026-11-14_20-05-00.json", "label": "14 Nov 20:05", "fights": 2,
                 "last": "Crownless"},
            ],
        )
        running = os.path.join(self.folder, "2026-11-15_16-30-05.json")
        self.assertEqual(len(sessions.listing(skip=running, folder=self.folder)), 1)
        self.assertEqual(sessions.listing(folder=os.path.join(self.root, "nowhere")), [])

    def test_only_a_session_file_by_its_own_name_is_read(self):
        self.write("2026-11-14_20-05-00.json", [fight(1, "Crownless", 1.0), "junk", {"id": 2}])
        self.assertEqual(
            [f["title"] for f in sessions.read("2026-11-14_20-05-00.json", self.folder)], ["Crownless"]
        )
        with open(os.path.join(self.root, "secret.json"), "w", encoding="utf-8") as fh:
            json.dump({"fights": [fight(1, "outside the folder", 1.0)]}, fh)
        for name in ("../secret.json", "..\\secret.json", "secret.json", "", "2026-11-14_20-05-00.json/.."):
            self.assertEqual(sessions.read(name, self.folder), [], name)

    def test_the_single_list_of_an_earlier_version_becomes_a_session(self):
        old = os.path.join(self.root, "history.json")
        first_began = time.mktime((2026, 11, 15, 16, 16, 59, 0, 0, -1))
        with open(old, "w", encoding="utf-8") as fh:
            json.dump({"v": 1, "fights": [
                fight(2, "Second", first_began + 200.0), fight(1, "First", first_began + 60.0),
            ]}, fh)
        name = sessions.adopt_old_list(old, self.folder)
        self.assertEqual(name, "2026-11-15_16-16-59.json")  # dated by when its first fight began
        self.assertFalse(os.path.exists(old))
        self.assertEqual([f["title"] for f in sessions.read(name, self.folder)], ["Second", "First"])
        self.assertEqual(sessions.adopt_old_list(old, self.folder), "")  # nothing left to adopt

    def test_an_old_list_that_cannot_be_read_is_left_where_it_is(self):
        old = os.path.join(self.root, "history.json")
        with open(old, "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        self.assertEqual(sessions.adopt_old_list(old, self.folder), "")
        self.assertTrue(os.path.exists(old))


if __name__ == "__main__":
    unittest.main()
