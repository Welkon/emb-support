"""Fluke PM3370/3380/3390 CombiScope."""

from __future__ import annotations

from ..common import fnum
from .base import Dialect

class FlukeDialect(Dialect):
    """Fluke PM3370/PM3380/PM3390 CombiScope (SCPI-99 style manual)."""

    name = "fluke"

    def channel_display(self, n, on):
        return f'SENSe:FUNCtion:{"ON" if on else "OFF"} "XTIMe:VOLTage{n}"'
    def channel_scale(self, n, v): return f"SENSe:VOLTage:RANGe:PTPeak {fnum(v)}"
    def channel_offset(self, n, v): return f"SENSe:VOLTage:RANGe:OFFSet {fnum(v)}"

    def timebase_scale(self, v): return f"SENSe:SWEep:TIME {fnum(v)}"
    def timebase_offset(self, v): return f"SENSe:SWEep:OFFSet:TIME {fnum(v)}"

    def trigger_source(self, n): return f"TRIGger:SOURce INTernal{n}"
    def trigger_level(self, v): return f"TRIGger:LEVel {fnum(v)}"

    def measure_query(self, item, n): return None
    def screenshot_queries(self): return [":DISPlay:DATA?"]

    def acquire(self, inst, ch, points):
        raise RuntimeError(
            "Fluke CombiScope traces use TRACe?/TRACe:POINts with instrument-specific "
            "scaling; capture is not implemented. Use measure/scpi or FlukeView.")
