"""Rigol DS/MSO/DHO."""

from __future__ import annotations

from ..common import fnum
from .base import Dialect

class RigolDialect(Dialect):
    name = "rigol"

    def timebase_scale(self, v): return f":TIMebase:MAIN:SCALe {fnum(v)}"

    def waveform_setup(self, n, points):
        cmds = [f":WAVeform:SOURce {self.wave_source(n)}",
                ":WAVeform:FORMat BYTE", ":WAVeform:MODE NORMal"]
        if points:
            cmds.append(f":WAVeform:POINts {int(points)}")
        return cmds

    def screenshot_queries(self):
        return [":DISPlay:DATA?", ":DISPlay:DATA? PNG"]
