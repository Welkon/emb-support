import pathlib
import sys
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from atklogic.capabilities import options_from, resolve, summarise  # noqa: E402
from atklogic.common import SkillError  # noqa: E402

OPTIONS = [
    {"frequencyHz": 1_000_000, "timings": [
        {"durationMs": 1, "rle": False},
        {"durationMs": 10, "rle": False},
        {"durationMs": 1000, "rle": True},
    ]},
    {"frequencyHz": 2_000_000, "timings": [
        {"durationMs": 1, "rle": False},
        {"durationMs": 10, "rle": False},
    ]},
]


class ShapeTest(unittest.TestCase):
    def test_full_options(self):
        self.assertEqual(len(options_from({"options": OPTIONS})), 2)

    def test_duration_query(self):
        payload = {
            "ok": True, "query": "durationOptions", "frequencyHz": 1_000_000,
            "durationOptionsMs": [1000, 10, 1], "maxDurationMs": 1000,
        }
        options = options_from(payload)
        self.assertEqual(options[0]["frequencyHz"], 1_000_000)
        self.assertEqual([t["durationMs"] for t in options[0]["timings"]], [1000, 10, 1])

    def test_frequency_query(self):
        payload = {
            "ok": True, "query": "frequencyOptions", "durationMs": 10,
            "frequencyOptionsHz": [2_000_000, 1_000_000],
        }
        options = options_from(payload)
        self.assertEqual([o["frequencyHz"] for o in options], [2_000_000, 1_000_000])
        self.assertEqual(options[1]["timings"], [{"durationMs": 10, "rle": False}])

    def test_unknown_shape(self):
        with self.assertRaises(SkillError):
            options_from({"ok": True})


class ResolveTest(unittest.TestCase):
    def test_exact(self):
        chosen = resolve(OPTIONS, 1_000_000, 10)
        self.assertEqual((chosen["frequencyHz"], chosen["durationMs"]), (1_000_000, 10))
        self.assertEqual(chosen["adjustments"], [])
        self.assertEqual(chosen["samplingDepth"], 10_000)

    def test_frequency_is_reduced_not_raised(self):
        chosen = resolve(OPTIONS, 3_000_000, 10)
        self.assertEqual(chosen["frequencyHz"], 2_000_000)
        self.assertTrue(chosen["adjustments"][0].startswith("frequency 3 MHz -> 2 MHz"))

    def test_below_smallest(self):
        chosen = resolve(OPTIONS, 10_000, 10)
        self.assertEqual(chosen["frequencyHz"], 1_000_000)

    def test_duration_rounds_down(self):
        chosen = resolve(OPTIONS, 1_000_000, 500)
        self.assertEqual(chosen["durationMs"], 10)
        self.assertIn("500 ms -> 10 ms", chosen["adjustments"][0])

    def test_duration_below_smallest(self):
        chosen = resolve(OPTIONS, 2_000_000, 0)
        self.assertEqual(chosen["durationMs"], 1)

    def test_rle_is_reported(self):
        chosen = resolve(OPTIONS, 1_000_000, 1000)
        self.assertTrue(chosen["rle"])

    def test_strict_refuses(self):
        with self.assertRaises(SkillError) as raised:
            resolve(OPTIONS, 3_000_000, 10, strict=True)
        self.assertEqual(raised.exception.code, "invalid_capture_combination")
        self.assertIn("2 MHz", raised.exception.suggestions[0])

    def test_strict_accepts_legal(self):
        chosen = resolve(OPTIONS, 1_000_000, 1000, strict=True)
        self.assertEqual(chosen["durationMs"], 1000)

    def test_no_options(self):
        with self.assertRaises(SkillError):
            resolve([], 1_000_000, 10)


class SummaryTest(unittest.TestCase):
    def test_rows(self):
        summary = summarise(OPTIONS)
        self.assertEqual(summary["frequencyCount"], 2)
        top = summary["options"][0]
        self.assertEqual(top["frequencyHz"], 2_000_000)
        self.assertEqual(top["durationCount"], 2)
        self.assertEqual(top["rleDurationsMs"], [])
        self.assertEqual(summary["options"][1]["rleDurationsMs"], [1000])


if __name__ == "__main__":
    unittest.main()
