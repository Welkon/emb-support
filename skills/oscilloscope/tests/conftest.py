import importlib.util
import socket
import sys
import socketserver
import threading
from pathlib import Path

import pytest

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def block(data: bytes) -> bytes:
    n = str(len(data))
    return b"#" + str(len(n)).encode() + n.encode() + data


class MockScope:
    """Minimal SCPI instrument over TCP, with Rigol and Tek dialects."""

    def __init__(self, family="rigol"):
        self.family = family
        self.commands = []
        self.samples = list(range(100))
        if family == "tektronix":
            self.idn = "TEKTRONIX,TBS1102B,C012345,CFG100"
        else:
            self.idn = "RIGOL TECHNOLOGIES,DHO804,DHO8A000000001,00.01.00"
        scope = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                for raw in self.rfile:
                    cmd = raw.decode(errors="replace").strip()
                    if not cmd:
                        continue
                    resp = scope.handle(cmd)
                    if resp is None:
                        continue
                    self.wfile.write(resp if isinstance(resp, bytes) else resp.encode() + b"\n")

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.server.scope = self
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def handle(self, cmd):
        self.commands.append(cmd)
        u = cmd.upper()
        if u == "*IDN?":
            return self.idn
        if u in (":WAVEFORM:DATA?", ":WAV:DATA?", "WAV:DATA?"):
            return block(bytes(self.samples))
        if "?" in u:
            if "XINCR" in u:
                return "1e-06"
            if "XZERO" in u:
                return "-5e-05"
            if "PT_OFF" in u:
                return "0"
            if "YMULT" in u:
                return "0.01"
            if "YZERO" in u:
                return "0"
            if "YOFF" in u:
                return "50"
            if "NR_PT" in u:
                return str(len(self.samples))
            if "PREAMBLE" in u:
                return "0,0,100,1,1e-06,-5e-05,0,0.01,0,50"
            if u.startswith(":CURVE") or u == "CURVE?":
                return ",".join(str(x) for x in self.samples)
            if "MEAS" in u:
                return "2.0"
            if "TRIGGER:STATE" in u:
                return "STOP"
            if "ACQUIRE:STATE" in u:
                return "0"
            if "DISPLAY:DATA" in u:
                return block(PNG)
            return ""
        return None


class MockOwon(MockScope):
    """Owon dialect: 4-byte length prefix + JSON header / 16-bit samples."""

    def __init__(self):
        super().__init__("owon")
        self.idn = "OWON,XDS3104,SN1234,1.0.0"
        self.header = {
            "TIMEBASE": {"SCALE": "1ms", "HOFFSET": 0},
            "SAMPLE": {"DATALEN": 100, "SAMPLERATE": "(25KS/s)", "DEPMEM": "5K"},
            "CHANNEL": [{"NAME": "CH1", "SCALE": "1.00V", "PROBE": "10X",
                         "COUPLING": "DC", "OFFSET": 0, "DISPLAY": "ON"}],
        }

    @staticmethod
    def prefixed(data: bytes) -> bytes:
        return len(data).to_bytes(4, "little") + data

    def handle(self, cmd):
        self.commands.append(cmd)
        u = cmd.strip().upper()
        if u == "*IDN?":
            return self.idn
        if "HEAD?" in u:
            import json as _json
            return self.prefixed(_json.dumps(self.header).encode())
        if "SCREEN:CH1?" in u:
            return self.prefixed(b"".join(int(v).to_bytes(2, "little") for v in self.samples))
        if "MEAS" in u and "PKPK" in u:
            return "Vpp : 2.040V->"
        if "TRIG:STAT" in u:
            return "STOP"
        if "SCREEN:BMP" in u:
            return self.prefixed(b"BM" + b"\x00" * 32)
        if "?" in u:
            return ""
        return None


class MockMicsig(MockScope):
    """Micsig: 9-field preamble, no points field."""

    def __init__(self):
        super().__init__("rigol")
        self.idn = "MICSIG,MHO14-200N,SN1234,1.143.72"

    def handle(self, cmd):
        u = cmd.strip().upper()
        if "PREAMBLE" in u:
            self.commands.append(cmd)
            return "0,0,100,1e-06,-5e-05,0,0.01,0,0"
        return super().handle(cmd)


@pytest.fixture
def micsig():
    s = MockMicsig()
    yield s
    s.stop()


@pytest.fixture
def owon():
    s = MockOwon()
    yield s
    s.stop()


@pytest.fixture
def mock_scope():
    created = []

    def factory(family="rigol"):
        s = MockScope(family)
        created.append(s)
        return s

    yield factory
    for s in created:
        s.stop()


@pytest.fixture
def rigol(mock_scope):
    return mock_scope("rigol")


@pytest.fixture
def tek(mock_scope):
    return mock_scope("tektronix")


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "scope.py"
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(scope="session")
def scope():
    spec = importlib.util.spec_from_file_location("scope", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
