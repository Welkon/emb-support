"""Invariants that keep the intent layer from turning back into a script.

These are the coverage mechanism: a new verb, dialect or measurement that
breaks the contract fails here instead of on the bench.
"""

import json
from pathlib import Path

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
