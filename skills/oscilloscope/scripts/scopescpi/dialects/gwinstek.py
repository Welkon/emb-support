"""GW Instek GDS series."""

from __future__ import annotations

from .base import Dialect

class GwInstekDialect(Dialect):
    name = "gwinstek"

    def acquire(self, inst, ch, points):
        raise RuntimeError(
            "GW Instek GDS waveform transfer uses a model-specific command "
            "(:CHANnel<n>:DATA?); not verified for this family. Use scpi.")

    def measure_query(self, item, n):
        mapping = {"vpp": "VPP", "vmax": "VMAX", "vmin": "VMIN", "vavg": "VAV",
                   "vrms": "VRMS", "freq": "FREQ", "period": "PER"}
        key = mapping.get(item)
        return f":MEASure:{key}? CHANnel{n}" if key else None
