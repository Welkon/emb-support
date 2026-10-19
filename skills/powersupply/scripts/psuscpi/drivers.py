"""Device drivers: SCPI supplies plus HID/serial protocols.

The CLI talks to `Device` objects so non-SCPI supplies (ALIENTEK DP100 over
USB HID, FNIRSI DPS-150 and B&K 168x over serial) share the same commands.
"""

from __future__ import annotations

import struct
import time

from .common import die, load_config
from .dialects import make_dialect
from .transport import SerialInstrument, connect


def find_dp100() -> list[dict]:
    try:
        import hid
        return list(hid.enumerate(DP100_VID, DP100_PID))
    except Exception:
        return []


class Device:
    idn = ""
    family = ""
    resource = ""
    channels: tuple[int, ...] = (1,)
    supports_power = False
    supports_ovp = False
    supports_ocp = False
    supports_output_state = False

    def close(self):
        pass

    def set_voltage(self, ch, v): raise NotImplementedError
    def set_current(self, ch, a): raise NotImplementedError
    def get_voltage(self, ch): raise NotImplementedError
    def get_current(self, ch): raise NotImplementedError
    def measure_voltage(self, ch): raise NotImplementedError
    def measure_current(self, ch): raise NotImplementedError
    def measure_power(self, ch): return None
    def output(self, ch, on): raise NotImplementedError
    def output_state(self, ch): return None
    def set_ovp(self, ch, v): raise NotImplementedError
    def set_ocp(self, ch, a): raise NotImplementedError


class ScpiDevice(Device):
    def __init__(self, inst, dialect):
        self.inst = inst
        self.dialect = dialect
        self.idn = inst.query("*IDN?")
        self.family = dialect.name
        self.resource = inst.resource
        self.channels = dialect.channels
        self.supports_power = dialect.measure_power(1) is not None
        self.supports_ovp = dialect.ovp(1, 1) is not None
        self.supports_ocp = dialect.ocp(1, 1) is not None
        self.supports_output_state = dialect.output_state(1) is not None

    def _select(self, ch):
        cmd = self.dialect.select(ch)
        if cmd:
            self.inst.write(cmd)

    def close(self):
        self.inst.close()

    def set_voltage(self, ch, v):
        self._select(ch)
        self.inst.write(self.dialect.set_voltage(ch, v))

    def set_current(self, ch, a):
        self._select(ch)
        self.inst.write(self.dialect.set_current(ch, a))

    def get_voltage(self, ch):
        self._select(ch)
        return _qfloat(self.inst, self.dialect.get_voltage(ch))

    def get_current(self, ch):
        self._select(ch)
        return _qfloat(self.inst, self.dialect.get_current(ch))

    def measure_voltage(self, ch):
        self._select(ch)
        return _qfloat(self.inst, self.dialect.measure_voltage(ch))

    def measure_current(self, ch):
        self._select(ch)
        return _qfloat(self.inst, self.dialect.measure_current(ch))

    def measure_power(self, ch):
        q = self.dialect.measure_power(ch)
        if not q:
            return None
        self._select(ch)
        return _qfloat(self.inst, q)

    def output(self, ch, on):
        self._select(ch)
        self.inst.write(self.dialect.output(ch, on))

    def output_state(self, ch):
        q = self.dialect.output_state(ch)
        if not q:
            return None
        self._select(ch)
        return self.inst.query(q).strip()

    def set_ovp(self, ch, v):
        cmd = self.dialect.ovp(ch, v)
        if not cmd:
            raise RuntimeError("OVP is not supported by this dialect")
        self._select(ch)
        self.inst.write(cmd)

    def set_ocp(self, ch, a):
        cmd = self.dialect.ocp(ch, a)
        if not cmd:
            raise RuntimeError("OCP is not supported by this dialect")
        self._select(ch)
        self.inst.write(cmd)


def _qfloat(inst, cmd):
    try:
        text = inst.query(cmd).strip()
        return float(text) if text else None
    except Exception:
        return None


# --------------------------------------------------------------------- DP100

DP100_VID = 0x2E3C
DP100_PID = 0xAF01
_DP_H2D = 0xFB
_DP_D2H = 0xFA
_OP_INFO = 0x10
_OP_BASIC = 0x30
_OP_SET = 0x35
_SET_MODIFY = 0x20


def _crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def _dp_frame(opcode: int, data: bytes = b"") -> bytes:
    body = bytes([_DP_H2D, opcode, 0x00, len(data)]) + data
    crc = _crc16_modbus(body)
    return body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def _dp_parse(raw: bytes):
    if len(raw) < 6:
        raise RuntimeError(f"short DP100 response: {raw.hex()}")
    if raw[0] != _DP_D2H:
        raise RuntimeError(f"unexpected DP100 direction 0x{raw[0]:02x}: {raw.hex()}")
    length = raw[3]
    end = 4 + length + 2
    if len(raw) < end:
        raise RuntimeError(f"truncated DP100 response: {raw.hex()}")
    if _crc16_modbus(raw[:end]) != 0:
        raise RuntimeError(f"DP100 CRC error: {raw.hex()}")
    return raw[1], raw[4:4 + length]


class Dp100Device(Device):
    """ALIENTEK DP100 USB-HID supply (VID:PID 2e3c:af01).

    Official specs (DP100 user manual V1.2): 0-30 V, 0-5 A, 100 W,
    10 mV / 1 mA setpoint resolution, OVP 0-30.5 V, OCP 0-5.05 A.
    """

    family = "dp100"
    MAX_VOLTAGE = 30.0
    MAX_CURRENT = 5.0
    MAX_OVP = 30.5
    MAX_OCP = 5.05
    MAX_POWER = 100.0
    channels = (1,)
    supports_power = True
    supports_ovp = True
    supports_ocp = True
    supports_output_state = True

    def __init__(self, path=None):
        try:
            import hid
        except ImportError:
            die("hidapi is required for DP100. Run: psu.py setup")
        try:
            self.dev = hid.Device(path=path) if path else hid.Device(DP100_VID, DP100_PID)
        except Exception as e:
            die(f"cannot open DP100: {e} (check udev/hidraw permissions)")
        self.resource = f"hid:{DP100_VID:04x}:{DP100_PID:04x}"
        info = self._device_info()
        self.idn = (f"ALIENTEK,DP100,{info.get('serial_number_hex', '?')},"
                    f"{info.get('app_version', '?')}")
        self._max_v = self._basic().get("vo_max_mv", 30000) / 1000.0
        s = self._settings()
        self._v = s["vset_v"]
        self._i = s["iset_a"]
        self._ovp = s["ovp_v"]
        self._ocp = s["ocp_a"]
        self._out = bool(s["state"])
        self.limits = {"max_voltage": self.MAX_VOLTAGE,
                       "max_current": self.MAX_CURRENT,
                       "max_ovp": self.MAX_OVP,
                       "max_ocp": self.MAX_OCP,
                       "max_power": self.MAX_POWER}

    def close(self):
        try:
            self.dev.close()
        except Exception:
            pass

    def _read_report(self) -> bytes:
        """Read one 64-byte HID report, with a finite timeout when supported."""
        for kwargs in ({"timeout_ms": 1000}, {"timeout": 1000}):
            try:
                return bytes(self.dev.read(64, **kwargs))
            except TypeError:
                continue
        return bytes(self.dev.read(64))

    def _exchange(self, opcode, data=b""):
        self.dev.write(_dp_frame(opcode, data))
        time.sleep(0.05)
        try:
            raw = self._read_report()
        except OSError as e:
            raise RuntimeError(f"DP100 HID read failed: {e}") from e
        if not raw:
            raise RuntimeError(
                "DP100 did not respond (HID read timeout). Check the cable, "
                "hidraw permissions, and that no other program holds the device.")
        op, payload = _dp_parse(raw)
        if op != opcode:
            raise RuntimeError(f"unexpected DP100 opcode 0x{op:02x}, expected 0x{opcode:02x}")
        return payload

    def _device_info(self):
        d = self._exchange(_OP_INFO)
        return {
            "device_type": d[0:15].split(b"\x00")[0].decode(errors="replace"),
            "app_version": ((d[19] << 8) | d[18]) / 10,
            "serial_number_hex": d[24:35].hex(),
        }

    def _basic(self):
        d = self._exchange(_OP_BASIC)
        return {
            "vout_mv": (d[3] << 8) | d[2],
            "iout_ma": (d[5] << 8) | d[4],
            "vo_max_mv": (d[7] << 8) | d[6],
            "out_mode": d[14],
            "work_state": d[15],
        }

    def _settings(self):
        d = self._exchange(_OP_SET, bytes([0x80]))
        return {
            "state": d[1],
            "vset_v": ((d[3] << 8) | d[2]) / 1000,
            "iset_a": ((d[5] << 8) | d[4]) / 1000,
            "ovp_v": ((d[7] << 8) | d[6]) / 1000,
            "ocp_a": ((d[9] << 8) | d[8]) / 1000,
        }

    def _apply(self):
        if self._v < 0 or self._v > min(self.MAX_VOLTAGE, self._max_v) + 1e-9:
            raise RuntimeError(
                f"DP100 voltage {self._v} V outside 0..{min(self.MAX_VOLTAGE, self._max_v):.2f} V")
        if self._i < 0 or self._i > self.MAX_CURRENT + 1e-9:
            raise RuntimeError(f"DP100 current {self._i} A outside 0..{self.MAX_CURRENT:.2f} A")
        v_mv = int(round(self._v * 1000))
        i_ma = int(round(self._i * 1000))
        ovp = int(round((self._ovp if self._ovp is not None else self._v * 1.1) * 1000))
        ocp = int(round((self._ocp if self._ocp is not None else self._i * 1.1) * 1000))
        payload = bytes([_SET_MODIFY, 1 if self._out else 0,
                         v_mv & 0xFF, (v_mv >> 8) & 0xFF,
                         i_ma & 0xFF, (i_ma >> 8) & 0xFF,
                         ovp & 0xFF, (ovp >> 8) & 0xFF,
                         ocp & 0xFF, (ocp >> 8) & 0xFF])
        self._exchange(_OP_SET, payload)

    def set_voltage(self, ch, v):
        self._v = float(v)
        self._apply()

    def set_current(self, ch, a):
        self._i = float(a)
        self._apply()

    def get_voltage(self, ch):
        return self._settings()["vset_v"]

    def get_current(self, ch):
        return self._settings()["iset_a"]

    def measure_voltage(self, ch):
        return self._basic()["vout_mv"] / 1000

    def measure_current(self, ch):
        return self._basic()["iout_ma"] / 1000

    def measure_power(self, ch):
        b = self._basic()
        return b["vout_mv"] * b["iout_ma"] / 1e6

    def output(self, ch, on):
        self._out = bool(on)
        self._apply()

    def output_state(self, ch):
        b = self._basic()
        return "ON" if b["out_mode"] == 1 else "OFF"

    def set_ovp(self, ch, v):
        if v < 0 or v > self.MAX_OVP + 1e-9:
            raise RuntimeError(f"DP100 OVP {v} V outside 0..{self.MAX_OVP} V")
        self._ovp = float(v)
        self._apply()

    def set_ocp(self, ch, a):
        if a < 0 or a > self.MAX_OCP + 1e-9:
            raise RuntimeError(f"DP100 OCP {a} A outside 0..{self.MAX_OCP} A")
        self._ocp = float(a)
        self._apply()


# -------------------------------------------------------------------- BK168x

class Bk168xDevice(Device):
    """B&K 1685B/1687B/1688B and Manson HCS-3xxx (ASCII over serial)."""

    family = "bk168x"
    channels = (1,)
    supports_power = False
    supports_ovp = True
    supports_ocp = True
    supports_output_state = True

    def __init__(self, port, current_decimals: int = 1, timeout: float = 1.0):
        try:
            import serial
        except ImportError:
            die("pyserial is required for B&K 168x. Run: psu.py setup")
        self.ser = serial.Serial(port, 9600, timeout=timeout)
        self.cdec = current_decimals
        self.resource = f"ASRL::{port}"
        self.idn = f"B&K,168x,{port},serial"

    def _cmd(self, command: str) -> list[str]:
        self.ser.reset_input_buffer()
        self.ser.write(command.encode() + b"\r")
        lines, buf = [], b""
        deadline = time.time() + 3
        while time.time() < deadline:
            chunk = self.ser.read(64)
            if chunk:
                buf += chunk
                while b"\r" in buf:
                    line, _, buf = buf.partition(b"\r")
                    text = line.decode(errors="replace").strip()
                    if text == "OK":
                        return lines
                    if text:
                        lines.append(text)
        raise RuntimeError(f"no OK from supply for {command!r}")

    def close(self):
        self.ser.close()

    def _set(self, prefix, value, decimals):
        self._cmd(f"{prefix}{int(round(value * 10 ** decimals)):0{3 + decimals}d}")

    def set_voltage(self, ch, v):
        self._set("VOLT", v, 1)

    def set_current(self, ch, a):
        self._set("CURR", a, self.cdec)

    def _settings(self):
        raw = self._cmd("GETS")[0]
        v = int(raw[0:3]) / 10
        i = int(raw[3:]) / (10 ** self.cdec)
        return v, i

    def get_voltage(self, ch):
        return self._settings()[0]

    def get_current(self, ch):
        return self._settings()[1]

    def _display(self):
        raw = self._cmd("GETD")[0]
        return int(raw[0:4]) / 100, int(raw[4:8]) / 100, raw[8:9]

    def measure_voltage(self, ch):
        return self._display()[0]

    def measure_current(self, ch):
        return self._display()[1]

    def measure_power(self, ch):
        v, i, _ = self._display()
        return v * i

    def output(self, ch, on):
        self._cmd("SOUT0" if on else "SOUT1")

    def output_state(self, ch):
        return None

    def set_ovp(self, ch, v):
        self._set("SOVP", v, 1)

    def set_ocp(self, ch, a):
        self._set("SOCP", a, self.cdec)


# ------------------------------------------------------------------- factory

def open_device(a) -> Device:
    cfg = load_config()
    family = getattr(a, "family", None) or cfg.get("family")
    serial_port = getattr(a, "serial", None) or cfg.get("serial")
    hid_name = getattr(a, "hid", None) or cfg.get("hid")

    if hid_name == "dp100":
        return Dp100Device(getattr(a, "hid_path", None))

    host = getattr(a, "host", None) or cfg.get("host")
    resource = getattr(a, "resource", None) or cfg.get("resource")
    if not any((host, resource, serial_port, hid_name)) and find_dp100():
        return Dp100Device()

    if serial_port:
        if family == "dps150":
            return Dps150Device(serial_port)
        if family == "bk168x" or family == "bk":
            return Bk168xDevice(serial_port, int(getattr(a, "current_decimals", 1) or 1))
        inst = SerialInstrument(serial_port, int(getattr(a, "baud", None) or cfg.get("baud") or 9600),
                                float(getattr(a, "timeout", None) or 3.0))
        return ScpiDevice(inst, make_dialect("", family))

    inst = connect(a)
    return ScpiDevice(inst, make_dialect(inst.query("*IDN?"), family))


class Dps150Device(Device):
    """FNIRSI DPS-150 USB-CDC supply (F1/F0 framed float32 registers)."""

    family = "dps150"
    channels = (1,)
    supports_power = True
    supports_ovp = True
    supports_ocp = True
    supports_output_state = True

    H2D = 0xF1
    D2H = 0xF0
    CMD_READ = 0xA1
    CMD_WRITE = 0xB1
    CMD_SESSION = 0xC1

    def __init__(self, port, baud=115200, timeout=0.5):
        try:
            import serial
        except ImportError:
            die("pyserial is required for DPS-150. Run: psu.py setup")
        self.ser = serial.Serial(port, baud, timeout=timeout)
        try:
            self.ser.rts = True
        except Exception:
            pass
        self.resource = f"ASRL::{port}"
        self._packet(self.CMD_SESSION, 0x00, b"\x01")
        self.idn = f"FNIRSI,DPS-150,{self._read_string(0xDE)},{self._read_string(0xE0)}"
        self._max_v = self._read_float(0xE2)
        self._max_i = self._read_float(0xE3)

    def close(self):
        self.ser.close()

    @staticmethod
    def _checksum(reg, data):
        return (reg + len(data) + sum(data)) & 0xFF

    def _packet(self, cmd, reg, data=b""):
        body = bytes([self.H2D, cmd, reg, len(data)]) + data
        self.ser.write(body + bytes([self._checksum(reg, data)]))
        return self._response()

    def _response(self):
        header = self.ser.read(4)
        if len(header) < 4:
            raise RuntimeError(f"short DPS-150 response: {header.hex()}")
        if header[0] != self.D2H:
            raise RuntimeError(f"unexpected DPS-150 header 0x{header[0]:02x}")
        length = header[3]
        data = self.ser.read(length)
        crc = self.ser.read(1)
        if not crc or self._checksum(header[2], data) != crc[0]:
            raise RuntimeError("DPS-150 checksum error")
        return header[2], data

    def _write_float(self, reg, value):
        self._packet(self.CMD_WRITE, reg, struct.pack("<f", float(value)))

    def _read_float(self, reg):
        _, data = self._packet(self.CMD_READ, reg)
        return struct.unpack("<f", data[:4])[0] if len(data) >= 4 else None

    def _read_u8(self, reg):
        _, data = self._packet(self.CMD_READ, reg)
        return data[0] if data else None

    def _read_string(self, reg):
        _, data = self._packet(self.CMD_READ, reg)
        return data.split(b"\x00")[0].decode(errors="replace")

    def set_voltage(self, ch, v):
        if v > self._max_v + 1e-9:
            raise RuntimeError(f"DPS-150 max voltage is {self._max_v:.2f} V")
        self._write_float(0xC1, v)

    def set_current(self, ch, a):
        if a > self._max_i + 1e-9:
            raise RuntimeError(f"DPS-150 max current is {self._max_i:.2f} A")
        self._write_float(0xC2, a)

    def get_voltage(self, ch): return self._read_float(0xC1)
    def get_current(self, ch): return self._read_float(0xC2)

    def _meas(self):
        _, data = self._packet(self.CMD_READ, 0xC3)
        if len(data) < 12:
            return None, None, None
        return struct.unpack("<3f", data[:12])

    def measure_voltage(self, ch): return self._meas()[0]
    def measure_current(self, ch): return self._meas()[1]
    def measure_power(self, ch): return self._meas()[2]

    def output(self, ch, on):
        self._packet(self.CMD_WRITE, 0xDB, bytes([1 if on else 0]))

    def output_state(self, ch):
        value = self._read_u8(0xDB)
        return None if value is None else ("ON" if value else "OFF")

    def set_ovp(self, ch, v): self._write_float(0xD1, v)
    def set_ocp(self, ch, a): self._write_float(0xD2, a)
