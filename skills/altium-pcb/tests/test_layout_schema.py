"""Layout-schema contract tests for the altium-pcb skill.

The analysis artifact (`analysis.board-layout.json`) is produced by emb-agent's
`ingest board`; the skill validates its shape before planning against it.
`fixtures/analysis.board-layout.json` is a real artifact from
`ingest board` on AltiumSharp's MAX5719 Breakout.PcbDoc.

Run: python3 -m unittest discover -s skills/altium-pcb/tests
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "analysis.board-layout.json"
sys.path.insert(0, str(SCRIPTS))

from altium_pcb_lib.common import validate_layout  # noqa: E402
from altium_pcb_lib.planner import build_placement_plan  # noqa: E402


def real_layout() -> dict:
    with FIXTURE.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class ValidateLayoutTests(unittest.TestCase):
    def test_real_emb_artifact_validates(self) -> None:
        parsed = real_layout()
        self.assertIs(validate_layout(parsed), parsed)
        self.assertEqual(parsed["coverage"]["components"], 49)
        self.assertEqual(parsed["coverage"]["nets"], 28)
        self.assertEqual(parsed["coverage"]["pads"], 143)
        for key in ("min_x_mm", "min_y_mm", "max_x_mm", "max_y_mm"):
            self.assertIsInstance(parsed["board"]["bounds"][key], float)

    def test_non_object_is_rejected(self) -> None:
        for value in ([], "x", 3, None):
            with self.assertRaisesRegex(ValueError, "must be a JSON object"):
                validate_layout(value)

    def test_coverage_must_be_integers(self) -> None:
        parsed = real_layout()
        parsed["coverage"]["components"] = "49"
        with self.assertRaisesRegex(ValueError, "coverage.components"):
            validate_layout(parsed)
        parsed = real_layout()
        parsed["coverage"] = []
        with self.assertRaisesRegex(ValueError, "coverage must be an object"):
            validate_layout(parsed)

    def test_bounds_require_all_keys_and_numbers(self) -> None:
        parsed = real_layout()
        del parsed["board"]["bounds"]["min_y_mm"]
        with self.assertRaisesRegex(ValueError, "board.bounds.min_y_mm"):
            validate_layout(parsed)

        parsed = real_layout()
        parsed["board"]["bounds"]["max_x_mm"] = "wide"
        with self.assertRaisesRegex(ValueError, "board.bounds.max_x_mm"):
            validate_layout(parsed)

        parsed = real_layout()
        parsed["board"]["bounds"] = []
        with self.assertRaisesRegex(ValueError, "board.bounds must be an object"):
            validate_layout(parsed)

    def test_list_fields_are_type_checked(self) -> None:
        parsed = real_layout()
        parsed["pads"] = {}
        with self.assertRaisesRegex(ValueError, "pads must be a list"):
            validate_layout(parsed)

    def test_missing_optional_sections_are_allowed(self) -> None:
        # A minimal artifact without coverage/board still validates.
        self.assertEqual(validate_layout({"format": "altium-pcbdoc"}), {"format": "altium-pcbdoc"})


class PlanAgainstRealArtifactTests(unittest.TestCase):
    def test_real_artifact_plans(self) -> None:
        parsed = real_layout()
        plan = build_placement_plan(parsed, {"locked": [], "limit": 200})
        self.assertTrue(plan)
        self.assertGreaterEqual(len(plan.get("placements", [])), 1)
        refs = {item.get("designator") for item in plan.get("placements", [])}
        self.assertIn("R1", refs)
        summary = plan.get("summary") or {}
        self.assertEqual(summary.get("components"), 49)
        self.assertEqual(summary.get("pads"), 143)
        self.assertEqual(summary.get("placements"), len(plan.get("placements", [])))

    def test_plan_cli_accepts_real_artifact(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "altium_pcb.py"), "plan", "--parsed", str(FIXTURE)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["command"], "altium-pcb plan")
        self.assertIn("placements", payload["placement_plan"])

    def test_plan_cli_rejects_invalid_schema(self) -> None:
        bad = copy.deepcopy(real_layout())
        bad["coverage"]["nets"] = "many"
        bad_path = FIXTURE.parent / "invalid.board-layout.json"
        bad_path.write_text(json.dumps(bad), encoding="utf-8")
        try:
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "altium_pcb.py"), "plan", "--parsed", str(bad_path)],
                capture_output=True,
                text=True,
            )
        finally:
            bad_path.unlink(missing_ok=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("coverage.nets", result.stderr)


if __name__ == "__main__":
    unittest.main()
