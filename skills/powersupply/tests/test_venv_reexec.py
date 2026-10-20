import pathlib
import sys

import pytest

from psuscpi import common


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
    monkeypatch.delenv("PSU_NO_REEXEC", raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_venv.parent.parent / "other-python"))
    monkeypatch.setattr(common, "missing_runtime_modules", lambda: ["hid"])
    argv = ["/x/psu.py", "get", "--hid", "dp100"]
    assert common.venv_reexec_argv(argv) == [str(fake_venv), "/x/psu.py", "get", "--hid", "dp100"]


def test_no_reexec_when_already_inside(fake_venv, monkeypatch):
    monkeypatch.delenv("PSU_NO_REEXEC", raising=False)
    # venv/bin/python symlinks to the base interpreter, so membership is decided
    # by sys.prefix, never by the executable path.
    monkeypatch.setattr(sys, "prefix", str(fake_venv.parent))
    assert common.venv_reexec_argv(["/x/psu.py", "doctor"]) is None


def test_no_reexec_for_setup_and_test(fake_venv, monkeypatch):
    monkeypatch.delenv("PSU_NO_REEXEC", raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_venv.parent.parent / "other-python"))
    assert common.venv_reexec_argv(["/x/psu.py", "setup", "--dev"]) is None
    assert common.venv_reexec_argv(["/x/psu.py", "test", "--install"]) is None


def test_reexec_env_override(fake_venv, monkeypatch):
    monkeypatch.setenv("PSU_NO_REEXEC", "1")
    monkeypatch.setattr(sys, "executable", str(fake_venv.parent.parent / "other-python"))
    assert common.venv_reexec_argv(["/x/psu.py", "doctor"]) is None


def test_no_reexec_without_venv(tmp_path, monkeypatch):
    monkeypatch.delenv("PSU_NO_REEXEC", raising=False)
    monkeypatch.setattr(common, "VENV", tmp_path / "missing")
    assert common.venv_reexec_argv(["/x/psu.py", "doctor"]) is None


# ------------------------------------------------------------------ lazy exec

def test_no_reexec_when_runtime_modules_present(fake_venv, monkeypatch):
    """A sandbox prompts for every exec outside the project: skip it when unneeded."""
    monkeypatch.delenv("PSU_NO_REEXEC", raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_venv.parent.parent / "other-python"))
    monkeypatch.setattr(common, "missing_runtime_modules", lambda: [])
    assert common.venv_reexec_argv(["/x/psu.py", "get", "--hid", "dp100"]) is None


def test_missing_runtime_modules_shape(monkeypatch):
    monkeypatch.setattr(common, "REQUIRED_MODULES", ("hid",))
    assert common.missing_runtime_modules() == []


# ------------------------------------------------------------------- data home

def _home(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path / "home")
    monkeypatch.delenv("PSU_HOME", raising=False)


def test_data_home_env_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("PSU_HOME", str(tmp_path / "explicit"))
    assert common.data_home() == tmp_path / "explicit"


def test_data_home_uses_existing_project_home(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    local = proj / ".emb-agent" / "bench" / "psu"
    local.mkdir(parents=True)
    monkeypatch.chdir(proj)
    assert common.data_home() == local


def test_data_home_stays_inside_for_a_new_project(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    (proj / ".emb-agent").mkdir(parents=True)
    monkeypatch.chdir(proj)
    assert common.data_home() == proj / ".emb-agent" / "bench" / "psu"


def test_data_home_keeps_a_legacy_dir(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    legacy = tmp_path / "home" / ".local" / "share" / "psu"
    legacy.mkdir(parents=True)
    proj = tmp_path / "proj"
    (proj / ".emb-agent").mkdir(parents=True)
    monkeypatch.chdir(proj)
    assert common.data_home() == legacy


def test_data_home_outside_any_project_is_legacy(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    assert common.data_home() == tmp_path / "home" / ".local" / "share" / "psu"
