import types

import pytest

from scopescpi import transport as transport_mod
from scopescpi import wsl as wsl_mod


class DummyUsbtmc:
    def __init__(self, path, timeout):
        self.path = path
        self.timeout = timeout


def test_pick_single_resource(scope):
    assert scope.pick_single_resource([]) is None
    assert scope.pick_single_resource(["USB0::1::INSTR"]) == "USB0::1::INSTR"
    assert scope.pick_single_resource(["USB0::1::INSTR", "TCPIP::2::INSTR"]) is None
    assert scope.pick_single_resource(["ASRL1::INSTR"]) is None


def test_ensure_attached_no_device(scope, monkeypatch):
    monkeypatch.setattr(wsl_mod, "list_devices", lambda path=None: ([], None))
    assert scope.ensure_scope_attached(wait_seconds=0)["status"] == "no-device"


def test_ensure_attached_already(scope, monkeypatch):
    dev = {"busid": "2-3", "vendor": "Tektronix", "state": "Attached", "attached": True}
    monkeypatch.setattr(wsl_mod, "list_devices", lambda path=None: ([dev], None))
    assert scope.ensure_scope_attached(wait_seconds=0)["status"] == "already-attached"


def test_ensure_attached_needs_bind(scope, monkeypatch):
    dev = {"busid": "2-3", "vendor": "Tektronix", "state": "Not shared", "attached": False}
    monkeypatch.setattr(wsl_mod, "list_devices", lambda path=None: ([dev], None))
    out = scope.ensure_scope_attached(wait_seconds=0)
    assert out["status"] == "needs-bind"
    assert out["needs_bind"][0]["busid"] == "2-3"


def test_ensure_attached_shared(scope, monkeypatch):
    dev = {"busid": "2-3", "vendor": "Tektronix", "state": "Shared", "attached": False}
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(wsl_mod, "list_devices", lambda path=None: ([dev], None))
    monkeypatch.setattr(wsl_mod, "usbipd_path", lambda: "/fake/usbipd.exe")
    monkeypatch.setattr(wsl_mod.subprocess, "run", fake_run)
    out = scope.ensure_scope_attached(wait_seconds=0)
    assert out["status"] in ("attached", "attached-no-node")
    assert calls and calls[0][1:5] == ["attach", "--wsl", "--busid", "2-3"]


def test_connect_auto_attaches_on_wsl(scope, monkeypatch):
    state = {"attached": False}
    monkeypatch.setattr(transport_mod, "is_wsl", lambda: True)
    monkeypatch.setattr(transport_mod, "ensure_scope_attached",
                        lambda: (state.update(attached=True) or {"status": "attached"}))
    monkeypatch.setattr(transport_mod.glob, "glob",
                        lambda pattern: ["/dev/usbtmc0"] if state["attached"] else [])
    monkeypatch.setattr(transport_mod, "UsbtmcInstrument", DummyUsbtmc)
    ns = types.SimpleNamespace(resource=None, host=None, port=None, timeout=2,
                               backend=None, no_auto_attach=False)
    inst = scope.connect(ns)
    assert isinstance(inst, DummyUsbtmc)
    assert inst.path == "/dev/usbtmc0"


def test_connect_no_auto_attach(scope, monkeypatch):
    monkeypatch.setattr(transport_mod, "is_wsl", lambda: True)
    monkeypatch.setattr(transport_mod.glob, "glob", lambda pattern: [])
    monkeypatch.setattr(transport_mod, "_list_resources", lambda backend: [])
    ns = types.SimpleNamespace(resource=None, host=None, port=None, timeout=2,
                               backend=None, no_auto_attach=True)
    with pytest.raises(SystemExit):
        scope.connect(ns)
