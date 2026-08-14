#!/usr/bin/env python3
"""
CACHIP Tool 触摸调试驱动 (Linux/Windows)
========================================
基于官方 CACHIP_TOOL_4.1.3.exe 逆向 + 实测验证 (2025)

✅ 实测通过: 连接调试板/目标芯片, 读取触摸数据
   - 当前值(raw): 持续变动 (用户触摸时明显变化)
   - 基准值(baseline): 缓慢跟踪
   - 差值 = 基准值 - 当前值; 差值 > 门限值时按键触发
   - 电压: 3.29V (实测)
   - 按键标志: 0=未按, 1=按下

协议: 发送 TEA 加密命令(65B) → 读 TEA 加密响应(65B)
响应格式: [cmd][00][通道][值 2B LE] + 填充 (后 8B 重复)

依赖: pip install hidapi
"""

import struct
import time

# ============================================================
# 常量
# ============================================================
VID, PID = 0xFFCA, 0x0125

TEA_KEY = bytes.fromhex("135a64305a5a1766b0500f664d0a075f")
_K0, _K1, _K2, _K3 = struct.unpack('<4I', TEA_KEY)
_DELTA = 0x9E3779B9

# TD_* 命令
TD_CONNECT            = 0x50   # 连接调试板
TD_DISCONNECT         = 0x51   # 断开
TD_GET_STATE          = 0x52   # 状态 (01=已连接)
TD_GET_CHANNEL_COUNT  = 0x53   # 通道数
TD_GET_REF_CH_DATA    = 0x54   # 参考通道数据
TD_GET_KEYS_FLAG_SN   = 0x55   # 按键标志
TD_GET_BASELINE_DATA  = 0x56   # 基准值
TD_GET_RAW_DATA       = 0x57   # 当前值
TD_GET_THRESHOLD_DATA = 0x58   # 门限值
TD_SET_THRESHOLD_DATA = 0x59   # 设置门限值 (在线修改!)
TD_GET_CHANNEL_NUMBER = 0x5A   # 通道号

# ============================================================
# TEA 加密/解密
# ============================================================
def _tea_enc_block(v0, v1):
    sm = 0
    for _ in range(32):
        sm = (sm + _DELTA) & 0xFFFFFFFF
        v0 = (v0 + ((((v1 << 4) & 0xFFFFFFFF) + _K0) ^ (v1 + sm) ^ (((v1 >> 5) & 0xFFFFFFFF) + _K1))) & 0xFFFFFFFF
        v1 = (v1 + ((((v0 << 4) & 0xFFFFFFFF) + _K2) ^ (v0 + sm) ^ (((v0 >> 5) & 0xFFFFFFFF) + _K3))) & 0xFFFFFFFF
    return v0, v1

def _tea_dec_block(v0, v1):
    sm = (_DELTA * 32) & 0xFFFFFFFF
    for _ in range(32):
        v1 = (v1 - ((((v0 << 4) & 0xFFFFFFFF) + _K2) ^ (v0 + sm) ^ (((v0 >> 5) & 0xFFFFFFFF) + _K3))) & 0xFFFFFFFF
        v0 = (v0 - ((((v1 << 4) & 0xFFFFFFFF) + _K0) ^ (v1 + sm) ^ (((v1 >> 5) & 0xFFFFFFFF) + _K1))) & 0xFFFFFFFF
        sm = (sm - _DELTA) & 0xFFFFFFFF
    return v0, v1

def encrypt(plain: bytes) -> bytes:
    padded = plain.ljust(64, b"\x00")[:64]
    out = b""
    for i in range(0, 64, 8):
        v0, v1 = struct.unpack('<2I', padded[i:i+8])
        e0, e1 = _tea_enc_block(v0, v1)
        out += struct.pack('<2I', e0, e1)
    return out

def decrypt(data: bytes) -> bytes:
    out = b""
    for i in range(0, len(data)-7, 8):
        v0, v1 = struct.unpack('<2I', data[i:i+8])
        d0, d1 = _tea_dec_block(v0, v1)
        out += struct.pack('<2I', d0, d1)
    return out

# ============================================================
# HID 传输 (hidapi, Linux/Windows 通用)
# ============================================================
class HidTransport:
    def __init__(self):
        import hid
        self._hid = hid
        self.dev = hid.device()
        self.dev.open(VID, PID)

    def command(self, plain: bytes, timeout=2000) -> bytes:
        """发送命令 + 读响应, 返回响应明文 (64B)"""
        self.dev.write(bytes([0x00]) + encrypt(plain))
        r = bytes(self.dev.read(65, timeout_ms=timeout))
        if len(r) < 64:
            raise RuntimeError(f"读响应超时/短: {len(r)}")
        return decrypt(r[-64:])

    def close(self):
        self.dev.close()

# ============================================================
# 触摸调试器
# ============================================================
class TouchDebugger:
    def __init__(self, transport=None):
        self.t = transport or HidTransport()
        self.channels = []
        self.voltage = 0.0
        self.thresholds = {}

    def _cmd(self, plain: bytes) -> bytes:
        return self.t.command(plain)

    def _flush(self, seconds):
        """阻塞短超时清 FIFO (不用 set_nonblocking, 避免切换 bug)"""
        import time as _t
        _end = _t.time() + seconds
        while _t.time() < _end:
            try:
                self.t.dev.read(65, timeout_ms=20)
            except Exception:
                pass

    def deep_reset(self):
        """深度重置: 长清 FIFO + 多次断开 (同一句柄内) 防止残留"""
        import time as _t
        self._flush(1.0)
        for _ in range(3):
            self.t.dev.write(bytes([0x00]) + encrypt(bytes([0x51])))
            self._flush(0.3)
        self._flush(1.0)

    def connect(self, deep=False):
        """连接调试板 + 目标芯片 (deep=True 时先深度重置, 默认不用!) """
        if deep:
            self.deep_reset()
        # 清空设备 FIFO 残留
        self._flush(0.5)
        print("[1/5] 断开残留连接...")
        self._cmd(bytes([TD_DISCONNECT]))
        self._cmd(bytes([0x11, 0x02]))
        print("[2/5] 连接调试板...")
        self._cmd(bytes([TD_CONNECT]))
        r = self._cmd(bytes([0x11, 0x03]))   # 打开电源 → 电压
        self.voltage = struct.unpack('<H', r[1:3])[0] / 100.0
        print(f"  目标电压: {self.voltage:.2f}V")
        self._cmd(bytes([0x10, 0x04, 0x03]))  # 调试模式
        print("[3/5] 读取状态...")
        r = self._cmd(bytes([TD_GET_STATE]))
        state = r[2]
        if state != 1:
            raise RuntimeError(f"目标芯片未连接 (状态={state})")
        print("  已连接目标芯片")
        print("[4/5] 读取通道数...")
        r = self._cmd(bytes([TD_GET_CHANNEL_COUNT]))
        n = r[2]  # 响应: [53][00][通道数][...]
        print(f"  通道数: {n}")
        r = self._cmd(bytes([TD_GET_CHANNEL_NUMBER, 0x01]))
        ch = r[3]  # 响应: [5A][00][01][通道号] → TK3 = 3
        print(f"  触摸通道: TK{ch}")
        self.channels = [ch] if ch else list(range(1, n + 1))
        print("[5/5] 读取门限值...")
        for ch in self.channels:
            r = self._cmd(bytes([TD_GET_THRESHOLD_DATA, 0x00, ch]))
            self.thresholds[ch] = struct.unpack('<H', r[3:5])[0]
            print(f"  通道{ch} 门限值: {self.thresholds[ch]}")
        print("连接完成!\n")

    def set_threshold(self, ch: int = None, value: int = None) -> bool:
        """在线设置门限值 (0x59), 无需重烧固件!
        实测: 59 00 [通道] [值 2B LE] → 响应回显
        默认用第一个触摸通道 (如 TK3 = 3)
        """
        if ch is None:
            ch = self.channels[0]
        if value is None:
            value = self.thresholds.get(ch, 500)
        r = self._cmd(bytes([TD_SET_THRESHOLD_DATA, 0x00, ch]) + struct.pack('<H', value))
        if r[0] == 0x59 and r[2] == ch:
            self.thresholds[ch] = value
            print(f"  通道{ch} 门限已设为: {value}")
            return True
        print(f"  设置门限失败! 响应={r[:8].hex()}")
        return False

    def poll_once(self) -> dict:
        """轮询一次, 返回 {voltage, keys, raws, baselines, thresholds, diffs}"""
        r = self._cmd(bytes([0x11, 0x03]))   # 电源保持 + 电压
        self.voltage = struct.unpack('<H', r[1:3])[0] / 100.0

        r = self._cmd(bytes([TD_GET_KEYS_FLAG_SN]))
        key_flags = r[2]

        raws, baselines = {}, {}
        for ch in self.channels:
            r = self._cmd(bytes([TD_GET_THRESHOLD_DATA, 0x00, ch]))
            self.thresholds[ch] = struct.unpack('<H', r[3:5])[0]
            r = self._cmd(bytes([TD_GET_BASELINE_DATA, 0x00, ch]))
            baselines[ch] = struct.unpack('<H', r[3:5])[0]
            r = self._cmd(bytes([TD_GET_RAW_DATA, 0x00, ch]))
            raws[ch] = struct.unpack('<H', r[3:5])[0]
        self._cmd(bytes([TD_GET_REF_CH_DATA]))

        return {
            'voltage': self.voltage,
            'key_flags': key_flags,
            'raws': raws,
            'baselines': baselines,
            'thresholds': self.thresholds,
        }

    def disconnect(self):
        """断开"""
        try:
            self._cmd(bytes([TD_DISCONNECT]))
            self._cmd(bytes([0x11, 0x02]))
            print("已断开")
        except Exception:
            pass

    def close(self):
        try:
            self.t.close()
        except Exception:
            pass

# ============================================================
# 主程序
# ============================================================
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="CACHIP Tool 触摸调试 (Linux/Windows)")
    p.add_argument("--count", type=int, default=100, help="轮询次数 (默认 100)")
    p.add_argument("--interval", type=float, default=0.05, help="轮询间隔秒 (默认 0.05)")
    args = p.parse_args()

    td = TouchDebugger()
    try:
        td.connect()
        print(f"电压: {td.voltage:.2f}V\n")
        print(f"{'通道':<6}{'当前值':>8}{'基准值':>8}{'差值':>8}{'门限':>8}{'按键':>6}")
        for i in range(args.count):
            d = td.poll_once()
            for ch in td.channels:
                raw = d['raws'][ch]
                base = d['baselines'][ch]
                diff = base - raw
                thr = d['thresholds'][ch]
                key = d['key_flags']
                print(f"CH{ch:<5}{raw:>8}{base:>8}{diff:>8}{thr:>8}{key:>6}")
            if i < args.count - 1:
                time.sleep(args.interval)
        td.disconnect()
    except Exception as e:
        print(f"错误: {e}")
        td.disconnect()
    finally:
        td.close()
