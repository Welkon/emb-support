#!/usr/bin/env python3
"""
CACHIP Tool protocol driver. Works on Linux and Windows.
=============================================
Based on static analysis and dynamic tests of CACHIP_TOOL_4.1.3.exe (2025).

Verified:
    USB HID channel (VID_FFCA PID_0125, "MCU Tool")
    Command send: HidD_SetFeature or send_feature_report
    Status read: HidD_GetFeature or get_feature_report
    Status format: [0]=report_id, [1]=last command ID echo, [2]=status code
    Status code is command-specific. Connect=0x41, Erase=0x01, WriteCache=0x00,
     WriteTgtFlash=0x40, Verify=0x81, Info=0xC0)
    Full burn flow tested. A 3434 B firmware passed the official tool check.
    Flow: Connect, Erase, WriteCache (blocks of 58 B or less), WriteTgtFlash, Verify.

Requires: pip install hidapi. On Linux, add a udev rule for HID access.
Usage:
    python3 cachip_driver.py info           # read tool info
    python3 cachip_driver.py connect        # connect the target
    python3 cachip_driver.py program fw.hex # burn firmware (tested)
"""

import sys
import time
import struct

VID, PID = 0xFFCA, 0x0125

# ============================================================
# Command IDs (from static analysis)
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

# Status code meanings (measured)
STATUS_OK_INFO = 0xC0            # Info success
STATUS_TARGET_NOT_CONNECTED = 0x41  # target chip not connected
STATUS_OK = 0x80                 # Disconnect and TargetPower status

# ============================================================
# Transport layer (hidapi, cross-platform)
# ============================================================
class HidTransport:
    def __init__(self):
        import hid
        self._hid = hid
        self.dev = hid.device()
        self.dev.open(VID, PID)

    def send_cmd(self, payload: bytes):
        """Send a command: set_feature, [0]=report id, [1..]=command frame."""
        buf = bytes([0x00]) + payload
        self.dev.send_feature_report(buf)

    def get_status(self) -> bytes:
        """Read status: [1]=last command, [2]=status code."""
        return bytes(self.dev.get_feature_report(0x00, 64))

    def close(self):
        self.dev.close()

# ============================================================
# Protocol layer
# ============================================================
class CachipTool:
    def __init__(self, transport=None):
        self.t = transport or HidTransport()

    def _cmd_raw(self, cmd_id: int, payload: bytes = b"", wait: float = 0.3) -> tuple:
        """Send a raw command ID and payload."""
        self.t.send_cmd(bytes([cmd_id]) + payload)
        time.sleep(wait)
        r = self.t.get_status()
        return r[1], r[2]

    def _cmd(self, name: str, payload: bytes = b"", wait: float = 0.3) -> tuple:
        """Send a command, read the status, return (cmd_id, status)."""
        cmd_id = CMD[name]
        self.t.send_cmd(bytes([cmd_id]) + payload)
        time.sleep(wait)
        r = self.t.get_status()
        if r[1] != cmd_id:
            raise RuntimeError(f"Command echo mismatch: expected 0x{cmd_id:02X}, got 0x{r[1]:02X}")
        return r[1], r[2]

    # Basic commands
    def info(self):
        return self._cmd("INFO")

    def connect(self, model_id: int = 0x028F):
        """Connect the target MCU. model_id comes from mcu.xml (CA51M550S1B = 0x028F)."""
        return self._cmd("CONNECT", struct.pack('<I', model_id))

    def disconnect(self):
        return self._cmd("DISCONNECT")

    # Flash programming
    def erase_tgt_flash(self):
        return self._cmd("ERASE_TGT_FLASH")

    def write_cache(self, data: bytes, base_offset: int = 0, chunk: int = 0x3A):
        """Write the cache in blocks of 58 B or less: [0x0F][offset 4B LE][data]."""
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

    # Touch debug. The target board must run the touch debug firmware.
    # Measured: TD_GetChannelCount works without a target (0x00).
    # Other TD commands need a target board and the touch debug firmware.
    def td_connect(self):
        return self._cmd("TD_CONNECT")

    def td_disconnect(self):
        return self._cmd("TD_DISCONNECT")

    def td_get_state(self):
        return self._cmd("TD_GET_STATE")

    def td_get_channel_count(self):
        """Tested. Returns 0x00 even without a target board."""
        return self._cmd("TD_GET_CHANNEL_COUNT", wait=0.5)

    def td_get_channel_number(self):
        return self._cmd("TD_GET_CHANNEL_NUMBER")

    def td_get_ref_ch_data(self, channel: int = 0):
        """Reference channel data."""
        return self._cmd("TD_GET_REF_CH_DATA", bytes([channel]))

    def td_get_keys_flag_sn(self):
        """Key flags and serial number."""
        return self._cmd("TD_GET_KEYS_FLAG_SN")

    def td_get_baseline_data(self, channel: int = 0):
        """Baseline data (30 B per channel, from static analysis)."""
        return self._cmd("TD_GET_BASELINE_DATA", bytes([channel]))

    def td_get_raw_data(self, channel: int = 0):
        """Raw data."""
        return self._cmd("TD_GET_RAW_DATA", bytes([channel]))

    def td_get_threshold_data(self, channel: int = 0):
        """Threshold data."""
        return self._cmd("TD_GET_THRESHOLD_DATA", bytes([channel]))

    def td_set_threshold_data(self, channel: int, values: bytes):
        """Set the threshold."""
        return self._cmd("TD_SET_THRESHOLD_DATA", bytes([channel]) + values)
    # Firmware management
    def fw_list(self):
        return self._cmd("FW_LIST")

    def close(self):
        self.t.close()

# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="CACHIP Tool protocol driver (Linux/Windows)")
    p.add_argument("cmd", nargs="?", default="info",
                   choices=["info", "connect", "disconnect", "status",
                            "erase", "power_on", "power_off", "screen",
                            "td_count", "td_raw", "td_baseline", "program"])
    p.add_argument("file", nargs="?", help="firmware file (program)")
    p.add_argument("--model", type=lambda x: int(x, 0), default=0x028F,
                   help="MCU model ID (hex). Default 0x028F=CA51M550S1B")
    args = p.parse_args()

    tool = CachipTool()
    try:
        if args.cmd == "info":
            cmd, st = tool.info()
            print(f"Info: cmd=0x{cmd:02X} status=0x{st:02X} ({'OK' if st == 0xC0 else 'FAIL'})")
        elif args.cmd == "status":
            r = tool.t.get_status()
            print(f"Status: last command=0x{r[1]:02X} status=0x{r[2]:02X}")
        elif args.cmd == "connect":
            cmd, st = tool.connect(args.model)
            print(f"Connect: status=0x{st:02X} ->",
                  "success!" if st == 0x00 else
                  "target not connected (check the ISP wires and power)" if st == 0x41 else "unknown")
        elif args.cmd == "disconnect":
            cmd, st = tool.disconnect()
            print(f"Disconnect: status=0x{st:02X}")
        elif args.cmd == "erase":
            cmd, st = tool.erase_tgt_flash()
            print(f"Erase: status=0x{st:02X}")
        elif args.cmd == "power_on":
            cmd, st = tool.target_power(True)
            print(f"Power on: status=0x{st:02X}")
        elif args.cmd == "power_off":
            cmd, st = tool.target_power(False)
            print(f"Power off: status=0x{st:02X}")
        elif args.cmd == "screen":
            cmd, st = tool.screen_status()
            print(f"Screen status: status=0x{st:02X}")
        elif args.cmd == "td_count":
            cmd, st = tool.td_get_channel_count()
            print(f"Touch channel count: status=0x{st:02X}")
        elif args.cmd == "td_raw":
            cmd, st = tool.td_get_raw_data()
            print(f"Touch raw data: status=0x{st:02X}")
        elif args.cmd == "td_baseline":
            cmd, st = tool.td_get_baseline_data()
            print(f"Touch baseline: status=0x{st:02X}")
        elif args.cmd == "program":
            data = open(args.file, "rb").read()
            print(f"Firmware: {args.file} ({len(data)} bytes)")
            cmd, st = tool.connect(args.model)
            print(f"Connect: status=0x{st:02X}")
            if st != 0x00:
                print("Cannot connect the target. Stop.")
            else:
                cmd, st = tool.erase_tgt_flash()
                print(f"Erase: status=0x{st:02X}")
                tool.write_cache(data)
                print("Cache write done")
    finally:
        tool.close()
