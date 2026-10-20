import sys
import types

import pytest


def _crc(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def _resp(op, data=b""):
    body = bytes([0xFA, op, 0x00, len(data)]) + data
    c = _crc(body)
    return body + bytes([c & 0xFF, (c >> 8) & 0xFF])


class FakeDp100:
    def __init__(self, *args, **kwargs):
        self.frames = []
        self.queue = []

    def write(self, frame):
        self.frames.append(frame)
        op = frame[1]
        if op == 0x10:
            d = bytearray(40)
            d[0:15] = b"DP100\x00" + b"\x00" * 9
            d[18], d[19] = 10, 1           # app version 1.0
            d[24:35] = b"SN123456789"
            self.queue.append(_resp(op, bytes(d)))
        elif op == 0x30:
            d = (12000).to_bytes(2, "little") + (5000).to_bytes(2, "little") \
                + (1000).to_bytes(2, "little") + (30000).to_bytes(2, "little") \
                + b"\x00" * 6 + bytes([2, 0])
            self.queue.append(_resp(op, d))
        elif op == 0x35:
            d = bytes([0, 1]) + (5000).to_bytes(2, "little") + (1000).to_bytes(2, "little") \
                + (5500).to_bytes(2, "little") + (1100).to_bytes(2, "little")
            self.queue.append(_resp(op, d))
        else:
            self.queue.append(_resp(op, b""))

    def read(self, n):
        return self.queue.pop(0)

    def close(self):
        pass


def test_dp100_driver(monkeypatch):
    fake = FakeDp100()
    hid = types.SimpleNamespace(Device=lambda *a, **k: fake,
                                enumerate=lambda vid, pid: [{"serial_number": "SN123456789"}])
    monkeypatch.setitem(sys.modules, "hid", hid)
    from psuscpi.drivers import Dp100Device
    dev = Dp100Device()
    assert dev.family == "dp100"
    assert "DP100" in dev.idn
    dev.set_voltage(1, 12)
    payload = fake.frames[-1]
    assert payload[1] == 0x35
    assert int.from_bytes(payload[6:8], "little") == 12000
    dev.set_current(1, 0.5)
    assert int.from_bytes(fake.frames[-1][8:10], "little") == 500
    dev.output(1, True)
    assert fake.frames[-1][5] == 1
    assert dev.measure_voltage(1) == pytest.approx(5.0)
    assert dev.measure_power(1) == pytest.approx(5.0)
    assert dev.measure_input_voltage(1) == pytest.approx(12.0)
    snap = dev.snapshot(1)
    assert snap["output"] == "ON"
    assert snap["setpoint"] == {"voltage": 5.0, "current": 1.0}
    assert snap["measurement"]["input_voltage"] == pytest.approx(12.0)
    assert snap["measurement"]["power"] == pytest.approx(5.0)
    assert dev.limits["max_voltage"] == 30.0
    assert dev.limits["max_ovp"] == 30.5
    dev.set_ovp(1, 30.5)
    dev.set_ocp(1, 5.05)
    with pytest.raises(RuntimeError):
        dev.set_ovp(1, 31)
    with pytest.raises(RuntimeError):
        dev.set_ocp(1, 5.1)


class FakeSerial:
    def __init__(self, port, baud, timeout=None, **kw):
        self.port = port
        self.responses = {
            "GETS": b"123050\rOK\r",
            "GETD": b"123404970\rOK\r",
        }
        self.writes = []
        self.buf = b""

    def reset_input_buffer(self):
        self.buf = b""

    def write(self, data):
        cmd = data.decode().strip()
        self.writes.append(cmd)
        self.buf = self.responses.get(cmd, b"OK\r")

    def read(self, n):
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def close(self):
        pass


def test_bk168x_driver(monkeypatch):
    serial = types.SimpleNamespace(Serial=FakeSerial)
    monkeypatch.setitem(sys.modules, "serial", serial)
    from psuscpi.drivers import Bk168xDevice
    dev = Bk168xDevice("/dev/fake", current_decimals=1)
    dev.set_voltage(1, 12.3)
    dev.set_current(1, 5.0)
    assert dev.get_voltage(1) == pytest.approx(12.3)
    assert dev.get_current(1) == pytest.approx(5.0)
    assert dev.measure_voltage(1) == pytest.approx(12.34)
    assert dev.measure_current(1) == pytest.approx(4.97)
    dev.output(1, True)
    assert dev.ser.writes[-1] == "SOUT0"


class FakeDpsSerial:
    def __init__(self, port, baud, timeout=None, **kw):
        self.q = bytearray()
        self.set_v = 0.0
        self.set_i = 0.0
        self.out = False
        self.rts = False

    @staticmethod
    def _checksum(reg, data):
        return (reg + len(data) + sum(data)) & 0xFF

    def _queue(self, cmd, reg, data=b""):
        self.q += bytes([0xF0, cmd, reg, len(data)]) + data + bytes([self._checksum(reg, data)])

    def _value(self, reg):
        import struct
        table = {
            0xDE: b"DPS-150\x00",
            0xE0: b"1.0\x00",
            0xE2: struct.pack("<f", 30.0),
            0xE3: struct.pack("<f", 5.0),
            0xC1: struct.pack("<f", self.set_v),
            0xC2: struct.pack("<f", self.set_i),
            0xC3: struct.pack("<fff", 12.0, 1.5, 18.0),
            0xDB: bytes([1 if self.out else 0]),
            0xD1: struct.pack("<f", 13.0),
            0xD2: struct.pack("<f", 2.0),
        }
        return table.get(reg, b"")

    def write(self, data):
        cmd, reg, ln = data[1], data[2], data[3]
        payload = data[4:4 + ln]
        if cmd == 0xC1:
            self._queue(0xC1, reg)
        elif cmd == 0xB1:
            import struct
            if reg == 0xC1:
                self.set_v = struct.unpack("<f", payload)[0]
            elif reg == 0xC2:
                self.set_i = struct.unpack("<f", payload)[0]
            elif reg == 0xDB:
                self.out = bool(payload[0])
            self._queue(0xB1, reg)
        elif cmd == 0xA1:
            self._queue(0xA1, reg, self._value(reg))

    def read(self, n):
        out = bytes(self.q[:n])
        del self.q[:n]
        return out

    def close(self):
        pass


def test_dps150_driver(monkeypatch):
    serial = types.SimpleNamespace(Serial=FakeDpsSerial)
    monkeypatch.setitem(sys.modules, "serial", serial)
    from psuscpi.drivers import Dps150Device
    dev = Dps150Device("/dev/fake")
    assert "DPS-150" in dev.idn
    dev.set_voltage(1, 12)
    dev.set_current(1, 1.5)
    assert dev.get_voltage(1) == pytest.approx(12.0)
    assert dev.get_current(1) == pytest.approx(1.5)
    assert dev.measure_power(1) == pytest.approx(18.0)
    dev.output(1, True)
    assert dev.output_state(1) == "ON"


def test_dp100_golden_frames():
    """Frames captured by weigu1/dp100_manipulator on real hardware."""
    from psuscpi.drivers import _dp_frame
    assert _dp_frame(0x10).hex() == "fb10000030c5"
    assert _dp_frame(0x30).hex() == "fb300000310f"
    assert _dp_frame(0x35, b"\x80").hex() == "fb35000180ce28"
