import json

from test_cli import base, run


def test_status_describes_the_whole_supply_in_one_call(psu, tmp_path):
    home = tmp_path / "home"
    p = run(base(psu, "status", "--json"), home)
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    assert data["ok"] is True
    assert data["family"] == "rigol"
    assert set(data["channels"]) == {"1", "2", "3"}
    ch1 = data["channels"]["1"]
    for key in ("voltage_set", "current_set", "voltage", "current", "output"):
        assert key in ch1, key
    assert data["capabilities"]["output_state"] is True
    assert "warnings" not in data


def test_status_reports_live_setpoints_and_output(psu, tmp_path):
    home = tmp_path / "home"
    assert run(base(psu, "set", "--ch", "1", "--voltage", "5", "--current", "1"), home).returncode == 0
    assert run(base(psu, "output", "on", "--ch", "1", "--yes"), home).returncode == 0
    p = run(base(psu, "status", "--json"), home)
    assert p.returncode == 0, p.stderr
    ch1 = json.loads(p.stdout)["channels"]["1"]
    assert ch1["voltage_set"] == 5.0
    assert ch1["current_set"] == 1.0
    assert ch1["voltage"] == 5.0
    assert ch1["output"] == "ON"


def test_status_warns_that_an_output_is_still_on(psu, tmp_path):
    home = tmp_path / "home"
    assert run(base(psu, "output", "on", "--ch", "2", "--yes"), home).returncode == 0
    data = json.loads(run(base(psu, "status", "--json"), home).stdout)
    assert any("channel 2" in w for w in data["warnings"])
