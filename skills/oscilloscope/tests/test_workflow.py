"""Intent-level commands: one invocation per bench question.

The point of these tests is the number of round trips, not the SCPI strings:
`arm` must set up, trigger, capture and measure in one connection; `watch`
must sample repeatedly in one connection; `status` must survive a query the
instrument rejects.
"""

import json
import types

import pytest

from test_capture import base, run


def test_rigol_volts_match_the_instrument(scope):
    """DS1000Z YORigin is in counts; the preamble alone gives -114 V.

    Numbers from a live DS1202Z-E (fw 00.06.04): offset -2.3 V -> yorig -115,
    codes 151..203 -> 2.78..3.82 V, which is what the instrument measures.
    """
    d = scope.RigolDialect("RIGOL TECHNOLOGIES,DS1202Z-E,DS1ZE255216073,00.06.04")
    meta = {"yincr": 0.02, "yorig": -115.0, "yref": 127.0, "ycenter": 2.3}
    assert d.to_volts([151, 177, 203], meta) == pytest.approx([2.78, 3.30, 3.82])
    # A second offset proves the centre is the inverted channel offset.
    meta2 = {"yincr": 0.02, "yorig": -175.0, "yref": 127.0, "ycenter": 3.5}
    assert d.to_volts([91, 117, 143], meta2) == pytest.approx([2.78, 3.30, 3.82])


def test_rigol_ds1000z_queries_stay_in_the_driver(scope):
    d = scope.RigolDialect("RIGOL TECHNOLOGIES,DS1202Z-E,DS1ZE255216073,00.04.04")
    assert d.status_queries()["acquire_points"] == ":ACQuire:MDEPth?"
    assert d.measure_query("vavg", 1) == ":MEASure:ITEM? VAVG,CHANnel1"
    assert d.measure_query("vpp", 2) == ":MEASure:ITEM? VPP,CHANnel2"
    assert d.measure_query("pulse_width", 2) == ":MEASure:ITEM? PWIDth,CHANnel2"


def test_pulse_width_is_computed_when_the_driver_has_no_query(scope):
    d = scope.make_dialect("ANY", "generic")
    assert d.measure_query("pulse_width", 1) is None
    times = [i * 1e-6 for i in range(2000)]
    volts = [3.3 if (t % 1e-3) < 300e-6 else 0.0 for t in times]
    st = scope.stats(volts, times)
    assert st["max_high_s"] == pytest.approx(300e-6, abs=2e-6)
    assert st["max_low_s"] == pytest.approx(700e-6, abs=2e-6)


def test_acquire_reconnects_after_a_lost_transfer(scope, monkeypatch):
    """A bad block read leaves the handle out of sync; a fresh handle recovers."""
    from scopescpi import cli as cli_mod

    class Fake:
        def __init__(self, dead):
            self.dead = dead

        def write(self, cmd):
            pass

        def query(self, cmd):
            if "PREamble" in cmd:
                return "0,0,4,1,1e-06,0,0,0.1,0,0"
            if "OFFSet" in cmd:
                return "0"
            return "0"

        def query_block(self, cmd):
            if self.dead:
                raise RuntimeError("VI_ERROR_TMO (-1073807339): timeout")
            return bytes([0, 1, 2, 3])

        def close(self):
            pass

    dead, alive = Fake(True), Fake(False)
    monkeypatch.setattr(cli_mod, "connect", lambda a: alive)
    a = types.SimpleNamespace(resource=None, host=None, port=None, timeout=1,
                              backend=None, family=None)
    d = scope.RigolDialect("RIGOL")
    inst, data, log = cli_mod._acquire_resilient(a, dead, d, [1], None, no_recovery=True)
    assert inst is alive
    assert log == []
    assert data[1]["volts"] == pytest.approx([0.0, 0.1, 0.2, 0.3])


def test_status_reconnects_after_a_dead_query(scope, monkeypatch):
    from scopescpi import cli as cli_mod

    class Flaky:
        def __init__(self, fail=None):
            self.fail, self.closed, self.queries = fail, False, []

        def query(self, cmd):
            self.queries.append(cmd)
            if self.fail and self.fail in cmd:
                raise RuntimeError("Invalid session handle")
            return "1"

        def close(self):
            self.closed = True

    first, second = Flaky(fail="POIN"), Flaky()
    monkeypatch.setattr(cli_mod, "connect", lambda a: second)
    reconnects = [0]
    inst, value, err = cli_mod._status_query(
        types.SimpleNamespace(), first, ":ACQuire:POINts?", reconnects)
    assert (inst, value, err) == (second, "1", None)
    assert first.closed is True
    assert reconnects == [1]
    assert second.queries == [":ACQuire:POINts?"]


def test_status_does_not_reconnect_on_a_normal_error(scope, monkeypatch):
    from scopescpi import cli as cli_mod

    class Broken:
        def query(self, cmd):
            raise ValueError("syntax error")

        def close(self):
            pass

    calls = []
    monkeypatch.setattr(cli_mod, "connect", lambda a: calls.append(a) or Broken())
    reconnects = [0]
    _, value, err = cli_mod._status_query(
        types.SimpleNamespace(), Broken(), ":BOGus?", reconnects)
    assert value is None and "syntax error" in err
    assert calls == [] and reconnects == [0]


def test_cli_arm_one_shot(rigol, tmp_path):
    home = tmp_path / "home"
    out = tmp_path / "wave.csv"
    p = run(base(rigol, "arm", "--ch", "1:0.5:-2.3:10:DC", "--timebase", "50e-6",
                 "--source", "1", "--level", "1.5", "--slope", "rising",
                 "--channels", "1", "--wait", "2", "--measure", "vpp,vavg",
                 "--out", str(out), "--json"), home)
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    assert data["captured"] is True
    assert data["trigger_state"] == "STOP"
    assert data["channels"]["1"]["points"] == 100
    assert "setup" not in data          # the caller gets values, not commands
    assert data["measurements"]["1"]["vpp"] == 2.0
    assert data["measurements"]["1"]["vavg"] == 2.0
    assert out.exists()
    cmds = " ".join(rigol.commands)
    assert ":CHANnel1:SCALe 0.5" in cmds
    assert ":CHANnel1:OFFSet -2.3" in cmds
    assert ":CHANnel1:PROBe 10" in cmds
    assert ":TIMebase:MAIN:SCALe 5e-05" in cmds
    assert ":TRIGger:EDGE:LEVel 1.5" in cmds
    assert cmds.count(":TRIGger:MODE EDGE") == 1


def test_cli_arm_reports_a_timeout_without_capturing(rigol, tmp_path):
    home = tmp_path / "home"
    rigol.trigger_status = "RUN"       # never reaches STOP
    p = run(base(rigol, "arm", "--wait", "0.2", "--json"), home)
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    assert data["captured"] is False
    assert data["timed_out"] is True
    assert not any("DATA?" in c for c in rigol.commands)


def test_cli_watch_samples_one_connection(rigol, tmp_path):
    home = tmp_path / "home"
    p = run(base(rigol, "watch", "--channel", "1,2", "--items", "vpp,vavg",
                 "--samples", "3", "--interval", "0", "--state", "--json"), home)
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    assert len(data["rows"]) == 3
    assert data["summary"]["1"]["vpp"]["min"] == 2.0
    assert data["rows"][0]["trigger_state"] is True
    assert data["rows"][0]["channels"]["2"]["vavg"] == 2.0


def test_cli_scpi_batch_runs_on_one_connection(rigol, tmp_path):
    home = tmp_path / "home"
    p = run(base(rigol, "scpi", "*IDN?", ":TRIGger:STATus?", "--query", "--json"), home)
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    assert [r["response"] for r in data] == [rigol.idn, "STOP"]
    assert all(r["ok"] for r in data)


def test_explicit_connection_is_remembered(rigol, tmp_path):
    home = tmp_path / "home"
    assert run(base(rigol, "idn"), home).returncode == 0
    cfg = json.loads((home / "config.json").read_text())
    assert cfg["host"] == "127.0.0.1"
    assert cfg["port"] == rigol.port
    # No --host/--port: the next command must reuse the remembered connection.
    p = run(["idn"], home)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout)["idn"] == rigol.idn
