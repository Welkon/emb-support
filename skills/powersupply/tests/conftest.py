import os
import socketserver
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "psu.py"


class MockPsu:
    def __init__(self):
        self.idn = "RIGOL TECHNOLOGIES,DP832,DP8A000000001,00.01.00"
        self.channels = {}
        scope = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                for raw in self.rfile:
                    cmd = raw.decode(errors="replace").strip()
                    if not cmd:
                        continue
                    resp = scope.handle(cmd)
                    if resp is not None:
                        self.wfile.write((resp + "\n").encode())

        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def ch(self, n):
        return self.channels.setdefault(n, {"v": 0.0, "i": 0.0, "out": False,
                                            "ovp": None, "ocp": None})

    def handle(self, cmd):
        u = cmd.upper()
        if u == "*IDN?":
            return self.idn
        for n in (1, 2, 3):
            if f":CHANNEL{n}:VOLTAGE " in u:
                self.ch(n)["v"] = float(cmd.split()[-1])
                return None
            if f":CHANNEL{n}:CURRENT " in u:
                self.ch(n)["i"] = float(cmd.split()[-1])
                return None
            if f":CHANNEL{n}:OVP " in u:
                self.ch(n)["ovp"] = float(cmd.split()[-1])
                return None
            if f":CHANNEL{n}:OCP " in u:
                self.ch(n)["ocp"] = float(cmd.split()[-1])
                return None
            if u == f":CHANNEL{n}:VOLTAGE?":
                return f"{self.ch(n)['v']:.3f}"
            if u == f":CHANNEL{n}:CURRENT?":
                return f"{self.ch(n)['i']:.3f}"
            if f":MEASURE:VOLTAGE? CHANNEL{n}" in u:
                c = self.ch(n)
                return f"{c['v'] if c['out'] else 0.0:.4f}"
            if f":MEASURE:CURRENT? CHANNEL{n}" in u:
                c = self.ch(n)
                return f"{c['i'] if c['out'] else 0.0:.4f}"
            if f":MEASURE:POWER? CHANNEL{n}" in u:
                c = self.ch(n)
                return f"{(c['v'] * c['i']) if c['out'] else 0.0:.4f}"
            if u.startswith(f":OUTPUT CHANNEL{n},"):
                self.ch(n)["out"] = u.endswith(",ON")
                return None
            if u == f":OUTPUT? CHANNEL{n}":
                return "ON" if self.ch(n)["out"] else "OFF"
        if "?" in u:
            return ""
        return None


@pytest.fixture
def psu():
    s = MockPsu()
    yield s
    s.stop()


@pytest.fixture(scope="session")
def module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("psu", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
