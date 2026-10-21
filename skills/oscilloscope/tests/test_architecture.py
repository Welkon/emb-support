"""Invariants that keep the intent layer from turning back into a script.

These are the coverage mechanism: a new verb, dialect or measurement that
breaks the contract fails here instead of on the bench.
"""

import json
from pathlib import Path

import pytest

from test_capture import base, run

ROOT = Path(__file__).resolve().parents[1]


def test_verbs_do_not_open_connections(scope):
    """One Session per intent; the retry/close policy lives in session.py."""
    source = (ROOT / "scripts" / "scopescpi" / "cli.py").read_text()
    assert "connect(" not in source
    assert "Session(a)" in source


def test_every_capability_is_total(scope):
    """Each measurement is either queried or computed; never unreachable."""
    from scopescpi.capabilities import MEASUREMENTS
    from scopescpi.dialects import FAMILIES

    for family, dialect_cls in FAMILIES.items():
        dialect = dialect_cls("IDN")
        for item, capability in MEASUREMENTS.items():
            query = dialect.measure_query(item, 1)
            assert query is None or isinstance(query, str), (family, item)
            assert query is not None or capability.fallback, (
                f"{family}/{item}: no driver query and no waveform fallback")


def test_status_advertises_what_can_be_asked(rigol, tmp_path):
    p = run(base(rigol, "status", "--json"), tmp_path / "home")
    assert p.returncode == 0, p.stderr
    caps = json.loads(p.stdout)["capabilities"]
    assert "vpp" in caps["measurements"]
    assert "pulse_width" in caps["measurements"]
    assert caps["screenshot"] is True
    assert caps["pulse_trigger"] is False


def test_result_refuses_to_emit_instrument_commands(scope):
    from scopescpi.result import Result

    result = Result()
    result.set("command", ":TIMebase:MAIN:SCALe 1")
    with pytest.raises(ValueError):
        result.to_dict()


def test_evidence_writes_are_atomic(scope, tmp_path):
    from scopescpi.evidence import Evidence

    evidence = Evidence()
    path = tmp_path / "artifact.json"
    evidence.json("json", path, {"ok": True})
    assert json.loads(path.read_text()) == {"ok": True}
    assert not list(tmp_path.glob("*.tmp"))


def test_verbs_write_through_evidence(scope):
    source = (ROOT / "scripts" / "scopescpi" / "cli.py").read_text()
    assert "write_svg(" not in source
    assert ".write_text(" not in source


def test_verbs_share_the_plan_executor(scope):
    """arm, capture --single and monitor all arm through Executor."""
    source = (ROOT / "scripts" / "scopescpi" / "cli.py").read_text()
    assert source.count("Executor(inst, d)") >= 3
    assert "for cmd in d.arm_single()" not in source


def test_connection_resolution_has_one_home(scope):
    cli = (ROOT / "scripts" / "scopescpi" / "cli.py").read_text()
    transport = (ROOT / "scripts" / "scopescpi" / "transport.py").read_text()
    connection = (ROOT / "scripts" / "scopescpi" / "connection.py").read_text()
    assert "connect(" not in cli
    assert "def connect(" not in transport
    assert "def resolve(" in connection
