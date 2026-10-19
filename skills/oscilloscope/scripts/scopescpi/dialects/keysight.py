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
    """Rohde & Schwarz RTB/RTO/HMO: CHANnel<n>:DATA? plus X/Y increment queries."""

    name = "rns"

    def acquire(self, inst, ch, points):
        inst.write("FORMat UINT,8")
        raw = inst.query_block(f"CHANnel{ch}:DATA?")
        samples = list(raw)
        meta = {
            "points": len(samples), "count": len(samples), "format": 0, "type": 0,
            "xincr": float(inst.query(f"CHANnel{ch}:DATA:XINCrement?")),
            "xorig": float(inst.query(f"CHANnel{ch}:DATA:XORigin?")),
            "xref": 0,
            "yincr": float(inst.query(f"CHANnel{ch}:DATA:YINCrement?")),
            "yorig": float(inst.query(f"CHANnel{ch}:DATA:YORigin?")),
            "yref": 0,
        }
        return meta, samples
