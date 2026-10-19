import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "scope.py"


def run(args, home, timeout=25):
    env = dict(os.environ, SCOPE_HOME=str(home))
    return subprocess.run([sys.executable, str(SCRIPT)] + args,
                          capture_output=True, text=True, env=env, timeout=timeout)


def base(owon, *rest):
    return [rest[0], "--host", "127.0.0.1", "--port", str(owon.port)] + list(rest[1:])


def test_owon_acquire_and_measure(scope, owon):
    inst = scope.SocketInstrument("127.0.0.1", owon.port, timeout=2)
    try:
        d = scope.OwonDialect(owon.idn)
        data = scope.acquire_channels(inst, d, [1], None)
        assert len(data[1]["volts"]) == 100
        assert data[1]["volts"][0] == pytest.approx(0)
        assert data[1]["volts"][1] == pytest.approx(1 / 6400)
        assert data[1]["times"][1] - data[1]["times"][0] == pytest.approx(1 / 25000)
        assert scope.measure_channel(inst, d, 1, ["vpp"])["vpp"] == pytest.approx(2.04)
    finally:
        inst.close()


def test_owon_cli_capture_and_shot(owon, tmp_path):
    home = tmp_path / "home"
    out = tmp_path / "wave.csv"
    p = run(base(owon, "capture", "--channels", "1", "--out", str(out), "--json"), home)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout)["channels"]["1"]["points"] == 100

    shot = tmp_path / "screen.bmp"
    p = run(base(owon, "shot", "--out", str(shot)), home)
    assert p.returncode == 0, p.stderr
    assert shot.read_bytes().startswith(b"BM")


def test_owon_monitor(owon, tmp_path):
    outdir = tmp_path / "caps"
    p = run(base(owon, "monitor", "--channels", "1", "--max-events", "1",
                 "--outdir", str(outdir), "--prefix", "ev", "--json"), tmp_path / "home")
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    assert len(data["events"]) == 1
    assert (outdir / "ev-01.csv").exists()


def test_owon_measure_cli(owon, tmp_path):
    p = run(base(owon, "measure", "--items", "vpp"), tmp_path / "home")
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout)["measurements"]["vpp"] == pytest.approx(2.04)
