"""Tektronix TBS/TDS/DPO/MSO."""

from __future__ import annotations

import re

from ..common import fnum
from .base import Dialect

TEK_PREAMBLE = {
    "xincr": ("WFMPre:XINcr?", "WFMOutpre:XINcr?", "WFMPRE:XINCR?"),
    "xorig": ("WFMPre:XZEro?", "WFMOutpre:XZEro?", "WFMPRE:XZERO?"),
    "xref": ("WFMPre:PT_Off?", "WFMOutpre:PT_Off?", "WFMPRE:PT_OFF?"),
    "yincr": ("WFMPre:YMUlt?", "WFMOutpre:YMUlt?", "WFMPRE:YMULT?"),
    "yorig": ("WFMPre:YZEro?", "WFMOutpre:YZEro?", "WFMPRE:YZERO?"),
    "yref": ("WFMPre:YOFf?", "WFMOutpre:YOFf?", "WFMPRE:YOFF?"),
    "points": ("WFMOutpre:NR_Pt?", "WFMPre:NR_Pt?"),
}


def _q_first(inst, commands):
    last = None
    for cmd in commands:
        try:
            val = inst.query(cmd).strip()
            if val:
                return val
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"no response for {commands[0]}: {last}")


class TektronixDialect(Dialect):
    """Tektronix TBS/TDS/DPO family.

    Uses the ASCII curve path that is validated on TBS1102B; preamble fields are
    probed with WFMPre/WFMOutpre/WFMPRE fallbacks because the spelling differs
    across firmware generations.
    """

    name = "tektronix"

    def ch(self, n): return f"CH{n}"

    def timebase_scale(self, v): return f":HORizontal:SCAle {fnum(v)}"
    def timebase_offset(self, v): return f":HORizontal:POSition {fnum(v)}"

    def trigger_source(self, n): return f":TRIGger:A:EDGE:SOURce CH{n}"
    def trigger_level(self, v): return f":TRIGger:A:EDGE:LEVel {fnum(v)}"
    def trigger_slope(self, v): return f":TRIGger:A:EDGE:SLOpe {v}"
    def trigger_sweep(self, v): return f":TRIGger:A:MODe {v}"
    def trigger_type(self): return ":TRIGger:A:TYPe EDGE"

    def trigger_pulse(self, width, polarity="POSitive", when="LESSthan"):
        return [":TRIGger:A:TYPe PULSe",
                f":TRIGger:A:PULse:WIDth:WHEn {when}",
                f":TRIGger:A:PULse:WIDth:WIDth {fnum(width)}",
                f":TRIGger:A:PULse:POLarity {polarity}"]

    def arm_single(self):
        return [":ACQuire:STOPAfter SEQuence", ":ACQuire:STATE RUN"]

    def state_queries(self):
        return [":ACQuire:STATE?", ":TRIGger:STATe?"]

    def measure_query(self, item, n): return None

    def screenshot_queries(self):
        return [":SAVE:IMAGe:FILEFormat PNG", ":DISPlay:DATA? PNG"]

    def acquire(self, inst, ch, points):
        inst.write(f"DATa:SOUrce CH{ch}")
        inst.write("DATa:ENCdg ASCII")
        inst.write("DATa:WIDth 1")
        if points:
            inst.write("DATa:STARt 1")
            inst.write(f"DATa:STOP {int(points)}")
        text = inst.query("CURVe?")
        samples = [float(x) for x in re.split(r"[,;\s]+", text.strip()) if x]
        meta = {key: float(_q_first(inst, cmds)) for key, cmds in TEK_PREAMBLE.items()}
        meta.update({"points": len(samples), "count": len(samples),
                     "format": 0, "type": 0})
        return meta, samples
