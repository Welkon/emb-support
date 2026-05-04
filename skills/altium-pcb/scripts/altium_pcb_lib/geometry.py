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


def rotated_aabb_size(width_mm: Any, height_mm: Any, rotation: Any) -> Dict[str, float]:
    radians = abs(parse_rotation_degrees(rotation) % 180) * math.pi / 180
    cos_value = abs(math.cos(radians))
    sin_value = abs(math.sin(radians))
    return {
        "aabb_width_mm": round_mm(float(width_mm) * cos_value + float(height_mm) * sin_value),
        "aabb_height_mm": round_mm(float(width_mm) * sin_value + float(height_mm) * cos_value),
    }


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
