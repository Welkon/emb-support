#!/usr/bin/env python3
"""CACHIP touch automatic tuning (minimal version)."""
import time, statistics, argparse, sys, builtins
sys.path.insert(0, '.')
from cachip_touch_debug import TouchDebugger

print = lambda *a, **k: builtins.print(*a, **k, flush=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    td = TouchDebugger()
    try:
        td.connect()
        ch = td.channels[0]
        orig = td.thresholds[ch]
        print(f"\n=== channel TK{ch} current threshold {orig} ===")

        # 1. No touch (5 s)
        print("\n[1/2] Capture no-touch data for 5 s. Do not touch. Move your hand away.")
        idle = []
        for i in range(50):
            d = td.poll_once()
            idle.append(d["raws"][ch])
            if i % 10 == 9:
                sd = statistics.stdev(idle)
                print(f"  {i+1}/50 σ={sd:.1f}")
            time.sleep(0.1)
        im = statistics.mean(idle)
        isd = statistics.stdev(idle)
        idmax = max(im - r for r in idle)
        print(f"  done: mean={im:.0f} sigma={isd:.1f} range=[{min(idle)},{max(idle)}] max delta={idmax:.0f}")

        # 2. Touch (detect 3 presses)
        print(f"\n[2/2] Touch TK{ch}: press 1 s, release 1 s, 3 times (30 s timeout).")
        diffs = []
        ev = 0
        last = 0
        dl = time.time() + 30
        while ev < 3 and time.time() < dl:
            d = td.poll_once()
            diff = im - d["raws"][ch]
            key = d["key_flags"]
            if key == 1:
                diffs.append(diff)   # record only the delta at press time
            if key == 1 and last == 0:
                ev += 1
                print(f"  OK touch {ev}/3 (delta {diff:.0f})")
            last = key
            time.sleep(0.05)
        if ev == 0:
            print("  no touch detected!")
            return
        tmin = statistics.median(sorted(diffs))
        print(f"  touch delta (median): {tmin:.0f}")

        # 3. Compute and write
        best = int((idmax + tmin) / 2)
        best = max(best, 100)
        print(f"\n=== Suggested threshold {best} (current {orig}) ===")
        td.set_threshold(ch, best)
        td.poll_once()
        print(f"  verify: {td.thresholds[ch]} {'OK' if td.thresholds[ch]==best else 'FAIL'}")
        if not args.keep:
            td.set_threshold(ch, orig)
            print(f"  restored {orig}")
        td.disconnect()
    except Exception as e:
        print(f"Error: {e}")
        try: td.disconnect()
        except Exception: pass
    finally:
        td.close()

if __name__ == "__main__":
    main()
