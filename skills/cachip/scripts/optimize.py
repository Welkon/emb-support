#!/usr/bin/env python3
"""
CACHIP 触摸门限贝叶斯寻优 (Linux/Windows)
==========================================
核心思路: 一次采集原始 raw 数据 → 离线模拟任意门限 → 权衡曲线 → 最优门限

[1/3] 采集未触摸 raw (10 秒)     → 模拟各门限下误触率
[2/3] 采集触摸 raw (按 8 次)     → 模拟各门限下触发成功率
[3/3] 权衡曲线: 门限 vs (误触率, 触发率) → 最优门限 → 在线写入

使用: python3 optimize.py --mis 0.01   (误触容忍 1%)
      python3 optimize.py --env wet    (环境模式: dry/normal/wet)
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
    ap.add_argument("--idle", type=float, default=10, help="未触摸采集秒数")
    ap.add_argument("--touches", type=int, default=8, help="触摸次数")
    ap.add_argument("--mis", type=float, default=0.01, help="误触容忍率 (默认 1%)")
    ap.add_argument("--env", choices=["dry", "normal", "wet"], default="normal",
                    help="环境模式 (影响门限余量)")
    ap.add_argument("--keep", action="store_true", help="保留新门限 (默认恢复)")
    args = ap.parse_args()

    # 环境模式 → 噪声余量系数
    env_margin = {"dry": 2.0, "normal": 3.0, "wet": 5.0}[args.env]

    td = TouchDebugger()
    try:
        td.connect()
        ch = td.channels[0]
        orig = td.thresholds[ch]
        print(f"\n=== TK{ch} 门限寻优 (环境: {args.env}, 误触容忍 {args.mis*100:.0f}%) ===")

        # ========== 1. 未触摸采集 ==========
        print(f"\n[1/3] 采集未触摸数据 {args.idle:.0f} 秒 --- 请勿触摸!")
        idle = []
        for i in range(int(args.idle / 0.1)):
            d = td.poll_once()
            idle.append(d['raws'][ch])
            time.sleep(0.1)
        im = statistics.mean(idle)
        print(f"  基线: 均值={im:.0f} σ={statistics.stdev(idle):.1f} 范围=[{min(idle)},{max(idle)}]")
        # 未触摸时的差值序列 (模拟各门限误触)
        idle_diff = [im - r for r in idle]

        # ========== 2. 触摸采集 ==========
        print(f"\n[2/3] 采集触摸数据 --- 请按 TK{ch} {args.touches} 次 (按1秒松1秒, 30秒超时)")
        touch_diffs = []   # 每个触摸事件按下期间的差值
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
                print(f"  ✓ {ev}/{args.touches} (差值 {diff:.0f})")
            last = key
            time.sleep(0.05)
        if ev == 0:
            print("  ❌ 未检测到触摸!")
            return
        print(f"  触摸差值范围: [{min(touch_diffs):.0f}, {max(touch_diffs):.0f}]")

        # ========== 3. 离线模拟所有门限 ==========
        print("\n[3/3] 离线模拟门限权衡曲线...")
        candidates = sorted(set(
            [50, 100, 150, 200, 250, 300, 400, 500, 600, 800, 1000, 1500, 2000] +
            [int(max(idle_diff)) * 2, int(min(touch_diffs)) // 2,
             int((max(idle_diff) + min(touch_diffs)) / 2)]
        ))
        candidates = [c for c in candidates if 20 < c < max(touch_diffs) * 1.2]

        print(f"  {'门限':>6} {'误触率':>8} {'触发率':>8}  判定")
        print("  " + "-" * 40)
        results = []
        for thr in candidates:
            # 误触率: 未触摸数据中差值 > 门限的占比
            miss = sum(1 for x in idle_diff if x > thr) / len(idle_diff)
            # 触发率: 触摸事件 (按下期间差值最大值 > 门限 即视为触发)
            # 用每 0.25s 窗口的触摸差值峰值模拟 (每事件至少 4 个采样)
            trig_ok = sum(1 for x in touch_diffs if x > thr) / len(touch_diffs)
            verdict = ""
            if miss <= args.mis and trig_ok >= 0.9:
                verdict = "✅ 可行"
            elif miss <= args.mis:
                verdict = "⚠️ 触发不足"
            else:
                verdict = "❌ 误触超标"
            results.append((thr, miss, trig_ok, verdict))
            print(f"  {thr:>6} {miss*100:>7.1f}% {trig_ok*100:>7.1f}%  {verdict}")

        # 最优: 误触达标且触发率最高; 并列取最低门限 (更灵敏)
        ok = [r for r in results if r[1] <= args.mis and r[2] >= 0.9]
        if ok:
            best = min(ok, key=lambda r: (-r[2], r[0]))[0]
        else:
            # 找不到完美: 误触容忍内触发率最高
            ok2 = [r for r in results if r[1] <= args.mis * 3]
            best = max(ok2, key=lambda r: r[2])[0] if ok2 else candidates[0]
            print(f"\n  ⚠️ 无完美门限, 折中选择 {best}")

        # 环境余量修正
        noise = max(idle_diff) if idle_diff else 0
        env_min = int(noise * env_margin)
        if best < env_min:
            print(f"  💡 环境模式({args.env})要求门限 ≥ {env_min} (噪声 {noise:.0f} × {env_margin:.0f}), 修正")
            best = env_min

        print(f"\n=== 🎯 最优门限: {best} (原 {orig}) ===")
        td.set_threshold(ch, best)
        td.poll_once()
        print(f"  验证: {td.thresholds[ch]} {'✅' if td.thresholds[ch] == best else '❌'}")
        if not args.keep:
            td.set_threshold(ch, orig)
            print(f"  已恢复 {orig}")
        td.disconnect()
    except Exception as e:
        print(f"错误: {e}")
        try:
            td.disconnect()
        except Exception:
            pass
    finally:
        td.close()


if __name__ == "__main__":
    main()
