"""Rigol DS/MSO/DHO."""

from __future__ import annotations

from ..common import fnum
from .base import Dialect

class RigolDialect(Dialect):
    name = "rigol"

    def state_queries(self):
        # DS1000Z uses STATus. ACQuire:STATE? does not exist on these models.
        return [":TRIGger:STATus?"]

    def screenshot_queries(self):
        idn = getattr(self, "idn", "").upper()
        # DS1000Z-E models do not answer the screen-dump query.
        if "DS1" in idn and "Z-E" in idn:
            return []
        return [":DISPlay:DATA?", ":DISPlay:DATA? PNG"]

    def timebase_scale(self, v): return f":TIMebase:MAIN:SCALe {fnum(v)}"

    def waveform_setup(self, n, points):
        cmds = [f":WAVeform:SOURce {self.wave_source(n)}",
                ":WAVeform:FORMat BYTE", ":WAVeform:MODE NORMal"]
        if points:
            cmds.append(f":WAVeform:POINts {int(points)}")
        return cmds

