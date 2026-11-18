import pathlib
import tempfile
import unittest

from atklogic import vcd
from atklogic.common import SkillError

TRACE = """$timescale 1ns $end
$scope module top $end
$var wire 1 ! scl $end
$var wire 1 " sda $end
$upscope $end
$enddefinitions $end
#0
0!
1"
#100
1!
#200
0!
#300
0"
"""


class VcdTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.dir.name) / "t.vcd"
        self.path.write_text(TRACE)

    def tearDown(self):
        self.dir.cleanup()

    def test_parse_reads_timescale_and_events(self):
        trace = vcd.parse(self.path)
        self.assertEqual(trace["scale"], 1e-9)
        events = trace["signals"]["scl"]
        self.assertEqual([level for _, level in events], [0, 1, 0])
        self.assertAlmostEqual(events[1][0], 100e-9, places=15)

    def test_sample_packs_eight_samples_per_byte(self):
        trace = vcd.parse(self.path)
        channels = vcd.sample(trace["signals"], {"scl": "scl"}, 10_000_000)
        bits = "".join(f"{byte:08b}"[::-1] for byte in channels["scl"])
        self.assertEqual(int(channels["scl"].__len__()), (int(300e-9 * 10e6) + 7) // 8)
        self.assertIn("1", bits)

    def test_missing_signal_is_reported(self):
        trace = vcd.parse(self.path)
        with self.assertRaises(SkillError):
            vcd.sample(trace["signals"], {"sda": "nope"}, 1_000_000)
