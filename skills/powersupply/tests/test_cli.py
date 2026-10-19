import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "psu.py"


def run(args, home, timeout=25):
    env = dict(os.environ, PSU_HOME=str(home))
    return subprocess.run([sys.executable, str(SCRIPT)] + args,
                          capture_output=True, text=True, env=env, timeout=timeout)


def base(psu, *rest):
    return [rest[0], "--host", "127.0.0.1", "--port", str(psu.port)] + list(rest[1:])


def test_idn_and_channels(psu, tmp_path):
    home = tmp_path / "home"
    p = run(base(psu, "idn", "--json"), home)
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    assert data["family"] == "rigol"

    p = run(base(psu, "channels", "--json"), home)
    assert p.returncode == 0, p.stderr
    caps = json.loads(p.stdout)
    assert caps["channels"] == [1, 2, 3]
    assert caps["capabilities"]["power"] is True


def test_set_and_get(psu, tmp_path):
    home = tmp_path / "home"
    p = run(base(psu, "set", "--ch", "1", "--voltage", "5", "--current", "1",
                 "--verify", "--json"), home)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout)["readback"]["voltage"] == pytest.approx(5.0)

    p = run(base(psu, "get", "--ch", "1", "--json"), home)
    data = json.loads(p.stdout)
    assert data["voltage"] == pytest.approx(5.0)
    assert data["current"] == pytest.approx(1.0)


def test_safety_limit(psu, tmp_path):
    p = run(base(psu, "set", "--ch", "1", "--voltage", "40"), tmp_path / "home")
    assert p.returncode != 0
    assert "safety limit" in p.stderr


def test_output_interlock(psu, tmp_path):
    home = tmp_path / "home"
    p = run(base(psu, "output", "--ch", "1", "on"), home)
    assert p.returncode != 0
    assert "--yes" in p.stderr

    p = run(base(psu, "output", "--ch", "1", "on", "--yes", "--json"), home)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout)["readback"] == "ON"

    p = run(base(psu, "all-off", "--json"), home)
    assert p.returncode == 0
    assert json.loads(p.stdout)["outputs_off"] == [1, 2, 3]


def test_measure_and_protect(psu, tmp_path):
    home = tmp_path / "home"
    run(base(psu, "set", "--ch", "1", "--voltage", "5", "--current", "1"), home)
    run(base(psu, "output", "--ch", "1", "on", "--yes"), home)
    p = run(base(psu, "measure", "--ch", "1", "--json"), home)
    m = json.loads(p.stdout)["measurements"]
    assert m["voltage"] == pytest.approx(5.0)
    assert m["current"] == pytest.approx(1.0)
    assert m["power"] == pytest.approx(5.0)

    p = run(base(psu, "protect", "--ch", "1", "--ovp", "6", "--ocp", "1.5", "--json"), home)
    assert p.returncode == 0
    assert psu.ch(1)["ovp"] == pytest.approx(6.0)
    assert psu.ch(1)["ocp"] == pytest.approx(1.5)


def test_ramp(psu, tmp_path):
    home = tmp_path / "home"
    p = run(base(psu, "ramp", "--ch", "1", "--start", "0", "--to", "1",
                 "--step", "0.5", "--delay", "0", "--yes", "--json"), home)
    assert p.returncode == 0, p.stderr
    assert psu.ch(1)["v"] == pytest.approx(1.0)


def test_sequence(psu, tmp_path):
    home = tmp_path / "home"
    seq = tmp_path / "seq.json"
    seq.write_text(json.dumps({"steps": [
        {"voltage": 1, "current": 0.5, "delay": 0},
        {"voltage": 2, "current": 0.5, "delay": 0},
    ]}))
    p = run(base(psu, "sequence", str(seq), "--yes", "--json"), home)
    assert p.returncode == 0, p.stderr
    assert psu.ch(1)["v"] == pytest.approx(2.0)
    assert psu.ch(1)["i"] == pytest.approx(0.5)


def test_log(psu, tmp_path):
    home = tmp_path / "home"
    out = tmp_path / "log.csv"
    run(base(psu, "set", "--ch", "1", "--voltage", "5", "--current", "1"), home)
    run(base(psu, "output", "--ch", "1", "on", "--yes"), home)
    p = run(base(psu, "log", "--ch", "1", "--duration", "0.3", "--interval", "0.1",
                 "--out", str(out), "--json"), home)
    assert p.returncode == 0, p.stderr
    rows = list(csv.reader(out.open()))
    assert rows[0] == ["time", "voltage", "current", "power"]
    assert len(rows) >= 2
