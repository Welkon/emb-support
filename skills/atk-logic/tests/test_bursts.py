import pathlib
import sys
import tempfile
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from atklogic import bursts  # noqa: E402


def pack(bits):
    out = bytearray((len(bits) + 7) // 8)
    for index, bit in enumerate(bits):
        if bit:
            out[index // 8] |= 1 << (index % 8)
    return bytes(out)


class BurstTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.dir.name) / "channel_0.bin"
        # two bursts of 8 cycles each (period 10, 50 % duty), 200 samples apart
        bits = []
        for burst in range(2):
            for _ in range(8):
                bits.extend([1] * 5 + [0] * 5)
            bits.extend([0] * 200)
        self.bits = bits
        self.path.write_bytes(pack(bits))

    def tearDown(self):
        self.dir.cleanup()

    def test_two_bursts(self):
        result = bursts.measure(self.path, len(self.bits), 50, 1_000_000)
        self.assertEqual(result["count"], 2)
        first = result["bursts"][0]
        self.assertEqual(first["edges"], 16)
        self.assertGreater(first["dutyPercent"], 40.0)
        self.assertLess(first["dutyPercent"], 55.0)
        self.assertEqual(first["frequencyHz"], 100_000.0)
        self.assertGreater(result["bursts"][1]["gapMs"], 0)

    def test_ramp_is_reported_not_averaged_away(self):
        # one burst whose duty climbs from 10 % to 90 % (period 100, 9 slices)
        bits = []
        for step, width in enumerate([10, 20, 30, 40, 50, 60, 70, 80, 90]):
            bits.extend([1] * width + [0] * (100 - width))
        path = pathlib.Path(self.dir.name) / "ramp.bin"
        path.write_bytes(pack(bits))
        result = bursts.measure(path, len(bits), 200, 1_000_000)
        self.assertEqual(result["count"], 1)
        burst = result["bursts"][0]
        self.assertEqual(burst["dutyTrend"], "ramp-up")
        self.assertLess(burst["dutyMinPercent"], 20)
        self.assertGreater(burst["dutyMaxPercent"], 80)
        self.assertIsNotNone(burst.get("rampMs"))
        self.assertGreater(burst["rampMs"], 0)

    def test_quiet_capture_has_no_bursts(self):
        self.path.write_bytes(pack([0] * 500))
        result = bursts.measure(self.path, 500, 50, 1_000_000)
        self.assertEqual(result["count"], 0)
