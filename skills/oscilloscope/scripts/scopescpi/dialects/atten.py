"""ATTEN ADS/AT series (no public SCPI reference)."""

from __future__ import annotations

from .base import Dialect

class AttenDialect(Dialect):
    """ATTEN ADS/AT series: no public SCPI reference found; generic fallback."""

    name = "atten"

    def acquire(self, inst, ch, points):
        raise RuntimeError("ATTEN waveform command is not documented publicly; use scpi.")
