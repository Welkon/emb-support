import json
from types import SimpleNamespace

import pytest


def test_record_writes_evidence(fake, iso, monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, timeout=0):
        calls.append(cmd)
        return 0, '{"ok": true, "checks": []}', ""

    monkeypatch.setattr(fake.dap, "run", fake_run)
    ns = SimpleNamespace(out=str(tmp_path / "evidence"), elf=None, target=None,
                         rtt_log=None, timeout=5)
    try:
        fake.dap.cmd_record(ns)
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("cmd_record must exit with a status code")

    out = tmp_path / "evidence"
    assert (out / "selfcheck.json").exists()
    meta = json.loads((out / "metadata.json").read_text())
    assert meta["selfcheck_ok"] is True
    assert any("selfcheck" in " ".join(c) for c in calls)


def test_recording_includes_diagnose_when_elf_is_given(fake, iso, monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, timeout=0):
        calls.append(cmd)
        return 0, '{"ok": true}', ""

    monkeypatch.setattr(fake.dap, "run", fake_run)
    ns = SimpleNamespace(out=str(tmp_path / "evidence"), elf=str(fake.elf), target="stm32f103rc",
                         rtt_log=None, timeout=5)
    try:
        fake.dap.cmd_record(ns)
    except SystemExit as exc:
        assert exc.code == 0
    assert any("diagnose" in " ".join(c) for c in calls)


def test_record_failure_writes_valid_json(fake, iso, monkeypatch, tmp_path):
    def fake_run(cmd, timeout=0):
        return 1, "", "\x1b[31mNo connected debug probes\x1b[0m\n"

    monkeypatch.setattr(fake.dap, "run", fake_run)
    ns = SimpleNamespace(out=str(tmp_path / "evidence"), elf=None, target="stm32f103rc",
                         toolchain="gcc-13.2", opt="-O2", rtt_log=None, timeout=5)
    with pytest.raises(SystemExit) as exc:
        fake.dap.cmd_record(ns)
    assert exc.value.code == 1

    out = tmp_path / "evidence"
    data = json.loads((out / "selfcheck.json").read_text())
    assert data["ok"] is False
    assert data["rc"] == 1
    assert "No connected debug probes" in data["error"]
    assert "\x1b" not in data["error"]

    meta = json.loads((out / "metadata.json").read_text())
    assert meta["chip"] == "stm32f103rc"
    assert meta["toolchain"] == "gcc-13.2"
    assert meta["opt"] == "-O2"


def test_record_metadata_uses_target_and_probe_from_selfcheck(fake, iso, monkeypatch, tmp_path):
    def fake_run(cmd, timeout=0):
        return 0, json.dumps({"ok": True, "checks": [
            {"name": "probe", "ok": True, "detail": "ABC123"},
            {"name": "target", "ok": True, "detail": "STM32F103RC"},
        ]}), ""

    monkeypatch.setattr(fake.dap, "run", fake_run)
    ns = SimpleNamespace(out=str(tmp_path / "evidence"), elf=None, target=None,
                         toolchain=None, opt=None, rtt_log=None, timeout=5)
    with pytest.raises(SystemExit) as exc:
        fake.dap.cmd_record(ns)
    assert exc.value.code == 0
    meta = json.loads((tmp_path / "evidence" / "metadata.json").read_text())
    assert meta["chip"] == "STM32F103RC"
    assert meta["probe"] == "ABC123"
