import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "scope.py"


def test_parse_block(scope):
    assert scope.parse_block(b"#15hello") == b"hello"
    assert scope.parse_block(b"#0raw\n") == b"raw\n"
    assert scope.parse_block(b"#210" + b"x" * 10) == b"x" * 10
    assert scope.parse_block(b"plain") == b"plain"


def test_socket_query_and_block(scope, rigol):
    inst = scope.SocketInstrument("127.0.0.1", rigol.port, timeout=2)
    try:
        assert "RIGOL" in inst.query("*IDN?")
        pre = inst.query(":WAVeform:PREamble?")
        assert pre.split(",")[2] == "100"
        data = inst.query_block(":WAV:DATA?")
        assert len(data) == 100 and data[0] == 0 and data[99] == 99
    finally:
        inst.close()


def test_q_first_fallback(scope):
    class Fake:
        def __init__(self):
            self.calls = []

        def query(self, cmd):
            self.calls.append(cmd)
            if cmd.startswith("WFMPre"):
                raise RuntimeError("unsupported")
            return "42"

    f = Fake()
    assert scope._q_first(f, ("WFMPre:XINcr?", "WFMOutpre:XINcr?")) == "42"
    assert len(f.calls) == 2


def test_detect_family(scope):
    assert scope.detect_family("RIGOL TECHNOLOGIES,DHO804") == "rigol"
    assert scope.detect_family("KEYSIGHT TECHNOLOGIES,DSOX1102G") == "keysight"
    assert scope.detect_family("TEKTRONIX,TBS1102B") == "tektronix"
    assert scope.detect_family("Siglent Technologies,SDS1104X-E") == "siglent"
    assert scope.detect_family("LECROY,WAVERUNNER 8104") == "lecroy"
    assert scope.detect_family("ACME,SCOPE-1") == "generic"
