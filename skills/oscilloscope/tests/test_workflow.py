"""Intent-level commands: one invocation per bench question.

The point of these tests is the number of round trips, not the SCPI strings:
`arm` must set up, trigger, capture and measure in one connection; `watch`
must sample repeatedly in one connection; `status` must survive a query the
instrument rejects.
"""

import csv
import json
import math
import re
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


def test_cli_arm_no_wait_reports_armed_without_capturing(rigol, tmp_path):
    p = run(base(rigol, "arm", "--no-wait", "--json"), tmp_path / "home")
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    assert data["armed"] is True
    assert data["captured"] is False
    assert data["trigger_state"] == "STOP"
    assert "timed_out" not in data
    assert not any("DATA?" in c for c in rigol.commands)


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


# ---------------------------------------------------------------- invariants

SCPI_LIKE = re.compile(r"^[:*][A-Za-z]")


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for key, value in obj.items():
            yield from _strings(key)
            yield from _strings(value)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            yield from _strings(value)


def test_status_reports_where_the_connection_came_from(rigol, tmp_path):
    home = tmp_path / "home"
    first = json.loads(run(base(rigol, "status", "--json"), home).stdout)
    assert first["connection"]["source"] == "explicit-host"
    assert first["connection"]["endpoint"].startswith("TCPIP::")
    second = json.loads(run(["status", "--json"], home).stdout)
    assert second["connection"]["source"] == "config-host"


def test_intent_outputs_do_not_leak_instrument_commands(rigol, tmp_path):
    """The caller reads values and paths, never a command it must reason about."""
    home = tmp_path / "home"
    cases = [
        ("status", "--channels", "1,2", "--json"),
        ("arm", "--wait", "1", "--measure", "vpp,pulse_width",
         "--out", str(tmp_path / "run.csv"), "--json"),
        ("watch", "--channel", "1,2", "--samples", "1", "--json"),
        ("capture", "--out", str(tmp_path / "cap.csv"), "--json"),
        ("measure", "--items", "vpp,pulse_width", "--json"),
        ("run", "run", "--json"),
        ("channel", "--ch", "1", "--scale", "1", "--json"),
        ("timebase", "--scale", "1e-3", "--json"),
        ("trigger", "--source", "1", "--level", "1", "--json"),
        ("shot", "--out", str(tmp_path / "shot.png"), "--json"),
        ("monitor", "--dry-run", "--json"),
        ("monitor", "--channels", "1", "--max-events", "1", "--duration", "2",
         "--outdir", str(tmp_path / "events"), "--json"),
    ]
    for args in cases:
        p = run(base(rigol, *args), home)
        assert p.returncode == 0, (args, p.stderr)
        leaked = [s for s in _strings(json.loads(p.stdout)) if SCPI_LIKE.match(s)]
        assert not leaked, (args, leaked)


def test_remembered_connection_covers_every_verb(rigol, tmp_path):
    home = tmp_path / "home"
    assert run(base(rigol, "idn"), home).returncode == 0
    cases = [
        ["status", "--json"],
        ["measure", "--items", "vpp", "--json"],
        ["capture", "--out", str(tmp_path / "cap.csv"), "--json"],
        ["watch", "--samples", "1", "--json"],
        ["arm", "--wait", "1", "--json"],
        ["shot", "--out", str(tmp_path / "shot.png"), "--json"],
    ]
    for args in cases:
        p = run(args, home)          # no --host/--port on purpose
        assert p.returncode == 0, (args, p.stderr)


def test_session_reconnects_and_retries_once(scope, monkeypatch):
    from scopescpi import session as sm

    class Fake:
        def __init__(self, fail):
            self.fail, self.closed, self.calls = fail, False, 0

        def query(self, cmd):
            self.calls += 1
            if self.fail:
                raise RuntimeError("VI_ERROR_TMO (-1): timeout")
            return "ok"

        def close(self):
            self.closed = True

    first, second = Fake(True), Fake(False)
    seq = iter([first, second])
    monkeypatch.setattr(sm, "connect", lambda a: next(seq))
    s = sm.Session(types.SimpleNamespace())
    assert s.query("X") == "ok"
    assert first.closed is True
    assert s.reconnects == 1


def test_session_does_not_reconnect_on_a_usage_error(scope, monkeypatch):
    from scopescpi import session as sm

    class Fake:
        def query(self, cmd):
            raise ValueError("wrong argument")

        def close(self):
            pass

    calls = []
    monkeypatch.setattr(sm, "connect", lambda a: calls.append(a) or Fake())
    s = sm.Session(types.SimpleNamespace())
    with pytest.raises(ValueError):
        s.query("X")
    assert s.reconnects == 0
    assert len(calls) == 1


def test_every_measurement_item_has_a_host_side_path(scope):
    class HostOnly(scope.Dialect):
        def measure_query(self, item, n):
            return None

        def acquire(self, inst, ch, points):
            volts = [3.3 if (i % 100) < 30 else 0.0 for i in range(1000)]
            meta = {"points": 1000, "xincr": 1e-6, "xorig": 0.0, "xref": 0.0,
                    "yincr": 1.0, "yorig": 0.0, "yref": 0.0}
            return meta, volts

    got = scope.measure_channel(None, HostOnly("X"), 1, scope.MEASURE_ITEMS)
    assert set(scope.MEASURE_ITEMS) <= set(got)


def test_analyze_covers_every_channel(tmp_path):
    path = tmp_path / "two.csv"
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "ch1", "ch2"])
        for i in range(3000):
            t = i * 1e-6
            w.writerow([f"{t:.12g}", f"{math.sin(2 * math.pi * 1000 * t):.9g}",
                        "3.3" if (t % 1e-3) < 300e-6 else "0"])
    p = run(["analyze", "--csv", str(path), "--channel", "2", "--json"], tmp_path / "home")
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    assert set(data["channels"]) == {"1", "2"}
    assert data["channel"] == "2"
    assert data["max_high_s"] == pytest.approx(300e-6, abs=2e-6)
    assert data["channels"]["2"]["max_low_s"] == pytest.approx(700e-6, abs=2e-6)
    assert data["channels"]["1"]["freq"] == pytest.approx(1000, rel=0.02)
