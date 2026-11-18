import pathlib
import sys
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from atklogic.common import (  # noqa: E402
    SkillError,
    fmt_hz,
    fmt_ms,
    parse_channel_spec,
    parse_channels,
    parse_duration_ms,
    parse_frequency,
    parse_percent,
    parse_trigger,
    parse_volts,
)


class FrequencyTest(unittest.TestCase):
    def test_suffixes(self):
        self.assertEqual(parse_frequency("1m"), 1_000_000)
        self.assertEqual(parse_frequency("2.5MHz"), 2_500_000)
        self.assertEqual(parse_frequency("100k"), 100_000)
        self.assertEqual(parse_frequency("1G"), 1_000_000_000)
        self.assertEqual(parse_frequency("250000000"), 250_000_000)
        self.assertEqual(parse_frequency(20_000_000), 20_000_000)

    def test_rejects_nonsense(self):
        for value in ("", "fast", "1x"):
            with self.assertRaises(SkillError) as raised:
                parse_frequency(value)
            self.assertEqual(raised.exception.code, "invalid_arguments")


class DurationTest(unittest.TestCase):
    def test_units(self):
        self.assertEqual(parse_duration_ms("10ms"), 10)
        self.assertEqual(parse_duration_ms("10"), 10)
        self.assertEqual(parse_duration_ms("1s"), 1000)
        self.assertEqual(parse_duration_ms("500us"), 1)
        self.assertEqual(parse_duration_ms("30"), 30)

    def test_rounding_never_returns_zero(self):
        self.assertEqual(parse_duration_ms("0.1ms"), 1)
        self.assertEqual(parse_duration_ms(0), 1)


class VoltageTest(unittest.TestCase):
    def test_forms(self):
        self.assertAlmostEqual(parse_volts("1.8"), 1.8)
        self.assertAlmostEqual(parse_volts("1800mv"), 1.8)
        self.assertAlmostEqual(parse_volts("3.3v"), 3.3)
        self.assertAlmostEqual(parse_volts("-5"), -5.0)

    def test_range(self):
        with self.assertRaises(SkillError) as raised:
            parse_volts("5.1")
        self.assertEqual(raised.exception.code, "invalid_arguments")
        self.assertIn("[-5, 5]", raised.exception.message)


class ChannelTest(unittest.TestCase):
    def test_defaults_to_no_trigger(self):
        self.assertEqual(parse_channel_spec("3"), {"id": 3, "trigger": "none"})

    def test_names_trigger(self):
        self.assertEqual(parse_channel_spec("0:rising"), {"id": 0, "trigger": "rising"})

    def test_shorthand_list(self):
        channels = parse_channels(["0,2,3"])
        self.assertEqual([channel["id"] for channel in channels], [0, 2, 3])
        self.assertTrue(all(channel["trigger"] == "none" for channel in channels))

    def test_mixed_list(self):
        channels = parse_channels(["3:falling,1:both"])
        self.assertEqual(channels, [{"id": 1, "trigger": "both"}, {"id": 3, "trigger": "falling"}])

    def test_duplicate_rejected(self):
        with self.assertRaises(SkillError) as raised:
            parse_channels(["0", "0:rising"])
        self.assertEqual(raised.exception.code, "invalid_arguments")

    def test_unknown_trigger_rejected(self):
        with self.assertRaises(SkillError):
            parse_channel_spec("0:edge")

    def test_empty_rejected(self):
        with self.assertRaises(SkillError):
            parse_channels(None)


class PercentTest(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(parse_percent("50"), 50.0)
        self.assertEqual(parse_percent("50%"), 50.0)

    def test_range(self):
        with self.assertRaises(SkillError):
            parse_percent("101")


class TriggerTest(unittest.TestCase):
    def test_names(self):
        for name in ("none", "rising", "high", "falling", "low", "both"):
            self.assertEqual(parse_trigger(name.upper()), name)


class FormatTest(unittest.TestCase):
    def test_hz(self):
        self.assertEqual(fmt_hz(1_000_000), "1 MHz")
        self.assertEqual(fmt_hz(2_500_000), "2.5 MHz")
        self.assertEqual(fmt_hz(500_000), "500 kHz")
        self.assertEqual(fmt_hz(20), "20 Hz")

    def test_ms(self):
        self.assertEqual(fmt_ms(10), "10 ms")
        self.assertEqual(fmt_ms(1000), "1 s")
        self.assertEqual(fmt_ms(7200000), "7200 s")


if __name__ == "__main__":
    unittest.main()
