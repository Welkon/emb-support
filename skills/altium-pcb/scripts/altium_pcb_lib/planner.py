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


def resolve_collision(
    point: Dict[str, Any],
    envelope: Dict[str, Any],
    occupied: List[Dict[str, Any]],
    board_bounds: Optional[Dict[str, Any]],
    clearance_mm: float,
    edge_margin_mm: float,
) -> Dict[str, Any]:
    candidate = clamp_to_bounds(point, board_bounds, edge_margin_mm, envelope) or clone_point(point)
    for attempt in range(96):
        candidate_bounds = bounds_for_center(candidate, envelope)
        candidate_occupancy = {"bounds": candidate_bounds, "collision_layers": envelope.get("collision_layers", [])}
        collision = None
        for item in occupied:
            if layers_overlap(candidate_occupancy, item) and rects_overlap(
                expand_bounds(candidate_bounds, clearance_mm), expand_bounds(item.get("bounds"), clearance_mm)
            ):
                collision = item
                break
        if not collision:
            return {"center": candidate, "bounds": candidate_bounds, "collision": None, "unresolved": False}
        angle = attempt * 0.61803398875 * math.pi * 2
        step = clearance_mm + max(float(envelope.get("aabb_width_mm") or 0), float(envelope.get("aabb_height_mm") or 0)) / 2 + (attempt + 1) * 0.65
        candidate = clamp_to_bounds(
            {"x_mm": round_mm(float(point["x_mm"]) + math.cos(angle) * step), "y_mm": round_mm(float(point["y_mm"]) + math.sin(angle) * step)},
            board_bounds,
            edge_margin_mm,
            envelope,
        ) or candidate
    return {"center": candidate, "bounds": bounds_for_center(candidate, envelope), "collision": "unresolved", "unresolved": True}


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
        occupied.append(
            {
                "designator": component.get("designator"),
                "center": next_center,
                "bounds": resolved["bounds"],
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
                "confidence": "low" if resolved["unresolved"] else ("medium" if anchor_weighted else "low"),
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
            "warnings": len(warnings),
        },
        "placements": placements,
        "warnings": warnings,
        "next_steps": [
            "Review placement_plan.placements before applying to a PCB editor.",
            "Apply only to a copy unless the user explicitly accepts --in-place --confirm.",
            "Run DRC and manual mechanical review after any placement apply.",
        ],
    }
