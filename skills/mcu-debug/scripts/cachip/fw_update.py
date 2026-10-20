#!/usr/bin/env python3
"""
CACHIP downloader firmware update (Linux/Windows)
======================================
Official firmware update protocol (UPGRADE_*, measured):

    E0 = start update          (response E0 02)
    E4 = confirm update mode
    E3 = erase a 2 KB sector   (E3 + 0000 + address 4B + 01)
    E2 = write memory          (E2 + 0000 + address 4B + length 1B + 00 + data)
    E1 = read and verify       (E1 + 0000 + address 4B + length 1B + 00 + 00...)
                                                     response = the read-back data

Firmware layout: 0x08000000-0x08005800 = boot area (keep!)
                          0x08005800+ = firmware area (erase and rewrite)

Usage:
    python3 fw_update.py verify fw.bin    # read-back verify (safe)
    python3 fw_update.py update fw.bin    # full update (risky)
"""

import struct
import time
import argparse
import sys
import builtins
sys.path.insert(0, '.')
from cachip_touch_debug import TouchDebugger, encrypt

print = lambda *a, **k: builtins.print(*a, **k, flush=True)

FW_BASE = 0x08005800      # firmware start (boot area 0x5800 is kept)
SECTOR = 0x800            # 2 KB sector
WRITE_LEN = 56            # E2 write block
READ_LEN = 60             # E1 read block
VERIFY_END = 0x0802ACB0   # verify end (end of code; the tail config area is not verified)


class FWUpdater:
    def __init__(self):
        self.td = TouchDebugger()
        self.t = self.td.t

    def _cmd(self, plain: bytes, timeout=3000) -> bytes:
        return self.t.command(plain, timeout)

    def start(self):
        """Enter update mode: E0, heartbeat, E4 (triggers a device restart), reopen the device."""
        try:
            r = self._cmd(bytes([0xE0]), timeout=3000)
            print(f"  update start -> state {r[1]}")
        except Exception as e:
            print(f"  E0 did not respond ({e}). The device may already be in update mode. Continue.")
        self._cmd(bytes([0x00, 0x07]))          # heartbeat
        # E4 is send-only. It switches the device to update mode and may re-enumerate USB.
        try:
            self.t.dev.write(bytes([0x00]) + encrypt(bytes([0xE4, 0x01])))
        except Exception:
            pass
        print("  wait for the device to enter update mode...")
        time.sleep(2.0)
        # Reconnect the device. The handle may be invalid.
        import hid as _hid
        try:
            self.t.dev.close()
        except Exception:
            pass
        for attempt in range(10):
            try:
                self.t.dev = _hid.device()
                self.t.dev.open(0xFFCA, 0x0125)
                print(f"  device reconnected (attempt {attempt+1})")
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("Device reconnect failed!")

    def _cmd_retry(self, plain: bytes, want: int, timeout=5000, tries=3) -> bytes:
        """Send a command, read the response, check the command echo, retry on mismatch."""
        for i in range(tries):
            try:
                r = self.t.command(plain, timeout)
                if r[0] == want:
                    return r
                print(f"  discard mismatched response: {r[0]:02X} (expected {want:02X})")
            except Exception as e:
                print(f"  retry {i+1}: {e}")
            time.sleep(0.5)
        raise RuntimeError(f"Command 0x{want:02X} got no response after several tries!")
        # Reopen the device after the USB re-enumeration.
        import hid as _hid
        try:
            self.t.dev.close()
        except Exception:
            pass
        self.t.dev = _hid.device()
        for attempt in range(10):
            try:
                self.t.dev.open(0xFFCA, 0x0125)
                print(f"  device reconnected (attempt {attempt+1})")
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("Device reconnect failed! Unplug and replug USB.")

    def erase_sectors(self, size: int):
        """Erase one 2 KB sector at a time."""
        n = 0
        addr = FW_BASE
        while addr < FW_BASE + size:
            r = self._cmd_retry(bytes([0xE3]) + bytes(1) + struct.pack('<I', addr) + bytes([1]) + bytes([0]), 0xE3)
            addr += SECTOR
            n += 1
            if n % 10 == 0:
                print(f"  erase sector {n} (0x{addr:X})...")
        print(f"  sector erase: {n} sectors (0x{FW_BASE:X} - 0x{addr:X})")

    def write_fw(self, fw: bytes):
        """Write the firmware in 56 B blocks."""
        addr = FW_BASE
        n = 0
        for off in range(0, len(fw), WRITE_LEN):
            chunk = fw[off:off + WRITE_LEN]
            frame = (bytes([0xE2]) + bytes(1) + struct.pack('<I', addr)
                     + bytes([len(chunk)]) + bytes([0]) + chunk)
            r = self._cmd_retry(frame, 0xE2)
            addr += len(chunk)
            n += 1
            if n % 200 == 0:
                print(f"  write block {n} (0x{addr:X})...")
        print(f"  written: {n} blocks ({len(fw)} bytes)")

    def verify_fw(self, fw: bytes) -> bool:
        """Read back and verify in 60 B blocks up to VERIFY_END."""
        addr = FW_BASE
        n = 0
        ok = True
        # Verify through VERIFY_END, including the last block (address aligned to 0x0802ACB0).
        vlen = min(len(fw), (VERIFY_END - FW_BASE) + READ_LEN)
        for off in range(0, vlen, READ_LEN):
            frame = (bytes([0xE1]) + bytes(1) + struct.pack('<I', addr)
                     + bytes([READ_LEN]) + bytes([0]))
            r = self._cmd_retry(frame, 0xE1)
            # Response: E1 + 00 + [length] + [00] + [data]
            got = r[4:4 + READ_LEN]
            want = fw[off:off + READ_LEN]
            if got[:len(want)] != want:
                ok = False
                if n < 3:
                    print(f"  FAIL 0x{addr:X}: expected {want[:8].hex()}, read {got[:8].hex()}")
            addr += READ_LEN
            n += 1
        # Add the last block at 0x0802ACB0 (official last verify address; it triggers the restart).
        r = self._cmd_retry(bytes([0xE1]) + bytes(1) + struct.pack('<I', VERIFY_END) + bytes([READ_LEN]) + bytes([0]), 0xE1)
        got = r[4:4 + READ_LEN]
        off = VERIFY_END - FW_BASE
        want = fw[off:off + READ_LEN]
        if got[:len(want)] == want:
            print(f"  last block 0x{VERIFY_END:X} OK (the device should restart)")
        else:
            print(f"  last block 0x{VERIFY_END:X} MISMATCH!")
            ok = False
        print(f"  verify: {n + 1} blocks {'PASS' if ok else 'FAILED'}")
        return ok

    def close(self):
        try:
            self.td.disconnect()
        except Exception:
            pass
        self.td.close()


def main():
    ap = argparse.ArgumentParser(description="CACHIP downloader firmware update")
    ap.add_argument("cmd", choices=["verify", "update"], help="verify=read-back check (safe), update=full update (risky)")
    ap.add_argument("fw", help="firmware BIN file")
    args = ap.parse_args()

    fw = open(args.fw, 'rb').read()
    # The BIN is a full flash image. The firmware area starts at 0x5800.
    if len(fw) < 0x5800:
        print(f"Error: firmware is too small ({len(fw)} < 0x5800)")
        return
    body = fw[0x5800:]
    print(f"Firmware: {len(fw)} B, firmware area: {len(body)} B (from 0x{FW_BASE:X})")

    up = FWUpdater()
    try:
        if args.cmd == "verify":
            up.start()
            print("\n[Read-back verify]")
            up.verify_fw(body)
        else:
            print("WARNING: updating the downloader firmware can brick the device. The boot area is kept and can be reflashed.")
            up.start()
            print("\n[Sector erase]")
            up.erase_sectors(len(body))
            print("\n[Write]")
            up.write_fw(body)
            print("\n[Verify]")
            ok = up.verify_fw(body)
            print(f"\n{'Update OK!' if ok else 'Update FAILED!'}")
            if ok:
                print("\n[Done] Verify complete. Wait for the device to restart (official timing)...")
                time.sleep(15)
                import hid as _hid
                try:
                    up.t.dev.close()
                except Exception:
                    pass
                # CM_Reenumerate the parent device (USB composite device).
                import ctypes, subprocess
                from ctypes import wintypes
                cfgmgr32 = ctypes.WinDLL("cfgmgr32")
                cfgmgr32.CM_Locate_DevNodeW.argtypes = [ctypes.POINTER(wintypes.ULONG), wintypes.LPCWSTR, wintypes.ULONG]
                cfgmgr32.CM_Locate_DevNodeW.restype = wintypes.DWORD
                cfgmgr32.CM_Reenumerate_DevNode.argtypes = [wintypes.ULONG, wintypes.ULONG]
                cfgmgr32.CM_Reenumerate_DevNode.restype = wintypes.DWORD
                out = subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-PnpDevice | Where-Object {$_.InstanceId -like 'USB\\VID_FFCA*' -and $_.InstanceId -notlike '*&MI_*'} | Select-Object -First 1 -ExpandProperty InstanceId"],
                    capture_output=True, text=True, timeout=15).stdout.strip()
                print(f"  parent device: {out}")
                if out:
                    dev = wintypes.ULONG()
                    if cfgmgr32.CM_Locate_DevNodeW(ctypes.byref(dev), out, 0) == 0:
                        r = cfgmgr32.CM_Reenumerate_DevNode(dev, 0)
                        print(f"  CM_Reenumerate: {'OK' if r == 0 else f'failed ({r})'}")
                time.sleep(5)
                # Check that the device is back (use the normal-mode command 10 00).
                for attempt in range(20):
                    try:
                        d = _hid.device()
                        d.open(0xFFCA, 0x0125)
                        d.write(bytes([0x00]) + encrypt(bytes([0x10, 0x00])))
                        r = bytes(d.read(65, timeout_ms=3000))
                        d.close()
                        if len(r) >= 64:
                            print(f"Device restarted and is in normal mode (attempt {attempt+1})")
                            break
                    except Exception:
                        time.sleep(2)
                else:
                    print("WARNING: the device did not fully restart. Software cannot trigger an internal reset.")
                    print("  The update is complete. Unplug and replug the downloader USB once.")
        up.close()
    except Exception as e:
        print(f"Error: {e}")
        up.close()


if __name__ == "__main__":
    main()
