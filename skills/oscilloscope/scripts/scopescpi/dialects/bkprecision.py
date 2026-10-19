"""BK Precision 2540/2560 (LeCroy MAUI command set)."""

from __future__ import annotations

from ..common import fnum
from .base import Dialect

class BkPrecisionDialect(Dialect):
    """BK Precision 2540/2560 (LeCroy MAUI command set)."""

    name = "bkprecision"

    def ch(self, n): return f"C{n}"
    def channel_scale(self, n, v): return f"C{n}:VDIV {fnum(v)}"
    def channel_offset(self, n, v): return f"C{n}:OFST {fnum(v)}"
    def channel_coupling(self, n, v): return f"C{n}:CPL {v}"
    def channel_probe(self, n, v): return f"C{n}:ATTN {fnum(v)}"
    def channel_display(self, n, on): return f"C{n}:TRA {'ON' if on else 'OFF'}"

    def timebase_scale(self, v): return f"TDIV {fnum(v)}"
    def timebase_offset(self, v): return f"TIME {fnum(v)}"

    def trigger_level(self, v): return f"TRLV {fnum(v)}"
    def trigger_slope(self, v): return f"TRSL {'POS' if 'RIS' in v.upper() else 'NEG'}"
    def trigger_sweep(self, v):
        v = v.upper()
        return f"TRMD {'NORM' if v.startswith('NORM') else v}"
    def trigger_type(self): return "TRSE EDGE"
    def trigger_source(self, n): return f"TRSE EDGE,SR,C{n},HT,OFF"
    def arm_single(self): return ["TRMD SINGLE"]
    def state_queries(self): return []

    MEAS = {"vpp": "VPP", "vmax": "MAX", "vmin": "MIN", "mean": "MEAN",
            "rms": "RMS", "freq": "FREQ", "period": "PER"}

    def measure_query(self, item, n):
        key = self.MEAS.get(item)
        return f"C{n}:PAVA? {key}" if key else None

    def screenshot_queries(self): return ["SCDP", ":DISPlay:DATA?"]

    def acquire(self, inst, ch, points):
        raise RuntimeError(
            "BK Precision captures use LeCroy's binary WAVEDESC format (C{n}:WF? DAT2); "
            "not implemented. Use measure/scpi or the vendor software.")
