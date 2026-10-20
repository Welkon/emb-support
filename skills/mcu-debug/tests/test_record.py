import json
from types import SimpleNamespace


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
