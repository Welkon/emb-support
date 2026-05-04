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
from .geometry import bounds_for_center, bounds_from_points, rotated_aabb_size


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


def layer_key(value: Any) -> str:
    text = ensure_string(value).upper()
    return "B" if text == "B" or text.startswith("BOTTOM") else "F"


def is_through_hole_like(component: Dict[str, Any]) -> bool:
    footprint = ensure_string(component.get("footprint"))
    role = component_role(component)
    return role == "connector" or bool(re.search(r"\b(?:XH|PH|ZH|HEADER|HDR|CONN|CONNECTOR|DIP|SIP|TH|PTH|VS)\b", footprint, re.I))


def collision_layers(component: Dict[str, Any]) -> List[str]:
    return ["F", "B"] if is_through_hole_like(component) else [layer_key(component.get("layer"))]


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
