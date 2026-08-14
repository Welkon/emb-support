#!/usr/bin/env python3
"""
CACHIP Tool 协议驱动 — 完整版 (Linux/Windows)
=============================================
基于 CACHIP_TOOL_4.1.3.exe 完整逆向 + 实测验证 (2025)

✅ 已验证: 完整烧录流程, OLED 显示"烧录成功 100%"
✅ 官方工具校验通过 (The verification was successful)

依赖: pip install hidapi pyserial (Linux 需 udev 规则)
"""

import struct
import time
from mcu_table import MODELS, FAMILIES

# ============================================================
# 常量
# ============================================================
VID, PID = 0xFFCA, 0x0125

# TEA 加密密钥 (官方 exe 内嵌)
TEA_KEY = bytes.fromhex("135a64305a5a1766b0500f664d0a075f")
_K0, _K1, _K2, _K3 = struct.unpack('<4I', TEA_KEY)
_DELTA = 0x9E3779B9

# ============================================================
# TEA 加密
# ============================================================
def _tea_encrypt_block(v0, v1):
    sm = 0
    for _ in range(32):
        sm = (sm + _DELTA) & 0xFFFFFFFF
        v0 = (v0 + ((((v1 << 4) & 0xFFFFFFFF) + _K0) ^ (v1 + sm) ^ (((v1 >> 5) & 0xFFFFFFFF) + _K1))) & 0xFFFFFFFF
        v1 = (v1 + ((((v0 << 4) & 0xFFFFFFFF) + _K2) ^ (v0 + sm) ^ (((v0 >> 5) & 0xFFFFFFFF) + _K3))) & 0xFFFFFFFF
    return v0, v1

def encrypt_frame(plain: bytes) -> bytes:
    """明文帧 → 填充到 64 → TEA ECB 加密 (8 块)"""
    padded = plain.ljust(64, b"\x00")[:64]
    out = b""
    for i in range(0, 64, 8):
        v0, v1 = struct.unpack('<2I', padded[i:i+8])
        e0, e1 = _tea_encrypt_block(v0, v1)
        out += struct.pack('<2I', e0, e1)
    return out

# ============================================================
# Checksum (官方算法: sum(固件+0xFF填充到flashSize) + flashSize*2 + 1)
# ============================================================
def calc_checksum(fw: bytes, flash_size_kb: int) -> int:
    size = flash_size_kb * 1024
    padded = fw + b'\xff' * (size - len(fw))
    return (sum(padded) + size * 2 + 1) & 0xFFFFFFFF

def find_model(name: str):
    """查型号: 返回 (model_id, flash_size_kb)"""
    if name not in MODELS:
        raise RuntimeError(f"未知型号: {name}")
    model = MODELS[name]
    # 找家族 (型号名前缀匹配)
    fs = None
    for fam, size in FAMILIES.items():
        if name.startswith(fam):
            fs = size
            break
    if fs is None:
        raise RuntimeError(f"找不到 {name} 的家族")
    return model, fs

# ============================================================
# Intel HEX 解析 (官方行为: 空洞填 0x00, 尾部 0xFF)
# ============================================================
def parse_hex(path: str) -> bytes:
    """解析 Intel HEX
    固件内空洞(未定义地址)填 0x00
    返回固件数据
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
    """固件 → 数据块列表
    每块 32 字节, 尾部补 0xFF, 加一块全 0xFF (官方行为)
    """
    blocks = []
    for i in range(0, len(fw), chunk):
        blk = fw[i:i+chunk].ljust(chunk, b'\xff')
        blocks.append(blk)
    blocks.append(b'\xff' * chunk)  # 补一块 (0xD80)
    return blocks

# ============================================================
# HID 传输 (中断端点, 官方通道)
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
            raise RuntimeError("CACHIP Tool 未连接!")
        self.h = self.kernel32.CreateFileW(path, 0xC0000000, 0x3, None, 3, 0, None)
        # hidapi 设备 (读响应用!)
        self._hid_dev = hid.device()
        self._hid_dev.open(VID, PID)

    def send_cmd(self, plain: bytes):
        """加密发送命令帧"""
        enc = encrypt_frame(plain)
        frame = (bytes([0x00]) + enc).ljust(65, b"\x00")[:65]
        written = self._ctypes.wintypes.DWORD()
        ok = self.kernel32.WriteFile(self.h, frame, 65, self._ctypes.byref(written), None)
        if not ok:
            raise RuntimeError(f"WriteFile 失败 err={self.kernel32.GetLastError()}")
        time.sleep(0.01)  # 块间节奏

    def command(self, plain: bytes, timeout=3000) -> bytes:
        """发送 + 读响应 + 校验状态, 返回响应明文 (64B)"""
        import hid as _hid
        # 用 hidapi 读 (Windows 重叠 IO 由 hidapi 处理!)
        d = self._hid_dev
        d.write(bytes([0x00]) + encrypt_frame(plain))
        r = bytes(d.read(65, timeout_ms=timeout))
        if len(r) < 64:
            raise RuntimeError(f"读响应超时/短: {len(r)}")
        from cachip_touch_debug import decrypt as _dec
        resp = _dec(r[-64:])
        # 校验: 响应 cmd 匹配!
        if resp[0] != plain[0]:
            raise RuntimeError(f"响应错位: 请求={plain[0]:02X} 响应={resp[0]:02X}")
        # 状态检查 (心跳 00/电源 11 特殊: 心跳带版本, 电源带电压!)
        if plain[0] not in (0x00, 0x11) and len(plain) > 1 and resp[1] != 0x00:
            raise RuntimeError(f"命令 0x{plain[0]:02X} 失败: 状态={resp[1]:02X}")
        return resp

    def close(self):
        self.kernel32.CloseHandle(self.h)

# ============================================================
# 烧录器
# ============================================================
class CachipBurner:
    def __init__(self, transport=None):
        self.t = transport or HidTransport()

    def _cmd(self, plain: bytes, timeout=3000):
        return self.t.command(plain, timeout)

    def burn(self, fw_path: str, model_name: str = "CA51M550S1B", chunk=32):
        """完整烧录 (官方流程, 全自动)
        model_name: 型号名 (如 CA51M550S1B)
        """
        model, flash_kb = find_model(model_name)
        fw = parse_hex(fw_path)
        checksum = calc_checksum(fw, flash_kb)
        blocks = prepare_firmware(fw, chunk)
        total = len(blocks)

        print(f"型号: {model_name} (ID=0x{model:04X}, Flash={flash_kb}KB)")
        print(f"固件: {len(fw)} bytes, {total} 块, Checksum=0x{checksum:08X}")

        # 1. 初始化
        self._cmd(bytes([0x00, 0x04]))              # 心跳
        self._cmd(bytes([0x10, 0x00]))
        self._cmd(bytes([0x10, 0x01]) + struct.pack('<I', checksum))
        self._cmd(bytes([0x10, 0x02, 0x01]))
        self._cmd(bytes([0x10, 0x04, 0x01]))

        # 2. Connect (检查目标芯片!)
        conn = (bytes([0x08]) + struct.pack('<H', model) + b'5M'
                + model_name.encode() + bytes(5)
                + model_name.encode() + bytes(5))
        r = self._cmd(conn, timeout=10000)   # Connect 响应慢 (目标检测)!
        got_model = struct.unpack('<H', r[2:4])[0]
        if got_model != model:
            raise RuntimeError(f"目标芯片型号不匹配! 期望 0x{model:04X} 检测到 0x{got_model:04X}")
        print(f"  ✓ 目标芯片已连接 (0x{got_model:04X})")

        # 3. 供电 + 检查电压!
        r = self._cmd(bytes([0x11, 0x03]))          # TargetPower
        v = struct.unpack('<H', r[1:3])[0] / 100.0
        if v < 2.0:
            raise RuntimeError(f"目标电压异常: {v:.2f}V (目标板供电?)")
        print(f"  ✓ 目标电压: {v:.2f}V")
        self._cmd(bytes([0x13, 0x01]))              # WriteEvent
        self._cmd(bytes([0x10, 0x02, 0x04]))
        self._cmd(bytes([0x10, 0x03, 0x00]))        # 进度 0

        # 4. 擦除
        r = self._cmd(bytes([0x0B, 0x02, 0, 0, 0, 0, 0, 0]), timeout=8000)
        print("  ✓ 擦除完成")
        time.sleep(1.0)

        # 5. 写入循环 (0F 缓存 + 0C 写Flash)
        addr = 0
        for i, blk in enumerate(blocks):
            self._cmd(bytes([0x0F, 0, 0, 0, 0, 0x20]) + blk)   # 写缓存
            self._cmd(bytes([0x0C]) + struct.pack('<I', addr) + struct.pack('<I', 0) + bytes([0x20, 0x00]))
            addr += chunk
            pct = min((i + 1) * 100 // total, 100)
            self._cmd(bytes([0x10, 0x03, pct]))
        print("写入完成")

        # 6. 切换校验
        self._cmd(bytes([0x10, 0x03, 100]))
        time.sleep(0.2)
        self._cmd(bytes([0x10, 0x02, 0x07]))        # 校验中
        time.sleep(0.2)
        self._cmd(bytes([0x10, 0x03, 0x00]))        # 进度 0
        time.sleep(0.2)

        # 7. 校验循环 (0D + 期望数据)
        addr = 0
        for i, blk in enumerate(blocks):
            self._cmd(bytes([0x0D]) + struct.pack('<I', addr) + bytes([0x20]) + blk)
            addr += chunk
            pct = min((i + 1) * 100 // total, 100)
            self._cmd(bytes([0x10, 0x03, pct]))
        print("校验完成")

        # 8. 完成
        self._cmd(bytes([0x10, 0x03, 100]))
        time.sleep(0.3)
        self._cmd(bytes([0x09]))                    # Disconnect
        time.sleep(0.3)
        self._cmd(bytes([0x10, 0x02, 0x05]))
        time.sleep(0.3)
        self._cmd(bytes([0x11, 0x00]))              # 断电
        print("烧录完成!")

    def close(self):
        self.t.close()

# ============================================================
# 主程序
# ============================================================
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="CACHIP Tool Linux 烧录工具")
    p.add_argument("hex", help="固件文件 (Intel HEX)")
    p.add_argument("--name", default="CA51M550S1B", help="MCU 型号名 (如 CA51M550S1B)")
    p.add_argument("--list", action="store_true", help="列出所有支持型号")
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
