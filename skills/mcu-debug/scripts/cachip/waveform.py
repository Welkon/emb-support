#!/usr/bin/env python3
"""
CACHIP touch waveform analysis (Linux/Windows)
====================================
Capture the raw waveform of each touch, extract features and classify it.

Features:
    - depth (maximum delta)
    - fall time (time to reach 50% of the delta)
    - release recovery time (time to return to 50%)
    - duration (press to release)
    - oscillation (delta variation during the press)

Classes (rules):
    - tap: short duration (<0.4 s), normal depth
    - long press: duration > 1 s
    - double tap: two fast presses (interval < 0.5 s)
    - possible false touch: shallow depth, slow slope or large oscillation

Usage: python3 waveform.py --count 6
"""

import time
import statistics
import argparse
import sys
import builtins
sys.path.insert(0, '.')
from cachip_touch_debug import TouchDebugger

print = lambda *a, **k: builtins.print(*a, **k, flush=True)

PRE = 10    # samples before the press
POST = 40   # samples after the press (0.05 s = 2 s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=6, help="number of touches to capture")
    args = ap.parse_args()

    td = TouchDebugger()
    try:
        td.connect()
        ch = td.channels[0]
        print(f"\n=== TK{ch} waveform capture: touch the key {args.count} times in different ways ===")
        print("    (tap, long press, fast multi-tap; mix them freely)")

        ev = 0
        last = 0
        last_release = None   # release time of the previous event (multi-tap check)
        ring = []          # ring buffer: samples before the press (value, ts)
        during = []        # samples during the press (value, ts)
        dl = time.time() + 60

        def fast_poll():
            """Fast sample: read only key flag and raw value (3 frames, about 30 ms)."""
            td._cmd(bytes([0x11, 0x03]))
            rk = td._cmd(bytes([0x55]))
            rr = td._cmd(bytes([0x57, 0x00, ch]))
            import struct as _s
            return rk[2], _s.unpack('<H', rr[3:5])[0]

        while ev < args.count and time.time() < dl:
            key, raw = fast_poll()
            now = time.time()
            if key == 0 and last == 0:
                ring.append((raw, now))
                if len(ring) > PRE:
                    ring.pop(0)
            elif key == 1:
                during.append((raw, now))
                if last == 0:
                    ev += 1
                    print(f"  event {ev}/{args.count} start...")
            elif key == 0 and last == 1:
                # Release: analyse. The ring keeps rolling and supports fast multi-tap.
                base = statistics.mean([v for v, _ in ring]) if len(ring) >= 3 else 8000
                seq = ring[-PRE:] + during
                wave = [base - v for v, _ in seq]
                ts = [t for _, t in seq]
                now_t = ts[-1] if ts else time.time()
                gap = (now_t - last_release) if last_release else None
                last_release = now_t
                during = []
                analyze(wave, ev, ts, gap)
            last = key
            time.sleep(0.02)

        print(f"\nCaptured {ev} waveforms")
        td.disconnect()
    except Exception as e:
        print(f"Error: {e}")
        try:
            td.disconnect()
        except Exception:
            pass
    finally:
        td.close()


def analyze(wave, idx, ts=None, gap=None):
    """Analyse one touch waveform."""
    if len(wave) < 8:
        print(f"    event {idx}: waveform too short")
        return
    depth = max(wave)                       # maximum delta (depth)
    if depth <= 0:
        print(f"    event {idx}: no valid delta")
        return

    t0 = ts[0] if ts else 0
    # Press time (first delta > 20% of depth)
    half = depth * 0.5
    press_i = None
    for i, v in enumerate(wave):
        if v > half:
            press_i = i
            break
    # Release time (last delta < 20% of depth)
    release_i = None
    for i in range(len(wave) - 1, -1, -1):
        if wave[i] > half:
            release_i = i
            break

    press_t = (ts[press_i] - t0) if (press_i is not None and ts) else None
    release_t = (ts[release_i] - t0) if (release_i is not None and ts) else None
    dur = (release_t - press_t) if (press_t is not None and release_t is not None) else None
    rise = press_t  # time to reach 50%
    # Oscillation: sigma of the delta during the press divided by the depth
    during_vals = [v for v in wave if v > depth * 0.2]
    osc = statistics.stdev(during_vals) / depth if len(during_vals) > 3 else 0

    # Classification
    cls = classify(dur, depth, rise, osc, gap)

    # ASCII waveform (height 8)
    print(f"\n  -- event {idx} waveform ----------------------------")
    draw_wave(wave, depth)
    print(f"  ──────────────────────────────────────────────")
    print(f"  depth: {depth:.0f} | 50% time: {rise:.2f} s | duration: {dur:.2f} s | oscillation: {osc:.2f}")
    gap_s = f" | gap to previous: {gap:.2f} s" if gap is not None else ""
    print(f"  class: {cls}{gap_s}")

    # Store features globally for ML training
    with open(r"C:\temp\wave_features.csv", "a") as f:
        f.write(f"{depth:.0f},{rise:.2f},{dur:.2f},{osc:.2f},{cls}\n")


def classify(dur, depth, rise, osc, gap=None):
    if dur is None:
        return "unknown"
    if gap is not None and gap < 0.35:
        return "multi-tap (fast)"
    if gap is not None and gap < 0.6:
        return "multi-tap"
    if dur < 0.5:
        return "tap"
    if dur > 1.0:
        return "long press"
    if osc > 0.3:
        return "possible false touch / unstable"
    if rise is not None and rise > 0.4:
        return "slow press (possible false touch)"
    return "standard press"


def draw_wave(wave, depth, height=8):
    """ASCII waveform."""
    if depth <= 0:
        return
    rows = [""] * height
    for v in wave:
        h = int(v / depth * (height - 1))
        for r in range(height):
            rows[r] += "█" if (height - 1 - r) <= h else " "
    for r in rows:
        print(f"      {r}")


if __name__ == "__main__":
    main()
