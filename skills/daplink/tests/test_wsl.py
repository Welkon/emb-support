from types import SimpleNamespace

SAMPLE = (
    "Connected:\r\n"
    "BUSID  VID:PID    DEVICE                                                        STATE\r\n"
    "1-4    0489:e0d8  RZ616 Bluetooth(R) Adapter                                    Not shared\r\n"
    "2-1    0d28:0204  DAPLink CMSIS-DAP                                             Not shared\r\n"
    "\r\nPersisted:\r\n"
)


def fake_usbipd(dap, monkeypatch, output=SAMPLE, rc=0):
    monkeypatch.setattr(dap, "usbipd_exe", lambda: "/fake/usbipd.exe")
    monkeypatch.setattr(dap, "run", lambda *a, **k: (rc, output, ""))


def test_parse_usbipd(dap, monkeypatch):
    fake_usbipd(dap, monkeypatch)
    devices = dap.usbipd_devices()
    assert len(devices) == 2
    probe = [d for d in devices if d["probe"]]
    assert probe and probe[0]["busid"] == "2-1"
    assert probe[0]["probe"] == "DAPLink/CMSIS-DAP"


def test_wsl_hint(dap, monkeypatch):
    fake_usbipd(dap, monkeypatch, output=SAMPLE.replace("Not shared", "Shared     "))
    hint = dap.wsl_probe_hint()
    assert "2-1" in hint and "wsl attach" in hint


def test_wsl_status_json(dap, monkeypatch):
    fake_usbipd(dap, monkeypatch)
    calls = []
    dap.emit = lambda data, **kw: calls.append(data)
    dap.cmd_wsl(SimpleNamespace(action="status", busid=None, dry_run=False))
    assert calls[0]["ok"] is True
    assert calls[0]["probes"][0]["busid"] == "2-1"


def test_wsl_attach_requires_bind(dap, monkeypatch):
    fake_usbipd(dap, monkeypatch)
    try:
        dap.cmd_wsl(SimpleNamespace(action="attach", busid="2-1", dry_run=True))
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected SystemExit for a not-shared device")


def test_wsl_attach_dry_run_when_shared(dap, monkeypatch):
    shared = SAMPLE.replace("Not shared", "Shared     ")
    fake_usbipd(dap, monkeypatch, output=shared)
    calls = []
    dap.emit = lambda data, **kw: calls.append(data)
    dap.cmd_wsl(SimpleNamespace(action="attach", busid="2-1", dry_run=True))
    assert calls[0]["dry_run"] is True
    assert calls[0]["command"][-2:] == ["--busid", "2-1"]


SHARED = SAMPLE.replace("Not shared", "Shared     ")


def test_auto_attach_shared_probe(dap, monkeypatch):
    calls = []
    monkeypatch.setattr(dap, "usbipd_exe", lambda: "/fake/usbipd.exe")

    def fake_run(args, timeout=0):
        calls.append(args)
        if args[1:] == ["list"]:
            return 0, SHARED, ""
        return 0, "", ""

    monkeypatch.setattr(dap, "run", fake_run)
    assert dap.wsl_auto_attach(verbose=False) == ["2-1"]
    assert any(a[1] == "attach" and a[-1] == "2-1" for a in calls)


def test_auto_attach_skips_not_shared(dap, monkeypatch):
    calls = []
    monkeypatch.setattr(dap, "usbipd_exe", lambda: "/fake/usbipd.exe")

    def fake_run(args, timeout=0):
        calls.append(args)
        return 0, SAMPLE, ""

    monkeypatch.setattr(dap, "run", fake_run)
    assert dap.wsl_auto_attach(verbose=False) == []
    assert not any(a[1] == "attach" for a in calls)


def test_auto_attach_can_be_disabled(dap, monkeypatch):
    monkeypatch.setenv("DAP_WSL_AUTO_ATTACH", "0")
    assert dap.wsl_auto_enabled(SimpleNamespace(wsl_auto_attach=True)) is False


def test_hint_requires_bind_for_unshared(dap, monkeypatch):
    fake_usbipd(dap, monkeypatch)
    assert "usbipd bind" in dap.wsl_probe_hint()
