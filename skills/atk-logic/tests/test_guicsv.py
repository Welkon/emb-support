import pathlib
import sys
import tempfile
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from atklogic import guicsv  # noqa: E402
from atklogic.common import SkillError  # noqa: E402

HEADER = "序号,开始,时间,名称,数值,\n"


def write_csv(root: pathlib.Path, body: str, encoding: str = "gb18030") -> pathlib.Path:
    path = root / "decode.csv"
    path.write_text(HEADER + body, encoding=encoding)
    return path


class SummaryTest(unittest.TestCase):
    def test_period_duty_and_frequency(self):
        root = pathlib.Path(tempfile.mkdtemp())
        path = write_csv(
            root,
            "0,150 ns,249.950000 µs,Duty cycles,1.200240%,\n"
            "1,250.100000 µs,250.200000 µs,Duty cycles,60.000000%,\n"
            "2,150 ns,249.950000 µs,Periods,249.950000 µs,\n"
            "3,150 ns,249.950000 µs,Frequencies,4.000800 kHz,\n",
        )
        summary = guicsv.summarise(path)
        self.assertEqual(summary["encoding"], "gb18030")
        self.assertEqual(summary["rows"], 4)
        self.assertEqual(summary["skipped"], 0)
        kinds = {item["name"]: item for item in summary["kinds"]}
        duty = kinds["Duty cycles"]
        self.assertEqual(duty["count"], 2)
        self.assertEqual(duty["unit"], "percent")
        self.assertAlmostEqual(duty["min"], 1.20024)
        self.assertAlmostEqual(duty["max"], 60.0)
        self.assertAlmostEqual(duty["mean"], 30.60012)
        self.assertEqual(duty["samples"][0]["value"], "1.200240%")
        self.assertAlmostEqual(kinds["Periods"]["mean"], 249_950, delta=1)
        self.assertEqual(kinds["Periods"]["unit"], "ns")
        self.assertAlmostEqual(kinds["Frequencies"]["mean"], 4_000.8, delta=0.1)

    def test_utf8_with_bom_and_unknown_units(self):
        root = pathlib.Path(tempfile.mkdtemp())
        path = write_csv(
            root,
            "0,150 ns,249.950000 µs,Data,0x55AA,\n"
            "1,250.100000 µs,250.200000 µs,Data,0x1234,\n",
            encoding="utf-8-sig",
        )
        summary = guicsv.summarise(path)
        data = summary["kinds"][0]
        self.assertEqual(data["count"], 2)
        self.assertIsNone(data["min"])
        self.assertEqual(data["textSamples"], ["0x55AA", "0x1234"])

    def test_missing_file(self):
        with self.assertRaises(SkillError) as raised:
            guicsv.summarise(pathlib.Path(tempfile.mkdtemp()) / "nope.csv")
        self.assertEqual(raised.exception.code, "gui_csv_not_found")

    def test_short_rows_are_counted_not_crashing(self):
        root = pathlib.Path(tempfile.mkdtemp())
        path = write_csv(root, "0,only-two-fields\n1,150 ns,1 µs,Duty cycles,50%,\n")
        summary = guicsv.summarise(path)
        self.assertEqual(summary["rows"], 1)
        self.assertEqual(summary["skipped"], 1)


if __name__ == "__main__":
    unittest.main()
