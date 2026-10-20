import pathlib
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
    monkeypatch.setattr(common, "missing_runtime_modules", lambda: ["pyvisa"])
    argv = ["/x/scope.py", "doctor", "--json"]
    assert common.venv_reexec_argv(argv) == [str(fake_venv), "/x/scope.py", "doctor", "--json"]


def test_no_reexec_when_already_inside(fake_venv, monkeypatch):
    monkeypatch.delenv("SCOPE_NO_REEXEC", raising=False)
    # venv/bin/python symlinks to the base interpreter, so membership is decided
    # by sys.prefix, never by the executable path.
    monkeypatch.setattr(common, "missing_runtime_modules", lambda: ["pyvisa"])
    monkeypatch.setattr(sys, "prefix", str(common.VENV))
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


# ------------------------------------------------------------------ lazy exec

def test_no_reexec_when_runtime_modules_present(fake_venv, monkeypatch):
    """A sandbox prompts for every exec outside the project: skip it when unneeded."""
    monkeypatch.delenv("SCOPE_NO_REEXEC", raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_venv.parent.parent / "other-python"))
    monkeypatch.setattr(common, "missing_runtime_modules", lambda: [])
    assert common.venv_reexec_argv(["/x/scope.py", "idn", "--json"]) is None


def test_missing_runtime_modules_reports_what_is_absent(monkeypatch):
    """Independent of what the test environment happens to have installed."""
    import importlib.util

    monkeypatch.setattr(common, "REQUIRED_MODULES", ("pyvisa", "definitely-not-a-module"))
    missing = common.missing_runtime_modules()
    assert "definitely-not-a-module" in missing
    if importlib.util.find_spec("pyvisa") is None:
        assert "pyvisa" in missing
    else:
        assert "pyvisa" not in missing


# ------------------------------------------------------------------- data home

def _home(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path / "home")
    monkeypatch.delenv("SCOPE_HOME", raising=False)


def test_data_home_env_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("SCOPE_HOME", str(tmp_path / "explicit"))
    assert common.data_home() == tmp_path / "explicit"


def test_data_home_uses_existing_project_home(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    local = proj / ".emb-agent" / "bench" / "scope"
    local.mkdir(parents=True)
    monkeypatch.chdir(proj)
    assert common.data_home() == local


def test_data_home_stays_inside_for_a_new_project(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    proj = tmp_path / "proj"
    (proj / ".emb-agent").mkdir(parents=True)
    monkeypatch.chdir(proj)
    assert common.data_home() == proj / ".emb-agent" / "bench" / "scope"


def test_data_home_keeps_a_legacy_dir(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    legacy = tmp_path / "home" / ".local" / "share" / "scope"
    legacy.mkdir(parents=True)
    proj = tmp_path / "proj"
    (proj / ".emb-agent").mkdir(parents=True)
    monkeypatch.chdir(proj)
    assert common.data_home() == legacy


def test_data_home_outside_any_project_is_legacy(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    assert common.data_home() == tmp_path / "home" / ".local" / "share" / "scope"
