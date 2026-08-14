#!/usr/bin/env python3
"""CACHIP 触摸 AI 自动调参 (极简版)"""
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
        print(f"\n=== 通道 TK{ch} 当前门限 {orig} ===")

        # 1. 未触摸 (5 秒)
        print("\n[1/2] 采集未触摸数据 5 秒 --- 请勿触摸! 手拿开!")
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
        print(f"  完成: 均值={im:.0f} σ={isd:.1f} 范围=[{min(idle)},{max(idle)}] 最大差值={idmax:.0f}")

        # 2. 触摸 (检测 3 次)
        print(f"\n[2/2] 请触摸 TK{ch}: 按1秒松1秒, 共3次! (30秒超时)")
        diffs = []
        ev = 0
        last = 0
        dl = time.time() + 30
        while ev < 3 and time.time() < dl:
            d = td.poll_once()
            diff = im - d["raws"][ch]
            key = d["key_flags"]
            if key == 1:
                diffs.append(diff)   # 只记录按下时的差值
            if key == 1 and last == 0:
                ev += 1
                print(f"  ✓ 触摸 {ev}/3 (差值 {diff:.0f})")
            last = key
            time.sleep(0.05)
        if ev == 0:
            print("  ❌ 未检测到触摸!")
            return
        tmin = statistics.median(sorted(diffs))
        print(f"  触摸差值(中位): {tmin:.0f}")

        # 3. 计算 + 写入
        best = int((idmax + tmin) / 2)
        best = max(best, 100)
        print(f"\n=== 建议门限 {best} (当前 {orig}) ===")
        td.set_threshold(ch, best)
        td.poll_once()
        print(f"  验证: {td.thresholds[ch]} {'✅' if td.thresholds[ch]==best else '❌'}")
        if not args.keep:
            td.set_threshold(ch, orig)
            print(f"  已恢复 {orig}")
        td.disconnect()
    except Exception as e:
        print(f"错误: {e}")
        try: td.disconnect()
        except Exception: pass
    finally:
        td.close()

if __name__ == "__main__":
    main()
