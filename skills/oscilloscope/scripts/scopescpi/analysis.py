"""Advanced waveform analysis and dependency-free SVG plotting."""

from __future__ import annotations

import math
from pathlib import Path


def _np():
    try:
        import numpy as np
        return np
    except ImportError:
        return None


def advanced(volts: list[float], times: list[float], meta: dict | None = None) -> dict:
    """Overshoot, noise, crest factor and optional spectrum."""
    n = len(volts)
    out: dict = {}
    if n < 4:
        return out
    vmin, vmax = min(volts), max(volts)
    vpp = vmax - vmin
    mean = sum(volts) / n
    rms = math.sqrt(sum(v * v for v in volts) / n)
    if rms:
        out["crest_factor"] = max(abs(vmin), abs(vmax)) / rms

    mid = (vmin + vmax) / 2
    high = [v for v in volts if v >= mid]
    low = [v for v in volts if v < mid]
    top = sum(high) / len(high) if high else vmax
    base = sum(low) / len(low) if low else vmin
    amp = top - base
    if amp > 0:
        out["top"] = top
        out["base"] = base
        out["overshoot_pct"] = max(0.0, (vmax - top) / amp * 100)
        out["undershoot_pct"] = max(0.0, (base - vmin) / amp * 100)

    # Noise estimate: residual after subtracting a 5-sample moving average.
    if n >= 9:
        smooth = [(volts[max(0, i - 2)] + volts[max(0, i - 1)] + volts[i]
                   + volts[min(n - 1, i + 1)] + volts[min(n - 1, i + 2)]) / 5
                  for i in range(n)]
        out["noise_rms"] = math.sqrt(sum((v - s) ** 2 for v, s in zip(volts, smooth)) / n)

    dt = (meta or {}).get("xincr") or (times[1] - times[0] if len(times) > 1 else 0)
    if dt > 0:
        try:
            out.update(spectrum(volts, dt))
        except RuntimeError as e:
            out["fft_error"] = str(e)
    return out


def classify(volts: list[float], times: list[float], stats: dict,
             analysis: dict) -> dict:
    """Classify the dominant waveform from duty, rails, harmonics and THD."""
    if not volts:
        return {"type": "empty"}
    vmin, vmax = min(volts), max(volts)
    vpp = vmax - vmin
    if vpp <= 1e-9:
        return {"type": "dc", "confidence": "high"}
    tol = 0.05 * vpp
    rail = sum(1 for v in volts if v <= vmin + tol or v >= vmax - tol) / len(volts)
    duty = stats.get("duty_pct")
    thd = analysis.get("thd_pct")
    harmonics = analysis.get("harmonics") or []
    even = harmonics[0]["relative"] if harmonics and harmonics[0]["order"] == 2 else 0.0
    result = {"type": "unknown", "confidence": "low"}
    if even > 0.25:
        result = {"type": "sawtooth", "confidence": "medium"}
    elif thd is not None and thd < 5 and rail < 0.35:
        result = {"type": "sine", "confidence": "high"}
    elif thd is not None and 8 <= thd <= 20 and rail < 0.2:
        result = {"type": "triangle", "confidence": "medium"}
    elif rail > 0.35 and duty is not None and 40 <= duty <= 60 and (thd or 0) > 20:
        result = {"type": "square", "confidence": "high"}
    elif duty is not None and (duty < 40 or duty > 60):
        result = {"type": "pulse", "confidence": "medium"}
    elif rail > 0.3:
        result = {"type": "pulse", "confidence": "low"}
    return result


def spectrum(volts: list[float], dt: float, harmonics: int = 5) -> dict:
    np = _np()
    if np is None:
        raise RuntimeError("FFT requires numpy; run: scope.py setup")
    x = np.asarray(volts, dtype=float)
    x = x - x.mean()
    n = len(x)
    if n < 8:
        return {}
    window = np.hanning(n)
    mag = np.abs(np.fft.rfft(x * window))
    freqs = np.fft.rfftfreq(n, d=dt)
    if len(mag) > 1:
        mag[0] = 0.0
    k = int(np.argmax(mag))
    if k == 0 or mag[k] == 0:
        return {}
    f0 = float(freqs[k])
    fundamental = float(mag[k])
    result = {"fundamental_hz": f0, "peak_bin": k}
    harmonic_energy = 0.0
    found = []
    for h in range(2, harmonics + 1):
        idx = int(round(f0 * h * n * dt))
        if 0 < idx < len(mag):
            amp = float(mag[idx])
            found.append({"order": h, "hz": f0 * h, "relative": amp / fundamental if fundamental else 0})
            harmonic_energy += amp * amp
    if found:
        result["harmonics"] = found
        result["thd_pct"] = math.sqrt(harmonic_energy) / fundamental * 100 if fundamental else None
    return result


def decimate(times: list[float], volts: list[float], target: int = 4000):
    n = len(volts)
    if n <= target:
        return times, volts
    step = max(1, n // target)
    return times[::step], volts[::step]


def write_svg(path: Path, times: list[float], volts: list[float],
              title: str = "waveform", extra: dict | None = None,
              width: int = 1000, height: int = 420,
              max_points: int = 4000) -> None:
    """Dependency-free SVG plot with axes and min/max markers."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    times, volts = decimate(times, volts, max(2, min(max_points, width * 2)))
    n = len(volts)
    if n < 2:
        raise ValueError("not enough samples to plot")
    vmin, vmax = min(volts), max(volts)
    t0, t1 = times[0], times[-1]
    span = (vmax - vmin) or 1.0
    left, right, top, bottom = 60, width - 20, 40, height - 50

    def px(t):
        return left + (t - t0) / ((t1 - t0) or 1.0) * (right - left)

    def py(v):
        return bottom - (v - vmin) / span * (bottom - top)

    points = " ".join(f"{px(t):.1f},{py(v):.1f}" for t, v in zip(times, volts))
    stats_line = f"Vpp {vmax - vmin:.4g} V | min {vmin:.4g} V | max {vmax:.4g} V | {n} pts"
    if extra and extra.get("fundamental_hz"):
        stats_line += f" | f0 {extra['fundamental_hz']:.5g} Hz"
        if extra.get("thd_pct") is not None:
            stats_line += f" | THD {extra['thd_pct']:.2f}%"
    svg = f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<style>
 text{{font:12px ui-monospace,monospace;fill:#c9d1d9}}
 .axis{{stroke:#39424f;stroke-width:1}}
 .grid{{stroke:#232a33;stroke-width:1}}
 .wave{{stroke:#5da9ff;stroke-width:1.2;fill:none}}
</style>
<rect width="100%" height="100%" fill="#0f1115"/>
<text x="{left}" y="24" font-size="14">{title}</text>
<text x="{left}" y="36" font-size="11">{stats_line}</text>
'''
    for i in range(1, 6):
        y = top + (bottom - top) * i / 5
        svg += f'<line class="grid" x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}"/>\n'
    svg += f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{bottom}"/>\n'
    svg += f'<line class="axis" x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}"/>\n'
    svg += f'<polyline class="wave" points="{points}"/>\n'
    svg += f'<text x="{left}" y="{bottom + 18}">{t0:.6g} s</text>\n'
    svg += f'<text x="{right - 60}" y="{bottom + 18}">{t1:.6g} s</text>\n'
    svg += f'<text x="6" y="{top + 8}">{vmax:.3g} V</text>\n'
    svg += f'<text x="6" y="{bottom}">{vmin:.3g} V</text>\n'
    svg += '</svg>\n'
    path.write_text(svg)


def save_npz(path: Path, data: dict) -> None:
    np = _np()
    if np is None:
        raise RuntimeError("npz output requires numpy; run: scope.py setup")
    arrays = {}
    for ch, item in data.items():
        arrays[f"ch{ch}_t"] = item["times"]
        arrays[f"ch{ch}_v"] = item["volts"]
    np.savez(path, **arrays)


def load_npz(path: Path) -> dict:
    np = _np()
    if np is None:
        raise RuntimeError("npz input requires numpy; run: scope.py setup")
    with np.load(path) as z:
        out = {}
        for key in z.files:
            if key.endswith("_t"):
                ch = key[2:-2]
                out[ch] = {"times": list(z[key]), "volts": list(z[f"ch{ch}_v"]), "meta": {}}
        return out
