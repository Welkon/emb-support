#!/usr/bin/env python3
"""Conservative Altium PCB layout helper."""

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


FREE_SECTOR = 0xFFFFFFFF
END_OF_CHAIN = 0xFFFFFFFE
NO_STREAM = 0xFFFFFFFF
CFB_SIGNATURE = bytes([0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1])


def make_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def ensure_string(value: Any) -> str:
    return "" if value is None else str(value).strip()


def normalize_ref(value: Any) -> str:
    return ensure_string(value).upper()


def unique(values: Iterable[Any]) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        text = ensure_string(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def round_mm(value: Any) -> float:
    return round(float(value), 3)


def is_finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def clone_point(point: Optional[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    if not point:
        return None
    if not is_finite_number(point.get("x_mm")) or not is_finite_number(point.get("y_mm")):
        return None
    return {"x_mm": round_mm(point["x_mm"]), "y_mm": round_mm(point["y_mm"])}


def distance(a: Optional[Dict[str, Any]], b: Optional[Dict[str, Any]]) -> Optional[float]:
    if not a or not b:
        return None
    if not is_finite_number(a.get("x_mm")) or not is_finite_number(b.get("x_mm")):
        return None
    dx = float(a["x_mm"]) - float(b["x_mm"])
    dy = float(a["y_mm"]) - float(b["y_mm"])
    return math.sqrt(dx * dx + dy * dy)


def delta_point(from_point: Optional[Dict[str, Any]], to_point: Optional[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    if not from_point or not to_point:
        return None
    dist = distance(from_point, to_point) or 0.0
    return {
        "dx_mm": round_mm(float(to_point["x_mm"]) - float(from_point["x_mm"])),
        "dy_mm": round_mm(float(to_point["y_mm"]) - float(from_point["y_mm"])),
        "distance_mm": round_mm(dist),
    }


def is_power_net_name(name: Any) -> bool:
    return bool(
        re.match(
            r"^(?:gnd|ground|agnd|dgnd|pgnd|vss|vdd|vcc|vin|vbat|bat\+?|b\+|b-|3v3|3\.3v|5v|12v|24v|\+?\d+(?:\.\d+)?v)$",
            ensure_string(name),
            re.I,
        )
    )


def component_role(component: Dict[str, Any]) -> str:
    text = " ".join(
        [
            ensure_string(component.get("designator")),
            ensure_string(component.get("value")),
            ensure_string(component.get("footprint")),
        ]
    )
    ref = ensure_string(component.get("designator"))
    if re.match(r"^(?:U|IC|MCU)\d*", ref, re.I) or re.search(
        r"\b(?:mcu|microcontroller|stm32|sc8|pic|attiny|atmega|esp32)\b", text, re.I
    ):
        return "ic"
    if re.match(r"^C\d+", ref, re.I) or re.search(r"\b(?:capacitor|cap|\d+(?:\.\d+)?\s*(?:pf|nf|uf))\b", text, re.I):
        return "capacitor"
    if re.match(r"^(?:J|P|CN|CON|USB)\d*", ref, re.I) or re.search(r"\b(?:connector|header|usb)\b", text, re.I):
        return "connector"
    if re.match(r"^(?:Y|X)\d*", ref, re.I) or re.search(r"\b(?:crystal|oscillator|resonator)\b", text, re.I):
        return "clock"
    if re.match(r"^L\d+", ref, re.I) or re.search(r"\binductor\b", text, re.I):
        return "inductor"
    if re.match(r"^R\d+", ref, re.I):
        return "resistor"
    return ""


def truthy_locked_value(value: Any) -> bool:
    text = ensure_string(value).lower()
    return text in {"1", "true", "yes", "y", "locked", "fixed"}


def component_locked(component: Dict[str, Any]) -> bool:
    if not isinstance(component, dict):
        return False
    if component.get("locked") is True or truthy_locked_value(component.get("locked")):
        return True
    fields = component.get("fields") or component.get("raw_fields") or {}
    if not isinstance(fields, dict):
        fields = {}
    return any(
        truthy_locked_value(fields.get(key))
        for key in ["LOCKED", "LOCK", "ISLOCKED", "COMPLOCKED", "FIXED", "LOCKPRIMS", "PRIMITIVESLOCKED"]
    )


def parse_rotation_degrees(value: Any) -> float:
    text = re.sub(r"\s+", "", ensure_string(value))
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        match = re.search(r"[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?", text, re.I)
        return float(match.group(0)) if match else 0.0


def bounds_from_points(points: Iterable[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    valid = [
        point
        for point in points
        if point and is_finite_number(point.get("x_mm")) and is_finite_number(point.get("y_mm"))
    ]
    if not valid:
        return None
    xs = [float(point["x_mm"]) for point in valid]
    ys = [float(point["y_mm"]) for point in valid]
    return {
        "min_x_mm": round_mm(min(xs)),
        "min_y_mm": round_mm(min(ys)),
        "max_x_mm": round_mm(max(xs)),
        "max_y_mm": round_mm(max(ys)),
        "width_mm": round_mm(max(xs) - min(xs)),
        "height_mm": round_mm(max(ys) - min(ys)),
    }


def footprint_text_envelope_size(value: Any, source_name: str = "footprint-name") -> Optional[Dict[str, Any]]:
    footprint = ensure_string(value).upper()
    if not footprint:
        return None
    chip_sizes = {
        "0201": (0.6, 0.3),
        "0402": (1.0, 0.5),
        "0603": (1.6, 0.8),
        "0805": (2.0, 1.25),
        "1206": (3.2, 1.6),
        "1210": (3.2, 2.5),
        "1812": (4.5, 3.2),
        "2010": (5.0, 2.5),
        "2512": (6.3, 3.2),
    }
    chip_match = re.search(r"(?:^|[^0-9])(0201|0402|0603|0805|1206|1210|1812|2010|2512)(?:[^0-9]|$)", footprint)
    if chip_match:
        width, height = chip_sizes[chip_match.group(1)]
        return {"width_mm": width + 0.5, "height_mm": height + 0.5, "source": source_name, "confidence": "medium"}
    soic_match = re.search(r"\b(?:SOIC|SOP|SO)(\d+)\b", footprint)
    if soic_match:
        pins = int(soic_match.group(1))
        return {
            "width_mm": 10.2 if pins >= 14 else 6.2,
            "height_mm": 6.2 if pins >= 14 else 5.4,
            "source": source_name,
            "confidence": "medium",
        }
    if re.search(r"\bTSSOP(\d+)?\b", footprint):
        return {"width_mm": 6.8, "height_mm": 5.2, "source": source_name, "confidence": "medium"}
    if re.search(r"\bSOT[-_ ]?23(?:-\d+)?\b", footprint):
        return {"width_mm": 3.2, "height_mm": 2.2, "source": source_name, "confidence": "medium"}
    if re.search(r"\bSOT[-_ ]?89\b", footprint):
        return {"width_mm": 4.8, "height_mm": 4.5, "source": source_name, "confidence": "medium"}
    if re.search(r"\bTO[-_ ]?252|DPAK\b", footprint):
        return {"width_mm": 10.2, "height_mm": 7.2, "source": source_name, "confidence": "medium"}
    if re.search(r"\bUSB|TYPE[-_ ]?C\b", footprint):
        return {"width_mm": 10.5, "height_mm": 8.5, "source": source_name, "confidence": "medium"}
    if re.search(r"\b(?:XH|PH|ZH|HEADER|HDR|CONN|CONNECTOR)\b", footprint):
        pin_match = re.search(r"(?:X|P|PIN|HDR|HEADER)?(\d{1,2})(?:P|PIN)?", footprint)
        pins = max(2, int(pin_match.group(1))) if pin_match else 2
        return {
            "width_mm": min(30, max(6, pins * 2.54 + 2)),
            "height_mm": 6.5,
            "source": source_name,
            "confidence": "low",
        }
    return None


def fallback_envelope_size(component: Dict[str, Any]) -> Dict[str, Any]:
    role = component_role(component)
    if role == "connector":
        return {"width_mm": 9, "height_mm": 6, "source": "role-fallback", "confidence": "low"}
    if role == "ic":
        return {"width_mm": 7, "height_mm": 7, "source": "role-fallback", "confidence": "low"}
    if role == "inductor":
        return {"width_mm": 5, "height_mm": 5, "source": "role-fallback", "confidence": "low"}
    if role == "clock":
        return {"width_mm": 4, "height_mm": 2.5, "source": "role-fallback", "confidence": "low"}
    if role in {"capacitor", "resistor"}:
        return {"width_mm": 2.2, "height_mm": 1.4, "source": "role-fallback", "confidence": "low"}
    return {"width_mm": 4, "height_mm": 4, "source": "role-fallback", "confidence": "low"}


def merge_envelope_sizes(primary: Optional[Dict[str, Any]], secondary: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not primary:
        return secondary
    if not secondary:
        return primary
    return {
        **primary,
        "width_mm": max(float(primary["width_mm"]), float(secondary["width_mm"])),
        "height_mm": max(float(primary["height_mm"]), float(secondary["height_mm"])),
        "source": f"{primary.get('source', 'unknown')}+{secondary.get('source', 'unknown')}",
        "confidence": "medium" if primary.get("confidence") == "medium" or secondary.get("confidence") == "medium" else "low",
    }


def rotated_aabb_size(width_mm: Any, height_mm: Any, rotation: Any) -> Dict[str, float]:
    radians = abs(parse_rotation_degrees(rotation) % 180) * math.pi / 180
    cos_value = abs(math.cos(radians))
    sin_value = abs(math.sin(radians))
    return {
        "aabb_width_mm": round_mm(float(width_mm) * cos_value + float(height_mm) * sin_value),
        "aabb_height_mm": round_mm(float(width_mm) * sin_value + float(height_mm) * cos_value),
    }


def layer_key(value: Any) -> str:
    text = ensure_string(value).upper()
    return "B" if text == "B" or text.startswith("BOTTOM") else "F"


def is_through_hole_like(component: Dict[str, Any]) -> bool:
    footprint = ensure_string(component.get("footprint"))
    role = component_role(component)
    return role == "connector" or bool(re.search(r"\b(?:XH|PH|ZH|HEADER|HDR|CONN|CONNECTOR|DIP|SIP|TH|PTH|VS)\b", footprint, re.I))


def collision_layers(component: Dict[str, Any]) -> List[str]:
    return ["F", "B"] if is_through_hole_like(component) else [layer_key(component.get("layer"))]


def bounds_for_center(center: Optional[Dict[str, Any]], envelope: Optional[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    if not center or not envelope:
        return None
    half_width = float(envelope.get("aabb_width_mm") or envelope.get("width_mm") or 0) / 2
    half_height = float(envelope.get("aabb_height_mm") or envelope.get("height_mm") or 0) / 2
    return {
        "min_x_mm": round_mm(float(center["x_mm"]) - half_width),
        "min_y_mm": round_mm(float(center["y_mm"]) - half_height),
        "max_x_mm": round_mm(float(center["x_mm"]) + half_width),
        "max_y_mm": round_mm(float(center["y_mm"]) + half_height),
        "width_mm": round_mm(half_width * 2),
        "height_mm": round_mm(half_height * 2),
    }


def pad_envelope_size(component: Dict[str, Any], pads_by_ref: Dict[str, List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    pads = pads_by_ref.get(normalize_ref(component.get("designator")), [])
    points: List[Dict[str, Any]] = []
    for pad in pads:
        bounds = pad.get("bounds")
        if bounds:
            points.extend(
                [
                    {"x_mm": bounds.get("min_x_mm"), "y_mm": bounds.get("min_y_mm")},
                    {"x_mm": bounds.get("max_x_mm"), "y_mm": bounds.get("max_y_mm")},
                ]
            )
        elif pad.get("center"):
            points.append(pad["center"])
    pad_bounds = bounds_from_points(points)
    if not pad_bounds or len(pads) < 2:
        return None
    return {
        "width_mm": max(1, pad_bounds["width_mm"] + 0.4),
        "height_mm": max(1, pad_bounds["height_mm"] + 0.4),
        "source": "pad-size-bounds" if any(pad.get("bounds") for pad in pads) else "pad-center-bounds",
        "confidence": "medium",
        "pad_count": len(pads),
        "pad_bounds": pad_bounds,
    }


def body_envelope_size(component: Dict[str, Any], bodies_by_ref: Dict[str, List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    bodies = bodies_by_ref.get(normalize_ref(component.get("designator")), [])
    sizes = [footprint_text_envelope_size(body.get("model_name"), "component-body-model") for body in bodies]
    sizes = [size for size in sizes if size]
    if not sizes:
        return None
    best = sizes[0]
    for size in sizes[1:]:
        best = {
            "width_mm": max(float(best["width_mm"]), float(size["width_mm"])),
            "height_mm": max(float(best["height_mm"]), float(size["height_mm"])),
            "source": best["source"] if best["source"] == size["source"] else f"{best['source']}+{size['source']}",
            "confidence": "medium" if best.get("confidence") == "medium" or size.get("confidence") == "medium" else "low",
        }
    return {
        **best,
        "body_count": len(bodies),
        "model_names": unique(body.get("model_name") for body in bodies)[:4],
    }


def build_footprint_envelope(
    component: Dict[str, Any],
    pads_by_ref: Dict[str, List[Dict[str, Any]]],
    bodies_by_ref: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    size = merge_envelope_sizes(
        merge_envelope_sizes(pad_envelope_size(component, pads_by_ref), body_envelope_size(component, bodies_by_ref)),
        footprint_text_envelope_size(component.get("footprint"), "footprint-name"),
    ) or fallback_envelope_size(component)
    aabb = rotated_aabb_size(size["width_mm"], size["height_mm"], component.get("rotation"))
    center = clone_point(component.get("center"))
    envelope = {
        "width_mm": round_mm(size["width_mm"]),
        "height_mm": round_mm(size["height_mm"]),
        **aabb,
        "source": size.get("source"),
        "confidence": size.get("confidence"),
        "pad_count": size.get("pad_count", 0),
        "body_count": size.get("body_count", 0),
        "model_names": size.get("model_names", []),
        "pad_bounds": size.get("pad_bounds"),
        "collision_layers": collision_layers(component),
    }
    envelope["bounds"] = bounds_for_center(center, envelope)
    return envelope


def clamp_to_bounds(
    point: Optional[Dict[str, Any]],
    bounds: Optional[Dict[str, Any]],
    margin_mm: float,
    envelope: Optional[Dict[str, Any]],
) -> Optional[Dict[str, float]]:
    if not point or not bounds:
        return clone_point(point)
    margin = margin_mm if math.isfinite(float(margin_mm)) else 1.0
    half_width = float(envelope.get("aabb_width_mm") or envelope.get("width_mm") or 0) / 2 if envelope else 0
    half_height = float(envelope.get("aabb_height_mm") or envelope.get("height_mm") or 0) / 2 if envelope else 0
    min_x = float(bounds["min_x_mm"]) + margin + half_width
    max_x = float(bounds["max_x_mm"]) - margin - half_width
    min_y = float(bounds["min_y_mm"]) + margin + half_height
    max_y = float(bounds["max_y_mm"]) - margin - half_height
    if min_x > max_x or min_y > max_y:
        return clone_point(point)
    return {
        "x_mm": round_mm(min(max(float(point["x_mm"]), min_x), max_x)),
        "y_mm": round_mm(min(max(float(point["y_mm"]), min_y), max_y)),
    }


def expand_bounds(bounds: Optional[Dict[str, Any]], margin_mm: float) -> Optional[Dict[str, float]]:
    if not bounds:
        return None
    return {
        "min_x_mm": float(bounds["min_x_mm"]) - margin_mm,
        "min_y_mm": float(bounds["min_y_mm"]) - margin_mm,
        "max_x_mm": float(bounds["max_x_mm"]) + margin_mm,
        "max_y_mm": float(bounds["max_y_mm"]) + margin_mm,
    }


def rects_overlap(left: Optional[Dict[str, Any]], right: Optional[Dict[str, Any]]) -> bool:
    if not left or not right:
        return False
    return not (
        float(left["max_x_mm"]) <= float(right["min_x_mm"])
        or float(left["min_x_mm"]) >= float(right["max_x_mm"])
        or float(left["max_y_mm"]) <= float(right["min_y_mm"])
        or float(left["min_y_mm"]) >= float(right["max_y_mm"])
    )


def layers_overlap(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    left_layers = set(make_list(left.get("collision_layers")))
    return any(layer in left_layers for layer in make_list(right.get("collision_layers")))


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


def weighted_centroid(items: List[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    weighted = [item for item in items if item.get("point") and float(item.get("weight", 0)) > 0]
    total = sum(float(item["weight"]) for item in weighted)
    if total <= 0:
        return None
    return {
        "x_mm": round_mm(sum(float(item["point"]["x_mm"]) * float(item["weight"]) for item in weighted) / total),
        "y_mm": round_mm(sum(float(item["point"]["y_mm"]) * float(item["weight"]) for item in weighted) / total),
    }


def offset_near(anchor: Dict[str, Any], index: int, spacing_mm: float) -> Dict[str, float]:
    angle = (index % 8) * (math.pi / 4)
    return {
        "x_mm": round_mm(float(anchor["x_mm"]) + math.cos(angle) * spacing_mm),
        "y_mm": round_mm(float(anchor["y_mm"]) + math.sin(angle) * spacing_mm),
    }


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


def read_u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def read_u64(data: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


class Cfb:
    def __init__(self, data: bytearray):
        if len(data) < 512 or bytes(data[:8]) != CFB_SIGNATURE:
            raise ValueError("PcbDoc file does not look like an OLE compound file")
        self.data = data
        self.sector_size = 1 << read_u16(data, 30)
        self.mini_sector_size = 1 << read_u16(data, 32)
        self.num_fat_sectors = read_u32(data, 44)
        self.first_dir_sector = read_u32(data, 48)
        self.mini_stream_cutoff = read_u32(data, 56)
        self.first_difat_sector = read_u32(data, 68)
        self.num_difat_sectors = read_u32(data, 72)
        self.fat_entries = self._build_fat()
        self.entries = self._parse_directory_entries()
        roots = [entry for entry in self.entries if entry["type"] == 5]
        self.root_entry = roots[0] if roots else (self.entries[0] if self.entries else None)

    def _read_sector(self, sector_index: int) -> bytes:
        offset = (sector_index + 1) * self.sector_size
        end = offset + self.sector_size
        if offset < 0 or end > len(self.data):
            raise ValueError(f"CFB sector {sector_index} is outside file bounds")
        return bytes(self.data[offset:end])

    def _collect_difat_sector_ids(self) -> List[int]:
        difat: List[int] = []
        for index in range(109):
            sector_id = read_u32(self.data, 76 + index * 4)
            if sector_id != FREE_SECTOR:
                difat.append(sector_id)
        next_difat_sector = self.first_difat_sector
        remaining = self.num_difat_sectors
        max_entries = self.sector_size // 4 - 1
        while remaining > 0 and next_difat_sector not in {END_OF_CHAIN, FREE_SECTOR}:
            sector = self._read_sector(next_difat_sector)
            for index in range(max_entries):
                sector_id = read_u32(sector, index * 4)
                if sector_id != FREE_SECTOR:
                    difat.append(sector_id)
            next_difat_sector = read_u32(sector, self.sector_size - 4)
            remaining -= 1
        return difat[: self.num_fat_sectors]

    def _build_fat(self) -> List[int]:
        entries: List[int] = []
        for sector_id in self._collect_difat_sector_ids():
            sector = self._read_sector(sector_id)
            for offset in range(0, len(sector), 4):
                entries.append(read_u32(sector, offset))
        return entries

    def _read_chain(self, start_sector: int, expected_size: Optional[int] = None) -> bytes:
        if start_sector in {END_OF_CHAIN, FREE_SECTOR}:
            return b""
        seen = set()
        chunks = []
        current = start_sector
        while current not in {END_OF_CHAIN, FREE_SECTOR}:
            if current in seen:
                raise ValueError(f"CFB sector chain loop detected at sector {current}")
            if current >= len(self.fat_entries):
                raise ValueError(f"CFB sector {current} is outside FAT range")
            seen.add(current)
            chunks.append(self._read_sector(current))
            current = self.fat_entries[current]
        data = b"".join(chunks)
        return data[:expected_size] if expected_size is not None else data

    def _parse_directory_entries(self) -> List[Dict[str, Any]]:
        directory_data = self._read_chain(self.first_dir_sector)
        entries = []
        for offset in range(0, len(directory_data) - 127, 128):
            name_length = read_u16(directory_data, offset + 64)
            if name_length >= 2:
                name = directory_data[offset : offset + name_length - 2].decode("utf-16le", errors="ignore").rstrip("\x00")
            else:
                name = ""
            if not name:
                continue
            entries.append(
                {
                    "id": offset // 128,
                    "name": name,
                    "type": directory_data[offset + 66],
                    "left": read_u32(directory_data, offset + 68),
                    "right": read_u32(directory_data, offset + 72),
                    "child": read_u32(directory_data, offset + 76),
                    "starting_sector": read_u32(directory_data, offset + 116),
                    "size": read_u64(directory_data, offset + 120),
                }
            )
        return entries

    def _entry_by_id(self, entry_id: int) -> Optional[Dict[str, Any]]:
        return next((entry for entry in self.entries if entry["id"] == entry_id), None)

    def sorted_children(self, parent_id: int) -> List[Dict[str, Any]]:
        parent = self._entry_by_id(parent_id)
        result: List[Dict[str, Any]] = []

        def walk(entry_id: int) -> None:
            if entry_id == NO_STREAM:
                return
            entry = self._entry_by_id(entry_id)
            if not entry:
                return
            walk(entry["left"])
            result.append(entry)
            walk(entry["right"])

        if parent:
            walk(parent["child"])
        return result

    def find_entry_by_path(self, path: str) -> Optional[Dict[str, Any]]:
        if not self.root_entry:
            return None
        parts = [part for part in path.split("/") if part]
        if parts and parts[0] == self.root_entry["name"]:
            parts = parts[1:]
        current = self.root_entry
        for part in parts:
            current = next((entry for entry in self.sorted_children(current["id"]) if entry["name"] == part), None)
            if not current:
                return None
        return current

    def read_stream(self, entry: Dict[str, Any]) -> bytes:
        if not entry or entry["type"] != 2:
            raise ValueError("CFB entry is not a stream")
        if entry["size"] < self.mini_stream_cutoff:
            raise ValueError("CFB mini streams are not supported by this placement patcher")
        return self._read_chain(entry["starting_sector"], entry["size"])

    def stream_file_ranges(self, entry: Dict[str, Any]) -> List[Dict[str, int]]:
        if not entry or entry["type"] != 2:
            raise ValueError("CFB entry is not a stream")
        if entry["size"] < self.mini_stream_cutoff:
            raise ValueError("CFB mini streams cannot be patched in place")
        ranges = []
        seen = set()
        current = entry["starting_sector"]
        remaining = int(entry["size"])
        stream_offset = 0
        while current not in {END_OF_CHAIN, FREE_SECTOR} and remaining > 0:
            if current in seen:
                raise ValueError(f"CFB sector chain loop detected at sector {current}")
            if current >= len(self.fat_entries):
                raise ValueError(f"CFB sector {current} is outside FAT range")
            file_offset = (current + 1) * self.sector_size
            length = min(self.sector_size, remaining)
            ranges.append({"sector": current, "stream_offset": stream_offset, "file_offset": file_offset, "length": length})
            seen.add(current)
            stream_offset += length
            remaining -= length
            current = self.fat_entries[current]
        if remaining > 0:
            raise ValueError("CFB stream chain ended before declared stream size")
        return ranges


def build_record_chunks(stream: bytes) -> List[Dict[str, Any]]:
    records = []
    offset = 0
    while offset + 4 <= len(stream):
        length = read_u32(stream, offset)
        start = offset + 4
        end = start + length
        if length <= 0 or end > len(stream):
            break
        records.append(
            {
                "index": len(records),
                "offset": offset,
                "length": length,
                "start": start,
                "end": end,
                "text": stream[start:end].decode("latin1", errors="ignore"),
            }
        )
        offset = end
    return records


def locate_field_value(record_text: str, key: str) -> Optional[Dict[str, Any]]:
    match = re.search(rf"(^|\|){re.escape(key)}=([^|]*)", record_text)
    if not match:
        return None
    value_start = match.start() + len(match.group(1)) + len(key) + 1
    value = match.group(2)
    return {"start": value_start, "end": value_start + len(value), "value": value}


def parse_record_fields(record_text: str) -> Dict[str, str]:
    fields = {}
    for part in str(record_text or "").split("|"):
        separator = part.find("=")
        if separator <= 0:
            continue
        key = part[:separator].strip()
        value = re.sub(r"[\x00-\x1f]+$", "", part[separator + 1 :]).strip()
        if key:
            fields[key] = value
    return fields


def mm_to_mil(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number / 0.0254


def format_mil_for_original_length(mm: Any, original: str) -> Optional[str]:
    target_length = len(str(original or ""))
    mil = mm_to_mil(mm)
    if mil is None or target_length < 4:
        return None
    integer = f"{round(mil)}mil"
    if len(integer) <= target_length:
        return integer.rjust(target_length)
    max_numeric_length = target_length - 3
    if max_numeric_length <= 0:
        return None
    fixed0 = str(round(mil))
    if len(fixed0) <= max_numeric_length:
        return f"{fixed0.rjust(max_numeric_length)}mil"
    return None


def write_stream_bytes(file_data: bytearray, ranges: List[Dict[str, int]], stream_offset: int, data: bytes) -> None:
    remaining = len(data)
    source_offset = 0
    target_offset = stream_offset
    while remaining > 0:
        target_range = next(
            (
                item
                for item in ranges
                if target_offset >= item["stream_offset"] and target_offset < item["stream_offset"] + item["length"]
            ),
            None,
        )
        if not target_range:
            raise ValueError(f"Stream offset {target_offset} is outside CFB stream ranges")
        within_range = target_offset - target_range["stream_offset"]
        writable = min(remaining, target_range["length"] - within_range)
        file_offset = target_range["file_offset"] + within_range
        file_data[file_offset : file_offset + writable] = data[source_offset : source_offset + writable]
        source_offset += writable
        target_offset += writable
        remaining -= writable


def placement_maps(plan: Dict[str, Any]) -> Tuple[Dict[int, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    by_record = {}
    by_ref = {}
    for placement in make_list(plan.get("placements")):
        try:
            record = int(placement.get("source_record"))
            by_record[record] = placement
        except (TypeError, ValueError):
            pass
        ref = normalize_ref(placement.get("designator"))
        if ref:
            by_ref[ref] = placement
    return by_record, by_ref


def planned_placement_for_record(
    record: Dict[str, Any],
    fields: Dict[str, str],
    by_record: Dict[int, Dict[str, Any]],
    by_ref: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if record["index"] in by_record:
        return by_record[record["index"]]
    source_designator = normalize_ref(fields.get("SOURCEDESIGNATOR") or fields.get("DESIGNATOR") or fields.get("NAME") or fields.get("UNIQUEID"))
    return by_ref.get(source_designator) if source_designator else None


def should_skip_locked(fields: Dict[str, str], locked_refs: set, placement: Dict[str, Any]) -> bool:
    ref = normalize_ref(placement.get("designator"))
    if ref and ref in locked_refs:
        return True
    return component_locked({"fields": fields})


def resolve_output_path(input_path: Path, output: Optional[str], in_place: bool) -> Path:
    if in_place:
        return input_path
    if output:
        return Path(output).resolve()
    suffix = input_path.suffix or ".PcbDoc"
    return input_path.with_name(f"{input_path.stem}.placed{suffix}")


def apply_placement_plan_to_pcbdoc(input_path: Path, plan: Dict[str, Any], options: Dict[str, Any]) -> Dict[str, Any]:
    in_place = bool(options.get("in_place"))
    if in_place and options.get("confirm") is not True:
        raise ValueError("Refusing in-place PcbDoc update without --confirm")
    file_data = bytearray(input_path.read_bytes())
    cfb = Cfb(file_data)
    components_entry = cfb.find_entry_by_path("Root Entry/Components6/Data")
    if not components_entry:
        raise ValueError("PcbDoc Components6/Data stream was not found")
    ranges = cfb.stream_file_ranges(components_entry)
    stream = cfb.read_stream(components_entry)
    records = build_record_chunks(stream)
    by_record, by_ref = placement_maps(plan)
    locked_refs = {normalize_ref(item) for item in make_list(options.get("locked")) if normalize_ref(item)}
    patched = []
    skipped = []
    for record in records:
        fields = parse_record_fields(record["text"])
        placement = planned_placement_for_record(record, fields, by_record, by_ref)
        if not placement or not placement.get("suggested_center"):
            continue
        if placement.get("collision_status") == "unresolved":
            skipped.append({"designator": placement.get("designator", ""), "source_record": record["index"], "reason": "collision-unresolved"})
            continue
        if should_skip_locked(fields, locked_refs, placement):
            skipped.append({"designator": placement.get("designator", ""), "source_record": record["index"], "reason": "locked"})
            continue
        x_field = locate_field_value(record["text"], "X")
        y_field = locate_field_value(record["text"], "Y")
        if not x_field or not y_field:
            skipped.append({"designator": placement.get("designator", ""), "source_record": record["index"], "reason": "missing-x-y-fields"})
            continue
        suggested_center = placement["suggested_center"]
        next_x = format_mil_for_original_length(suggested_center.get("x_mm"), x_field["value"])
        next_y = format_mil_for_original_length(suggested_center.get("y_mm"), y_field["value"])
        if not next_x or not next_y or len(next_x) != len(x_field["value"]) or len(next_y) != len(y_field["value"]):
            skipped.append(
                {
                    "designator": placement.get("designator", ""),
                    "source_record": record["index"],
                    "reason": "coordinate-field-length-not-patchable",
                    "current": {"x": x_field["value"], "y": y_field["value"]},
                    "suggested_center": suggested_center,
                }
            )
            continue
        write_stream_bytes(file_data, ranges, record["start"] + x_field["start"], next_x.encode("latin1"))
        write_stream_bytes(file_data, ranges, record["start"] + y_field["start"], next_y.encode("latin1"))
        patched.append(
            {
                "designator": placement.get("designator", ""),
                "source_record": record["index"],
                "old_center": placement.get("old_center"),
                "suggested_center": suggested_center,
                "x": {"from": x_field["value"], "to": next_x.strip()},
                "y": {"from": y_field["value"], "to": next_y.strip()},
            }
        )

    output_path = resolve_output_path(input_path, options.get("output"), in_place)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(file_data)
    return {
        "status": "ok",
        "write_mode": "pcbdoc-in-place" if in_place else "pcbdoc-copy",
        "input": str(input_path),
        "output": str(output_path),
        "summary": {"requested": len(make_list(plan.get("placements"))), "patched": len(patched), "skipped": len(skipped)},
        "patched": patched,
        "skipped": skipped,
        "guarantees": {
            "patched_stream": "Root Entry/Components6/Data",
            "patch_mode": "in-place equal-length X/Y field replacement",
            "board_outline_modified": False,
            "routing_modified": False,
            "pads_modified": False,
            "nets_modified": False,
        },
    }


def parse_locked(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def unwrap_placement_plan(value: Dict[str, Any]) -> Dict[str, Any]:
    if "placement_plan" in value and isinstance(value["placement_plan"], dict):
        return value["placement_plan"]
    return value


def unwrap_mcp_export(value: Dict[str, Any]) -> Dict[str, Any]:
    if "mcp_export" in value and isinstance(value["mcp_export"], dict):
        return value["mcp_export"]
    return value


def unwrap_live_preflight(value: Dict[str, Any]) -> Dict[str, Any]:
    if "live_preflight" in value and isinstance(value["live_preflight"], dict):
        return value["live_preflight"]
    return value


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


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


def command_export_mcp(args: argparse.Namespace) -> Dict[str, Any]:
    plan = unwrap_placement_plan(read_json(Path(args.plan)))
    exported = export_altium_mcp_tool_calls(
        plan,
        {
            "locked": parse_locked(args.locked),
            "include_unresolved": args.include_unresolved,
            "include_rotation": args.include_rotation,
        },
    )
    if args.output:
        write_json(Path(args.output), exported)
        exported = {**exported, "artifacts": {"mcp_tool_calls": args.output}, "mcp_tool_calls_written": True}
    return {"command": "altium-pcb export-mcp", "mcp_export": exported}


def median(values: List[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def parse_json_text(value: str) -> Any:
    text = ensure_string(value)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


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
    for key in ["locked", "is_locked", "isLocked", "primitives_locked", "primitivesLocked"]:
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
        "backend": "altium-mcp",
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
        "next_steps": [
            "Review anchors and coordinate_transform before live apply.",
            "If status is blocked, refresh live component data or pass explicit --anchor refs that are fixed in both plan and Altium.",
            "Execute calibrated mcp_export.tool_calls only after confirming locked components remain skipped.",
        ],
    }


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
        },
    )
    if args.output:
        write_json(Path(args.output), preflight)
        preflight = {**preflight, "artifacts": {"live_preflight": args.output}, "live_preflight_written": True}
    return {"command": "altium-pcb preflight-live", "live_preflight": preflight}


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


def build_live_apply(preflight: Dict[str, Any], options: Dict[str, Any]) -> Dict[str, Any]:
    status = ensure_string(preflight.get("status"))
    allow_warnings = bool(options.get("allow_warnings"))
    confirmed = bool(options.get("confirm"))
    limit = int(options.get("limit") or 0)
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
    warnings = list(make_list(preflight.get("warnings")))
    if limited:
        warnings.append("live apply bundle was limited by --limit")
    if not confirmed:
        warnings.append("dry run only; rerun with --confirm after review to mark the bundle executable")

    return {
        "version": 1,
        "backend": "altium-mcp",
        "status": "ready-to-execute" if confirmed else "dry-run",
        "execution_mode": "emit-only",
        "confirmed": confirmed,
        "summary": {
            "preflight_status": status,
            "requested_tool_calls": len(requested_calls),
            "executable_tool_calls": len(executable_calls),
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
            "coordinate_policy": coordinate_policy,
            "actual_execution": "not performed by this helper; execute jsonrpc_requests or tool_calls through the MCP client",
        },
        "coordinate_transform": preflight.get("coordinate_transform"),
        "warnings": warnings,
        "tool_calls": executable_calls,
        "jsonrpc_requests": jsonrpc_requests,
        "skipped": skipped,
        "preflight_skipped": preflight_skipped,
        "next_steps": [
            "Review live_apply.tool_calls and anchor calibration one last time.",
            "Execute the JSON-RPC requests sequentially through an MCP client connected to the intended Altium board.",
            "Refresh get_all_component_data after execution and compare final coordinates before routing or DRC.",
        ],
    }


def command_apply_live(args: argparse.Namespace) -> Dict[str, Any]:
    preflight = unwrap_live_preflight(read_json(Path(args.preflight)))
    result = build_live_apply(
        preflight,
        {
            "locked": args.locked,
            "allow_warnings": args.allow_warnings,
            "confirm": args.confirm,
            "limit": args.limit,
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
    preflight_live.add_argument("--output", default="", help="Write calibrated preflight JSON to this path")
    preflight_live.set_defaults(func=command_preflight_live)

    apply_live = subparsers.add_parser("apply-live", help="prepare reviewed live altium-mcp placement execution")
    apply_live.add_argument("--preflight", required=True, help="JSON output from preflight-live")
    apply_live.add_argument("--locked", default="", help="Comma-separated designators to keep fixed")
    apply_live.add_argument("--allow-warnings", action="store_true", help="Allow ready-with-warnings preflight status")
    apply_live.add_argument("--limit", type=int, default=0, help="Limit emitted tool calls; 0 means no limit")
    apply_live.add_argument("--confirm", action="store_true", help="Mark the emitted bundle as reviewed and ready to execute")
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


if __name__ == "__main__":
    raise SystemExit(main())
