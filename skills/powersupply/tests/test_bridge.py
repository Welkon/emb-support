import pytest
from psuscpi import bridge


def test_wants_bridge_forms():
    assert bridge.wants_bridge(["psu.py", "--bridge", "windows", "status"]) == "windows"
    assert bridge.wants_bridge(["psu.py", "--bridge=Windows", "status"]) == "windows"
    assert bridge.wants_bridge(["psu.py", "status", "--json"]) is None


def test_strip_bridge_keeps_the_rest_of_the_arguments():
    argv = ["psu.py", "--bridge", "windows", "status", "--hid", "dp100", "--json"]
    assert bridge.strip_bridge(argv) == ["psu.py", "status", "--hid", "dp100", "--json"]
    assert bridge.strip_bridge(["psu.py", "--bridge=windows", "idn"]) == ["psu.py", "idn"]


def test_command_forwards_untouched_arguments(monkeypatch):
    monkeypatch.setattr(bridge, "windows_python", lambda explicit=None: r"C:\py\python.exe")
    monkeypatch.setattr(bridge, "windows_path", lambda path: r"\\wsl.localhost\D\psu.py")
    cmd = bridge.bridge_command(["psu.py", "--bridge", "windows", "status", "--hid", "dp100"])
    assert cmd == [r"C:\py\python.exe", r"\\wsl.localhost\D\psu.py", "status", "--hid", "dp100"]


def test_windows_python_prefers_the_explicit_flag(monkeypatch):
    monkeypatch.setattr(bridge, "wsl_view", lambda path: path)
    monkeypatch.setenv("PSU_WIN_PYTHON", r"C:\env\python.exe")
    assert bridge.windows_python(r"C:\flag\python.exe") == r"C:\flag\python.exe"
    assert bridge.windows_python() == r"C:\env\python.exe"


def test_run_refuses_outside_wsl(monkeypatch):
    monkeypatch.setattr(bridge, "is_wsl", lambda: False)
    with pytest.raises(bridge.BridgeError, match="only makes sense on WSL"):
        bridge.run(["psu.py", "--bridge", "windows", "status"])


def test_run_forwards_the_child_exit_code(monkeypatch):
    monkeypatch.setattr(bridge, "is_wsl", lambda: True)
    monkeypatch.setattr(bridge, "bridge_command", lambda argv, python=None: ["cmd"])
    seen = {}

    def fake_call(cmd, env=None):
        seen["cmd"] = cmd
        seen["env"] = env
        return 7

    monkeypatch.setattr(bridge.subprocess, "call", fake_call)
    assert bridge.run(["psu.py", "--bridge", "windows", "status"]) == 7
    assert seen["cmd"] == ["cmd"]
    assert seen["env"]["PSU_WIN_BRIDGED"] == "1"


def test_wsl_view_is_a_noop_when_wslpath_fails(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("no wslpath")

    monkeypatch.setattr(bridge.subprocess, "run", boom)
    assert bridge.wsl_view(r"C:\x\python.exe") == r"C:\x\python.exe"
