import pathlib
import random
import sys
import tempfile
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from atklogic import decode  # noqa: E402
from atklogic.common import SkillError  # noqa: E402


def pack(samples) -> bytes:
    payload = bytearray((len(samples) + 7) // 8)
    for index, value in enumerate(samples):
        if value:
            payload[index // 8] |= 1 << (index % 8)
    return bytes(payload)


def square(count, period=10):
    return [1 if (index // (period // 2)) % 2 else 0 for index in range(count)]


class StatsTest(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())

    def write(self, samples, name="channel_0.bin"):
        path = self.dir / name
        path.write_bytes(pack(samples))
        return path

    def test_bit_order_is_lsb_first(self):
        path = self.write([0, 1, 0, 0, 0, 0, 0, 0])
        self.assertEqual(path.read_bytes()[0], 0x02)
        self.assertEqual(decode.slice_levels(path, 8, 0, 2), [0, 1])

    def test_square_wave_counts(self):
        samples = square(400, period=10)
        result = decode.stats(self.write(samples), len(samples))
        self.assertEqual(result["bits"], 400)
        self.assertEqual(result["ones"], 200)
        self.assertAlmostEqual(result["duty"], 0.5)
        self.assertEqual(result["edges"], 79)
        self.assertEqual(result["rises"], 40)
        self.assertEqual(result["falls"], 39)
        self.assertEqual(result["minRunBits"], 5)
        self.assertEqual(result["maxRunBits"], 5)
        self.assertEqual(result["runCount"], 80)
        self.assertEqual(result["firstLevel"], 0)
        self.assertEqual(result["lastLevel"], 1)
        self.assertEqual(result["validBits"], 400)
        self.assertEqual(result["fileBits"], 400)

    def test_constant_line(self):
        result = decode.stats(self.write([1] * 101), 101)
        self.assertEqual(result["edges"], 0)
        self.assertEqual(result["duty"], 1.0)
        self.assertEqual(result["runCount"], 1)

    def test_last_byte_is_trimmed(self):
        result = decode.stats(self.write([1] * 3), 3)
        self.assertEqual(result["bits"], 3)
        self.assertEqual(result["ones"], 3)

    def test_fast_counts_matches_bitwalk(self):
        random.seed(7)
        for length in (1, 7, 8, 9, 63, 64, 65, 1000, 2049):
            samples = [random.randint(0, 1) for _ in range(length)]
            path = self.write(samples)
            fast = decode._fast_counts(path, length)
            accumulator = decode.StatsAccumulator()
            for chunk, bits in decode._read_bits(path, length):
                accumulator.push_bytes(chunk, bits)
            walked = accumulator.finish()
            for key in ("bits", "ones", "zeros", "edges", "rises", "falls",
                        "firstLevel", "lastLevel"):
                self.assertEqual(fast[key], walked[key], f"{key} at length {length}")

    def test_chunk_boundaries_are_not_edges(self):
        random.seed(11)
        samples = [random.randint(0, 1) for _ in range(5000)]
        path = self.write(samples)
        original = decode.FAST_CHUNK_BYTES
        decode.FAST_CHUNK_BYTES = 2  # 16 bits per chunk forces many boundaries
        try:
            fast = decode._fast_counts(path, len(samples))
        finally:
            decode.FAST_CHUNK_BYTES = original
        accumulator = decode.StatsAccumulator()
        for chunk, bits in decode._read_bits(path, len(samples)):
            accumulator.push_bytes(chunk, bits)
        walked = accumulator.finish()
        for key in ("bits", "ones", "edges", "rises", "falls", "firstLevel", "lastLevel"):
            self.assertEqual(fast[key], walked[key], key)

    def test_runs_and_transitions(self):
        samples = [0, 0, 1, 1, 1, 0]
        path = self.write(samples)
        self.assertEqual(list(decode.runs(path, 6)), [(0, 2), (1, 3), (0, 1)])
        self.assertEqual(list(decode.transitions(path, 6)), [(0, 0), (2, 1), (5, 0)])

    def test_glitches_are_counted(self):
        samples = [0] * 50 + [1] + [0] * 50 + [1, 1, 1] + [0] * 47
        result = decode.stats(self.write(samples), len(samples), glitch_bits=2)
        self.assertEqual(result["glitches"], 1)

    def test_large_file_skips_run_details(self):
        path = self.write(square(200, period=4))
        result = decode.stats(path, 200, pulse_limit=100)
        self.assertIn("runDetailsSkipped", result)
        self.assertNotIn("minRunBits", result)
        self.assertEqual(result["edges"], 99)


class CsvTest(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.path = self.dir / "channel_0.bin"
        self.path.write_bytes(pack(square(20, period=4)))

    def test_sample_csv(self):
        out = self.dir / "samples.csv"
        summary = decode.write_csv(out, self.path, 20, 1_000_000)
        self.assertEqual(summary["rows"], 20)
        lines = out.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "bit,time_s,level")
        levels = decode.slice_levels(self.path, 20, 0, 20)
        self.assertEqual(lines[1], f"0,0.000000000,{levels[0]}")
        self.assertEqual(lines[2], f"1,0.000001000,{levels[1]}")

    def test_slice(self):
        out = self.dir / "slice.csv"
        summary = decode.write_csv(out, self.path, 20, 1_000_000, start=4, count=3)
        self.assertEqual(summary["rows"], 3)
        self.assertTrue(out.read_text(encoding="utf-8").splitlines()[1].startswith("4,"))

    def test_transitions_csv(self):
        out = self.dir / "edges.csv"
        summary = decode.write_csv(out, self.path, 20, 1_000_000, transitions_only=True)
        self.assertEqual(summary["rows"], 10)
        self.assertEqual(len(out.read_text(encoding="utf-8").splitlines()), 11)

    def test_limit(self):
        with self.assertRaises(SkillError) as raised:
            decode.write_csv(self.dir / "big.csv", self.path, 20, 1_000_000, limit_bits=5)
        self.assertEqual(raised.exception.code, "too_many_samples")


class VcdTest(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.a = self.dir / "channel_0.bin"
        self.a.write_bytes(pack(square(20, period=4)))
        self.b = self.dir / "channel_2.bin"
        self.b.write_bytes(pack([0, 0, 0, 0, 1, 1, 1, 1] * 3))

    def test_vcd_contains_both_channels(self):
        out = self.dir / "trace.vcd"
        summary = decode.write_vcd(
            out,
            [
                {"id": 0, "file": self.a, "validBits": 20},
                {"id": 2, "file": self.b, "validBits": 24},
            ],
            1_000_000,
        )
        text = out.read_text(encoding="utf-8")
        self.assertIn("$timescale 1ns $end", text)
        self.assertIn("$var wire 1 ! ch0 $end", text)
        self.assertIn("$var wire 1 \" ch2 $end", text)
        self.assertIn("#1000", text)
        self.assertGreater(summary["edges"], 2)

    def test_vcd_limit(self):
        with self.assertRaises(SkillError):
            decode.write_vcd(
                self.dir / "big.vcd",
                [{"id": 0, "file": self.a, "validBits": 20}],
                1_000_000,
                limit_bits=5,
            )


class AnalyseCaptureTest(unittest.TestCase):
    def test_derived_rates(self):
        directory = pathlib.Path(tempfile.mkdtemp())
        samples = square(1_000_000, period=100)  # 10 kHz at 1 MHz
        (directory / "channel_0.bin").write_bytes(pack(samples))
        meta = {
            "frequencyHz": 1_000_000,
            "bin": [{"channel": 0, "file": str(directory / "channel_0.bin"),
                     "validBits": len(samples)}],
        }
        item = decode.analyse_capture(meta, directory)["channels"][0]
        self.assertAlmostEqual(item["cycleRateHz"], 10_000, delta=1)
        self.assertAlmostEqual(item["minPulseUs"], 50, delta=0.1)
        self.assertFalse(item["stuck"])
        self.assertAlmostEqual(item["duty"], 0.5, places=3)

    def test_partial_file_is_read(self):
        directory = pathlib.Path(tempfile.mkdtemp())
        (directory / "channel_0.bin.partial").write_bytes(pack(square(200, period=10)))
        meta = {
            "frequencyHz": 1_000_000,
            "status": "incomplete",
            "bin": [{"channel": 0, "file": "channel_0.bin", "validBits": 200}],
        }
        item = decode.analyse_capture(meta, directory)["channels"][0]
        self.assertTrue(item["file"].endswith("channel_0.bin.partial"))
        self.assertEqual(item["edges"], 39)
        self.assertNotIn("note", item)

    def test_missing_bin_is_reported(self):
        directory = pathlib.Path(tempfile.mkdtemp())
        meta = {"frequencyHz": 1_000_000,
                "bin": [{"channel": 3, "file": "channel_3.bin", "validBits": 10}]}
        item = decode.analyse_capture(meta, directory)["channels"][0]
        self.assertEqual(item["note"], "file missing")


if __name__ == "__main__":
    unittest.main()
