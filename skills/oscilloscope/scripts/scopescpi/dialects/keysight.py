"""Keysight/Agilent InfiniiVision and Rohde & Schwarz (shared style)."""

from __future__ import annotations

from ..common import fnum
from .base import Dialect

class KeysightDialect(Dialect):
    name = "keysight"

    def measure_query(self, item, n):
        mapping = {"vpp": "VPP", "vmax": "VMAX", "vmin": "VMIN", "vavg": "VAV",
                   "vrms": "VRMS", "freq": "FREQ", "period": "PER", "duty": "DUTY"}
        key = mapping.get(item)
        return f":MEASure:{key}? CHANnel{n}" if key else None

    def screenshot_queries(self):
        return [":DISPlay:DATA? PNG,SCReen,COLor", ":DISPlay:DATA? PNG", ":DISPlay:DATA?"]


class RnsDialect(KeysightDialect):
    name = "rns"

    def acquire(self, inst, ch, points):
        raise RuntimeError(
            "R&S RTB/RTO/HMO waveform transfer uses :CHANnel<n>:DATA? with a header "
            "query; not implemented for this dialect yet. Use scpi or the vendor tool.")
