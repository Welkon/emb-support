"""Waveform scaling, statistics and channel acquisition."""

from __future__ import annotations

import math
import time

from .capabilities import MEASUREMENTS, MEASURE_ITEMS
from .uncertainty import from_instrument, from_waveform

def to_volts(raw, meta: dict) -> list[float]:
    yincr, yorig, yref = meta["yincr"], meta["yorig"], meta["yref"]
    return [(float(b) - yref) * yincr + yorig for b in raw]


def to_times(meta: dict, n: int | None = None) -> list[float]:
    n = n or meta["points"]
    return [(i - meta["xref"]) * meta["xincr"] + meta["xorig"] for i in range(n)]


def stats(volts: list[float], times: list[float]) -> dict:
    if not volts:
        return {}
    n = len(volts)
    mean = sum(volts) / n
    rms = math.sqrt(sum(v * v for v in volts) / n)
    vmin, vmax = min(volts), max(volts)
    out = {"points": n, "vmin": vmin, "vmax": vmax, "vpp": vmax - vmin,
           "mean": mean, "rms": rms}
    if n > 2 and times:
        dt = (times[-1] - times[0]) / (n - 1)
        out["dt"] = dt
        mid = (vmin + vmax) / 2
        span = (vmax - vmin) * 0.5
        if span > 0:
            crossings = []
            for i in range(1, n):
                a, b = volts[i - 1], volts[i]
                if (a <= mid < b) or (a < mid <= b):
                    frac = (mid - a) / (b - a) if b != a else 0.0
                    t = times[i - 1] + frac * (times[i] - times[i - 1])
                    if not crossings or t - crossings[-1] > (times[1] - times[0]) * 0.5:
                        crossings.append(t)
            if len(crossings) >= 2:
                periods = [b - a for a, b in zip(crossings, crossings[1:])]
                period = sum(periods) / len(periods)
                if period > 0:
                    out["period"] = period
                    out["freq"] = 1.0 / period
            high = sum(1 for v in volts if v > mid) / n * 100.0
            out["duty_pct"] = high
            for key, above in (("max_high_s", True), ("max_low_s", False)):
                runs = [b - a for a, b in _level_runs(volts, times, mid, above)
                        if a > times[0] and b < times[-1]]
                if runs:
                    out[key] = max(runs)
            out.update(_edges(volts, times, vmin, vmax))
        if n >= 128:
            try:
                from .analysis import spectrum
                f0 = spectrum(volts, dt).get("fundamental_hz")
                if f0 and f0 > 0:
                    out["freq_crossing"] = out.get("freq")
                    out["period_crossing"] = out.get("period")
                    out["freq"] = f0
                    out["period"] = 1.0 / f0
            except RuntimeError:
                pass
    return out


def _level_runs(volts, times, level, above):
    """Time spans between mid-level crossings, on one side of the level.

    Runs that touch a window edge are excluded: a DC trace would otherwise
    report the whole record as one pulse.
    """
    runs, start = [], None
    inside = volts[0] >= level if above else volts[0] <= level
    if inside:
        start = times[0]
    for i in range(1, len(volts)):
        a, b = volts[i - 1], volts[i]
        now = b >= level if above else b <= level
        if now == inside:
            continue
        frac = (level - a) / (b - a) if b != a else 0.0
        t = times[i - 1] + frac * (times[i] - times[i - 1])
        if now:
            start = t
        elif start is not None:
            runs.append((start, t))
            start = None
        inside = now
    if start is not None:
        runs.append((start, times[-1]))
    return runs


def _edges(volts, times, vmin, vmax):
    """10-90% rise/fall of the first clean edge, with hysteresis."""
    vpp = vmax - vmin
    if vpp <= 0 or len(volts) < 3:
        return {}
    lo = vmin + 0.1 * vpp
    hi = vmin + 0.9 * vpp
    n = len(volts)

    def interp(i0, i1, level):
        v0, v1 = volts[i0], volts[i1]
        if v1 == v0:
            return times[i0]
        return times[i0] + (times[i1] - times[i0]) * (level - v0) / (v1 - v0)

    out = {}

    # Rising edge: arm below the low threshold, then wait for 90%.
    state = "low" if volts[0] < lo else "wait_low"
    start = None
    for i in range(1, n):
        if state == "wait_low":
            if volts[i] < lo:
                state = "low"
        elif state == "low":
            if volts[i - 1] < lo <= volts[i]:
                start = interp(i - 1, i, lo)
                state = "wait_hi"
        elif state == "wait_hi":
            if volts[i] >= hi:
                out["rise_time"] = interp(i - 1, i, hi) - start
                break
            if volts[i] < lo:
                state = "low"

    # Falling edge: arm above the high threshold, then wait for 10%.
    state = "high" if volts[0] > hi else "wait_high"
    start = None
    for i in range(1, n):
        if state == "wait_high":
            if volts[i] > hi:
                state = "high"
        elif state == "high":
            if volts[i - 1] > hi >= volts[i]:
                start = interp(i - 1, i, hi)
                state = "wait_lo"
        elif state == "wait_lo":
            if volts[i] <= lo:
                out["fall_time"] = interp(i - 1, i, lo) - start
                break
            if volts[i] > hi:
                state = "high"
    return out


def acquire_channels(inst, dialect, channels, points):
    result = {}
    scale = getattr(dialect, "to_volts", to_volts)
    for ch in channels:
        meta, raw = dialect.acquire(inst, ch, points)
        volts = scale(raw, meta)
        times = to_times(meta, len(volts))
        if not volts:
            # An empty transfer used to reach the caller as an empty list, where
            # min()/max() failed with "min() iterable argument is empty".
            raise RuntimeError(
                f"channel {ch} returned no samples. Check that the channel is on "
                f"(channel --ch {ch} --display on), that the trigger fires "
                f"(run --mode auto), and that --points is within the record length.")
        result[ch] = {"times": times, "volts": volts, "meta": meta}
    return result


def measure_channel_detailed(inst, dialect, ch, items):
    out = {}
    compute = []
    for item in items:
        q = dialect.measure_query(item, ch)
        if q:
            try:
                value = dialect.parse_measure(inst.query(q))
                if abs(value) > 1e30:      # Rigol and others use 9.9E+37 for "invalid"
                    raise ValueError("invalid measurement sentinel")
                out[item] = from_instrument(item, value)
                continue
            except Exception:
                pass
        compute.append(item)
    if compute:
        meta, raw = dialect.acquire(inst, ch, None)
        volts = getattr(dialect, "to_volts", to_volts)(raw, meta)
        times = to_times(meta, len(volts))
        st = stats(volts, times)
        for item in compute:
            cap = MEASUREMENTS.get(item)
            if cap and cap.fallback and cap.fallback in st:
                out[item] = from_waveform(item, st[cap.fallback], meta)
    return out


def measure_channel(inst, dialect, ch, items):
    return {item: result.value for item, result in
            measure_channel_detailed(inst, dialect, ch, items).items()}


# -------------------------------------------------------------------- commands


def _recover_step(inst, dialect, attempt, allow_autoset):
    try:
        if attempt == 0:
            inst.query("*OPC?")
            return "wait-opc"
        if attempt == 1:
            inst.write(dialect.run())
            try:
                inst.write(dialect.force_trigger())
            except Exception:
                pass
            return "run+force-trigger"
        if allow_autoset:
            inst.write(dialect.autoset())
            time.sleep(0.5)
            return "autoset"
    except Exception as e:  # noqa: BLE001
        return f"recovery failed: {type(e).__name__}: {e}"
    return "none"


def acquire_with_recovery(inst, dialect, channels, points,
                          attempts: int = 3, allow_autoset: bool = False):
    """Acquire channels, retrying with OPC wait / run+force / autoset."""
    log: list[dict] = []
    last: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            data = acquire_channels(inst, dialect, channels, points)
            empty = [ch for ch, item in data.items() if len(item["volts"]) < 2]
            if not empty:
                return data, log
            last = RuntimeError(f"empty waveform on channel(s) {empty}")
        except Exception as e:  # noqa: BLE001
            last = e
        if attempt + 1 < attempts:
            step = _recover_step(inst, dialect, attempt, allow_autoset)
            log.append({"attempt": attempt + 1,
                        "issue": f"{type(last).__name__}: {last}",
                        "recovery": step})
    if last is not None:
        text = str(last)
        if "TMO" in text or "timeout" in text.lower():
            raise RuntimeError(
                f"{last}. The waveform transfer timed out: retry with "
                "--acquire normal --points 1200 --timeout 30") from last
        raise last
    raise RuntimeError("acquisition failed")
