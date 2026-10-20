import pathlib

import pytest

import dap


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    for env in ("MCU_DEBUG_HOME", "DAPLINK_HOME"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path / "home")
    return tmp_path / "home"


def test_env_wins(fake_home, monkeypatch):
    monkeypatch.setenv("MCU_DEBUG_HOME", str(fake_home / "explicit"))
    assert dap._data_home() == fake_home / "explicit"


def test_legacy_env_still_accepted(fake_home, monkeypatch):
    monkeypatch.setenv("DAPLINK_HOME", str(fake_home / "daplink"))
    assert dap._data_home() == fake_home / "daplink"


def test_uses_existing_project_home(fake_home, monkeypatch, tmp_path):
    project = tmp_path / "proj"
    local = project / ".emb-agent" / "bench" / "mcu-debug"
    local.mkdir(parents=True)
    (fake_home / ".local/share/mcu-debug").mkdir(parents=True)
    monkeypatch.chdir(project)
    assert dap._data_home() == local


def test_new_project_stays_inside(fake_home, monkeypatch, tmp_path):
    project = tmp_path / "proj"
    (project / ".emb-agent").mkdir(parents=True)
    monkeypatch.chdir(project)
    assert dap._data_home() == project / ".emb-agent" / "bench" / "mcu-debug"


def test_keeps_legacy_dir(fake_home, monkeypatch, tmp_path):
    legacy = fake_home / ".local/share/daplink"
    legacy.mkdir(parents=True)
    project = tmp_path / "proj"
    (project / ".emb-agent").mkdir(parents=True)
    monkeypatch.chdir(project)
    assert dap._data_home() == legacy


def test_prefers_mcu_debug_over_daplink(fake_home, monkeypatch):
    (fake_home / ".local/share/mcu-debug").mkdir(parents=True)
    (fake_home / ".local/share/daplink").mkdir(parents=True)
    monkeypatch.chdir(fake_home)
    assert dap._data_home() == fake_home / ".local/share/mcu-debug"
