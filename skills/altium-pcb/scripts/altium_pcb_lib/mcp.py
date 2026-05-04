from __future__ import annotations

import argparse
import json
import math
import os
import re
import struct
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .common import *


def export_altium_mcp_tool_calls(plan: Dict[str, Any], options: Dict[str, Any]) -> Dict[str, Any]:
    locked_refs = {normalize_ref(item) for item in make_list(options.get("locked")) if normalize_ref(item)}
    include_unresolved = bool(options.get("include_unresolved"))
    include_rotation = bool(options.get("include_rotation"))
    tool_calls = []
    skipped = []

    for placement in make_list(plan.get("placements")):
        designator = ensure_string(placement.get("designator"))
        ref = normalize_ref(designator)
        suggested_center = placement.get("suggested_center")
        if not designator or not suggested_center:
            skipped.append({"designator": designator, "reason": "missing-designator-or-suggested-center"})
            continue
        if ref in locked_refs:
            skipped.append({"designator": designator, "reason": "locked"})
            continue
        if placement.get("collision_status") == "unresolved" and not include_unresolved:
            skipped.append({"designator": designator, "reason": "collision-unresolved"})
            continue

        x_mil = mm_to_mil(suggested_center.get("x_mm"))
        y_mil = mm_to_mil(suggested_center.get("y_mm"))
        if x_mil is None or y_mil is None:
            skipped.append({"designator": designator, "reason": "invalid-coordinate"})
            continue

        rotation = -1
        if include_rotation:
            rotation = parse_rotation_degrees(placement.get("rotation"))

        tool_calls.append(
            {
                "tool": "set_component_position",
                "arguments": {
                    "cmp_designator": designator,
                    "x": round(x_mil, 3),
                    "y": round(y_mil, 3),
                    "rotation": rotation,
                },
                "source": {
                    "old_center": placement.get("old_center"),
                    "suggested_center": suggested_center,
                    "delta": placement.get("delta"),
                    "collision_status": placement.get("collision_status", ""),
                    "confidence": placement.get("confidence", ""),
                },
            }
        )

    return {
        "version": 1,
        "backend": "altium-mcp",
        "format": "fastmcp-tool-calls",
        "units": {
            "source_plan": "mm",
            "altium_mcp_set_component_position": "mil",
        },
        "coordinate_policy": {
            "mode": "pcbdoc-mm-to-mil",
            "preflight_required": True,
            "note": "Before live apply, compare fixed anchor coordinates from the parsed plan with altium-mcp get_all_component_data output and apply any board-origin offset.",
        },
        "guards": {
            "board_outline_fixed": True,
            "locked_components_fixed": True,
            "skip_unresolved_collisions": not include_unresolved,
            "rotation_policy": "from-plan" if include_rotation else "keep-current",
        },
        "summary": {
            "placements_in_plan": len(make_list(plan.get("placements"))),
            "tool_calls": len(tool_calls),
            "skipped": len(skipped),
        },
        "tool_calls": tool_calls,
        "skipped": skipped,
        "next_steps": [
            "Run altium-mcp get_all_component_data on the live board before applying these calls.",
            "Calibrate board-origin offset with fixed anchors, especially locked components and connectors.",
            "Apply set_component_position calls only after confirming locked components and unresolved collisions remain skipped.",
        ],
    }


def mcp_jsonrpc_request(call: Dict[str, Any], request_id: int) -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {
            "name": call.get("tool", ""),
            "arguments": call.get("arguments") or {},
        },
    }


def mcp_batch_position_call(calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    positions = []
    for call in calls:
        arguments = call.get("arguments") or {}
        positions.append(
            {
                "designator": arguments.get("cmp_designator", ""),
                "x": arguments.get("x"),
                "y": arguments.get("y"),
                "rotation": arguments.get("rotation", -1),
            }
        )
    return {
        "tool": "set_component_positions",
        "arguments": {
            "positions": positions,
            "skip_if_locked": True,
            "stop_on_error": False,
        },
    }
