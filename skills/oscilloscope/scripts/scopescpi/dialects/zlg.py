"""ZLG ZDS series (no public SCPI reference)."""

from __future__ import annotations

from .base import Dialect

class ZlgDialect(Dialect):
    """ZLG ZDS series: no public SCPI reference found; generic fallback."""

    name = "zlg"

    def acquire(self, inst, ch, points):
        raise RuntimeError("ZLG ZDS waveform command is not documented publicly; use scpi.")
