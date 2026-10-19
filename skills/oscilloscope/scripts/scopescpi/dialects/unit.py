"""UNI-T UPO series."""

from __future__ import annotations

from ..common import fnum
from .base import Dialect

class UnitDialect(Dialect):
    """UNI-T UPO series (manual: UPO 3000E & UPO 2000E Programming Manual)."""

    name = "unit"

    def ch(self, n): return f"CHAN{n}"
    def channel_scale(self, n, v): return f":CHAN{n}:SCAL {fnum(v)}"
    def channel_offset(self, n, v): return f":CHAN{n}:OFFS {fnum(v)}"
    def channel_coupling(self, n, v): return f":CHAN{n}:COUP {v}"
    def channel_probe(self, n, v): return f":CHAN{n}:PROB {int(v)}"
    def channel_display(self, n, on): return f":CHAN{n}:DISP {'ON' if on else 'OFF'}"

    def timebase_scale(self, v): return f":TIMebase:SCALe {fnum(v)}"
    def timebase_offset(self, v): return f":TIMebase:OFFSet {fnum(v)}"

    def run(self): return ":RUN"
    def stop(self): return ":STOP"
    def single(self): return ":TRIGger:SWEep SINGle"
    def arm_single(self): return [":TRIGger:SWEep SINGle", ":RUN"] 

    def trigger_type(self): return ":TRIGger:MODE EDGE"
    def trigger_source(self, n): return f":TRIGger:SOURce CHAN{n}"
    def trigger_level(self, v): return f":TRIGger:LEVel {fnum(v)}"
    def trigger_slope(self, v): return f":TRIGger:EDGE:SLOPe {'POSitive' if 'RIS' in v.upper() else 'NEGative'}"
    def trigger_sweep(self, v): return f":TRIGger:SWEep {v}"

    def waveform_setup(self, n, points):
        cmds = [":WAVeform:FORMat BYTE", f":WAVeform:SOURce CHAN{n}"]
        if points:
            cmds.append(f":WAVeform:POINts {int(points)}")
        return cmds

    MEAS = {"vpp": "VPP", "vmax": "VMAX", "vmin": "VMIN", "mean": "VAVerage",
            "rms": "VRMS", "freq": "FREQuency", "period": "PERiod",
            "duty": "PDUTY", "rise": "RISetime", "fall": "FALLtime"}

    def measure_query(self, item, n):
        key = self.MEAS.get(item)
        return f":MEASure:{key}? CHAN{n}" if key else None

    def screenshot_queries(self): return [":DISPlay:DATA?"]
