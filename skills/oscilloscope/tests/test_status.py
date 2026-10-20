import json

from test_capture import base, run


def test_status_reads_the_instrument_in_one_call(rigol, tmp_path):
    home = tmp_path / "home"
    p = run(base(rigol, "status", "--channels", "1,2", "--json"), home)
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    assert data["ok"] is True
    assert data["family"] == "rigol"
    assert data["idn"].startswith("RIGOL")
    assert data["settings"]["trigger_status"] == "STOP"
    assert set(data["channels"]) == {"1", "2"}
    for key in ("display", "scale", "offset", "coupling", "probe"):
        assert key in data["channels"]["1"]


def test_status_lists_queries_the_instrument_did_not_answer(rigol, tmp_path):
    """An empty reply must not be reported as a value."""
    home = tmp_path / "home"
    data = json.loads(run(base(rigol, "status", "--json"), home).stdout)
    # The mock answers only a few queries; those it does not know return "".
    assert data["settings"]["timebase_scale"] is None
    assert "timebase_scale" in data["unsupported"]
