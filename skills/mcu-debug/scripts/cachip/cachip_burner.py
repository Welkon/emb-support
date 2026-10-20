#!/usr/bin/env python3
"""
CACHIP Tool protocol driver, full version (Linux/Windows).
=============================================
Based on a full reverse engineering and tests of CACHIP_TOOL_4.1.3.exe (2025).

Verified: full burn flow. The OLED showed "burn success 100%".
The official tool check passed ("The verification was successful").

Requires: pip install hidapi pyserial. On Linux, add a udev rule.
"""

import struct
import time
from mcu_table import MODELS, FAMILIES

# ============================================================
# Constants
# ============================================================
VID, PID = 0xFFCA, 0x0125

# TEA key (embedded in the official exe)
TEA_KEY = bytes.fromhex("135a64305a5a1766b0500f664d0a075f")
_K0, _K1, _K2, _K3 = struct.unpack('<4I', TEA_KEY)
_DELTA = 0x9E3779B9

# ============================================================
# TEA encryption
# ============================================================
def _tea_encrypt_block(v0, v1):
    sm = 0
    for _ in range(32):
        sm = (sm + _DELTA) & 0xFFFFFFFF
        v0 = (v0 + ((((v1 << 4) & 0xFFFFFFFF) + _K0) ^ (v1 + sm) ^ (((v1 >> 5) & 0xFFFFFFFF) + _K1))) & 0xFFFFFFFF
        v1 = (v1 + ((((v0 << 4) & 0xFFFFFFFF) + _K2) ^ (v0 + sm) ^ (((v0 >> 5) & 0xFFFFFFFF) + _K3))) & 0xFFFFFFFF
    return v0, v1

def encrypt_frame(plain: bytes) -> bytes:
    """Pad the plaintext frame to 64 B, then encrypt 8 blocks with TEA ECB."""
    padded = plain.ljust(64, b"\x00")[:64]
    out = b""
    for i in range(0, 64, 8):
        v0, v1 = struct.unpack('<2I', padded[i:i+8])
        e0, e1 = _tea_encrypt_block(v0, v1)
        out += struct.pack('<2I', e0, e1)
    return out

# ============================================================
# Checksum (official algorithm: sum(firmware padded with 0xFF to flashSize) + flashSize*2 + 1)
# ============================================================
def calc_checksum(fw: bytes, flash_size_kb: int) -> int:
    size = flash_size_kb * 1024
    padded = fw + b'\xff' * (size - len(fw))
    return (sum(padded) + size * 2 + 1) & 0xFFFFFFFF

def find_model(name: str):
    """Look up the model. Return (model_id, flash_size_kb)."""
    if name not in MODELS:
        raise RuntimeError(f"Unknown model: {name}")
    model = MODELS[name]
    # Find the family by model name prefix.
    fs = None
    for fam, size in FAMILIES.items():
        if name.startswith(fam):
            fs = size
            break
    if fs is None:
        raise RuntimeError(f"Cannot find the family of {name}")
    return model, fs

# ============================================================
# Intel HEX parser (official behavior: fill gaps with 0x00, pad the tail with 0xFF)
# ============================================================
def parse_hex(path: str) -> bytes:
    """Parse an Intel HEX file.
    Fill undefined gaps with 0x00.
    Return the firmware data.
    """
    data = bytearray()
    base = 0
    for line in open(path, 'r'):
        line = line.strip()
        if not line or line[0] != ':':
            continue
        try:
            b = bytes.fromhex(line[1:])
        except:
            continue
        count = b[0]
        addr = (b[1] << 8) | b[2]
        rtype = b[3]
        if rtype == 0:
            full = base + addr
            need = full + count - len(data)
            if need > 0:
                data.extend(b'\x00' * need)
            data[full:full+count] = b[4:4+count]
        elif rtype == 2:
            base = ((b[4] << 8) | b[5]) * 16
        elif rtype == 4:
            base = ((b[4] << 8) | b[5]) * 65536
        elif rtype == 1:
            break
    return bytes(data)

def prepare_firmware(fw: bytes, chunk=32) -> list:
    """Split the firmware into data blocks.
    Each block is 32 B. Pad the tail with 0xFF. Add one block of 0xFF (official behavior).
    """
    blocks = []
    for i in range(0, len(fw), chunk):
        blk = fw[i:i+chunk].ljust(chunk, b'\xff')
        blocks.append(blk)
    blocks.append(b'\xff' * chunk)  # add one block (0xD80)
    return blocks

# ============================================================
# HID transport (interrupt endpoint, official channel)
# ============================================================
class HidTransport:
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self._ctypes = ctypes
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel32.CreateFileW.restype = ctypes.c_void_p
        self.kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
        self.kernel32.WriteFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
        self.kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        self._open()

    def _open(self):
        import hid
        path = None
        for d in hid.enumerate():
            if d['vendor_id'] == VID and d['product_id'] == PID:
                path = d['path'].decode() if isinstance(d['path'], bytes) else d['path']
                break
        if not path:
            raise RuntimeError("CACHIP Tool is not connected!")
        self.h = self.kernel32.CreateFileW(path, 0xC0000000, 0x3, None, 3, 0, None)
        # hidapi device. Use it to read responses.
        self._hid_dev = hid.device()
        self._hid_dev.open(VID, PID)

    def send_cmd(self, plain: bytes):
        """Send an encrypted command frame."""
        enc = encrypt_frame(plain)
        frame = (bytes([0x00]) + enc).ljust(65, b"\x00")[:65]
        written = self._ctypes.wintypes.DWORD()
        ok = self.kernel32.WriteFile(self.h, frame, 65, self._ctypes.byref(written), None)
        if not ok:
            raise RuntimeError(f"WriteFile failed, err={self.kernel32.GetLastError()}")
        time.sleep(0.01)  # delay between blocks

    def command(self, plain: bytes, timeout=3000) -> bytes:
        """Send a command, read the response, check the status, return the 64 B plaintext."""
        import hid as _hid
        # Read with hidapi. hidapi handles Windows overlapped IO.
        d = self._hid_dev
        d.write(bytes([0x00]) + encrypt_frame(plain))
        r = bytes(d.read(65, timeout_ms=timeout))
        if len(r) < 64:
            raise RuntimeError(f"Response timeout or short read: {len(r)}")
        from cachip_touch_debug import decrypt as _dec
        resp = _dec(r[-64:])
        # Check that the response command matches.
        if resp[0] != plain[0]:
            raise RuntimeError(f"Response mismatch: request={plain[0]:02X} response={resp[0]:02X}")
        # Status check. Heartbeat (00) and power (11) are special: heartbeat carries the version, power carries the voltage.
        if plain[0] not in (0x00, 0x11) and len(plain) > 1 and resp[1] != 0x00:
            raise RuntimeError(f"Command 0x{plain[0]:02X} failed: status={resp[1]:02X}")
        return resp

    def close(self):
        self.kernel32.CloseHandle(self.h)

# ============================================================
# Burner
# ============================================================
class CachipBurner:
    def __init__(self, transport=None):
        self.t = transport or HidTransport()

    def _cmd(self, plain: bytes, timeout=3000):
        return self.t.command(plain, timeout)

    def burn(self, fw_path: str, model_name: str = "CA51M550S1B", chunk=32):
        """Run the full burn (official flow, automatic).
        model_name: model name (for example CA51M550S1B).
        """
        model, flash_kb = find_model(model_name)
        fw = parse_hex(fw_path)
        checksum = calc_checksum(fw, flash_kb)
        blocks = prepare_firmware(fw, chunk)
        total = len(blocks)

        print(f"Model: {model_name} (ID=0x{model:04X}, Flash={flash_kb}KB)")
        print(f"Firmware: {len(fw)} bytes, {total} blocks, Checksum=0x{checksum:08X}")

        # 1. Initialize
        self._cmd(bytes([0x00, 0x04]))              # heartbeat
        self._cmd(bytes([0x10, 0x00]))
        self._cmd(bytes([0x10, 0x01]) + struct.pack('<I', checksum))
        self._cmd(bytes([0x10, 0x02, 0x01]))
        self._cmd(bytes([0x10, 0x04, 0x01]))

        # 2. Connect (checks the target chip)
        conn = (bytes([0x08]) + struct.pack('<H', model) + b'5M'
                + model_name.encode() + bytes(5)
                + model_name.encode() + bytes(5))
        r = self._cmd(conn, timeout=10000)   # Connect is slow (target detection)
        got_model = struct.unpack('<H', r[2:4])[0]
        if got_model != model:
            raise RuntimeError(f"Target model mismatch! Expected 0x{model:04X}, detected 0x{got_model:04X}")
        print(f"  target chip connected (0x{got_model:04X})")

        # 3. Power on and check the voltage
        r = self._cmd(bytes([0x11, 0x03]))          # TargetPower
        v = struct.unpack('<H', r[1:3])[0] / 100.0
        if v < 2.0:
            raise RuntimeError(f"Target voltage is out of range: {v:.2f} V (target board power?)")
        print(f"  target voltage: {v:.2f} V")
        self._cmd(bytes([0x13, 0x01]))              # WriteEvent
        self._cmd(bytes([0x10, 0x02, 0x04]))
        self._cmd(bytes([0x10, 0x03, 0x00]))        # progress 0

        # 4. Erase
        r = self._cmd(bytes([0x0B, 0x02, 0, 0, 0, 0, 0, 0]), timeout=8000)
        print("  erase done")
        time.sleep(1.0)

        # 5. Write loop (0F cache + 0C write flash)
        addr = 0
        for i, blk in enumerate(blocks):
            self._cmd(bytes([0x0F, 0, 0, 0, 0, 0x20]) + blk)   # write cache
            self._cmd(bytes([0x0C]) + struct.pack('<I', addr) + struct.pack('<I', 0) + bytes([0x20, 0x00]))
            addr += chunk
            pct = min((i + 1) * 100 // total, 100)
            self._cmd(bytes([0x10, 0x03, pct]))
        print("Write done")

        # 6. Switch to verify
        self._cmd(bytes([0x10, 0x03, 100]))
        time.sleep(0.2)
        self._cmd(bytes([0x10, 0x02, 0x07]))        # verifying
        time.sleep(0.2)
        self._cmd(bytes([0x10, 0x03, 0x00]))        # progress 0
        time.sleep(0.2)

        # 7. Verify loop (0D plus expected data)
        addr = 0
        for i, blk in enumerate(blocks):
            self._cmd(bytes([0x0D]) + struct.pack('<I', addr) + bytes([0x20]) + blk)
            addr += chunk
            pct = min((i + 1) * 100 // total, 100)
            self._cmd(bytes([0x10, 0x03, pct]))
        print("Verify done")

        # 8. Finish
        self._cmd(bytes([0x10, 0x03, 100]))
        time.sleep(0.3)
        self._cmd(bytes([0x09]))                    # Disconnect
        time.sleep(0.3)
        self._cmd(bytes([0x10, 0x02, 0x05]))
        time.sleep(0.3)
        self._cmd(bytes([0x11, 0x00]))              # power off
        print("Burn complete!")

    def close(self):
        self.t.close()

# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="CACHIP Tool Linux burner")
    p.add_argument("hex", help="firmware file (Intel HEX)")
    p.add_argument("--name", default="CA51M550S1B", help="MCU model name (for example CA51M550S1B)")
    p.add_argument("--list", action="store_true", help="list all supported models")
    args = p.parse_args()

    if args.list:
        for name in sorted(MODELS):
            fs = "?"
            for fam, size in FAMILIES.items():
                if name.startswith(fam):
                    fs = f"{size}KB"
                    break
            print(f"  {name} (0x{MODELS[name]:04X}, {fs})")
        exit(0)

    burner = CachipBurner()
    try:
        burner.burn(args.hex, args.name)
    finally:
        burner.close()
