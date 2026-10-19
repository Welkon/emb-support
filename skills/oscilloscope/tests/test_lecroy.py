import struct

import pytest


def make_payload(count=10, gain=0.01, voff=0.5, interval=1e-6, hoff=-5e-5, bits=16):
    desc_len = 346
    buf = bytearray(desc_len)
    buf[0:8] = b"WAVEDESC"
    struct.pack_into("<h", buf, 34, 1)          # little endian
    struct.pack_into("<h", buf, 32, 1 if bits == 16 else 0)
    struct.pack_into("<i", buf, 36, desc_len)
    struct.pack_into("<i", buf, 40, 0)
    struct.pack_into("<i", buf, 48, 0)
    if bits == 16:
        data = struct.pack(f"<{count}h", *range(count))
    else:
        data = bytes(range(count))
    struct.pack_into("<i", buf, 60, len(data))
    struct.pack_into("<i", buf, 116, count)
    struct.pack_into("<f", buf, 156, gain)
    struct.pack_into("<f", buf, 160, voff)
    struct.pack_into("<f", buf, 176, interval)
    struct.pack_into("<d", buf, 180, hoff)
    return bytes(buf) + data


def test_parse_wavedesc(scope):
    meta, samples = scope.parse_wavedesc(make_payload())
    assert samples[:3] == [0, 1, 2]
    assert meta["points"] == 10
    volts = [(s - meta["yref"]) * meta["yincr"] + meta["yorig"] for s in samples]
    assert volts[0] == pytest.approx(-0.5)
    assert volts[1] == pytest.approx(-0.49)


def test_parse_wavedesc_8bit(scope):
    meta, samples = scope.parse_wavedesc(make_payload(bits=8, gain=0.1, voff=0.0))
    assert samples[:3] == [0, 1, 2]
    assert meta["format"] == 0


def test_lecroy_acquire(scope):
    class Fake:
        def query_block(self, cmd):
            assert cmd == "C1:WF? DAT2"
            return make_payload()

    meta, samples = scope.LeCroyDialect("LECROY").acquire(Fake(), 1, None)
    assert len(samples) == 10
    assert meta["xincr"] == pytest.approx(1e-6)


def test_bk_is_lecroy(scope):
    d = scope.BkPrecisionDialect("B&K")
    assert d.name == "bkprecision"
    assert d.measure_query("vpp", 2) == "C2:PAVA? VPP"
