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
from .live import build_live_apply, build_live_preflight
from .mcp import export_altium_mcp_tool_calls
from .pcbdoc import apply_placement_plan_to_pcbdoc
from .planner import build_placement_plan


def command_plan(args: argparse.Namespace) -> Dict[str, Any]:
    parsed = read_json(Path(args.parsed))
    plan = build_placement_plan(
        parsed,
        {
            "locked": parse_locked(args.locked),
            "limit": args.limit,
            "clearance_mm": args.clearance_mm,
            "edge_margin_mm": args.edge_margin_mm,
            "anchor_connectors": not args.no_anchor_connectors,
        },
    )
    if args.output:
        write_json(Path(args.output), plan)
        plan = {**plan, "artifacts": {"placement_plan": args.output}, "placement_plan_written": True}
    return {"command": "altium-pcb plan", "placement_plan": plan}


def command_apply(args: argparse.Namespace) -> Dict[str, Any]:
    plan = unwrap_placement_plan(read_json(Path(args.plan)))
    result = apply_placement_plan_to_pcbdoc(
        Path(args.file).resolve(),
        plan,
        {"output": args.output, "in_place": args.in_place, "confirm": args.confirm, "locked": parse_locked(args.locked)},
    )
    return {"command": "altium-pcb apply", "apply_result": result, "artifacts": {"pcbdoc": result["output"]}}


def command_export_mcp(args: argparse.Namespace) -> Dict[str, Any]:
    plan = unwrap_placement_plan(read_json(Path(args.plan)))
    exported = export_altium_mcp_tool_calls(
        plan,
        {
            "locked": parse_locked(args.locked),
            "include_unresolved": args.include_unresolved,
            "include_rotation": args.include_rotation,
            "allow_unreviewed": args.allow_unreviewed,
        },
    )
    if args.output:
        write_json(Path(args.output), exported)
        exported = {**exported, "artifacts": {"mcp_tool_calls": args.output}, "mcp_tool_calls_written": True}
    return {"command": "altium-pcb export-mcp", "mcp_export": exported}


def command_preflight_live(args: argparse.Namespace) -> Dict[str, Any]:
    plan = unwrap_placement_plan(read_json(Path(args.plan)))
    live_data = read_json(Path(args.live_components))
    preflight = build_live_preflight(
        plan,
        live_data,
        {
            "locked": args.locked,
            "anchors": args.anchor,
            "tolerance_mil": args.tolerance_mil,
            "include_unresolved": args.include_unresolved,
            "include_rotation": args.include_rotation,
            "allow_unreviewed": args.allow_unreviewed,
        },
    )
    if args.output:
        write_json(Path(args.output), preflight)
        preflight = {**preflight, "artifacts": {"live_preflight": args.output}, "live_preflight_written": True}
    return {"command": "altium-pcb preflight-live", "live_preflight": preflight}


def command_apply_live(args: argparse.Namespace) -> Dict[str, Any]:
    preflight = unwrap_live_preflight(read_json(Path(args.preflight)))
    result = build_live_apply(
        preflight,
        {
            "locked": args.locked,
            "allow_warnings": args.allow_warnings,
            "confirm": args.confirm,
            "limit": args.limit,
            "allow_unreviewed": args.allow_unreviewed,
        },
    )
    if args.output:
        write_json(Path(args.output), result)
        result = {**result, "artifacts": {"live_apply": args.output}, "live_apply_written": True}
    return {"command": "altium-pcb apply-live", "live_apply": result}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Conservative Altium PCB layout helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="generate a placement plan from parsed board layout JSON")
    plan.add_argument("--parsed", required=True, help="Path to analysis.board-layout.json from emb-agent ingest board")
    plan.add_argument("--locked", default="", help="Comma-separated designators to keep fixed")
    plan.add_argument("--limit", type=int, default=200, help="Maximum number of movable placements to emit")
    plan.add_argument("--clearance-mm", type=float, default=0.5, help="Same-layer envelope clearance")
    plan.add_argument("--edge-margin-mm", type=float, default=1.0, help="Board edge margin")
    plan.add_argument("--no-anchor-connectors", action="store_true", help="Do not treat connectors as fixed mechanical anchors")
    plan.add_argument("--output", default="", help="Write plan JSON to this path")
    plan.set_defaults(func=command_plan)

    apply_cmd = subparsers.add_parser("apply", help="apply a placement plan to a PcbDoc copy")
    apply_cmd.add_argument("--file", required=True, help="Input .PcbDoc path")
    apply_cmd.add_argument("--plan", required=True, help="Placement plan JSON path")
    apply_cmd.add_argument("--locked", default="", help="Comma-separated designators to keep fixed")
    apply_cmd.add_argument("--output", default="", help="Output .PcbDoc path; defaults to <input>.placed.PcbDoc")
    apply_cmd.add_argument("--in-place", action="store_true", help="Overwrite input .PcbDoc")
    apply_cmd.add_argument("--confirm", action="store_true", help="Required with --in-place")
    apply_cmd.set_defaults(func=command_apply)

    export_mcp = subparsers.add_parser("export-mcp", help="export a placement plan as altium-mcp tool-call JSON")
    export_mcp.add_argument("--plan", required=True, help="Placement plan JSON path")
    export_mcp.add_argument("--locked", default="", help="Comma-separated designators to keep fixed")
    export_mcp.add_argument("--include-unresolved", action="store_true", help="Include placements with unresolved collisions")
    export_mcp.add_argument("--include-rotation", action="store_true", help="Send plan rotation instead of keeping live rotation")
    export_mcp.add_argument("--allow-unreviewed", action="store_true", help="Export placements without accepted AI layout review")
    export_mcp.add_argument("--output", default="", help="Write altium-mcp tool-call JSON to this path")
    export_mcp.set_defaults(func=command_export_mcp)

    preflight_live = subparsers.add_parser("preflight-live", help="calibrate altium-mcp placement calls against live component data")
    preflight_live.add_argument("--plan", required=True, help="Placement plan JSON path")
    preflight_live.add_argument("--live-components", required=True, help="JSON output from altium-mcp get_all_component_data")
    preflight_live.add_argument("--locked", default="", help="Comma-separated designators to keep fixed")
    preflight_live.add_argument("--anchor", default="", help="Comma-separated fixed designators to use as coordinate anchors")
    preflight_live.add_argument("--tolerance-mil", type=float, default=10.0, help="Maximum allowed anchor offset disagreement")
    preflight_live.add_argument("--include-unresolved", action="store_true", help="Include placements with unresolved collisions")
    preflight_live.add_argument("--include-rotation", action="store_true", help="Send plan rotation instead of keeping live rotation")
    preflight_live.add_argument("--allow-unreviewed", action="store_true", help="Preflight placements without accepted AI layout review")
    preflight_live.add_argument("--output", default="", help="Write calibrated preflight JSON to this path")
    preflight_live.set_defaults(func=command_preflight_live)

    apply_live = subparsers.add_parser("apply-live", help="prepare reviewed live altium-mcp placement execution")
    apply_live.add_argument("--preflight", required=True, help="JSON output from preflight-live")
    apply_live.add_argument("--locked", default="", help="Comma-separated designators to keep fixed")
    apply_live.add_argument("--allow-warnings", action="store_true", help="Allow ready-with-warnings preflight status")
    apply_live.add_argument("--limit", type=int, default=0, help="Limit emitted tool calls; 0 means no limit")
    apply_live.add_argument("--confirm", action="store_true", help="Mark the emitted bundle as reviewed and ready to execute")
    apply_live.add_argument("--allow-unreviewed", action="store_true", help="Emit live calls without accepted AI layout review")
    apply_live.add_argument("--output", default="", help="Write live apply bundle JSON to this path")
    apply_live.set_defaults(func=command_apply_live)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
    except Exception as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
