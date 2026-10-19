import csv
import json
import math
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


def base(rigol, *rest):
    return [rest[0], "--host", "127.0.0.1", "--port", str(rigol.port)] + list(rest[1:])


def test_rigol_acquire(scope, rigol):
    inst = scope.SocketInstrument("127.0.0.1", rigol.port, timeout=2)
    try:
        d = scope.RigolDialect(rigol.idn)
        data = scope.acquire_channels(inst, d, [1], None)
    finally:
        inst.close()
    item = data[1]
    assert len(item["volts"]) == 100
    assert item["volts"][0] == pytest.approx(-0.5)
    assert item["volts"][-1] == pytest.approx(0.49)
    assert item["times"][1] - item["times"][0] == pytest.approx(1e-6)
    st = scope.stats(item["volts"], item["times"])
    assert st["vpp"] == pytest.approx(0.99)


def test_cli_capture_csv(rigol, tmp_path, monkeypatch):
    home = tmp_path / "home"
    out = tmp_path / "wave.csv"
    p = run(base(rigol, "capture", "--channels", "1", "--out", str(out), "--json"), home)
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    assert data["channels"]["1"]["points"] == 100
    rows = list(csv.reader(out.open()))
    assert rows[0] == ["time", "ch1"]
    assert len(rows) == 101
    assert float(rows[1][1]) == pytest.approx(-0.5)


def test_cli_measure_instrument(rigol, tmp_path):
    p = run(base(rigol, "measure", "--channel", "1", "--items", "vpp,rms"), tmp_path / "home")
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    assert data["measurements"]["vpp"] == 2.0


def test_cli_shot(rigol, tmp_path):
    out = tmp_path / "screen.png"
    p = run(base(rigol, "shot", "--out", str(out)), tmp_path / "home")
    assert p.returncode == 0, p.stderr
    assert out.read_bytes().startswith(b"\x89PNG")


def test_cli_monitor(rigol, tmp_path):
    outdir = tmp_path / "captures"
    p = run(base(rigol, "monitor", "--channels", "1", "--max-events", "1",
                 "--duration", "5", "--outdir", str(outdir), "--prefix", "ev", "--json"),
            tmp_path / "home")
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    assert len(data["events"]) == 1
    assert (outdir / "ev-01.csv").exists()
    meta = json.loads((outdir / "ev-01.json").read_text())
    assert meta["event"] == 1


def test_monitor_dry_run(rigol, tmp_path):
    p = run(base(rigol, "monitor", "--preset", "glitch-short", "--dry-run"), tmp_path / "home")
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    assert data["dry_run"] is True
    assert data["arm"]


def test_analyze_offline(tmp_path):
    path = tmp_path / "sine.csv"
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "ch1"])
        for i in range(3000):
            t = i * 1e-6
            w.writerow([f"{t:.12g}", f"{math.sin(2 * math.pi * 1000 * t):.9g}"])
    p = run(["analyze", "--csv", str(path), "--json"], tmp_path / "home")
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    assert data["freq"] == pytest.approx(1000, rel=0.02)
    assert data["logic_levels"]["high"] > 0.5


def test_cli_idn_and_aliases(rigol, tmp_path):
    home = tmp_path / "home"
    p = run(base(rigol, "idn", "--json"), home)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout)["family"] == "rigol"

    p = run(base(rigol, "query", ":TRIGger:STATe?", "--json"), home)
    assert json.loads(p.stdout)["response"] == "STOP"

    p = run(base(rigol, "write", ":STOP", "--json"), home)
    assert json.loads(p.stdout)["ok"] is True
