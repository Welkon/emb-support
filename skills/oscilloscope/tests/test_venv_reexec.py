import sys

import pytest

from scopescpi import common


@pytest.fixture
def fake_venv(tmp_path, monkeypatch):
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    exe = venv / ("Scripts/python.exe" if common.IS_WIN else "bin/python")
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("")
    monkeypatch.setattr(common, "VENV", venv)
    return exe


def test_reexec_targets_skill_venv(fake_venv, monkeypatch):
    monkeypatch.delenv("SCOPE_NO_REEXEC", raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_venv.parent.parent / "other-python"))
    argv = ["/x/scope.py", "doctor", "--json"]
    assert common.venv_reexec_argv(argv) == [str(fake_venv), "/x/scope.py", "doctor", "--json"]


def test_no_reexec_when_already_inside(fake_venv, monkeypatch):
    monkeypatch.delenv("SCOPE_NO_REEXEC", raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_venv))
    assert common.venv_reexec_argv(["/x/scope.py", "doctor"]) is None


def test_no_reexec_for_setup_and_test(fake_venv, monkeypatch):
    monkeypatch.delenv("SCOPE_NO_REEXEC", raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_venv.parent.parent / "other-python"))
    assert common.venv_reexec_argv(["/x/scope.py", "setup", "--dev"]) is None
    assert common.venv_reexec_argv(["/x/scope.py", "test", "--install"]) is None


def test_reexec_env_override(fake_venv, monkeypatch):
    monkeypatch.setenv("SCOPE_NO_REEXEC", "1")
    monkeypatch.setattr(sys, "executable", str(fake_venv.parent.parent / "other-python"))
    assert common.venv_reexec_argv(["/x/scope.py", "doctor"]) is None


def test_no_reexec_without_venv(tmp_path, monkeypatch):
    monkeypatch.delenv("SCOPE_NO_REEXEC", raising=False)
    monkeypatch.setattr(common, "VENV", tmp_path / "missing")
    assert common.venv_reexec_argv(["/x/scope.py", "doctor"]) is None
