import struct

import pytest


def test_rns_acquire(scope):
    class Fake:
        def write(self, cmd):
            pass

        def query_block(self, cmd):
            assert "CHANnel2:DATA?" in cmd
            return bytes([0, 1, 2])

        def query(self, cmd):
            table = {"XINCrement": "1e-6", "XORigin": "-5e-5",
                     "YINCrement": "0.01", "YORigin": "-0.5"}
            for key, value in table.items():
                if key in cmd:
                    return value
            raise AssertionError(cmd)

    meta, samples = scope.RnsDialect("R&S").acquire(Fake(), 2, None)
    volts = [(s - meta["yref"]) * meta["yincr"] + meta["yorig"] for s in samples]
    assert volts[0] == pytest.approx(-0.5)
    assert meta["xincr"] == pytest.approx(1e-6)


def make_hantek_packet(ch1, ch2):
    data = bytes(v & 0xFF for v in ch1) + bytes(v & 0xFF for v in ch2)
    meta = bytearray(99)
    meta[46:50] = b"11\x00\x00"  # CH1 and CH2 enabled
    header = b"#9" + f"{len(meta) + len(data):09d}".encode()
    header += f"{len(data):09d}".encode() + f"{0:09d}".encode()
    return header + bytes(meta) + data


def test_hantek_acquire(scope):
    class Fake:
        def __init__(self):
            ch1 = [(-100 + i % 200) for i in range(2000)]
            ch2 = [i % 200 for i in range(2000)]
            self.packet = make_hantek_packet(ch1, ch2)

        def query(self, cmd):
            if "SCALe" in cmd:
                return "1.0"
            if "OFFSet" in cmd:
                return "0.5"
            if "XINCrement" in cmd:
                return "1e-6"
            raise AssertionError(cmd)

        def read_message(self, cmd):
            assert cmd == "PRIVate:WAVeform:DATA:ALL?"
            return self.packet

    meta, samples = scope.HantekDialect("HANTEK").acquire(Fake(), 1, None)
    assert len(samples) == 2000
    volts = [(s - meta["yref"]) * meta["yincr"] + meta["yorig"] for s in samples]
    assert volts[0] == pytest.approx(-100 / 25.0 - 0.5)


def test_fluke_acquire(scope):
    class Fake:
        def write(self, cmd):
            pass

        def query_block(self, cmd):
            assert cmd.startswith("TRACe? CH1")
            return bytes([8]) + bytes(range(10)) + b"\x00\n"

        def query(self, cmd):
            if "PTPeak" in cmd:
                return "2.0"
            if "OFFSet" in cmd:
                return "0.0"
            if "SWEep:TIME" in cmd:
                return "1e-3"
            raise AssertionError(cmd)

    meta, samples = scope.FlukeDialect("FLUKE").acquire(Fake(), 1, None)
    assert samples == list(range(10))
    volts = [(s - meta["yref"]) * meta["yincr"] + meta["yorig"] for s in samples]
    assert volts[9] == pytest.approx(0.09)
    assert meta["xincr"] == pytest.approx(1e-4)
