#!/usr/bin/env python3
"""
CACHIP Writer / 软件管理 (固件管理器, Linux/Windows)
=====================================================
管理下载器内的固件槽 (离线烧录用):

  list      列出下载器固件
  info      查询固件信息
  create    添加固件到下载器 (分段写: 0F缓存 + 66同步)
  activate  激活固件 (作为烧录目标)
  delete    删除固件
  getlimit  查询烧录次数限制
  setkey    设置用户滚码密钥

协议 (实测):
  FW_List:      60 [索引] → 60 00 [名称] 00 [名称]...
  FW_Info:      61 [名长][名称] → 61 00 [大小4B][型号2B][槽地址4B]
  FW_Create:    62 [名长][名称][型号2B]["5M"][大小4B]
  FW_SetActive: 65 [名长][名称]
  FW_SyncCache: 66 [名长][名称][5B零][段偏移2B LE]  (每段 512B)
  FW_SetKey:    67 [名长][名称]
  FW_GetLimit:  69 [类型][名长][名称]
  写缓存:       0F [地址4B][长度][数据]  (58B/帧)

使用:
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

SEG_SIZE = 512          # 每段 512 字节 (同步偏移 × 256)
FRAME_SIZE = 58         # 0F 每帧数据 58 字节


class FWManager:
    def __init__(self):
        self.td = TouchDebugger()
        self.t = self.td.t

    def _cmd(self, plain: bytes) -> bytes:
        return self.t.command(plain)

    def _name(self, name: str, extra=b"") -> bytes:
        nb = name.encode()
        if len(nb) > 60:
            raise RuntimeError("名称太长 (≤60)")
        return bytes([len(nb)]) + nb + extra

    # ---------- 查询 ----------
    def list_fw(self):
        print("=== 下载器固件列表 ===")
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
            print(f"  槽{idx}: {' | '.join(names)}")
        return names

    def info(self, name: str):
        r = self._cmd(bytes([0x61]) + self._name(name))
        if r[0] != 0x61:
            print("  查询失败")
            return None
        size = struct.unpack('<I', r[2:6])[0]
        model = struct.unpack('<H', r[6:8])[0]
        slot = struct.unpack('<I', r[8:12])[0]
        print(f"  {name}: 大小={size} (0x{size:X}) 型号=0x{model:04X} 槽地址=0x{slot:X}")
        return {'size': size, 'model': model, 'slot': slot}

    # ---------- 写入 ----------
    def create(self, name: str, fw: bytes, model: int, slot_addr: int = None):
        print(f"创建固件槽: {name} ({len(fw)} 字节, 型号 0x{model:04X})")
        # 槽地址: 自动找最大槽地址 + 0xA780 (槽容量); 无固件时用起始 0x0833E0
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
                slot_addr = 0x08DB60  # 官方使用的槽地址
        # 1. Create: 62 [名长][名][4B零][型号2B]["5M"][槽地址4B]
        body = self._name(name) + bytes(4) + struct.pack('<H', model) + b'5M' + struct.pack('<I', slot_addr)
        r = self._cmd(bytes([0x62]) + body)
        print(f"  Create → 状态 {r[1]} (槽地址 0x{slot_addr:X})")

        # 2. 分段写入: 0F 缓存 + 66 同步
        # 官方 Sync: 66 [名长][名][00×5][段偏移/256 LE][00×2][段长度(0=满段,末段=精确)][段长度/256][00×3]
        off = 0
        while off < len(fw):
            seg = fw[off:off + SEG_SIZE]
            if len(seg) < SEG_SIZE:
                seg = seg + b'\xff' * (SEG_SIZE - len(seg))  # 末段填 0xFF!
            addr = 0
            while addr < len(seg):
                chunk = seg[addr:addr + FRAME_SIZE]
                frame = bytes([0x0F]) + struct.pack('<I', addr) + bytes([len(chunk)]) + chunk
                self._cmd(frame)
                addr += len(chunk)
            sync_off = (off // 256) & 0xFFFF
            # 满段格式: 末段长度=0, 长度/256=2 (末段精确长度>255 设备无响应!)
            body = (self._name(name) + bytes(5) + struct.pack('<H', sync_off)
                    + struct.pack('<H', 0) + struct.pack('<H', 2) + bytes(7))
            r = self._cmd(bytes([0x66]) + body)
            print(f"  同步 0x{off:X} (段偏移 {sync_off}, 512B) → 状态 {r[1]}")
            off += SEG_SIZE
        print("  写入完成")

    def activate(self, name: str):
        r = self._cmd(bytes([0x65]) + self._name(name) + bytes(16))
        print(f"激活 {name} → 状态 {r[1]}")

    def delete(self, name: str):
        """删除固件: 必须先 SetActive(65) 再 Delete(0x63)!"""
        r = self._cmd(bytes([0x65]) + self._name(name) + bytes(16))
        r = self._cmd(bytes([0x63]) + self._name(name))
        print(f"删除 {name} → 状态 {r[1]}")

    def get_limit(self, name: str, typ=3):
        r = self._cmd(bytes([0x69, typ]) + self._name(name))
        print(f"限制[{typ}] {name} → 状态 {r[1]} 数据 {r[2:10].hex()}")

    def set_key(self, name: str):
        r = self._cmd(bytes([0x67]) + self._name(name))
        print(f"设置密钥 {name} → 状态 {r[1]}")

    def close(self):
        try:
            self.td.disconnect()
        except Exception:
            pass
        self.td.close()


def main():
    ap = argparse.ArgumentParser(description="CACHIP 固件管理器 (Writer/软件管理)")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("list")
    p_info = sub.add_parser("info"); p_info.add_argument("name")
    p_create = sub.add_parser("create")
    p_create.add_argument("--name", required=True)
    p_create.add_argument("--model", type=lambda x: int(x, 0), default=0x028F)
    p_create.add_argument("fw", help="固件 bin 文件")
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
        print(f"错误: {e}")
        fwm.close()


if __name__ == "__main__":
    main()
