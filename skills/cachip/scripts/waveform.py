#!/usr/bin/env python3
"""
CACHIP 触摸波形分析 (Linux/Windows)
====================================
采集每次触摸的 raw 波形 → 提取特征 → 分类

特征:
  - 深度 (最大差值)
  - 下降速率 (差值达到 50% 的时间)
  - 释放恢复时间 (回到 50% 的时间)
  - 持续时间 (按下到释放)
  - 振荡 (按下后差值波动)

分类 (规则):
  - 轻点: 持续时间短 (<0.4s), 深度正常
  - 长按: 持续时间长 (>1s)
  - 双击: 两次快速按下 (间隔 <0.5s)
  - 疑似误触: 深度浅 / 斜率慢 / 振荡大

使用: python3 waveform.py --count 6
"""

import time
import statistics
import argparse
import sys
import builtins
sys.path.insert(0, '.')
from cachip_touch_debug import TouchDebugger

print = lambda *a, **k: builtins.print(*a, **k, flush=True)

PRE = 10    # 按下前采样
POST = 40   # 按下后采样 (0.05s = 2 秒)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=6, help="采集触摸次数")
    args = ap.parse_args()

    td = TouchDebugger()
    try:
        td.connect()
        ch = td.channels[0]
        print(f"\n=== TK{ch} 波形采集: 请用不同方式触摸 {args.count} 次 ===")
        print("    (轻点 / 长按 / 快速连点, 随意组合)")

        ev = 0
        last = 0
        last_release = None   # 上次事件释放时间 (连点检测)
        ring = []          # 环形缓冲: 按下前数据 (value, ts)
        during = []        # 按下期间数据 (value, ts)
        dl = time.time() + 60

        def fast_poll():
            """快采样: 只读按键 + raw (3 帧 ≈ 30ms)"""
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
                    print(f"  ⏺ 事件 {ev}/{args.count} 开始...")
            elif key == 0 and last == 1:
                # 释放: 分析! (ring 保留滚动, 支持快速连点)
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

        print(f"\n完成 {ev} 次波形采集")
        td.disconnect()
    except Exception as e:
        print(f"错误: {e}")
        try:
            td.disconnect()
        except Exception:
            pass
    finally:
        td.close()


def analyze(wave, idx, ts=None, gap=None):
    """分析一个触摸事件波形"""
    if len(wave) < 8:
        print(f"    ⚠️ 事件 {idx}: 波形太短")
        return
    depth = max(wave)                       # 最大差值 (深度)
    if depth <= 0:
        print(f"    ⚠️ 事件 {idx}: 无有效差值")
        return

    t0 = ts[0] if ts else 0
    # 按下时刻 (第一个差值 > 20% 深度)
    half = depth * 0.5
    press_i = None
    for i, v in enumerate(wave):
        if v > half:
            press_i = i
            break
    # 释放时刻 (最后差值 < 20% 深度)
    release_i = None
    for i in range(len(wave) - 1, -1, -1):
        if wave[i] > half:
            release_i = i
            break

    press_t = (ts[press_i] - t0) if (press_i is not None and ts) else None
    release_t = (ts[release_i] - t0) if (release_i is not None and ts) else None
    dur = (release_t - press_t) if (press_t is not None and release_t is not None) else None
    rise = press_t  # 达到 50% 的时间
    # 振荡: 按下期间差值的 σ / 深度
    during_vals = [v for v in wave if v > depth * 0.2]
    osc = statistics.stdev(during_vals) / depth if len(during_vals) > 3 else 0

    # 分类
    cls = classify(dur, depth, rise, osc, gap)

    # ASCII 波形 (高度 8)
    print(f"\n  ── 事件 {idx} 波形 ────────────────────────────")
    draw_wave(wave, depth)
    print(f"  ──────────────────────────────────────────────")
    print(f"  深度: {depth:.0f} | 达50%时间: {rise:.2f}s | 持续: {dur:.2f}s | 振荡率: {osc:.2f}")
    gap_s = f" | 与上次间隔: {gap:.2f}s" if gap is not None else ""
    print(f"  🏷️ 分类: {cls}{gap_s}")

    # 特征存到全局 (可用于后续 ML 训练)
    with open(r"C:\temp\wave_features.csv", "a") as f:
        f.write(f"{depth:.0f},{rise:.2f},{dur:.2f},{osc:.2f},{cls}\n")


def classify(dur, depth, rise, osc, gap=None):
    if dur is None:
        return "未知"
    if gap is not None and gap < 0.35:
        return "连点 ⚡⚡"
    if gap is not None and gap < 0.6:
        return "连点 ⚡"
    if dur < 0.5:
        return "轻点 👆"
    if dur > 1.0:
        return "长按 ✊"
    if osc > 0.3:
        return "疑似误触/不稳定 ⚠️"
    if rise is not None and rise > 0.4:
        return "缓按 (疑似误触) ⚠️"
    return "标准按 🖐️"


def draw_wave(wave, depth, height=8):
    """ASCII 波形图"""
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
