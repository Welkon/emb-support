"""Equal-length offline writer tests for the altium-pcb skill.

`apply` patches only `Root Entry/Components6/Data`, only by equal-length field
replacement, and only the fields the plan names. These tests lock the byte-length
invariant, the unauthorized-field guard, the copy-by-default rule and the
`--confirm` requirement for in-place writes.

The fixture `fixtures/board.PcbDoc` is AltiumSharp's MAX5719 Breakout.PcbDoc
(Apache-2.0; see fixtures/README.md).

Run: python3 -m unittest discover -s skills/altium-pcb/tests
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
BOARD = Path(__file__).resolve().parent / "fixtures" / "board.PcbDoc"
sys.path.insert(0, str(SCRIPTS))

from altium_pcb_lib.pcbdoc import (  # noqa: E402
    Cfb,
    apply_placement_plan_to_pcbdoc,
    build_record_chunks,
    parse_record_fields,
)


def mm(mil: float) -> float:
    return mil * 0.0254


def component_fields(path: Path, record_index: int) -> dict:
    data = bytearray(path.read_bytes())
    cfb = Cfb(data)
    entry = cfb.find_entry_by_path("Root Entry/Components6/Data")
    records = build_record_chunks(cfb.read_stream(entry))
    return parse_record_fields(records[record_index]["text"])


class EqualLengthWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "board.placed.PcbDoc"

    def plan(self, **overrides) -> dict:
        placement = {
            "designator": "TP10",
            "source_record": 0,
            # 2934.0709 mil rounds to an equal-length "    2934mil" replacement.
            "old_center": {"x_mm": mm(2933.0709), "y_mm": mm(1633.8584)},
            "suggested_center": {"x_mm": mm(2934.0709), "y_mm": mm(1633.8584)},
            "field_patches": {
                # ROTATION is stored leading-space padded; keep the exact width.
                "ROTATION": " 1.00000000000000E+0001",
                "LAYER": "BOT",  # 3 chars, like TOP
                "PATTERN": "TestPoint-2.0mm",  # 16 chars, like TestPoint-1.5mm
            },
        }
        placement.update(overrides)
        return {"placements": [placement]}

    def apply(self, plan: dict, **options):
        opts = {"output": str(self.output), "in_place": False, "confirm": False, "locked": []}
        opts.update(options)
        return apply_placement_plan_to_pcbdoc(BOARD, plan, opts)

    def test_equal_length_patches_and_unauthorized_field_guard(self) -> None:
        before = component_fields(BOARD, 0)
        input_bytes = BOARD.read_bytes()
        result = self.apply(self.plan())
        self.assertEqual(result["status"], "ok")

        # Byte length is invariant: only equal-length in-place replacement happens.
        self.assertEqual(self.output.stat().st_size, len(input_bytes))
        # Copy by default: the input board is untouched.
        self.assertEqual(BOARD.read_bytes(), input_bytes)

        after = component_fields(self.output, 0)
        # parse_record_fields strips surrounding whitespace; the on-disk field keeps
        # its original byte length (the file-size assertion above).
        self.assertEqual(after["X"], "2934mil")
        self.assertEqual(after["ROTATION"], "1.00000000000000E+0001")
        self.assertEqual(after["LAYER"], "BOT")
        self.assertEqual(after["PATTERN"], "TestPoint-2.0mm")
        # Not named by the plan -> untouched.
        self.assertEqual(after["SOURCEDESIGNATOR"], before["SOURCEDESIGNATOR"])
        # Coord patches round to whole mils while keeping the original field width.
        self.assertEqual(after["Y"], "1634mil")

        guarantees = result["guarantees"]
        self.assertEqual(guarantees["board_outline_modified"], False)
        self.assertEqual(guarantees["routing_modified"], False)
        self.assertEqual(guarantees["pads_modified"], False)
        self.assertEqual(guarantees["nets_modified"], False)

    def test_length_mismatch_is_skipped_not_written(self) -> None:
        before = component_fields(BOARD, 0)
        result = self.apply(
            self.plan(suggested_locked=True, field_patches={"ROTATION": "1.0E+001"})
        )
        reasons = {item.get("reason") for item in result["skipped"]}
        self.assertIn("field-length-not-patchable", reasons)
        self.assertIn("field-length-not-patchable", reasons)
        after = component_fields(self.output, 0)
        # ROTATION request was the wrong length -> unchanged.
        self.assertEqual(after["ROTATION"], before["ROTATION"])
        self.assertEqual(self.output.stat().st_size, BOARD.stat().st_size)

    def test_locked_convenience_patch_only_when_equal_length(self) -> None:
        result = self.apply(self.plan(suggested_locked=False))
        fields = result["patched"][0].get("fields", {})
        self.assertEqual(fields.get("LOCKED"), {"from": "FALSE", "to": "FALSE"})

        result = self.apply(self.plan(suggested_locked=True), output=str(self.output))
        reasons = [item for item in result["skipped"] if item.get("field") == "LOCKED"]
        self.assertTrue(reasons and reasons[0]["reason"] == "field-length-not-patchable")

    def test_in_place_requires_confirm(self) -> None:
        with self.assertRaisesRegex(ValueError, "confirm"):
            self.apply(self.plan(), in_place=True, confirm=False, output=None)
        input_bytes = BOARD.read_bytes()
        result = self.apply(self.plan(), in_place=True, confirm=True, output=None)
        self.assertEqual(result["write_mode"], "pcbdoc-in-place")
        # Restore the fixture after the deliberate in-place write.
        BOARD.write_bytes(input_bytes)
        self.assertEqual(BOARD.read_bytes(), input_bytes)

    def test_plan_document_roundtrip(self) -> None:
        # A serialized plan (as written by `plan --output`) is accepted.
        plan_text = json.dumps(self.plan())
        result = self.apply(json.loads(plan_text))
        self.assertGreaterEqual(result["summary"]["patched"], 1)


if __name__ == "__main__":
    unittest.main()
