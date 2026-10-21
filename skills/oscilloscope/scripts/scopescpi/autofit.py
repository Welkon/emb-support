"""Deterministic parameter fitting from a captured record.

The skill used to report CLIPPING / DC_OFFSET / ALIASING and leave the caller
to change scale, offset, timebase or trigger level and capture again. These
rules do that step: still plain control logic, no model, auditable in the
result as `adjustments`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields


@dataclass
class Adjustment:
    reason: str
    scale: float | None = None
    offset: float | None = None
    timebase: float | None = None
    trigger_level: float | None = None

    def as_dict(self) -> dict:
        out = {"reason": self.reason}
        for item in fields(self):
            if item.name == "reason":
                continue
            value = getattr(self, item.name)
            if value is not None:
                out[item.name] = value
        return out


def snap(value: float | None) -> float | None:
    """Snap to the 1-2-5 sequence most front ends accept."""
    if not value or value <= 0:
        return None
    exponent = math.floor(math.log10(value))
    fraction = value / 10 ** exponent
    step = 1 if fraction < 1.5 else 2 if fraction < 3.5 else 5 if fraction < 7.5 else 10
    return step * 10 ** exponent


def level_for(stats: dict) -> float:
    """Mid-level of the captured record, rounded to a stable trigger level."""
    return round(stats["vmin"] + 0.5 * stats["vpp"], 6)


def suggest(stats: dict, quality: list[dict], *, scale: float | None,
            timebase: float | None, offset_for_center,
            trigger_level: float | None = None) -> Adjustment | None:
    codes = {item["code"] for item in quality}
    vpp = stats.get("vpp") or 0.0
    center = (stats.get("vmin", 0.0) + stats.get("vmax", 0.0)) / 2
    reasons: list[str] = []
    new_scale = new_offset = new_timebase = new_level = None

    if "CLIPPING" in codes and scale:
        reasons.append("clipping: coarser vertical scale")
        new_scale = snap(scale * 2)
        new_offset = round(offset_for_center(center), 6)
    elif "LOW_RESOLUTION" in codes and scale and vpp > 0:
        target = snap(vpp / 5.0)
        if target and target < scale:
            reasons.append("low resolution: finer vertical scale")
            new_scale = target
            new_offset = round(offset_for_center(center), 6)

    if "DC_OFFSET" in codes and not reasons:
        reasons.append("large DC offset: center the trace")
        new_offset = round(offset_for_center(center), 6)

    period = stats.get("period")
    if period:
        if "ALIASING" in codes:
            reasons.append("aliasing: faster timebase")
            new_timebase = snap(period * 0.25)
        elif timebase:
            wanted = snap(period * 2.5 / 10)
            # Only fix the case that matters: fewer than two periods on screen.
            if wanted and timebase * 10 < period * 2:
                reasons.append("timebase shows too few periods")
                new_timebase = wanted

    if trigger_level is not None and vpp > 0:
        mid = stats["vmin"] + 0.5 * vpp
        if abs(trigger_level - mid) > 0.5 * vpp:
            reasons.append("trigger level is outside the signal")
            new_level = round(mid, 6)

    if not reasons:
        return None
    return Adjustment("; ".join(reasons), new_scale, new_offset,
                      new_timebase, new_level)


def apply_to_plan(plan, adjustment: Adjustment, target: int) -> None:
    """Mutate a Plan in place; the Executor applies it on the next attempt."""
    from .plan import ChannelSetup, TriggerSetup

    channel = next((item for item in plan.channels if item.n == target), None)
    if channel is None:
        channel = ChannelSetup(target)
        plan.channels.append(channel)
    if adjustment.scale is not None:
        channel.scale = adjustment.scale
    if adjustment.offset is not None:
        channel.offset = adjustment.offset
    if adjustment.timebase is not None:
        plan.timebase = adjustment.timebase
    if adjustment.trigger_level is not None:
        if plan.trigger is None:
            plan.trigger = TriggerSetup()
        plan.trigger.level = adjustment.trigger_level
