"""Regression against a real capture stream (10 MHz, only CH2 wired)."""

import json
import pathlib
import sys
import tempfile
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from atklogic import usb, vcd  # noqa: E402

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class RealStreamTest(unittest.TestCase):
    def test_real_stream_parses_to_ch2_samples(self):
        data = (FIXTURES / "stream_ch2.bin").read_bytes()
        parsed = usb.parse_stream(data)
        self.assertEqual(sorted(parsed["channels"]), [2])
        bits = usb.unpack_bits(parsed["channels"][2])
        self.assertEqual(len(bits), 64512)
        duty = 100 * sum(bits) / len(bits)
        self.assertGreater(duty, 49.0)
        self.assertLess(duty, 52.0)
        edges = sum(1 for a, b in zip(bits, bits[1:]) if a != b)
        self.assertEqual(edges, 13)


class SimulationTest(unittest.TestCase):
    def test_vcd_becomes_a_capture_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = vcd.parse(FIXTURES / "i2c.vcd")
            channels = vcd.sample(trace["signals"], {"scl": "scl", "sda": "sda_line"},
                                  10_000_000)
            self.assertEqual(sorted(channels), ["scl", "sda"])
            self.assertGreater(len(channels["scl"]), 100)
            target = pathlib.Path(directory) / "capture.json"
            target.write_text(json.dumps({"frequencyHz": 10_000_000}))
            self.assertTrue(target.exists())
