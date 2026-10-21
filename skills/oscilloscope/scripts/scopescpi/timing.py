"""Edge-to-edge timing between two captured channels.

Supply/enable questions ("how long after CH2 rises does CH1 droop?") need a
cross-channel number, not two independent statistics. This is pure data math on
one record, so it works the same online and in `analyze`.
"""

from __future__ import annotations

import statistics


def _level(volts: list[float]) -> float:
    return (min(volts) + max(volts)) / 2


def _period(edges: list[float]) -> float | None:
    if len(edges) < 2:
        return None
    gaps = [b - a for a, b in zip(edges, edges[1:])]
    return statistics.median(gaps)


def edge_times(times: list[float], volts: list[float], direction: str = "rising",
               level: float | None = None, min_gap: float | None = None) -> list[float]:
    """Mid-level crossing times, debounced by half a sample interval."""
    if len(times) < 2:
        return []
    level = _level(volts) if level is None else level
    dt = (times[-1] - times[0]) / (len(times) - 1)
    gap = 0.5 * dt if min_gap is None else min_gap
    found: list[float] = []
    for i in range(1, len(times)):
        a, b = volts[i - 1], volts[i]
        crossed = (a < level <= b) if direction == "rising" else (a > level >= b)
        if not crossed:
            continue
        fraction = (level - a) / (b - a) if b != a else 0.0
        stamp = times[i - 1] + fraction * (times[i] - times[i - 1])
        if not found or stamp - found[-1] > gap:
            found.append(stamp)
    return found


def channel_timing(channel_a: dict, channel_b: dict, edge_a: str = "rising",
                   edge_b: str = "rising", level_a: float | None = None,
                   level_b: float | None = None) -> dict:
    """Pair the k-th edge of A with the k-th edge of B on one record."""
    times_a = edge_times(channel_a["times"], channel_a["volts"], edge_a, level_a)
    times_b = edge_times(channel_b["times"], channel_b["volts"], edge_b, level_b)
    period_a, period_b = _period(times_a), _period(times_b)
    window = 0.5 * min(p for p in (period_a, period_b) if p) if (period_a or period_b) else None

    if window and times_b:
        # Pair each A edge with the nearest B edge inside half a period, so a
        # leading edge in one channel does not shift every later pair.
        deltas = []
        for stamp in times_a:
            nearest = min(times_b, key=lambda other: abs(other - stamp))
            if abs(nearest - stamp) <= window:
                deltas.append(nearest - stamp)
    else:
        deltas = [times_b[i] - times_a[i]
                  for i in range(min(len(times_a), len(times_b)))]

    out: dict = {
        "edge_a": edge_a,
        "edge_b": edge_b,
        "a_edges": len(times_a),
        "b_edges": len(times_b),
        "pairs": len(deltas),
        "window_s": window,
        "unit": "s",
    }
    if deltas:
        out["delay"] = statistics.fmean(deltas)
        out["delay_min"] = min(deltas)
        out["delay_max"] = max(deltas)
        out["skew"] = statistics.pstdev(deltas) if len(deltas) > 1 else None
        if len(deltas) > 1:
            out["jitter_peak_to_peak"] = max(deltas) - min(deltas)
    return out
