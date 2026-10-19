"""Siglent SDS series."""

from __future__ import annotations

import re

from ..common import fnum
from .base import Dialect

class SiglentDialect(Dialect):
    name = "siglent"

    def timebase_scale(self, v): return f":TDIV {fnum(v)}"

    def wave_source(self, n): return f"C{n}"

    def measure_source(self, n): return f"C{n}"

    def trigger_source(self, n): return f":TRIGger:EDGE:SOURce C{n}"

    def parse_preamble(self, text):
        vals = [v for v in re.split(r"[,]", text.strip()) if v != ""]
        if len(vals) >= 10:
            return super().parse_preamble(text)
        # Siglent SDS: 5 fields (points, xincr, xorig, yincr, yorig)
        if len(vals) >= 5:
            n, xincr, xorig, yincr, yorig = [float(v) for v in vals[:5]]
            return {"format": 0, "type": 0, "points": int(n), "count": int(n),
                    "xincr": xincr, "xorig": xorig, "xref": 0.0,
                    "yincr": yincr, "yorig": yorig, "yref": 0.0}
        raise ValueError(f"unexpected waveform preamble: {text[:120]}")
