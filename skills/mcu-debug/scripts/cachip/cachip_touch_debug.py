#!/usr/bin/env python3
"""
CACHIP Tool touch debug driver (Linux/Windows)
========================================
Based on reverse engineering and tests of CACHIP_TOOL_4.1.3.exe (2025)

Tested: connect the debug board and target, read touch data
      - raw value: changes over time. A touch causes a clear change.
      - baseline: tracks slowly
      - delta = baseline - raw. A key triggers when delta > threshold.
      - voltage: 3.29 V (measured)
      - key flag: 0 = released, 1 = pressed

Protocol: send a TEA-encrypted command (65 B), read a TEA-encrypted response (65 B)
Response format: [cmd][00][channel][value 2B LE] plus padding (last 8 B repeated)

Requires: pip install hidapi
"""

import struct
import time

# ============================================================
# Constants
# ============================================================
VID, PID = 0xFFCA, 0x0125

TEA_KEY = bytes.fromhex("135a64305a5a1766b0500f664d0a075f")
_K0, _K1, _K2, _K3 = struct.unpack('<4I', TEA_KEY)
_DELTA = 0x9E3779B9

# TD_* commands
TD_CONNECT            = 0x50   # connect the debug board
TD_DISCONNECT         = 0x51   # disconnect
TD_GET_STATE          = 0x52   # state (01 = connected)
TD_GET_CHANNEL_COUNT  = 0x53   # channel count
TD_GET_REF_CH_DATA    = 0x54   # reference channel data
TD_GET_KEYS_FLAG_SN   = 0x55   # key flags
TD_GET_BASELINE_DATA  = 0x56   # baseline
TD_GET_RAW_DATA       = 0x57   # raw value
TD_GET_THRESHOLD_DATA = 0x58   # threshold
TD_SET_THRESHOLD_DATA = 0x59   # set threshold online
TD_GET_CHANNEL_NUMBER = 0x5A   # channel number

# ============================================================
# TEA encryption and decryption
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
# HID transport (hidapi, Linux and Windows)
# ============================================================
class HidTransport:
    def __init__(self):
        import hid
        self._hid = hid
        self.dev = hid.device()
        self.dev.open(VID, PID)

    def command(self, plain: bytes, timeout=2000) -> bytes:
        """Send a command, read the response, return the 64 B plaintext."""
        self.dev.write(bytes([0x00]) + encrypt(plain))
        r = bytes(self.dev.read(65, timeout_ms=timeout))
        if len(r) < 64:
            raise RuntimeError(f"Response timeout or short read: {len(r)}")
        return decrypt(r[-64:])

    def close(self):
        self.dev.close()

# ============================================================
# Touch debugger
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
        """Clear the FIFO with a short blocking timeout. Do not use set_nonblocking."""
        import time as _t
        _end = _t.time() + seconds
        while _t.time() < _end:
            try:
                self.t.dev.read(65, timeout_ms=20)
            except Exception:
                pass

    def deep_reset(self):
        """Deep reset: long FIFO clear and several disconnects on the same handle."""
        import time as _t
        self._flush(1.0)
        for _ in range(3):
            self.t.dev.write(bytes([0x00]) + encrypt(bytes([0x51])))
            self._flush(0.3)
        self._flush(1.0)

    def connect(self, deep=False):
        """Connect the debug board and target. deep=True runs a deep reset first (off by default)."""
        if deep:
            self.deep_reset()
        # Clear leftover FIFO data.
        self._flush(0.5)
        print("[1/5] Disconnect leftover links...")
        self._cmd(bytes([TD_DISCONNECT]))
        self._cmd(bytes([0x11, 0x02]))
        print("[2/5] Connect the debug board...")
        self._cmd(bytes([TD_CONNECT]))
        r = self._cmd(bytes([0x11, 0x03]))   # power on -> voltage
        self.voltage = struct.unpack('<H', r[1:3])[0] / 100.0
        print(f"  target voltage: {self.voltage:.2f} V")
        self._cmd(bytes([0x10, 0x04, 0x03]))  # debug mode
        print("[3/5] Read state...")
        r = self._cmd(bytes([TD_GET_STATE]))
        state = r[2]
        if state != 1:
            raise RuntimeError(f"Target not connected (state={state})")
        print("  target connected")
        print("[4/5] Read channel count...")
        r = self._cmd(bytes([TD_GET_CHANNEL_COUNT]))
        n = r[2]  # response: [53][00][count][...]
        print(f"  channel count: {n}")
        r = self._cmd(bytes([TD_GET_CHANNEL_NUMBER, 0x01]))
        ch = r[3]  # response: [5A][00][01][channel] -> TK3 = 3
        print(f"  touch channel: TK{ch}")
        self.channels = [ch] if ch else list(range(1, n + 1))
        print("[5/5] Read thresholds...")
        for ch in self.channels:
            r = self._cmd(bytes([TD_GET_THRESHOLD_DATA, 0x00, ch]))
            self.thresholds[ch] = struct.unpack('<H', r[3:5])[0]
            print(f"  channel {ch} threshold: {self.thresholds[ch]}")
        print("Connected.\n")

    def set_threshold(self, ch: int = None, value: int = None) -> bool:
        """Set the threshold online (0x59). No firmware rewrite is needed.
        Measured: 59 00 [channel] [value 2B LE] -> response echo.
        Uses the first touch channel by default (TK3 = 3).
        """
        if ch is None:
            ch = self.channels[0]
        if value is None:
            value = self.thresholds.get(ch, 500)
        r = self._cmd(bytes([TD_SET_THRESHOLD_DATA, 0x00, ch]) + struct.pack('<H', value))
        if r[0] == 0x59 and r[2] == ch:
            self.thresholds[ch] = value
            print(f"  channel {ch} threshold set to: {value}")
            return True
        print(f"  Set threshold failed. Response={r[:8].hex()}")
        return False

    def poll_once(self) -> dict:
        """Poll once. Return {voltage, keys, raws, baselines, thresholds, diffs}."""
        r = self._cmd(bytes([0x11, 0x03]))   # keep power on + voltage
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
        """Disconnect."""
        try:
            self._cmd(bytes([TD_DISCONNECT]))
            self._cmd(bytes([0x11, 0x02]))
            print("Disconnected")
        except Exception:
            pass

    def close(self):
        try:
            self.t.close()
        except Exception:
            pass

# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="CACHIP Tool touch debug (Linux/Windows)")
    p.add_argument("--count", type=int, default=100, help="poll count (default 100)")
    p.add_argument("--interval", type=float, default=0.05, help="poll interval in seconds (default 0.05)")
    args = p.parse_args()

    td = TouchDebugger()
    try:
        td.connect()
        print(f"Voltage: {td.voltage:.2f} V\n")
        print(f"{'channel':<8}{'raw':>8}{'baseline':>10}{'delta':>9}{'threshold':>11}{'key':>6}")
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
        print(f"Error: {e}")
        td.disconnect()
    finally:
        td.close()
