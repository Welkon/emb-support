"""Heuristic signal-quality checks with actionable suggestions."""

from __future__ import annotations


def check(volts: list[float], times: list[float] | None = None,
          meta: dict | None = None) -> list[dict]:
    warnings: list[dict] = []
    n = len(volts)
    if n < 2:
        return [{"code": "EMPTY", "severity": "error",
                 "message": "waveform has fewer than 2 samples",
                 "suggestion": "check the probe, channel enable, and trigger"}]

    vmin, vmax = min(volts), max(volts)
    vpp = vmax - vmin
    mean = sum(volts) / n
    yincr = (meta or {}).get("yincr") or 0
    xincr = (meta or {}).get("xincr") or 0

    if vpp <= max(1e-9, abs(mean) * 1e-4):
        warnings.append({"code": "FLAT", "severity": "warning",
                         "message": f"signal is flat (Vpp={vpp:.6g} V)",
                         "suggestion": "check probe connection, channel display, and trigger source"})
    else:
        if abs(mean) > 0.5 * vpp:
            warnings.append({"code": "DC_OFFSET", "severity": "info",
                             "message": f"large DC offset (mean={mean:.4g} V, Vpp={vpp:.4g} V)",
                             "suggestion": "use AC coupling or adjust the vertical offset"})

        at_rail = sum(1 for v in volts if v == vmin or v == vmax)
        unique = len(set(volts))
        if vpp > 0 and at_rail / n > 0.02 and unique > 8:
            warnings.append({"code": "CLIPPING", "severity": "warning",
                             "message": f"{at_rail * 100 / n:.1f}% of samples sit on the extreme values",
                             "suggestion": "increase volts/div or check probe attenuation; the signal may be clipped"})

        if yincr and vpp < 20 * yincr:
            warnings.append({"code": "LOW_RESOLUTION", "severity": "info",
                             "message": f"signal spans only {vpp / yincr:.1f} ADC codes",
                             "suggestion": "decrease volts/div to use more of the ADC range"})

        if xincr and times:
            st = _stats_freq(volts, times)
            freq = st.get("freq")
            if freq and freq > 0.45 / xincr:
                warnings.append({"code": "ALIASING", "severity": "warning",
                                 "message": f"measured {freq:.4g} Hz is near the Nyquist limit ({0.5 / xincr:.4g} Hz)",
                                 "suggestion": "decrease the timebase (faster sample rate) or enable peak detect"})

    return warnings


def _stats_freq(volts, times):
    """Local copy of the crossing estimator to avoid a circular import."""
    n = len(volts)
    vmin, vmax = min(volts), max(volts)
    mid = (vmin + vmax) / 2
    crossings = []
    for i in range(1, n):
        a, b = volts[i - 1], volts[i]
        if (a <= mid < b) or (a < mid <= b):
            frac = (mid - a) / (b - a) if b != a else 0.0
            t = times[i - 1] + frac * (times[i] - times[i - 1])
            if not crossings or t - crossings[-1] > (times[1] - times[0]) * 0.5:
                crossings.append(t)
    if len(crossings) >= 2:
        period = (crossings[-1] - crossings[0]) / (len(crossings) - 1)
        if period > 0:
            return {"period": period, "freq": 1.0 / period}
    return {}
