#!/usr/bin/env python3
"""
CACHIP Writer and slot manager (Linux/Windows)
=====================================================
Manage the firmware slots in the downloader for offline burning:

    list      list the downloader firmware
    info      show firmware information
    create    add firmware to the downloader (0F cache plus 66 sync)
    activate  activate firmware as the burn target
    delete    delete firmware
    getlimit  read the burn count limit
    setkey    set the user rolling-code key

Protocol (measured):
    FW_List:      60 [index] -> 60 00 [name] 00 [name]...
    FW_Info:      61 [name length][name] -> 61 00 [size 4B][model 2B][slot 4B]
    FW_Create:    62 [name length][name][model 2B]["5M"][size 4B]
    FW_SetActive: 65 [name length][name]
    FW_SyncCache: 66 [name length][name][5B zero][segment offset 2B LE]  (512 B per segment)
    FW_SetKey:    67 [name length][name]
    FW_GetLimit:  69 [type][name length][name]
    Write cache:  0F [address 4B][length][data]  (58 B per frame)

Usage:
  python3 fw_manager.py list
  python3 fw_manager.py create --name MY_FW --model 0x028F fw.bin
  python3 fw_manager.py activate --name MY_FW
"""

import struct
import time
import argparse
import sys
import builtins
sys.path.insert(0, '.')
from cachip_touch_debug import TouchDebugger, encrypt

print = lambda *a, **k: builtins.print(*a, **k, flush=True)

SEG_SIZE = 512          # 512 bytes per segment (sync offset x 256)
FRAME_SIZE = 58         # 58 data bytes per 0F frame


class FWManager:
    def __init__(self):
        self.td = TouchDebugger()
        self.t = self.td.t

    def _cmd(self, plain: bytes) -> bytes:
        return self.t.command(plain)

    def _name(self, name: str, extra=b"") -> bytes:
        nb = name.encode()
        if len(nb) > 60:
            raise RuntimeError("Name too long (max 60)")
        return bytes([len(nb)]) + nb + extra

    # Query commands
    def list_fw(self):
        print("=== Downloader firmware list ===")
        for idx in range(8):
            r = self._cmd(bytes([0x60, idx]))
            if r[0] != 0x60:
                break
            names = []
            rest = r[2:]
            for part in rest.split(b'\x00'):
                if part:
                    try:
                        names.append(part.decode('ascii'))
                    except Exception:
                        names.append(part.hex())
            if not names:
                break
            print(f"  slot {idx}: {' | '.join(names)}")
        return names

    def info(self, name: str):
        r = self._cmd(bytes([0x61]) + self._name(name))
        if r[0] != 0x61:
            print("  query failed")
            return None
        size = struct.unpack('<I', r[2:6])[0]
        model = struct.unpack('<H', r[6:8])[0]
        slot = struct.unpack('<I', r[8:12])[0]
        print(f"  {name}: size={size} (0x{size:X}) model=0x{model:04X} slot=0x{slot:X}")
        return {'size': size, 'model': model, 'slot': slot}

    # Write commands
    def create(self, name: str, fw: bytes, model: int, slot_addr: int = None):
        print(f"Create slot: {name} ({len(fw)} bytes, model 0x{model:04X})")
        # Slot address: find the largest slot address and add 0xA780. With no firmware, start at 0x0833E0.
        if slot_addr is None:
            slot_addr = 0x0833E0
            max_addr = 0
            for idx in range(8):
                r = self._cmd(bytes([0x60, idx]))
                if r[0] != 0x60:
                    break
                for part in r[2:].split(b'\x00'):
                    if part:
                        try:
                            nm = part.decode('ascii')
                            ri = self._cmd(bytes([0x61]) + self._name(nm))
                            if ri[0] == 0x61:
                                sa = struct.unpack('<I', ri[8:12])[0]
                                if sa > max_addr:
                                    max_addr = sa
                        except Exception:
                            pass
            if max_addr:
                slot_addr = 0x08DB60  # slot address used by the official tool
        # 1. Create: 62 [name length][name][4B zero][model 2B]["5M"][slot 4B]
        body = self._name(name) + bytes(4) + struct.pack('<H', model) + b'5M' + struct.pack('<I', slot_addr)
        r = self._cmd(bytes([0x62]) + body)
        print(f"  Create -> state {r[1]} (slot 0x{slot_addr:X})")

        # 2. Write in segments: 0F cache plus 66 sync
        # Official Sync: 66 [name length][name][00x5][segment offset/256 LE][00x2][segment length (0=full)][length/256][00x3]
        off = 0
        while off < len(fw):
            seg = fw[off:off + SEG_SIZE]
            if len(seg) < SEG_SIZE:
                seg = seg + b'\xff' * (SEG_SIZE - len(seg))  # pad the last segment with 0xFF
            addr = 0
            while addr < len(seg):
                chunk = seg[addr:addr + FRAME_SIZE]
                frame = bytes([0x0F]) + struct.pack('<I', addr) + bytes([len(chunk)]) + chunk
                self._cmd(frame)
                addr += len(chunk)
            sync_off = (off // 256) & 0xFFFF
            # Full segment: last length 0, length/256=2. A precise last length above 255 makes the device silent.
            body = (self._name(name) + bytes(5) + struct.pack('<H', sync_off)
                    + struct.pack('<H', 0) + struct.pack('<H', 2) + bytes(7))
            r = self._cmd(bytes([0x66]) + body)
            print(f"  sync 0x{off:X} (segment offset {sync_off}, 512 B) -> state {r[1]}")
            off += SEG_SIZE
        print("  write done")

    def activate(self, name: str):
        r = self._cmd(bytes([0x65]) + self._name(name) + bytes(16))
        print(f"Activate {name} -> state {r[1]}")

    def delete(self, name: str):
        """Delete firmware. Call SetActive (65) before Delete (0x63)."""
        r = self._cmd(bytes([0x65]) + self._name(name) + bytes(16))
        r = self._cmd(bytes([0x63]) + self._name(name))
        print(f"Delete {name} -> state {r[1]}")

    def get_limit(self, name: str, typ=3):
        r = self._cmd(bytes([0x69, typ]) + self._name(name))
        print(f"Limit[{typ}] {name} -> state {r[1]} data {r[2:10].hex()}")

    def set_key(self, name: str):
        r = self._cmd(bytes([0x67]) + self._name(name))
        print(f"Set key {name} -> state {r[1]}")

    def close(self):
        try:
            self.td.disconnect()
        except Exception:
            pass
        self.td.close()


def main():
    ap = argparse.ArgumentParser(description="CACHIP firmware manager (Writer and slots)")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("list")
    p_info = sub.add_parser("info"); p_info.add_argument("name")
    p_create = sub.add_parser("create")
    p_create.add_argument("--name", required=True)
    p_create.add_argument("--model", type=lambda x: int(x, 0), default=0x028F)
    p_create.add_argument("fw", help="firmware BIN file")
    p_act = sub.add_parser("activate"); p_act.add_argument("name")
    p_del = sub.add_parser("delete"); p_del.add_argument("name")
    p_lim = sub.add_parser("getlimit"); p_lim.add_argument("name")
    p_key = sub.add_parser("setkey"); p_key.add_argument("name")
    args = ap.parse_args()

    fwm = FWManager()
    try:
        fwm.td.connect()
        if args.cmd == "list":
            fwm.list_fw()
        elif args.cmd == "info":
            fwm.info(args.name)
        elif args.cmd == "create":
            fw = open(args.fw, 'rb').read()
            fwm.create(args.name, fw, args.model)
        elif args.cmd == "activate":
            fwm.activate(args.name)
        elif args.cmd == "delete":
            fwm.delete(args.name)
        elif args.cmd == "getlimit":
            for t in (3, 4, 7):
                fwm.get_limit(args.name, t)
        elif args.cmd == "setkey":
            fwm.set_key(args.name)
        else:
            ap.print_help()
        fwm.close()
    except Exception as e:
        print(f"Error: {e}")
        fwm.close()


if __name__ == "__main__":
    main()
