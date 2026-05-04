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
from .mcp import (
    altium_bridge_batch_position_request,
    altium_bridge_request,
    export_altium_mcp_tool_calls,
    mcp_batch_position_call,
    mcp_jsonrpc_request,
)


def normalize_live_component_records(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, str):
        parsed = parse_json_text(value)
        return normalize_live_component_records(parsed)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []

    if isinstance(value.get("components"), list):
        return normalize_live_component_records(value["components"])
    if "result" in value:
        return normalize_live_component_records(value["result"])
    if "content" in value and isinstance(value["content"], list):
        records: List[Dict[str, Any]] = []
        for item in value["content"]:
            if isinstance(item, dict) and item.get("type") == "text":
                records.extend(normalize_live_component_records(item.get("text", "")))
        return records
    return []


def live_component_map(value: Any) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for component in normalize_live_component_records(value):
        ref = normalize_ref(component.get("designator") or component.get("refdes") or component.get("name"))
        if ref:
            result[ref] = component
    return result


def live_component_point_mil(component: Dict[str, Any]) -> Optional[Dict[str, float]]:
    if not component:
        return None
    x = component.get("x")
    y = component.get("y")
    if not is_finite_number(x) or not is_finite_number(y):
        return None
    return {"x_mil": round(float(x), 3), "y_mil": round(float(y), 3)}


def plan_point_mil(point: Optional[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    if not point:
        return None
    x = mm_to_mil(point.get("x_mm"))
    y = mm_to_mil(point.get("y_mm"))
    if x is None or y is None:
        return None
    return {"x_mil": round(x, 3), "y_mil": round(y, 3)}


def live_component_locked(component: Dict[str, Any]) -> bool:
    for key in ["locked", "is_locked", "isLocked"]:
        if truthy_locked_value(component.get(key)):
            return True
    return False


def select_anchor_components(plan: Dict[str, Any], anchor_refs: List[str], locked_refs: List[str]) -> List[Dict[str, Any]]:
    fixed = make_list((plan.get("constraints") or {}).get("fixed_components"))
    wanted = {normalize_ref(item) for item in anchor_refs if normalize_ref(item)}
    locked = {normalize_ref(item) for item in locked_refs if normalize_ref(item)}
    anchors = []
    for component in fixed:
        if not isinstance(component, dict):
            continue
        ref = normalize_ref(component.get("designator"))
        if not ref:
            continue
        if wanted and ref not in wanted:
            continue
        if not wanted and locked and ref not in locked and "connector-mechanical-anchor" not in make_list(component.get("reasons")):
            continue
        if component.get("center"):
            anchors.append(component)
    if anchors:
        return anchors
    placements = make_list(plan.get("placements"))
    for placement in placements:
        ref = normalize_ref(placement.get("designator"))
        if wanted and ref not in wanted:
            continue
        if locked and ref not in locked:
            continue
        if placement.get("old_center"):
            anchors.append({
                "designator": placement.get("designator"),
                "center": placement.get("old_center"),
                "reasons": ["placement-old-center-anchor"],
            })
    return anchors


def build_live_preflight(plan: Dict[str, Any], live_data: Any, options: Dict[str, Any]) -> Dict[str, Any]:
    locked_refs = parse_locked(options.get("locked", ""))
    anchor_refs = parse_locked(options.get("anchors", ""))
    tolerance_mil = float(options.get("tolerance_mil") or 10)
    live_by_ref = live_component_map(live_data)
    anchors = []

    for anchor in select_anchor_components(plan, anchor_refs, locked_refs):
        ref = normalize_ref(anchor.get("designator"))
        live = live_by_ref.get(ref)
        plan_point = plan_point_mil(anchor.get("center"))
        live_point = live_component_point_mil(live or {})
        if not live or not plan_point or not live_point:
            anchors.append({
                "designator": anchor.get("designator", ""),
                "status": "missing-live-or-plan-coordinate",
                "reasons": make_list(anchor.get("reasons")),
            })
            continue
        dx = round(live_point["x_mil"] - plan_point["x_mil"], 3)
        dy = round(live_point["y_mil"] - plan_point["y_mil"], 3)
        anchors.append({
            "designator": anchor.get("designator", ""),
            "status": "matched",
            "reasons": make_list(anchor.get("reasons")),
            "plan": plan_point,
            "live": live_point,
            "offset_mil": {"dx": dx, "dy": dy},
            "live_locked": live_component_locked(live),
        })

    matched = [item for item in anchors if item.get("status") == "matched"]
    if matched:
        offset = {
            "dx": round(median([item["offset_mil"]["dx"] for item in matched]), 3),
            "dy": round(median([item["offset_mil"]["dy"] for item in matched]), 3),
        }
    else:
        offset = {"dx": 0.0, "dy": 0.0}

    for item in matched:
        error = math.sqrt(
            (float(item["offset_mil"]["dx"]) - offset["dx"]) ** 2
            + (float(item["offset_mil"]["dy"]) - offset["dy"]) ** 2
        )
        item["offset_error_mil"] = round(error, 3)

    export = export_altium_mcp_tool_calls(
        plan,
        {
            "locked": locked_refs,
            "include_unresolved": bool(options.get("include_unresolved")),
            "include_rotation": bool(options.get("include_rotation")),
            "allow_unreviewed": bool(options.get("allow_unreviewed")),
        },
    )

    calibrated_calls = []
    skipped = list(make_list(export.get("skipped")))
    for call in make_list(export.get("tool_calls")):
        arguments = call.get("arguments") or {}
        ref = normalize_ref(arguments.get("cmp_designator"))
        live = live_by_ref.get(ref)
        if not live:
            skipped.append({"designator": arguments.get("cmp_designator", ""), "reason": "missing-live-component"})
            continue
        if live_component_locked(live):
            skipped.append({"designator": arguments.get("cmp_designator", ""), "reason": "live-component-locked"})
            continue
        calibrated = {
            **call,
            "arguments": {
                **arguments,
                "x": round(float(arguments["x"]) + offset["dx"], 3),
                "y": round(float(arguments["y"]) + offset["dy"], 3),
            },
            "preflight": {
                "source_arguments": arguments,
                "applied_offset_mil": offset,
                "live_current": live_component_point_mil(live),
            },
        }
        calibrated_calls.append(calibrated)

    max_anchor_error = max([float(item.get("offset_error_mil", 0)) for item in matched], default=0.0)
    warnings = []
    if not matched:
        warnings.append("no fixed anchors matched live Altium component data")
    if len(matched) == 1:
        warnings.append("only one anchor matched; translation can be estimated but rotation/scale mistakes cannot be detected")
    if max_anchor_error > tolerance_mil:
        warnings.append("anchor offsets are inconsistent beyond tolerance")

    status = "ready"
    if not matched or max_anchor_error > tolerance_mil:
        status = "blocked"
    elif warnings:
        status = "ready-with-warnings"

    calibrated_export = {
        **export,
        "coordinate_policy": {
            **(export.get("coordinate_policy") or {}),
            "mode": "pcbdoc-mm-to-live-mil-translation",
            "preflight_required": False,
            "translation_offset_mil": offset,
            "anchor_count": len(matched),
            "max_anchor_error_mil": round(max_anchor_error, 3),
            "tolerance_mil": tolerance_mil,
        },
        "summary": {
            **(export.get("summary") or {}),
            "tool_calls": len(calibrated_calls),
            "skipped": len(skipped),
        },
        "tool_calls": calibrated_calls,
        "skipped": skipped,
    }

    return {
        "version": 1,
        "backend": "altium-pcb-live",
        "status": status,
        "summary": {
            "live_components": len(live_by_ref),
            "anchors": len(anchors),
            "matched_anchors": len(matched),
            "calibrated_tool_calls": len(calibrated_calls),
            "skipped": len(skipped),
            "warnings": len(warnings),
        },
        "coordinate_transform": {
            "type": "translation",
            "offset_mil": offset,
            "max_anchor_error_mil": round(max_anchor_error, 3),
            "tolerance_mil": tolerance_mil,
        },
        "anchors": anchors,
        "warnings": warnings,
        "mcp_export": calibrated_export,
        "live_export": calibrated_export,
        "next_steps": [
            "Review anchors and coordinate_transform before live apply.",
            "If status is blocked, refresh live component data or pass explicit --anchor refs that are fixed in both plan and Altium.",
            "Execute calibrated live_export.tool_calls only after confirming locked components remain skipped.",
        ],
    }


def build_live_apply(preflight: Dict[str, Any], options: Dict[str, Any]) -> Dict[str, Any]:
    status = ensure_string(preflight.get("status"))
    allow_warnings = bool(options.get("allow_warnings"))
    confirmed = bool(options.get("confirm"))
    limit = int(options.get("limit") or 0)
    allow_unreviewed = bool(options.get("allow_unreviewed"))
    locked_refs = {normalize_ref(item) for item in parse_locked(options.get("locked", ""))}

    if status == "blocked":
        raise ValueError("Refusing live apply because preflight status is blocked")
    if status == "ready-with-warnings" and not allow_warnings:
        raise ValueError("Refusing live apply for ready-with-warnings without --allow-warnings")
    if status != "ready" and not (status == "ready-with-warnings" and allow_warnings):
        raise ValueError(f"Refusing live apply for unexpected preflight status: {status or 'missing'}")

    export = unwrap_mcp_export(preflight.get("mcp_export") or {})
    coordinate_policy = export.get("coordinate_policy") or {}
    if coordinate_policy.get("preflight_required") is True:
        raise ValueError("Refusing live apply because MCP export still requires preflight calibration")

    requested_calls = make_list(export.get("tool_calls"))
    executable_calls = []
    skipped = []
    limited = False
    allowed_unreviewed = 0
    for call in requested_calls:
        if not isinstance(call, dict):
            skipped.append({"designator": "", "reason": "invalid-tool-call"})
            continue
        tool = ensure_string(call.get("tool"))
        arguments = call.get("arguments") or {}
        designator = ensure_string(arguments.get("cmp_designator"))
        ref = normalize_ref(designator)
        if tool != "set_component_position":
            skipped.append({"designator": designator, "reason": "unsupported-tool", "tool": tool})
            continue
        if not designator:
            skipped.append({"designator": "", "reason": "missing-designator"})
            continue
        if ref in locked_refs:
            skipped.append({"designator": designator, "reason": "locked"})
            continue
        review = ((call.get("source") or {}).get("ai_review")) or {}
        if ai_review_rejected(review):
            skipped.append({"designator": designator, "reason": "ai-review-rejected", "ai_review": review})
            continue
        if ai_review_required(review) and not ai_review_accepted(review):
            if not allow_unreviewed:
                skipped.append({"designator": designator, "reason": "ai-review-required", "ai_review": review})
                continue
            allowed_unreviewed += 1
        if not is_finite_number(arguments.get("x")) or not is_finite_number(arguments.get("y")):
            skipped.append({"designator": designator, "reason": "invalid-coordinate"})
            continue
        if limit > 0 and len(executable_calls) >= limit:
            limited = True
            skipped.append({"designator": designator, "reason": "limit"})
            continue

        normalized_call = {
            "sequence": len(executable_calls) + 1,
            "tool": tool,
            "arguments": {
                "cmp_designator": designator,
                "x": round(float(arguments["x"]), 3),
                "y": round(float(arguments["y"]), 3),
                "rotation": parse_rotation_degrees(arguments.get("rotation")) if is_finite_number(arguments.get("rotation")) else -1,
            },
        }
        if call.get("source"):
            normalized_call["source"] = call.get("source")
        if call.get("preflight"):
            normalized_call["preflight"] = call.get("preflight")
        executable_calls.append(normalized_call)

    preflight_skipped = make_list(export.get("skipped"))
    jsonrpc_requests = [mcp_jsonrpc_request(call, index + 1) for index, call in enumerate(executable_calls)]
    batch_tool_call = mcp_batch_position_call(executable_calls) if executable_calls else None
    batch_jsonrpc_request = mcp_jsonrpc_request(batch_tool_call, 1) if batch_tool_call else None
    bridge_requests = [altium_bridge_request(call) for call in executable_calls]
    batch_bridge_request = altium_bridge_batch_position_request(executable_calls) if executable_calls else None
    warnings = list(make_list(preflight.get("warnings")))
    if limited:
        warnings.append("live apply bundle was limited by --limit")
    if allowed_unreviewed:
        warnings.append("live apply bundle includes placements without accepted AI layout review")
    if not executable_calls:
        warnings.append("no executable live calls emitted")
    if not confirmed:
        warnings.append("dry run only; rerun with --confirm after review to mark the bundle executable")

    output_status = "dry-run"
    if confirmed and executable_calls:
        output_status = "ready-to-execute"
    elif confirmed:
        output_status = "no-executable-calls"

    return {
        "version": 1,
        "backend": "altium-pcb-live",
        "status": output_status,
        "execution_mode": "emit-only",
        "confirmed": confirmed,
        "summary": {
            "preflight_status": status,
            "requested_tool_calls": len(requested_calls),
            "executable_tool_calls": len(executable_calls),
            "batch_tool_calls": 1 if batch_tool_call else 0,
            "skipped_before_apply": len(preflight_skipped),
            "skipped_in_apply": len(skipped),
            "warnings": len(warnings),
        },
        "guards": {
            "requires_preflight_status": "ready",
            "allow_ready_with_warnings": allow_warnings,
            "board_outline_fixed": True,
            "locked_components_fixed": True,
            "additional_locked_refs": sorted(locked_refs),
            "ai_review_required": not allow_unreviewed,
            "allow_unreviewed_ai_review": allow_unreviewed,
            "coordinate_policy": coordinate_policy,
            "actual_execution": "not performed by this helper; execute batch_bridge_request through the embedded Altium live backend, or use jsonrpc_requests for MCP-compatible clients",
        },
        "coordinate_transform": preflight.get("coordinate_transform"),
        "warnings": warnings,
        "tool_calls": executable_calls,
        "bridge_requests": bridge_requests,
        "batch_bridge_request": batch_bridge_request,
        "jsonrpc_requests": jsonrpc_requests,
        "batch_tool_call": batch_tool_call,
        "batch_jsonrpc_request": batch_jsonrpc_request,
        "skipped": skipped,
        "preflight_skipped": preflight_skipped,
        "next_steps": [
            "Review live_apply.tool_calls and anchor calibration one last time.",
            "Prefer batch_bridge_request with the embedded backend set_component_positions command; otherwise execute bridge_requests sequentially.",
            "Refresh get_all_component_data after execution and compare final coordinates before routing or DRC.",
        ],
    }
