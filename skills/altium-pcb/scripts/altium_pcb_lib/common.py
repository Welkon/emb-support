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


def mm_to_mil(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number / 0.0254


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
