import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dap.py"


@pytest.fixture
def fake_prs(tmp_path, monkeypatch):
    log = tmp_path / "prs.log"
    script = tmp_path / "probe-rs"
    script.write_text(
        '#!/bin/sh\n'
        'if [ "$1" = "chip" ] && [ "$2" = "list" ]; then\n'
        '  echo "$@" >> "$DAP_PRS_LOG"\n'
        '  echo STM32F103RC\n'
        '  echo STM32F407VG\n'
        '  exit 0\n'
        'fi\n'
        'echo "$@" >> "$DAP_PRS_LOG"\n'
        'exit 0\n'
    )
    script.chmod(0o755)
    monkeypatch.setenv("DAP_PROBE_RS", str(script))
    monkeypatch.setenv("DAP_PRS_LOG", str(log))
    return script, log


def run(args, home, log, timeout=30):
    env = dict(os.environ, DAPLINK_HOME=str(home), DAP_PRS_LOG=str(log),
               DAP_PROBE_RS=env_value("DAP_PROBE_RS"))
    return subprocess.run([sys.executable, str(SCRIPT)] + args,
                          capture_output=True, text=True, env=env, timeout=timeout)


def env_value(name):
    return os.environ[name]


def logged(log):
    return log.read_text().strip().splitlines()[-1]


def test_engine_helpers(fake_prs, dap, iso):
    assert dap._engine(SimpleNamespace(engine="probe-rs", chip="X")) == "probe-rs"
    assert dap._engine(SimpleNamespace(engine="auto", chip="X")) == "probe-rs"
    assert dap._engine(SimpleNamespace(engine="auto", chip=None)) == "pyocd"
    assert dap._engine(SimpleNamespace(engine=None)) == "pyocd"


def test_prs_common_mapping(fake_prs):
    import importlib.util
    spec = importlib.util.spec_from_file_location("dap_eng", SCRIPT)
    dap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dap)
    ns = SimpleNamespace(chip="STM32F103RC", probe="ABC", frequency=1_000_000, connect="under-reset")
    assert dap._prs_common(ns) == ["--chip", "STM32F103RC", "--non-interactive",
                                   "--probe", "ABC", "--speed", "1000", "--connect-under-reset"]


def test_resolve_chip_from_target(fake_prs, dap, iso, monkeypatch):
    monkeypatch.setattr(dap, "_PRS_CHIPS", ["STM32F103RC", "STM32F407VG"])
    assert dap._resolve_chip(SimpleNamespace(chip=None, target="stm32f103rc")) == "STM32F103RC"
    assert dap._resolve_chip(SimpleNamespace(chip=None, target="stm32")) is None
    assert dap._resolve_chip(SimpleNamespace(chip="EXPLICIT", target="whatever")) == "EXPLICIT"


def test_auto_routes_to_probe_rs_using_target(fake_prs, elf, tmp_path):
    home = tmp_path / "home"
    log = Path(os.environ["DAP_PRS_LOG"])
    assert run(["config", "set", "target", "stm32f103rc"], home, log).returncode == 0
    log.write_text("")
    p = run(["flash", str(elf), "--engine", "auto"], home, log)
    assert p.returncode == 0, p.stderr
    line = logged(log)
    assert "download" in line and "STM32F103RC" in line


def test_prs_common_requires_chip(fake_prs, dap, iso, monkeypatch):
    monkeypatch.setattr(dap, "_PRS_CHIPS", [])
    with pytest.raises(SystemExit):
        dap._prs_common(SimpleNamespace(chip=None, probe=None, frequency=None, connect=None))


def test_fw_format(dap):
    assert dap._fw_format(Path("a.elf"), None) == "elf"
    assert dap._fw_format(Path("a.hex"), None) == "hex"
    assert dap._fw_format(Path("a.bin"), None) == "bin"
    assert dap._fw_format(Path("a.unknown"), None) == "target"
    assert dap._fw_format(Path("a.elf"), "axf") == "elf"


@pytest.mark.parametrize("args,expected", [
    (["flash", "{elf}", "--engine", "probe-rs", "--chip", "STM32F103RC"],
     ["download", "--chip", "STM32F103RC", "--binary-format", "elf", "--verify", "--reset"]),
    (["verify", "{elf}", "--engine", "probe-rs", "--chip", "STM32F103RC"],
     ["verify", "--chip", "STM32F103RC", "--binary-format", "elf"]),
    (["erase", "--engine", "probe-rs", "--chip", "STM32F103RC"],
     ["erase", "--chip", "STM32F103RC"]),
    (["reset", "--engine", "probe-rs", "--chip", "STM32F103RC", "--core", "1"],
     ["reset", "--chip", "STM32F103RC", "--core", "1"]),
    (["rtt", "--duration", "1", "--elf", "{elf}", "--engine", "probe-rs", "--chip", "X"],
     ["attach", "--chip", "X"]),
    (["gdb", "--port", "4444", "--elf", "{elf}", "--engine", "probe-rs", "--chip", "X"],
     ["gdb", "--gdb-connection-string", "127.0.0.1:4444", "--chip", "X"]),
    (["profile", "--duration", "1", "--elf", "{elf}", "--engine", "probe-rs", "--chip", "X"],
     ["profile", "--duration", "1", "--chip", "X"]),
    (["swo", "--duration", "1", "--engine", "probe-rs", "--chip", "X"],
     ["itm", "swo", "1000", "72000000", "2000000", "--chip", "X"]),
    (["targets", "--engine", "probe-rs"],
     ["chip", "list"]),
])
def test_probe_rs_command_mapping(fake_prs, elf, tmp_path, args, expected):
    home = tmp_path / "home"
    log = Path(os.environ["DAP_PRS_LOG"])
    log.write_text("")
    argv = [a.format(elf=elf) for a in args]
    p = run(argv, home, log)
    assert p.returncode == 0, p.stderr
    line = logged(log)
    for token in expected:
        assert token in line, f"{token!r} not in {line!r}"


def test_erase_range_rejected_on_probe_rs(fake_prs, elf, tmp_path):
    home = tmp_path / "home"
    log = Path(os.environ["DAP_PRS_LOG"])
    p = run(["erase", "--range", "0x08010000+0x1000", "--engine", "probe-rs", "--chip", "X"], home, log)
    assert p.returncode != 0
    assert "whole chip" in p.stderr


def test_flash_chip_erase_maps(fake_prs, elf, tmp_path):
    home = tmp_path / "home"
    log = Path(os.environ["DAP_PRS_LOG"])
    log.write_text("")
    p = run(["flash", str(elf), "-e", "chip", "--engine", "probe-rs", "--chip", "X"], home, log)
    assert p.returncode == 0, p.stderr
    assert "--chip-erase" in logged(log)


def test_probe_rs_requires_chip(fake_prs, elf, tmp_path):
    home = tmp_path / "home"
    log = Path(os.environ["DAP_PRS_LOG"])
    p = run(["flash", str(elf), "--engine", "probe-rs"], home, log)
    assert p.returncode != 0
    assert "Cannot map this target to a probe-rs chip" in p.stderr


def test_engines_reports_probe_rs(fake_prs, tmp_path):
    home = tmp_path / "home"
    log = Path(os.environ["DAP_PRS_LOG"])
    p = run(["engines"], home, log)
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    assert data["probe-rs"]["available"] is True
    assert data["pyocd"]["available"] is True
