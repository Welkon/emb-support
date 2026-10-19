"""Micsig MHO series."""

from __future__ import annotations

import re

from ..common import fnum
from .base import Dialect

class MicsigDialect(Dialect):
    """Micsig MHO series (vendor SCPI manual + tralamazza/micsig-rs)."""

    name = "micsig"

    def ch(self, n): return f"CHANnel{n}"
    def channel_scale(self, n, v): return f":CHANnel{n}:SCALe {fnum(v)}"
    def channel_offset(self, n, v): return f":CHANnel{n}:POSition {fnum(v)}"
    def channel_coupling(self, n, v): return f":CHANnel{n}:COUPle {v}"
    def channel_probe(self, n, v): return f":CHANnel{n}:PROBe {int(v)}"
    def channel_display(self, n, on): return f":CHANnel{n}:DISPlay {'ON' if on else 'OFF'}"

    def timebase_scale(self, v): return f":TIMebase:EXTent {fnum(v)}"
    def timebase_offset(self, v): return f":TIMebase:POSition {fnum(v)}"

    def run(self): return ":MENU:RUN"
    def stop(self): return ":MENU:STOP"
    def single(self): return ":MENU:SINGLE"
    def arm_single(self): return [":MENU:SINGLE", ":MENU:RUN"]
    def state_queries(self): return [":TRIGger:STATus?"]

    def trigger_source(self, n): return f":TRIGger:EDGE:SOURce CH{n}"
    def trigger_level(self, v): return f":TRIGger:EDGE:LEVel {fnum(v)}"
    def trigger_slope(self, v): return f":TRIGger:EDGE:SLOPe {'RISE' if 'RIS' in v.upper() else 'FALL'}"
    def trigger_sweep(self, v):
        v = v.upper()
        return f":TRIGger:MODE {'AUTO' if v.startswith('AUTO') else 'NORMal'}"

    MEAS = {"vpp": "PKPK", "vmax": "MAX", "vmin": "MIN", "mean": "AVER",
            "freq": "FREQ", "period": "PER"}

    def measure_query(self, item, n):
        key = self.MEAS.get(item)
        return f":MEASure:{key}? CH{n}" if key else None

    def waveform_setup(self, n, points):
        cmds = [f":WAVeform:SOURce CH{n}", ":WAVeform:MODE NORMal", ":WAVeform:FORMat BYTE"]
        if points:
            cmds += [":WAVeform:STARt 1", f":WAVeform:STOP {int(points)}"]
        return cmds

    def parse_preamble(self, text):
        vals = [v for v in re.split(r",", text.strip()) if v != ""]
        if len(vals) < 9:
            raise ValueError(f"unexpected waveform preamble: {text[:120]}")
        n = [float(x) for x in vals[:9]]
        count = int(n[2])
        return {"format": int(n[0]), "type": int(n[1]), "points": count, "count": count,
                "xincr": n[3], "xorig": n[4], "xref": n[5],
                "yincr": n[6], "yorig": n[7], "yref": n[8]}

    def screenshot_queries(self): return [":SYS:SCR?"]
