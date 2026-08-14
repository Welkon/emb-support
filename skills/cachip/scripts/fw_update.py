#!/usr/bin/env python3
"""
CACHIP 下载器固件更新 (Linux/Windows)
======================================
官方固件更新协议 (UPGRADE_*, 实测):

  E0 = 升级开始        (响应 E0 02)
  E4 = 升级模式确认
  E3 = 2KB 扇区擦除    (E3 + 0000 + 地址4B + 01)
  E2 = 写内存          (E2 + 0000 + 地址4B + 长度1B + 00 + 数据)
  E1 = 读校验          (E1 + 0000 + 地址4B + 长度1B + 00 + 00...)
                        响应 = 读回数据!

固件布局: 0x08000000-0x08005800 = 引导区(保留!)
         0x08005800+ = 固件区(擦除+重写!)

使用:
  python3 fw_update.py verify fw.bin    # 读回校验 (无风险!)
  python3 fw_update.py update fw.bin    # 完整更新 (有风险!)
"""

import struct
import time
import argparse
import sys
import builtins
sys.path.insert(0, '.')
from cachip_touch_debug import TouchDebugger, encrypt

print = lambda *a, **k: builtins.print(*a, **k, flush=True)

FW_BASE = 0x08005800      # 固件区起点 (引导区 0x5800 保留!)
SECTOR = 0x800            # 2KB 扇区
WRITE_LEN = 56            # E2 写块
READ_LEN = 60             # E1 读块
VERIFY_END = 0x0802ACB0   # 校验结束地址 (代码末尾! 官方实测! 尾部配置区不校验!)


class FWUpdater:
    def __init__(self):
        self.td = TouchDebugger()
        self.t = self.td.t

    def _cmd(self, plain: bytes, timeout=3000) -> bytes:
        return self.t.command(plain, timeout)

    def start(self):
        """进入升级模式: E0 → 心跳 → E4(触发设备重启!) → 重开设备!"""
        try:
            r = self._cmd(bytes([0xE0]), timeout=3000)
            print(f"  升级开始 → 状态 {r[1]}")
        except Exception as e:
            print(f"  E0 无响应 ({e}) - 设备可能已在升级模式, 继续!")
        self._cmd(bytes([0x00, 0x07]))          # 心跳
        # E4 → 只发! (触发设备切升级模式, USB 可能重枚举!)
        try:
            self.t.dev.write(bytes([0x00]) + encrypt(bytes([0xE4, 0x01])))
        except Exception:
            pass
        print("  等待设备切换升级模式...")
        time.sleep(2.0)
        # 重连设备 (句柄可能失效)!
        import hid as _hid
        try:
            self.t.dev.close()
        except Exception:
            pass
        for attempt in range(10):
            try:
                self.t.dev = _hid.device()
                self.t.dev.open(0xFFCA, 0x0125)
                print(f"  设备重连 OK (尝试{attempt+1})")
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("设备重连失败!")

    def _cmd_retry(self, plain: bytes, want: int, timeout=5000, tries=3) -> bytes:
        """发送 + 读响应, 校验 cmd 匹配, 错位丢弃重试!"""
        for i in range(tries):
            try:
                r = self.t.command(plain, timeout)
                if r[0] == want:
                    return r
                print(f"  丢弃错位响应: {r[0]:02X} (期望 {want:02X})")
            except Exception as e:
                print(f"  重试{i+1}: {e}")
            time.sleep(0.5)
        raise RuntimeError(f"命令 0x{want:02X} 多次无响应!")
        # 重新打开设备 (USB 重枚举, 进入引导区 boot!)!
        import hid as _hid
        try:
            self.t.dev.close()
        except Exception:
            pass
        self.t.dev = _hid.device()
        for attempt in range(10):
            try:
                self.t.dev.open(0xFFCA, 0x0125)
                print(f"  设备已重连 (尝试{attempt+1})")
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("设备重连失败! 请重新插拔 USB!")

    def erase_sectors(self, size: int):
        """逐扇区擦除 (2KB)"""
        n = 0
        addr = FW_BASE
        while addr < FW_BASE + size:
            r = self._cmd_retry(bytes([0xE3]) + bytes(1) + struct.pack('<I', addr) + bytes([1]) + bytes([0]), 0xE3)
            addr += SECTOR
            n += 1
            if n % 10 == 0:
                print(f"  擦除 {n} 扇区 (0x{addr:X})...")
        print(f"  扇区擦除: {n} 个 (0x{FW_BASE:X} - 0x{addr:X})")

    def write_fw(self, fw: bytes):
        """写固件 (56B 块)"""
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
                print(f"  写入 {n} 块 (0x{addr:X})...")
        print(f"  写入: {n} 块 ({len(fw)} 字节)")

    def verify_fw(self, fw: bytes) -> bool:
        """读回校验 (60B 块, 到代码末尾 VERIFY_END!) """
        addr = FW_BASE
        n = 0
        ok = True
        # 校验到 VERIFY_END 含最后一块 (地址对齐官方 0x0802ACB0!)
        vlen = min(len(fw), (VERIFY_END - FW_BASE) + READ_LEN)
        for off in range(0, vlen, READ_LEN):
            frame = (bytes([0xE1]) + bytes(1) + struct.pack('<I', addr)
                     + bytes([READ_LEN]) + bytes([0]))
            r = self._cmd_retry(frame, 0xE1)
            # 响应: E1 + 00 + [长度] + [00] + [数据]
            got = r[4:4 + READ_LEN]
            want = fw[off:off + READ_LEN]
            if got[:len(want)] != want:
                ok = False
                if n < 3:
                    print(f"  ✗ 0x{addr:X}: 期望 {want[:8].hex()} 读到 {got[:8].hex()}")
            addr += READ_LEN
            n += 1
        # 补最后一块 0x0802ACB0 (官方最后校验地址, 触发设备自动重启!)!
        r = self._cmd_retry(bytes([0xE1]) + bytes(1) + struct.pack('<I', VERIFY_END) + bytes([READ_LEN]) + bytes([0]), 0xE1)
        got = r[4:4 + READ_LEN]
        off = VERIFY_END - FW_BASE
        want = fw[off:off + READ_LEN]
        if got[:len(want)] == want:
            print(f"  最后块 0x{VERIFY_END:X} ✅ (设备应自动重启!)")
        else:
            print(f"  最后块 0x{VERIFY_END:X} ✗ 不匹配!")
            ok = False
        print(f"  校验: {n + 1} 块 {'✅ 通过' if ok else '❌ 有错误'}")
        return ok

    def close(self):
        try:
            self.td.disconnect()
        except Exception:
            pass
        self.td.close()


def main():
    ap = argparse.ArgumentParser(description="CACHIP 下载器固件更新")
    ap.add_argument("cmd", choices=["verify", "update"], help="verify=读回校验(无风险) update=完整更新(风险!)")
    ap.add_argument("fw", help="固件 bin 文件")
    args = ap.parse_args()

    fw = open(args.fw, 'rb').read()
    # bin = 完整 Flash 映像! 固件区 = 0x5800 起!
    if len(fw) < 0x5800:
        print(f"错误: 固件太小 ({len(fw)} < 0x5800)")
        return
    body = fw[0x5800:]
    print(f"固件: {len(fw)}B, 固件区数据: {len(body)}B (0x{FW_BASE:X} 起)")

    up = FWUpdater()
    try:
        if args.cmd == "verify":
            up.start()
            print("\n[读回校验]")
            up.verify_fw(body)
        else:
            print("⚠️  更新下载器固件! 中断可能变砖 (引导区保留, 可重刷)")
            up.start()
            print("\n[扇区擦除]")
            up.erase_sectors(len(body))
            print("\n[写入]")
            up.write_fw(body)
            print("\n[校验]")
            ok = up.verify_fw(body)
            print(f"\n{'✅ 更新成功!' if ok else '❌ 更新失败!'}")
            if ok:
                print("\n[完成] 校验完成! 等待设备自动重启 (官方时序!)...")
                time.sleep(15)
                import hid as _hid
                try:
                    up.t.dev.close()
                except Exception:
                    pass
                # CM_Reenumerate 父设备 (USB 复合设备!)!
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
                print(f"  父设备: {out}")
                if out:
                    dev = wintypes.ULONG()
                    if cfgmgr32.CM_Locate_DevNodeW(ctypes.byref(dev), out, 0) == 0:
                        r = cfgmgr32.CM_Reenumerate_DevNode(dev, 0)
                        print(f"  CM_Reenumerate: {'✅' if r == 0 else f'失败 ({r})'}")
                time.sleep(5)
                # 验证设备恢复 (用 10 00 正常模式命令!)!
                for attempt in range(20):
                    try:
                        d = _hid.device()
                        d.open(0xFFCA, 0x0125)
                        d.write(bytes([0x00]) + encrypt(bytes([0x10, 0x00])))
                        r = bytes(d.read(65, timeout_ms=3000))
                        d.close()
                        if len(r) >= 64:
                            print(f"✅ 设备已重启并进入正常模式! (尝试{attempt+1})")
                            break
                    except Exception:
                        time.sleep(2)
                else:
                    print("⚠️ 设备未完全重启 (软件无法触发内部复位!)")
                    print("   ✅ 更新已完成! 请物理拔插下载器 USB 一次, 即恢复正常!")
        up.close()
    except Exception as e:
        print(f"错误: {e}")
        up.close()


if __name__ == "__main__":
    main()
