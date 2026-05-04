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
from .footprints import *
from .geometry import *


def net_weight(net: str) -> float:
    return 0.35 if is_power_net_name(net) else 1.0


def build_component_net_map(pads: List[Dict[str, Any]]) -> Dict[str, set]:
    result: Dict[str, set] = {}
    for pad in pads:
        ref = normalize_ref(pad.get("component"))
        net = ensure_string(pad.get("net"))
        if ref and net:
            result.setdefault(ref, set()).add(net)
    return result


def build_pads_by_component(pads: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    result: Dict[str, List[Dict[str, Any]]] = {}
    for pad in pads:
        ref = normalize_ref(pad.get("component"))
        if ref and pad.get("center"):
            result.setdefault(ref, []).append(pad)
    return result


def build_bodies_by_component(bodies: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    result: Dict[str, List[Dict[str, Any]]] = {}
    for body in bodies:
        ref = normalize_ref(body.get("component"))
        if ref:
            result.setdefault(ref, []).append(body)
    return result


def build_net_component_map(component_nets: Dict[str, set]) -> Dict[str, set]:
    result: Dict[str, set] = {}
    for ref, nets in component_nets.items():
        for net in nets:
            result.setdefault(net, set()).add(ref)
    return result


def shared_nets_for(component: Dict[str, Any], component_nets: Dict[str, set], net_components: Dict[str, set]) -> List[Dict[str, str]]:
    ref = normalize_ref(component.get("designator"))
    result = []
    for net in component_nets.get(ref, set()):
        for other_ref in net_components.get(net, set()):
            if other_ref != ref:
                result.append({"net": net, "ref": other_ref})
    return result


def placement_reason(role: str, anchor_weighted: List[Dict[str, Any]], neighbor_weighted: List[Dict[str, Any]]) -> str:
    if role == "capacitor":
        return "place near connected IC or power anchor for local decoupling"
    if role == "clock":
        return "place near connected IC clock domain"
    if anchor_weighted:
        return "place near locked or mechanical anchor connected by nets"
    if neighbor_weighted:
        return "place near connected net neighbors"
    return "keep current position; no useful placement anchor was recognized"


def deterministic_placement_score(
    role: str,
    old_center: Optional[Dict[str, Any]],
    next_center: Optional[Dict[str, Any]],
    resolved: Dict[str, Any],
    envelope: Dict[str, Any],
    anchor_weighted: List[Dict[str, Any]],
    neighbor_weighted: List[Dict[str, Any]],
    board_bounds: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    penalties = []

    def add_penalty(name: str, value: float, reason: str) -> None:
        if value <= 0:
            return
        penalties.append({"name": name, "points": round(float(value), 1), "reason": reason})

    move_distance = distance(old_center, next_center) or 0.0
    envelope_confidence = ensure_string(envelope.get("confidence")) or "unknown"
    hard_gates = {
        "collision_clear": not bool(resolved.get("unresolved")),
        "board_outline_known": bool(board_bounds),
        "locked_components_fixed": True,
        "component_envelope_known": bool(envelope.get("width_mm") and envelope.get("height_mm")),
    }

    if resolved.get("unresolved"):
        add_penalty("collision", 80, "candidate still overlaps an occupied footprint envelope")
    if not board_bounds:
        add_penalty("missing-board-outline", 15, "candidate cannot be clipped to a recognized board outline")
    if not anchor_weighted:
        add_penalty("no-fixed-net-anchor", 12, "no fixed connected anchor was recognized")
    if not neighbor_weighted:
        add_penalty("no-net-neighbor", 8, "no connected neighbor position was recognized")
    if envelope_confidence == "low":
        add_penalty("low-envelope-confidence", 8, "footprint envelope came from low-confidence evidence")
    if role in {"capacitor", "clock"} and not anchor_weighted:
        add_penalty("role-anchor-missing", 10, "role normally needs a close fixed functional anchor")
    if move_distance > 20:
        add_penalty("large-move", min(30, (move_distance - 20) * 0.8 + 12), "candidate is far from the current local placement")
    elif move_distance > 8:
        add_penalty("medium-move", min(12, (move_distance - 8) * 0.5 + 4), "candidate changes local placement noticeably")

    total = max(0.0, min(100.0, 100.0 - sum(float(item["points"]) for item in penalties)))
    if not hard_gates["collision_clear"]:
        band = "blocked"
    elif total >= 80:
        band = "high"
    elif total >= 60:
        band = "medium"
    else:
        band = "low"

    return {
        "total": round(total, 1),
        "band": band,
        "hard_gates": hard_gates,
        "penalties": penalties,
        "metrics": {
            "move_distance_mm": round_mm(move_distance),
            "anchor_count": len(anchor_weighted),
            "neighbor_count": len(neighbor_weighted),
            "envelope_confidence": envelope_confidence,
            "collision_status": "unresolved" if resolved.get("unresolved") else "clear",
        },
        "note": "Deterministic geometry/connectivity score only; AI layout-intent review is still required before live apply.",
    }


def build_ai_review_request(
    component: Dict[str, Any],
    role: str,
    old_center: Optional[Dict[str, Any]],
    next_center: Optional[Dict[str, Any]],
    score: Dict[str, Any],
    anchor_weighted: List[Dict[str, Any]],
    neighbor_weighted: List[Dict[str, Any]],
    resolved: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "required": True,
        "status": "pending",
        "decision": "pending",
        "score": None,
        "reason": "AI layout-intent review required before export or live apply",
        "review_prompt": {
            "task": "Review this PCB placement candidate. Accept only if the move improves functional placement and preserves mechanical/DFM intent.",
            "accept_only_if": [
                "collision_status is clear and all hard_gates are satisfied",
                "the component is near the correct functional anchors or connected neighbors",
                "the move does not create an obviously poor routing path, awkward orientation, or mechanical conflict",
                "keeping the original local placement is not better than the suggested move",
            ],
            "reject_if": [
                "candidate is only a geometric escape point",
                "USB, connector, switch, edge, mounting, or through-hole keepout intent looks violated",
                "critical nets would become longer or cross functional blocks unnecessarily",
            ],
            "context": {
                "designator": component.get("designator"),
                "role": role,
                "footprint": component.get("footprint", ""),
                "old_center": old_center,
                "suggested_center": next_center,
                "deterministic_score": {"total": score.get("total"), "band": score.get("band")},
                "anchors": unique(anchor["ref"] for anchor in anchor_weighted)[:8],
                "neighbor_refs": unique(neighbor["ref"] for neighbor in neighbor_weighted)[:12],
                "collision_status": "unresolved" if resolved.get("unresolved") else "clear",
                "collision": resolved.get("collision"),
            },
        },
    }


def collision_summary(item: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not item:
        return None
    return {
        "designator": item.get("designator", ""),
        "bounds": item.get("bounds"),
        "collision_layers": make_list(item.get("collision_layers")),
    }


def resolve_collision(
    point: Dict[str, Any],
    envelope: Dict[str, Any],
    occupied: List[Dict[str, Any]],
    board_bounds: Optional[Dict[str, Any]],
    clearance_mm: float,
    edge_margin_mm: float,
) -> Dict[str, Any]:
    candidate = clamp_to_bounds(point, board_bounds, edge_margin_mm, envelope) or clone_point(point)
    last_collision = None

    def first_collision(center: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        candidate_bounds = bounds_for_center(center, envelope)
        candidate_occupancy = {"bounds": candidate_bounds, "collision_layers": envelope.get("collision_layers", [])}
        for item in occupied:
            if layers_overlap(candidate_occupancy, item) and rects_overlap(
                expand_bounds(candidate_bounds, clearance_mm), expand_bounds(item.get("bounds"), clearance_mm)
            ):
                return item, candidate_bounds
        return None, candidate_bounds

    for attempt in range(96):
        collision, candidate_bounds = first_collision(candidate)
        if not collision:
            return {"center": candidate, "bounds": candidate_bounds, "collision": None, "unresolved": False}
        last_collision = collision
        angle = attempt * 0.61803398875 * math.pi * 2
        step = clearance_mm + max(float(envelope.get("aabb_width_mm") or 0), float(envelope.get("aabb_height_mm") or 0)) / 2 + (attempt + 1) * 0.65
        candidate = clamp_to_bounds(
            {"x_mm": round_mm(float(point["x_mm"]) + math.cos(angle) * step), "y_mm": round_mm(float(point["y_mm"]) + math.sin(angle) * step)},
            board_bounds,
            edge_margin_mm,
            envelope,
        ) or candidate

    grid_candidates = []
    half_width = float(envelope.get("aabb_width_mm") or envelope.get("width_mm") or 0) / 2
    half_height = float(envelope.get("aabb_height_mm") or envelope.get("height_mm") or 0) / 2
    step = max(0.1, min(0.5, clearance_mm / 2))
    if board_bounds:
        min_x = float(board_bounds["min_x_mm"]) + edge_margin_mm + half_width
        max_x = float(board_bounds["max_x_mm"]) - edge_margin_mm - half_width
        min_y = float(board_bounds["min_y_mm"]) + edge_margin_mm + half_height
        max_y = float(board_bounds["max_y_mm"]) - edge_margin_mm - half_height
        if min_x <= max_x and min_y <= max_y:
            y = min_y
            while y <= max_y + 1e-9:
                x = min_x
                while x <= max_x + 1e-9:
                    grid_candidates.append({"x_mm": round_mm(x), "y_mm": round_mm(y)})
                    x += step
                y += step
    else:
        radius = max(float(envelope.get("aabb_width_mm") or 0), float(envelope.get("aabb_height_mm") or 0), 4.0) * 2
        min_x = float(point["x_mm"]) - radius
        max_x = float(point["x_mm"]) + radius
        min_y = float(point["y_mm"]) - radius
        max_y = float(point["y_mm"]) + radius
        y = min_y
        while y <= max_y + 1e-9:
            x = min_x
            while x <= max_x + 1e-9:
                grid_candidates.append({"x_mm": round_mm(x), "y_mm": round_mm(y)})
                x += step
            y += step

    grid_candidates.sort(key=lambda candidate_point: distance(candidate_point, point) or 0)
    for candidate_point in grid_candidates:
        collision, candidate_bounds = first_collision(candidate_point)
        if not collision:
            return {"center": candidate_point, "bounds": candidate_bounds, "collision": None, "unresolved": False}

    collision, candidate_bounds = first_collision(candidate)
    if not collision:
        return {"center": candidate, "bounds": candidate_bounds, "collision": None, "unresolved": False}
    last_collision = collision
    return {
        "center": candidate,
        "bounds": candidate_bounds,
        "collision": collision_summary(last_collision),
        "unresolved": True,
    }


def classify_components(components: List[Dict[str, Any]], locked_refs: set, anchor_connectors: bool) -> List[Dict[str, Any]]:
    result = []
    for component in components:
        ref = normalize_ref(component.get("designator"))
        role = component_role(component)
        explicitly_locked = ref in locked_refs
        parsed_locked = component_locked(component)
        mechanical_anchor = role == "connector" and anchor_connectors
        fixed = explicitly_locked or parsed_locked or mechanical_anchor
        reasons = []
        if explicitly_locked:
            reasons.append("user-locked")
        if parsed_locked:
            reasons.append("pcb-locked")
        if mechanical_anchor:
            reasons.append("connector-mechanical-anchor")
        result.append({"component": component, "ref": ref, "role": role, "fixed": fixed, "fixed_reasons": reasons})
    return result


def build_placement_plan(parsed: Dict[str, Any], options: Dict[str, Any]) -> Dict[str, Any]:
    locked_refs = {normalize_ref(item) for item in make_list(options.get("locked")) if normalize_ref(item)}
    limit = int(options.get("limit") or 200)
    clearance_mm = float(options.get("clearance_mm") if options.get("clearance_mm") is not None else 0.5)
    edge_margin_mm = float(options.get("edge_margin_mm") if options.get("edge_margin_mm") is not None else 1.0)
    anchor_connectors = options.get("anchor_connectors") is not False

    components = [component for component in make_list(parsed.get("components")) if component and component.get("center")]
    pads = make_list(parsed.get("pads"))
    component_bodies = make_list(parsed.get("component_bodies"))
    bounds = (parsed.get("board") or {}).get("bounds")
    component_nets = build_component_net_map(pads)
    pads_by_ref = build_pads_by_component(pads)
    bodies_by_ref = build_bodies_by_component(component_bodies)
    net_components = build_net_component_map(component_nets)
    by_ref = {normalize_ref(component.get("designator")): component for component in components}
    envelope_by_ref = {
        normalize_ref(component.get("designator")): build_footprint_envelope(component, pads_by_ref, bodies_by_ref)
        for component in components
    }
    classified = classify_components(components, locked_refs, anchor_connectors)
    fixed_refs = {item["ref"] for item in classified if item["fixed"]}
    fixed_components = []
    for item in classified:
        if not item["fixed"]:
            continue
        component = item["component"]
        envelope = envelope_by_ref[item["ref"]]
        center = clone_point(component.get("center"))
        fixed_components.append(
            {
                "designator": component.get("designator"),
                "source_record": component.get("source_record"),
                "unique_id": component.get("unique_id", ""),
                "role": item["role"],
                "center": center,
                "footprint": component.get("footprint", ""),
                "envelope": envelope,
                "bounds": bounds_for_center(center, envelope),
                "reasons": item["fixed_reasons"],
            }
        )
    occupied = [
        {
            "designator": item.get("designator"),
            "center": item.get("center"),
            "bounds": item.get("bounds"),
            "collision_layers": (item.get("envelope") or {}).get("collision_layers", ["F"]),
        }
        for item in fixed_components
        if item.get("center") and item.get("bounds")
    ]
    warnings = []
    if not bounds:
        warnings.append("board outline bounds were not recognized; placement suggestions cannot be clipped to the board outline")
    if not pads:
        warnings.append("no pad/net ownership was recognized; placement suggestions are based mostly on current component positions")

    order = {"ic": 10, "clock": 20, "capacitor": 30, "inductor": 40, "resistor": 50, "connector": 90}
    movable = sorted([item for item in classified if not item["fixed"]], key=lambda item: (order.get(item["role"], 60), item["ref"]))
    placements = []
    local_index = 0
    for item in movable:
        if len(placements) >= limit:
            break
        component = item["component"]
        shared = shared_nets_for(component, component_nets, net_components)
        anchor_weighted = []
        neighbor_weighted = []
        for edge in shared:
            other = by_ref.get(edge["ref"])
            if not other or not other.get("center"):
                continue
            weight = net_weight(edge["net"]) * (3 if edge["ref"] in fixed_refs else 1)
            target = {"ref": edge["ref"], "net": edge["net"], "point": other["center"], "weight": weight}
            neighbor_weighted.append(target)
            if edge["ref"] in fixed_refs:
                anchor_weighted.append(target)

        suggested = weighted_centroid(anchor_weighted) or weighted_centroid(neighbor_weighted) or clone_point(component.get("center"))
        if item["role"] in {"capacitor", "clock"} and anchor_weighted:
            suggested = offset_near(weighted_centroid(anchor_weighted), local_index, 4 if item["role"] == "clock" else 2.5)
            local_index += 1
        envelope = envelope_by_ref[item["ref"]]
        suggested = clamp_to_bounds(suggested, bounds, edge_margin_mm, envelope) or suggested
        resolved = resolve_collision(suggested, envelope, occupied, bounds, clearance_mm, edge_margin_mm)
        old_center = clone_point(component.get("center"))
        next_center = clone_point(resolved["center"])
        deterministic_score = deterministic_placement_score(
            item["role"],
            old_center,
            next_center,
            resolved,
            envelope,
            anchor_weighted,
            neighbor_weighted,
            bounds,
        )
        ai_review = build_ai_review_request(
            component,
            item["role"],
            old_center,
            next_center,
            deterministic_score,
            anchor_weighted,
            neighbor_weighted,
            resolved,
        )
        occupied_center = old_center if resolved["unresolved"] else next_center
        occupied_bounds = bounds_for_center(old_center, envelope) if resolved["unresolved"] else resolved["bounds"]
        occupied.append(
            {
                "designator": component.get("designator"),
                "center": occupied_center,
                "bounds": occupied_bounds,
                "collision_layers": envelope.get("collision_layers", ["F"]),
            }
        )
        placements.append(
            {
                "designator": component.get("designator"),
                "source_record": component.get("source_record"),
                "unique_id": component.get("unique_id", ""),
                "role": item["role"],
                "layer": component.get("layer", ""),
                "rotation": component.get("rotation", ""),
                "old_center": old_center,
                "suggested_center": next_center,
                "delta": delta_point(old_center, next_center),
                "footprint": component.get("footprint", ""),
                "footprint_envelope": {**envelope, "bounds": bounds_for_center(old_center, envelope)},
                "suggested_bounds": resolved["bounds"],
                "nets": unique(component_nets.get(item["ref"], set()))[:12],
                "reason": placement_reason(item["role"], anchor_weighted, neighbor_weighted),
                "anchors": unique(anchor["ref"] for anchor in anchor_weighted)[:8],
                "neighbor_refs": unique(neighbor["ref"] for neighbor in neighbor_weighted)[:12],
                "constraints": [
                    "board-outline-fixed",
                    "locked-components-fixed",
                    "skip-if-altium-component-locked",
                    "avoid-overlap-footprint-envelope",
                ],
                "collision_status": "unresolved" if resolved["unresolved"] else "clear",
                "collision": resolved.get("collision"),
                "confidence": "low" if resolved["unresolved"] else ("medium" if anchor_weighted else "low"),
                "deterministic_score": deterministic_score,
                "ai_review": ai_review,
            }
        )

    envelope_sources: Dict[str, int] = {}
    for envelope in envelope_by_ref.values():
        key = ensure_string(envelope.get("source")) or "unknown"
        envelope_sources[key] = envelope_sources.get(key, 0) + 1

    return {
        "version": 1,
        "status": "candidate-only",
        "write_mode": "analysis-only",
        "policy": {
            "modifies_pcbdoc": False,
            "board_outline_fixed": True,
            "locked_components_fixed": True,
            "requires_altium_review_before_apply": True,
            "requires_ai_review_before_live_apply": True,
        },
        "constraints": {
            "board_bounds": bounds,
            "locked": sorted(locked_refs),
            "fixed_components": fixed_components,
            "movable_components": [item["component"].get("designator") for item in movable],
            "clearance_mm": clearance_mm,
            "edge_margin_mm": edge_margin_mm,
            "connector_default": "fixed-mechanical-anchor" if anchor_connectors else "movable",
        },
        "summary": {
            "components": len(components),
            "pads": len(pads),
            "component_bodies": len(component_bodies),
            "footprint_envelopes": len(envelope_by_ref),
            "envelope_sources": envelope_sources,
            "fixed_components": len(fixed_components),
            "movable_components": len(movable),
            "placements": len(placements),
            "unresolved_collisions": len([item for item in placements if item["collision_status"] == "unresolved"]),
            "ai_review_required": len([item for item in placements if ai_review_required(item.get("ai_review"))]),
            "ai_review_pending": len([item for item in placements if ai_review_required(item.get("ai_review")) and not ai_review_accepted(item.get("ai_review"))]),
            "warnings": len(warnings),
        },
        "placements": placements,
        "warnings": warnings,
        "next_steps": [
            "Review placement_plan.placements before applying to a PCB editor.",
            "Populate placement.ai_review.decision=accepted only after AI layout-intent review passes.",
            "Apply only to a copy unless the user explicitly accepts --in-place --confirm.",
            "Run DRC and manual mechanical review after any placement apply.",
        ],
    }
