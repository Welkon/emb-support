"""Split a channel into bursts of activity and quiet gaps, then measure each one.

A PWM/LED product shows a mode change as a sequence of activity bursts; measuring
them one by one is what turns "it blinked three times" into numbers.
"""

from __future__ import annotations

import bisect
import statistics
from pathlib import Path

from .decode import transitions


def _ones(path: Path, start: int, stop: int) -> int:
    """Number of high samples in ``[start, stop)``."""
    if stop <= start:
        return 0
    first, last = start // 8, (stop - 1) // 8
    with path.open("rb") as handle:
        handle.seek(first)
        data = handle.read(last - first + 1)
    total = 0
    for offset, byte in enumerate(data):
        low = 8 * (first + offset)
        mask = 0xFF
        if low < start:
            mask &= (0xFF << (start - low)) & 0xFF
        if low + 8 > stop:
            mask &= (0xFF >> (low + 8 - stop)) & 0xFF
        total += (byte & mask).bit_count()
    return total


def _runs(edges: list[tuple[int, int]], gap_bits: int) -> list[tuple[int, int]]:
    """Group consecutive transition indices separated by at most ``gap_bits``."""
    if not edges:
        return []
    runs: list[list[int]] = [[edges[0][0], edges[0][0]]]
    for index, _level in edges[1:]:
        if index - runs[-1][1] > gap_bits:
            runs.append([index, index])
        else:
            runs[-1][1] = index
    return [(first, last) for first, last in runs]


def _profile(path: Path, first: int, last: int, windows: int = 20) -> list[float]:
    """Duty in ``windows`` equal slices, so a ramp is visible instead of averaged."""
    span = last - first + 1
    if span < windows * 2:
        return []
    step = span // windows
    return [round(100 * _ones(path, first + i * step, first + (i + 1) * step) / step, 2)
            for i in range(windows)]


def measure(path: str | Path, valid_bits: int, gap_bits: int,
            frequency_hz: int, limit: int = 50) -> dict:
    """Measure every burst wider than ``gap_bits`` samples of silence."""
    path = Path(path)
    edges = list(transitions(path, valid_bits))
    times = [index for index, _level in edges]
    levels = [level for _index, level in edges]
    out: list[dict] = []
    previous_end: int | None = None
    for first, last in _runs(edges, gap_bits)[:limit]:
        length = last - first + 1
        ones = _ones(path, first, last + 1)
        low = bisect.bisect_left(times, first)
        high = bisect.bisect_right(times, last)
        if high - low < 2:
            continue
        rising = [times[position] for position in range(max(low, 1), high)
                  if levels[position] == 1 and levels[position - 1] == 0]
        periods = [b - a for a, b in zip(rising, rising[1:])]
        item = {
            "startSample": first,
            "endSample": last,
            "startSeconds": round(first / frequency_hz, 9) if frequency_hz else None,
            "endSeconds": round(last / frequency_hz, 9) if frequency_hz else None,
            "durationMs": round(length / frequency_hz * 1000, 3) if frequency_hz else None,
            "samples": length,
            "edges": high - low,
            "dutyPercent": round(100 * ones / length, 3) if length else None,
        }
        if previous_end is not None and frequency_hz:
            item["gapMs"] = round((first - previous_end) / frequency_hz * 1000, 3)
        profile = _profile(path, first, last + 1)
        fine = _profile(path, first, last + 1, windows=200)
        if fine and max(fine) - min(fine) > 10:
            low = fine.index(min(fine))
            high = fine.index(max(fine))
            step = (last - first + 1) / len(fine)
            item["rampMs"] = round(abs(high - low) * step / frequency_hz * 1000, 2) if frequency_hz else None
            item["rampFromPercent"] = fine[low]
            item["rampToPercent"] = fine[high]
        if profile:
            item["dutyStartPercent"] = profile[0]
            item["dutyEndPercent"] = profile[-1]
            item["dutyMinPercent"] = min(profile)
            item["dutyMaxPercent"] = max(profile)
            item["dutyTrend"] = ("ramp-up" if profile[-1] - profile[0] > 10
                                 else "ramp-down" if profile[0] - profile[-1] > 10
                                 else "steady")
        if periods:
            item["periodSamples"] = statistics.median(periods)
            item["frequencyHz"] = round(frequency_hz / statistics.median(periods), 1)
        out.append(item)
        previous_end = last
    return {"bursts": out, "count": len(out)}
