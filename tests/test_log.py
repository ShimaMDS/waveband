import os
import tempfile
import unittest

from wwmeter import logcodec
from wwmeter.logparse import parse_line
from wwmeter.logtail import LogTail, read_file

BOM = bytes([0xEF, 0xBB, 0xBF])
SKILL = (
    "[2026.11.15-08.56.03:712][400][GameThread]Sharphereal: Display: [C#][33679][Info][CombatInfo]"
    "[WCL][486698] [Skill][EntityId:11910:Player:BP_Feixue_C_2147397868] "
    "BaseSkillComponent.BeginSkillAsync [技能Id: 100001][技能名: 前闪][技能目标: null]"
)
PART = (
    "[2026.11.15-08.41.10:005][ 12][GameThread]Sharphereal: Display: [C#][20001][Info][CombatInfo]"
    "[WCL][319000] [Part][EntityId:13190:Monster:BP_ME1BinlangMd00601_C_2147382485] UpdatePartInfo "
    "[TagName: 怪物.common.背部弱点][Activated: True][LifeValue: 154434]"
)
NOISE = (
    "[2026.11.15-08.41.10:006][ 12][TaskGraphThreadHP 3]LogKuroRendering: Warning: "
    "Niagara Parameter Not Assigned:NiagaraSystem /Game/Aki/Render/X"
)


def encoded(*lines: str, bom: bool = False) -> bytes:
    text = "".join(line + "\r\n" for line in lines)
    return logcodec.encode((BOM if bom else b"") + text.encode("utf-8"))


class CodecTest(unittest.TestCase):
    def test_round_trip_every_byte(self):
        data = bytes(range(256))
        self.assertEqual(logcodec.decode(logcodec.encode(data)), data)

    def test_matches_bytes_seen_in_a_real_log(self):
        # first bytes of a real Client.log: BOM, then "[2026.11.15-08"
        real = bytes.fromhex("005450b4979597938bdede8bdedac2959d")
        self.assertEqual(logcodec.decode(real), BOM + b"[2026.11.15-08")

    def test_detects_keys_from_header(self):
        head = encoded(SKILL, bom=True)[:16]
        self.assertEqual(logcodec.detect_table(head), logcodec.DECODE)

    def test_plain_bom_followed_by_scrambled_text(self):
        # seen live: after some rotations the BOM is written as-is but the text is still scrambled
        head = BOM + encoded(SKILL)[:13]
        self.assertEqual(logcodec.detect_table(head), logcodec.DECODE)

    def test_scrambled_text_without_a_bom(self):
        self.assertEqual(logcodec.detect_table(encoded(SKILL)[:16]), logcodec.DECODE)

    def test_other_keys_are_recovered_from_the_header(self):
        table = logcodec.decode_table(0x31, 0x77)
        scramble = bytes((p ^ (0x77 if p & 1 else 0x31)) for p in range(256))
        head = (BOM + SKILL.encode("utf-8")).translate(scramble)[:16]
        self.assertEqual(logcodec.detect_table(head), table)

    def test_short_or_strange_header_falls_back_to_the_known_keys(self):
        self.assertEqual(logcodec.detect_table(b""), logcodec.DECODE)
        self.assertEqual(logcodec.detect_table(bytes(range(8))), logcodec.DECODE)

    def test_plaintext_log_is_left_alone(self):
        self.assertEqual(logcodec.detect_table(BOM + b"[2026.11.15"), logcodec.PLAIN)
        self.assertEqual(logcodec.detect_table(b"[2026.11.15-08.56"), logcodec.PLAIN)


class ParseTest(unittest.TestCase):
    def test_player_skill(self):
        event = parse_line(SKILL)
        self.assertEqual((event.module, event.sub, event.kind), ("CombatInfo", "Skill", "Player"))
        self.assertEqual((event.entity_id, event.actor), (11910, "BP_Feixue"))
        self.assertEqual(event.instance, "2147397868")
        self.assertEqual(event.text, "BaseSkillComponent.BeginSkillAsync")
        self.assertEqual(event.fields["技能名"], "前闪")
        self.assertEqual(event.tick, 486698)

    def test_numeric_field(self):
        event = parse_line(PART)
        self.assertEqual(event.sub, "Part")
        self.assertEqual(event.num("LifeValue"), 154434.0)
        self.assertEqual(event.num("missing", -1.0), -1.0)

    def test_engine_lines_are_ignored(self):
        self.assertIsNone(parse_line(NOISE))
        self.assertIsNone(parse_line(""))


class TailTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "Client.log")

    def tearDown(self):
        self.dir.cleanup()

    def test_follows_appends_and_drops_noise(self):
        with open(self.path, "wb") as fh:
            fh.write(encoded(PART, bom=True))
        tail = LogTail(self.path, from_start=True)
        self.addCleanup(tail.close)
        self.assertEqual(tail.poll(), [PART])
        with open(self.path, "ab") as fh:
            fh.write(encoded(NOISE, SKILL))
        self.assertEqual(tail.poll(), [SKILL])
        self.assertEqual(tail.poll(), [])

    def test_starts_at_the_end_by_default(self):
        with open(self.path, "wb") as fh:
            fh.write(encoded(PART, bom=True))
        tail = LogTail(self.path)
        self.addCleanup(tail.close)
        self.assertEqual(tail.poll(), [])
        with open(self.path, "ab") as fh:
            fh.write(encoded(SKILL))
        self.assertEqual(tail.poll(), [SKILL])

    def test_partial_line_waits_for_its_end(self):
        data = encoded(SKILL)
        with open(self.path, "wb") as fh:
            fh.write(data[:40])
        tail = LogTail(self.path, from_start=True)
        self.addCleanup(tail.close)
        self.assertEqual(tail.poll(), [])
        with open(self.path, "ab") as fh:
            fh.write(data[40:])
        self.assertEqual(tail.poll(), [SKILL])

    def test_game_can_rotate_the_file_while_it_is_being_followed(self):
        with open(self.path, "wb") as fh:
            fh.write(encoded(PART, bom=True))
        tail = LogTail(self.path, from_start=True)
        self.addCleanup(tail.close)
        self.assertEqual(tail.poll(), [PART])
        with open(self.path, "ab") as fh:
            fh.write(encoded(SKILL))
        # the rename must succeed even though the tail holds the file open
        os.rename(self.path, os.path.join(self.dir.name, "Client-backup.log"))
        with open(self.path, "wb") as fh:
            fh.write(encoded(PART, PART, bom=True))
        self.assertEqual(tail.poll(), [SKILL, PART, PART])

    def test_rotation_to_a_file_with_a_plain_bom(self):
        with open(self.path, "wb") as fh:
            fh.write(encoded(PART, bom=True))
        tail = LogTail(self.path, from_start=True)
        self.addCleanup(tail.close)
        self.assertEqual(tail.poll(), [PART])
        os.rename(self.path, os.path.join(self.dir.name, "Client-backup.log"))
        with open(self.path, "wb") as fh:
            fh.write(BOM + encoded(NOISE, SKILL, PART))
        self.assertEqual(tail.poll(), [SKILL, PART])

    def test_missing_file_is_not_an_error(self):
        tail = LogTail(os.path.join(self.dir.name, "nope.log"))
        self.assertEqual(tail.poll(), [])

    def test_read_file(self):
        with open(self.path, "wb") as fh:
            fh.write(encoded(PART, NOISE, SKILL, bom=True))
        self.assertEqual(list(read_file(self.path)), [PART, SKILL])


if __name__ == "__main__":
    unittest.main()
