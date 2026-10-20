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


def base(tek, *rest):
    return [rest[0], "--host", "127.0.0.1", "--port", str(tek.port)] + list(rest[1:])


def test_tek_ascii_acquire(scope, tek):
    inst = scope.SocketInstrument("127.0.0.1", tek.port, timeout=2)
    try:
        d = scope.TektronixDialect(tek.idn)
        data = scope.acquire_channels(inst, d, [1], None)
    finally:
        inst.close()
    volts = data[1]["volts"]
    assert len(volts) == 100
    assert volts[0] == pytest.approx(-0.5)
    assert volts[-1] == pytest.approx(0.49)
    # ASCII curve path, not a binary block
    assert any("CURVe?" in c or "CURVE?" in c for c in tek.commands)
    assert any("ENCdg ASCII" in c or "ENCDG ASCII" in c.upper().replace("ENCDG", "ENCdg") for c in tek.commands)


def test_tek_run_commands(scope):
    d = scope.TektronixDialect("TEKTRONIX")
    assert d.run_commands() == [":ACQuire:STOPAfter RUNSTOP", ":ACQuire:STATE RUN"]


def test_tek_screenshot_is_disabled(scope):
    assert scope.TektronixDialect("TEKTRONIX").screenshot_queries() == []


def test_tek_single_capture(tek, tmp_path):
    out = tmp_path / "one.csv"
    p = run(base(tek, "capture", "--single", "2", "--points", "100",
                 "--out", str(out), "--json"), tmp_path / "home")
    assert p.returncode == 0, p.stderr
    import json as _json
    data = _json.loads(p.stdout)
    assert data["channels"]["1"]["points"] == 100
    assert "analysis" in data["channels"]["1"]


def test_tek_idn_family(tek, tmp_path):
    p = run(base(tek, "idn", "--json"), tmp_path / "home")
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    assert data["family"] == "tektronix"
    assert data["idn"].startswith("TEKTRONIX")


def test_tek_monitor_preset_dry_run(tek, tmp_path):
    p = run(base(tek, "monitor", "--preset", "glitch-short", "--dry-run"), tmp_path / "home")
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    joined = " | ".join(data["setup"])
    assert "PULSe" in joined or "PULSE" in joined.upper()
    assert "STOPAfter" in " ".join(data["arm"])


def test_tek_shot_falls_back_to_plot(tek, tmp_path):
    out = tmp_path / "screen.png"
    p = run(base(tek, "shot", "--out", str(out)), tmp_path / "home")
    assert p.returncode == 0, p.stderr
    svg = tmp_path / "screen.svg"
    assert svg.exists() and "<polyline" in svg.read_text()


def test_tek_measure_falls_back_to_waveform(tek, tmp_path):
    p = run(base(tek, "measure", "--items", "vpp,freq"), tmp_path / "home")
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    # Tektronix has no measure_query mapping, so values come from the waveform
    assert data["measurements"]["vpp"] == pytest.approx(0.99)
