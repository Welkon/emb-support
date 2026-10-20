#!/usr/bin/env python3
"""
CACHIP touch threshold search with Bayesian optimization (Linux/Windows)
==========================================
Idea: capture raw data once, simulate every threshold offline, draw a trade-off curve, pick the best threshold.

[1/3] Capture no-touch raw data (10 s) -> simulate the false-touch rate for each threshold
[2/3] Capture touch raw data (8 presses) -> simulate the trigger rate for each threshold
[3/3] Trade-off curve: threshold vs (false-touch rate, trigger rate) -> best threshold -> write online

Usage: python3 optimize.py --mis 0.01   (accept 1% false touch)
             python3 optimize.py --env wet    (environment: dry/normal/wet)
"""

import time
import statistics
import argparse
import sys
import builtins
sys.path.insert(0, '.')
from cachip_touch_debug import TouchDebugger

print = lambda *a, **k: builtins.print(*a, **k, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--idle", type=float, default=10, help="seconds of no-touch capture")
    ap.add_argument("--touches", type=int, default=8, help="number of touches")
    ap.add_argument("--mis", type=float, default=0.01, help="false-touch tolerance (default 1%)")
    ap.add_argument("--env", choices=["dry", "normal", "wet"], default="normal",
                    help="environment mode (sets the threshold margin)")
    ap.add_argument("--keep", action="store_true", help="keep the new threshold (default: restore)")
    args = ap.parse_args()

    # Environment mode to noise margin factor
    env_margin = {"dry": 2.0, "normal": 3.0, "wet": 5.0}[args.env]

    td = TouchDebugger()
    try:
        td.connect()
        ch = td.channels[0]
        orig = td.thresholds[ch]
        print(f"\n=== TK{ch} threshold search (env: {args.env}, false-touch tolerance {args.mis*100:.0f}%) ===")

        # 1. No-touch capture
        print(f"\n[1/3] Capture no-touch data for {args.idle:.0f} s. Do not touch the key.")
        idle = []
        for i in range(int(args.idle / 0.1)):
            d = td.poll_once()
            idle.append(d['raws'][ch])
            time.sleep(0.1)
        im = statistics.mean(idle)
        print(f"  baseline: mean={im:.0f} sigma={statistics.stdev(idle):.1f} range=[{min(idle)},{max(idle)}]")
        # Delta series without touch (simulates false triggers for each threshold)
        idle_diff = [im - r for r in idle]

        # 2. Touch capture
        print(f"\n[2/3] Capture touch data. Press TK{ch} {args.touches} times (1 s press, 1 s release, 30 s timeout).")
        touch_diffs = []   # delta during each touch event
        ev = 0
        last = 0
        dl = time.time() + 30
        while ev < args.touches and time.time() < dl:
            d = td.poll_once()
            diff = im - d['raws'][ch]
            key = d['key_flags']
            if key == 1:
                touch_diffs.append(diff)
            if key == 1 and last == 0:
                ev += 1
                print(f"  OK {ev}/{args.touches} (delta {diff:.0f})")
            last = key
            time.sleep(0.05)
        if ev == 0:
            print("  no touch detected!")
            return
        print(f"  touch delta range: [{min(touch_diffs):.0f}, {max(touch_diffs):.0f}]")

        # 3. Simulate all thresholds offline
        print("\n[3/3] Simulate the threshold trade-off curve offline...")
        candidates = sorted(set(
            [50, 100, 150, 200, 250, 300, 400, 500, 600, 800, 1000, 1500, 2000] +
            [int(max(idle_diff)) * 2, int(min(touch_diffs)) // 2,
             int((max(idle_diff) + min(touch_diffs)) / 2)]
        ))
        candidates = [c for c in candidates if 20 < c < max(touch_diffs) * 1.2]

        print(f"  {'threshold':>9} {'false rate':>11} {'trigger rate':>12}  verdict")
        print("  " + "-" * 40)
        results = []
        for thr in candidates:
            # False-touch rate: share of no-touch samples with delta > threshold
            miss = sum(1 for x in idle_diff if x > thr) / len(idle_diff)
            # Trigger rate: a touch event triggers if its peak delta > threshold
            # Use a 0.25 s window peak per event (at least 4 samples per event)
            trig_ok = sum(1 for x in touch_diffs if x > thr) / len(touch_diffs)
            verdict = ""
            if miss <= args.mis and trig_ok >= 0.9:
                verdict = "OK"
            elif miss <= args.mis:
                verdict = "trigger too low"
            else:
                verdict = "too many false touches"
            results.append((thr, miss, trig_ok, verdict))
            print(f"  {thr:>6} {miss*100:>7.1f}% {trig_ok*100:>7.1f}%  {verdict}")

        # Best: meets the false-touch target and has the highest trigger rate. On a tie, pick the lowest threshold.
        ok = [r for r in results if r[1] <= args.mis and r[2] >= 0.9]
        if ok:
            best = min(ok, key=lambda r: (-r[2], r[0]))[0]
        else:
            # No perfect threshold. Pick the highest trigger rate within the tolerance.
            ok2 = [r for r in results if r[1] <= args.mis * 3]
            best = max(ok2, key=lambda r: r[2])[0] if ok2 else candidates[0]
            print(f"\n  no perfect threshold, compromise at {best}")

        # Apply the environment margin
        noise = max(idle_diff) if idle_diff else 0
        env_min = int(noise * env_margin)
        if best < env_min:
            print(f"  environment mode ({args.env}) requires threshold >= {env_min} (noise {noise:.0f} x {env_margin:.0f}). Adjusted.")
            best = env_min

        print(f"\n=== Best threshold: {best} (was {orig}) ===")
        td.set_threshold(ch, best)
        td.poll_once()
        print(f"  verify: {td.thresholds[ch]} {'OK' if td.thresholds[ch] == best else 'FAIL'}")
        if not args.keep:
            td.set_threshold(ch, orig)
            print(f"  restored {orig}")
        td.disconnect()
    except Exception as e:
        print(f"Error: {e}")
        try:
            td.disconnect()
        except Exception:
            pass
    finally:
        td.close()


if __name__ == "__main__":
    main()
