"""LeCroy MAUI family."""

from __future__ import annotations

from ..common import fnum
from .base import Dialect

class LeCroyDialect(Dialect):
    name = "lecroy"

    def acquire(self, inst, ch, points):
        raise RuntimeError(
            "LeCroy waveform transfer uses C{n}:WF? DAT2 (WAVEDESC binary); "
            "not implemented. Use measure/scpi or the LeCroy MAUI tools.")

    def timebase_scale(self, v): return f":TIMebase:SCALe {fnum(v)}"

    def measure_query(self, item, n): return None

    def screenshot_queries(self):
        return [":HARDcopy:SETUP? PNG", ":DISPlay:DATA?"]
