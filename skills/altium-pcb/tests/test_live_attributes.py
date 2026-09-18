"""Live-bridge operation tests for `set_component_attributes`.

These are structure-only: they assert the emitted emitter/apply JSON without
calling Altium. The DelphiScript side (`pcb_utils.pas` / `Altium_API.pas`)
dispatches the same `set_component_attributes` command.

Run: python3 -m unittest discover -s skills/altium-pcb/tests
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from altium_pcb_lib.live import build_live_apply  # noqa: E402
from altium_pcb_lib.mcp import export_altium_live_tool_calls  # noqa: E402


def placement(**overrides):
    base = {
        "designator": "R1",
        "source_record": 0,
        "suggested_center": {"x_mm": 1.0, "y_mm": 2.0},
        "old_center": {"x_mm": 1.0, "y_mm": 2.0},
        "collision_status": "clear",
        "rotation": "0",
        "attribute_patches": {"rotation": 90.0, "locked": True},
    }
    base.update(overrides)
    return base


class LiveAttributeEmitterTests(unittest.TestCase):
    def test_emits_set_component_attributes_call(self) -> None:
        export = export_altium_live_tool_calls({"placements": [placement()]}, {})
        calls = export["tool_calls"]
        attributes = [call for call in calls if call["tool"] == "set_component_attributes"]
        self.assertEqual(len(attributes), 1, calls)
        arguments = attributes[0]["arguments"]
        self.assertEqual(arguments["cmp_designator"], "R1")
        self.assertEqual(arguments["rotation"], 90.0)
        self.assertIs(arguments["locked"], True)

    def test_no_attribute_patches_emits_only_position(self) -> None:
        export = export_altium_live_tool_calls(
            {"placements": [placement(attribute_patches=None)]}, {}
        )
        tools = {call["tool"] for call in export["tool_calls"]}
        self.assertEqual(tools, {"set_component_position"})

    def test_invalid_attribute_patch_is_ignored(self) -> None:
        export = export_altium_live_tool_calls(
            {"placements": [placement(attribute_patches={"rotation": "ninety"})]}, {}
        )
        tools = {call["tool"] for call in export["tool_calls"]}
        self.assertNotIn("set_component_attributes", tools)


class LiveAttributeApplyTests(unittest.TestCase):
    def preflight(self, tool_calls):
        return {
            "status": "ready",
            "mcp_export": {
                "coordinate_policy": {"preflight_required": False},
                "tool_calls": tool_calls,
            },
        }

    def test_attribute_call_passes_through_apply(self) -> None:
        result = build_live_apply(
            self.preflight(
                [
                    {
                        "tool": "set_component_attributes",
                        "arguments": {"cmp_designator": "R1", "rotation": 180.0, "locked": False},
                    }
                ]
            ),
            {"confirm": True, "locked": "", "limit": 0},
        )
        calls = result.get("tool_calls") or result.get("executable_tool_calls") or result.get("calls")
        # Find the emitted bundle regardless of the exact top-level key name.
        bundle = result
        while isinstance(bundle, dict) and "tool_calls" not in bundle and "executable_calls" not in bundle:
            nested = [value for value in bundle.values() if isinstance(value, dict)]
            if not nested:
                break
            bundle = nested[0]
        emitted = bundle.get("tool_calls") or bundle.get("executable_calls") or calls or []
        self.assertTrue(
            any(call.get("tool") == "set_component_attributes" for call in emitted),
            result,
        )

    def test_attribute_call_without_attributes_is_skipped(self) -> None:
        result = build_live_apply(
            self.preflight(
                [{"tool": "set_component_attributes", "arguments": {"cmp_designator": "R1"}}]
            ),
            {"confirm": True, "locked": "", "limit": 0},
        )
        text = str(result)
        self.assertIn("no-attributes", text)

    def test_locked_designator_is_skipped(self) -> None:
        result = build_live_apply(
            self.preflight(
                [
                    {
                        "tool": "set_component_attributes",
                        "arguments": {"cmp_designator": "R1", "locked": True},
                    }
                ]
            ),
            {"confirm": True, "locked": "R1", "limit": 0},
        )
        self.assertIn("locked", str(result))


if __name__ == "__main__":
    unittest.main()
