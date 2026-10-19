import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dap.py"


def run(args, home, timeout=30):
    env = dict(os.environ, DAPLINK_HOME=str(home))
    return subprocess.run([sys.executable, str(SCRIPT)] + args,
                          capture_output=True, text=True, env=env, timeout=timeout)


@pytest.fixture
def home(tmp_path):
    return tmp_path / "home"


def test_help(home):
    p = run(["--help"], home)
    assert p.returncode == 0
    assert "diagnose" in p.stdout and "repl" in p.stdout


def test_symbols_offline(home, elf):
    p = run(["sym", "list", "--elf", str(elf), "--limit", "3"], home)
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    assert data["ok"] is True and len(data["symbols"]) == 3


def test_diagnose_from_snapshot(home, tmp_path):
    snap = {
        "captured_at": "2026-01-01T00:00:00", "elf": None, "target": "FAKE",
        "state": "HALTED", "halt_reason": "VECTOR_CATCH",
        "registers": {"pc": 0x08000100, "lr": 0, "sp": 0x20008000},
        "fault": {"CFSR": (1 << 9) | (1 << 15), "HFSR": 0, "BFAR": 8, "MMFAR": 0},
        "stack": {"initial_sp": 0x20008000, "sp": 0x20008000, "used": 0},
        "exception_frame": None, "backtrace": [],
        "regions": [{"name": "RAM", "start": 0x20000000, "end": 0x20005000, "type": "RAM"}],
        "disasm": [], "stack_words": [],
    }
    f = tmp_path / "snap.json"
    f.write_text(json.dumps(snap))
    p = run(["diagnose", "--snapshot", str(f), "--json"], home)
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    assert data["ok"] is True
    assert any("NULL" in h["cause"] for h in data["hypotheses"])


def test_no_probe_fails_fast(home, elf):
    t0 = time.time()
    p = run(["bt", "--elf", str(elf)], home, timeout=25)
    assert p.returncode != 0
    assert time.time() - t0 < 25
    assert "No usable probe" in p.stderr


def test_flash_without_probe_fails_fast(home, elf):
    t0 = time.time()
    p = run(["flash", str(elf), "-t", "stm32f103rc"], home, timeout=25)
    assert p.returncode != 0
    assert time.time() - t0 < 25


def test_config_roundtrip(home):
    assert run(["config", "set", "target", "stm32f103rc"], home).returncode == 0
    p = run(["config", "get", "target"], home)
    assert json.loads(p.stdout)["value"] == "stm32f103rc"
    p = run(["config", "list"], home)
    assert json.loads(p.stdout)["config"]["target"] == "stm32f103rc"
