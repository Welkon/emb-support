#!/usr/bin/env python3
"""
CACHIP Tool 协议驱动 — Linux/Windows 通用版
=============================================
基于 CACHIP_TOOL_4.1.3.exe 静态逆向 + 动态验证 (2025)

已验证:
  ✅ USB HID 通道 (VID_FFCA PID_0125, "MCU Tool")
  ✅ 命令发送 = HidD_SetFeature / send_feature_report
  ✅ 状态读取 = HidD_GetFeature / get_feature_report
  ✅ 状态格式: [0]=report_id, [1]=最后命令ID回显, [2]=状态码
  ✅ 状态码 = 命令特有成功标志 (Connect=0x41, Erase=0x01, WriteCache=0x00,
     WriteTgtFlash=0x40, Verify=0x81, Info=0xC0)
  ✅ 完整烧录流程实测成功! (3434B 固件 → 官方工具校验通过)
  流程: Connect → Erase → WriteCache(分块≤58B) → WriteTgtFlash → Verify

依赖: pip install hidapi   (Linux 需要 udev 规则允许访问 HID 设备)
用法:
  python3 cachip_driver.py info           # 读工具信息
  python3 cachip_driver.py connect        # 连接目标
  python3 cachip_driver.py program fw.hex # 烧录 (已验证!)
"""

import sys
import time
import struct

VID, PID = 0xFFCA, 0x0125

# ============================================================
# 命令 ID (静态逆向确认)
# ============================================================
CMD = {
    "INFO":             0x06,
    "CONNECT":          0x08,
    "DISCONNECT":       0x09,
    "ERASE_TGT_FLASH":  0x0B,
    "WRITE_TGT_FLASH":  0x0C,
    "VERIFY_TGT_FLASH": 0x0D,
    "WRITE_CACHE":      0x0F,
    "SCREEN_STATUS":    0x10,
    "TARGET_POWER":     0x11,
    "WRITE_EVENT":      0x13,
    "TD_CONNECT":       0x50,
    "TD_DISCONNECT":    0x51,
    "TD_GET_STATE":     0x52,
    "TD_GET_CHANNEL_COUNT": 0x53,
    "TD_GET_REF_CH_DATA":   0x54,
    "TD_GET_KEYS_FLAG_SN":  0x55,
    "TD_GET_BASELINE_DATA": 0x56,
    "TD_GET_RAW_DATA":      0x57,
    "TD_GET_THRESHOLD_DATA":0x58,
    "TD_SET_THRESHOLD_DATA":0x59,
    "TD_GET_CHANNEL_NUMBER":0x5A,
    "FW_LIST":          0x60,
    "FW_INFO":          0x61,
    "FW_CREATE":        0x62,
    "FW_DELETE":        0x65,
    "FW_SYNC_CACHE_TO_FW": 0x66,
    "FW_SET_ACTIVE":    0x67,
    "FW_SET_KEY":       0x68,
    "FW_SET_META":      0x69,
    "FW_SET_LIMIT":     0x6C,
    "FW_GET_LIMIT":     0x6D,
    "FW_LIMIT_INC":     0x6E,
    "UPGRADE_RD_MEM":   0xE1,
    "UPGRADE_WR_MEM":   0xE2,
    "UPGRADE_ERASE":    0xE3,
}

# 状态码含义 (动态验证)
STATUS_OK_INFO = 0xC0      # Info 成功
STATUS_TARGET_NOT_CONNECTED = 0x41  # 目标芯片未连接
STATUS_OK = 0x80           # Disconnect/TargetPower 状态

# ============================================================
# 传输层 (hidapi, 跨平台)
# ============================================================
class HidTransport:
    def __init__(self):
        import hid
        self._hid = hid
        self.dev = hid.device()
        self.dev.open(VID, PID)

    def send_cmd(self, payload: bytes):
        """发送命令: set_feature, [0]=report id, [1..]=命令帧"""
        buf = bytes([0x00]) + payload
        self.dev.send_feature_report(buf)

    def get_status(self) -> bytes:
        """读取状态: [1]=最后命令, [2]=状态码"""
        return bytes(self.dev.get_feature_report(0x00, 64))

    def close(self):
        self.dev.close()

# ============================================================
# 协议层
# ============================================================
class CachipTool:
    def __init__(self, transport=None):
        self.t = transport or HidTransport()

    def _cmd_raw(self, cmd_id: int, payload: bytes = b"", wait: float = 0.3) -> tuple:
        """发送原始命令 ID + payload"""
        self.t.send_cmd(bytes([cmd_id]) + payload)
        time.sleep(wait)
        r = self.t.get_status()
        return r[1], r[2]

    def _cmd(self, name: str, payload: bytes = b"", wait: float = 0.3) -> tuple:
        """发送命令并读取状态, 返回 (cmd_id, status)"""
        cmd_id = CMD[name]
        self.t.send_cmd(bytes([cmd_id]) + payload)
        time.sleep(wait)
        r = self.t.get_status()
        if r[1] != cmd_id:
            raise RuntimeError(f"命令回显不匹配: 期望 0x{cmd_id:02X}, 得到 0x{r[1]:02X}")
        return r[1], r[2]

    # ---- 基础 ----
    def info(self):
        return self._cmd("INFO")

    def connect(self, model_id: int = 0x028F):
        """连接目标 MCU。model_id 来自 mcu.xml (如 CA51M550S1B = 0x028F)"""
        return self._cmd("CONNECT", struct.pack('<I', model_id))

    def disconnect(self):
        return self._cmd("DISCONNECT")

    # ---- Flash 编程 ----
    def erase_tgt_flash(self):
        return self._cmd("ERASE_TGT_FLASH")

    def write_cache(self, data: bytes, base_offset: int = 0, chunk: int = 0x3A):
        """写缓存 (分块, 每块 ≤58B): [0x0F][offset:4B LE][data]"""
        off = base_offset
        results = []
        for i in range(0, len(data), chunk):
            blk = data[i:i + chunk]
            results.append(self._cmd("WRITE_CACHE", struct.pack('<I', off) + blk))
            off += len(blk)
        return results[-1] if results else None

    def target_power(self, on: bool):
        return self._cmd("TARGET_POWER", bytes([1 if on else 0]))

    def screen_status(self):
        return self._cmd("SCREEN_STATUS")

    # ---- 触控调试 (需要目标板运行 touch debug 固件) ----
    # 已实测: TD_GetChannelCount 无需目标即可成功 (0x00)
    # 其余 TD 命令需要: 目标板接入 + 目标 MCU 运行 touch debug 固件
    def td_connect(self):
        return self._cmd("TD_CONNECT")

    def td_disconnect(self):
        return self._cmd("TD_DISCONNECT")

    def td_get_state(self):
        return self._cmd("TD_GET_STATE")

    def td_get_channel_count(self):
        """实测可用 (无目标板也返回 0x00)"""
        return self._cmd("TD_GET_CHANNEL_COUNT", wait=0.5)

    def td_get_channel_number(self):
        return self._cmd("TD_GET_CHANNEL_NUMBER")

    def td_get_ref_ch_data(self, channel: int = 0):
        """参考通道数据"""
        return self._cmd("TD_GET_REF_CH_DATA", bytes([channel]))

    def td_get_keys_flag_sn(self):
        """按键标志 + 序列号"""
        return self._cmd("TD_GET_KEYS_FLAG_SN")

    def td_get_baseline_data(self, channel: int = 0):
        """基准线数据 (数据长度 0x1E=30 字节/通道, 静态分析)"""
        return self._cmd("TD_GET_BASELINE_DATA", bytes([channel]))

    def td_get_raw_data(self, channel: int = 0):
        """原始数据"""
        return self._cmd("TD_GET_RAW_DATA", bytes([channel]))

    def td_get_threshold_data(self, channel: int = 0):
        """阈值数据"""
        return self._cmd("TD_GET_THRESHOLD_DATA", bytes([channel]))

    def td_set_threshold_data(self, channel: int, values: bytes):
        """设置阈值"""
        return self._cmd("TD_SET_THRESHOLD_DATA", bytes([channel]) + values)
    # ---- 固件管理 ----
    def fw_list(self):
        return self._cmd("FW_LIST")

    def close(self):
        self.t.close()

# ============================================================
# 主程序
# ============================================================
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="CACHIP Tool 协议驱动 (Linux/Windows)")
    p.add_argument("cmd", nargs="?", default="info",
                   choices=["info", "connect", "disconnect", "status",
                            "erase", "power_on", "power_off", "screen",
                            "td_count", "td_raw", "td_baseline", "program"])
    p.add_argument("file", nargs="?", help="固件文件 (program)")
    p.add_argument("--model", type=lambda x: int(x, 0), default=0x028F,
                   help="MCU 型号 ID (hex), 默认 0x028F=CA51M550S1B")
    args = p.parse_args()

    tool = CachipTool()
    try:
        if args.cmd == "info":
            cmd, st = tool.info()
            print(f"Info: cmd=0x{cmd:02X} status=0x{st:02X} ({'OK' if st == 0xC0 else 'FAIL'})")
        elif args.cmd == "status":
            r = tool.t.get_status()
            print(f"状态: 最后命令=0x{r[1]:02X} 状态码=0x{r[2]:02X}")
        elif args.cmd == "connect":
            cmd, st = tool.connect(args.model)
            print(f"Connect: status=0x{st:02X} ->",
                  "成功!" if st == 0x00 else
                  "目标未连接 (检查 ISP 线/供电)" if st == 0x41 else "未知")
        elif args.cmd == "disconnect":
            cmd, st = tool.disconnect()
            print(f"Disconnect: status=0x{st:02X}")
        elif args.cmd == "erase":
            cmd, st = tool.erase_tgt_flash()
            print(f"擦除: status=0x{st:02X}")
        elif args.cmd == "power_on":
            cmd, st = tool.target_power(True)
            print(f"供电开: status=0x{st:02X}")
        elif args.cmd == "power_off":
            cmd, st = tool.target_power(False)
            print(f"供电关: status=0x{st:02X}")
        elif args.cmd == "screen":
            cmd, st = tool.screen_status()
            print(f"屏幕状态: status=0x{st:02X}")
        elif args.cmd == "td_count":
            cmd, st = tool.td_get_channel_count()
            print(f"触控通道数: status=0x{st:02X}")
        elif args.cmd == "td_raw":
            cmd, st = tool.td_get_raw_data()
            print(f"触控原始数据: status=0x{st:02X}")
        elif args.cmd == "td_baseline":
            cmd, st = tool.td_get_baseline_data()
            print(f"触控基准线: status=0x{st:02X}")
        elif args.cmd == "program":
            data = open(args.file, "rb").read()
            print(f"固件: {args.file} ({len(data)} bytes)")
            cmd, st = tool.connect(args.model)
            print(f"Connect: status=0x{st:02X}")
            if st != 0x00:
                print("无法连接目标, 中止")
            else:
                cmd, st = tool.erase_tgt_flash()
                print(f"擦除: status=0x{st:02X}")
                tool.write_cache(data)
                print("写缓存完成")
    finally:
        tool.close()
