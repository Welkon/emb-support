"""The closed vocabulary of questions the skill can answer.

Every measurement item is a capability with two possible paths: a driver
query, or a fallback computed from the captured waveform. `advertised()`
exposes that table through `status`, so a caller knows what is answerable
before asking. A capability with neither path is a bug caught by the
architecture test, not a surprise on the bench.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    item: str
    fallback: str | None = None      # key produced by acquisition.stats()


MEASUREMENTS = {
    "vpp": Capability("vpp", "vpp"),
    "vmin": Capability("vmin", "vmin"),
    "vmax": Capability("vmax", "vmax"),
    "mean": Capability("mean", "mean"),
    "vavg": Capability("vavg", "mean"),
    "rms": Capability("rms", "rms"),
    "freq": Capability("freq", "freq"),
    "period": Capability("period", "period"),
    "duty": Capability("duty", "duty_pct"),
    "rise": Capability("rise", "rise_time"),
    "fall": Capability("fall", "fall_time"),
    "pulse_width": Capability("pulse_width", "max_high_s"),
    "negative_width": Capability("negative_width", "max_low_s"),
}

MEASURE_ITEMS = list(MEASUREMENTS)


def advertised(dialect) -> dict:
    """What this driver can answer, without touching the instrument."""
    measured, computed = [], []
    for item in MEASUREMENTS:
        (measured if dialect.measure_query(item, 1) else computed).append(item)
    return {
        "measurements": measured + computed,
        "measured": measured,
        "computed": computed,
        "screenshot": bool(dialect.screenshot_queries()),
        "pulse_trigger": bool(dialect.trigger_pulse(1e-6)),
    }
