import pathlib
import sys
import tempfile
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from atklogic import find  # noqa: E402


def pack(bits):
    out = bytearray((len(bits) + 7) // 8)
    for index, bit in enumerate(bits):
        if bit:
            out[index // 8] |= 1 << (index % 8)
    return bytes(out)


class FindTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.dir.name)
        # channel 0: low until 100, high 100..199, low after
        # channel 1: low until 150, high afterwards
        ch0 = [0] * 100 + [1] * 100 + [0] * 100
        ch1 = [0] * 150 + [1] * 150
        for index, bits in enumerate((ch0, ch1)):
            (self.base / f"channel_{index}.bin").write_bytes(pack(bits))
        self.traces = {
            0: find.Trace(self.base / "channel_0.bin", len(ch0)),
            1: find.Trace(self.base / "channel_1.bin", len(ch1)),
        }

    def tearDown(self):
        self.dir.cleanup()

    def test_two_stage_sequence(self):
        hits = find.search(self.traces, [
            {"channel": 0, "state": "rising"},
            {"channel": 0, "state": "falling"},
        ])
        self.assertEqual(len(hits), 1)
        self.assertEqual((hits[0]["start"], hits[0]["end"]), (100, 200))

    def test_window_rejects_late_match(self):
        hits = find.search(self.traces, [
            {"channel": 0, "state": "rising"},
            {"channel": 1, "state": "high"},
        ], within=40)
        self.assertEqual(hits, [])

    def test_constant_channel_never_matches(self):
        self.assertIsNone(self.traces[0].next_match("high", 500))

    def test_level_lookup(self):
        self.assertEqual(self.traces[0].level_at(50), 0)
        self.assertEqual(self.traces[0].level_at(150), 1)
        self.assertEqual(self.traces[0].level_at(250), 0)
