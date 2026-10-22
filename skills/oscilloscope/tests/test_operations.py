"""Front-panel operations beyond the measurement path."""

import json

import pytest

from test_capture import base, run


def test_arm_sets_acquire_mode_and_holdoff(rigol, tmp_path):
    p = run(base(rigol, "arm", "--wait", "1", "--acquire", "average",
                 "--averages", "16", "--holdoff", "0.001", "--json"),
            tmp_path / "home")
    assert p.returncode == 0, p.stderr
    commands = " ".join(rigol.commands)
    assert ":ACQuire:TYPE AVERages" in commands
    assert ":ACQuire:AVERages 16" in commands
    assert ":TRIGger:HOLDoff 0.001" in commands


def test_arm_video_trigger(rigol, tmp_path):
    p = run(base(rigol, "arm", "--wait", "1", "--trigger-type", "video",
                 "--video-standard", "pal", "--video-polarity", "negative",
                 "--channels", "1", "--json"), tmp_path / "home")
    assert p.returncode == 0, p.stderr
    commands = " ".join(rigol.commands)
    assert ":TRIGger:MODE VIDeo" in commands
    assert ":TRIGger:VIDeo:STANdard PAL" in commands
    assert ":TRIGger:VIDeo:POLarity NEGATIVE" in commands


def test_arm_slope_trigger(rigol, tmp_path):
    p = run(base(rigol, "arm", "--wait", "1", "--trigger-type", "slope",
                 "--source", "1", "--level", "1", "--slope-level-b", "0.5",
                 "--json"), tmp_path / "home")
    assert p.returncode == 0, p.stderr
    commands = " ".join(rigol.commands)
    assert ":TRIGger:MODE SLOPe" in commands
    assert ":TRIGger:SLOPe:LEVelA 1" in commands
    assert ":TRIGger:SLOPe:LEVelB 0.5" in commands


def test_channel_invert_and_bandwidth_limit(rigol, tmp_path):
    p = run(base(rigol, "channel", "--ch", "2", "--invert", "on",
                 "--bw-limit", "20m", "--json"), tmp_path / "home")
    assert p.returncode == 0, p.stderr
    commands = " ".join(rigol.commands)
    assert ":CHANnel2:INVert ON" in commands
    assert ":CHANnel2:BWLimit 20M" in commands


def test_snapshot_apply_restores_the_setup(rigol, tmp_path):
    setup = {
        "idn": "RIGOL TECHNOLOGIES,DS1202Z-E,DS1ZE255216073,00.06.04",
        "family": "rigol",
        "settings": {
            "timebase_scale": "5.0000000e-05", "timebase_offset": "0.00015",
            "trigger_source": "CHAN2", "trigger_level": "1.5",
            "trigger_slope": "POSitive", "trigger_sweep": "NORMal",
            "trigger_holdoff": "1e-06", "acquire_type": "AVERages",
            "acquire_averages": "16", "acquire_points": "12000",
        },
        "channels": {"1": {"display": "1", "scale": "0.5", "offset": "-2.3",
                           "coupling": "DC", "probe": "10",
                           "invert": "0", "bw_limit": "OFF"}},
    }
    path = tmp_path / "setup.json"
    path.write_text(json.dumps(setup))
    p = run(base(rigol, "snapshot", "apply", str(path), "--json"), tmp_path / "home")
    assert p.returncode == 0, p.stderr
    commands = " ".join(rigol.commands)
    assert ":TIMebase:MAIN:SCALe 5e-05" in commands
    assert ":CHANnel1:SCALe 0.5" in commands
    assert ":CHANnel1:OFFSet -2.3" in commands
    assert ":TRIGger:EDGE:SOURce CHANnel2" in commands
    assert ":TRIGger:EDGE:LEVel 1.5" in commands
    assert ":ACQuire:TYPE AVERages" in commands
    assert ":ACQuire:AVERages 16" in commands


def test_snapshot_save_writes_a_restorable_file(rigol, tmp_path):
    path = tmp_path / "setup.json"
    p = run(base(rigol, "snapshot", "save", str(path), "--channels", "1,2", "--json"),
            tmp_path / "home")
    assert p.returncode == 0, p.stderr
    assert path.exists()
    saved = json.loads(path.read_text())
    assert "settings" in saved and "channels" in saved
    assert set(saved["channels"]) == {"1", "2"}


def test_capture_exports_in_normal_mode_then_restores(rigol, tmp_path):
    rigol.acquire_type = "HRES"
    p = run(base(rigol, "capture", "--channels", "1", "--json"), tmp_path / "home")
    assert p.returncode == 0, p.stderr
    commands = rigol.commands
    normal = commands.index(":ACQuire:TYPE NORMal")
    data = next(i for i, c in enumerate(commands) if c.startswith(":WAVeform:DATA?"))
    restored = max(i for i, c in enumerate(commands) if c == ":ACQuire:TYPE HRESolution")
    assert normal < data < restored


def test_an_explicit_acquire_mode_is_not_overridden(rigol, tmp_path):
    rigol.acquire_type = "HRES"
    p = run(base(rigol, "capture", "--channels", "1", "--acquire", "average", "--json"),
            tmp_path / "home")
    assert p.returncode == 0, p.stderr
    commands = " ".join(rigol.commands)
    assert ":ACQuire:TYPE AVERages" in commands
    assert ":ACQuire:TYPE NORMal" not in commands
    assert ":ACQuire:TYPE HRESolution" not in commands


def test_arm_restores_the_ambient_acquire_mode(rigol, tmp_path):
    rigol.acquire_type = "HRES"
    p = run(base(rigol, "arm", "--wait", "1", "--json"), tmp_path / "home")
    assert p.returncode == 0, p.stderr
    commands = rigol.commands
    normal = commands.index(":ACQuire:TYPE NORMal")
    data = next(i for i, c in enumerate(commands) if c.startswith(":WAVeform:DATA?"))
    restored = max(i for i, c in enumerate(commands) if c == ":ACQuire:TYPE HRESolution")
    assert normal < data < restored


def test_timeout_error_names_the_workaround(scope):
    class SlowDialect:
        def acquire(self, inst, ch, points):
            raise RuntimeError("VI_ERROR_TMO (-1073807339): Timeout expired")

    with pytest.raises(RuntimeError) as error:
        scope.acquire_with_recovery(object(), SlowDialect(), [1], None, attempts=1)
    assert "--acquire normal" in str(error.value)
    assert "--points 1200" in str(error.value)
