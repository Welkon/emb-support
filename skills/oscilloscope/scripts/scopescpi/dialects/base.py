"""Base SCPI dialect: command builders and waveform parsing hooks."""

from __future__ import annotations

import re

from ..common import fnum

class Dialect:
    """SCPI command builder. Override only what differs per vendor."""

    name = "generic"

    def __init__(self, idn: str = ""):
        self.idn = idn

    # --- channel
    def ch(self, n: int) -> str:
        return f"CHANnel{n}"

    def channel_scale(self, n, v): return f":{self.ch(n)}:SCALe {fnum(v)}"
    def channel_offset(self, n, v): return f":{self.ch(n)}:OFFSet {fnum(v)}"
    def channel_coupling(self, n, v): return f":{self.ch(n)}:COUPling {v}"
    def channel_probe(self, n, v): return f":{self.ch(n)}:PROBe {fnum(v)}"
    def channel_display(self, n, on): return f":{self.ch(n)}:DISPlay {'ON' if on else 'OFF'}"

    # --- timebase
    def timebase_scale(self, v): return f":TIMebase:SCALe {fnum(v)}"
    def timebase_offset(self, v): return f":TIMebase:OFFSet {fnum(v)}"

    # --- acquisition
    def run(self): return ":RUN"
    def run_commands(self): return [self.run()]
    def stop(self): return ":STOP"
    def single(self): return ":SINGle"
    def autoscale(self): return ":AUToscale"

    # --- trigger
    def trigger_source(self, n): return f":TRIGger:EDGE:SOURce CHANnel{n}"
    def trigger_level(self, v): return f":TRIGger:EDGE:LEVel {fnum(v)}"
    def trigger_slope(self, v): return f":TRIGger:EDGE:SLOPe {v}"
    def trigger_sweep(self, v): return f":TRIGger:SWEep {v}"
    def trigger_type(self): return ":TRIGger:MODE EDGE"
    def force_trigger(self): return ":TRIGger:FORCe"
    def autoset(self): return ":AUToscale"
    def trigger_pulse(self, width, polarity="POSitive", when="LESSthan"):
        return []
    def arm_single(self): return [self.single()]
    def state_queries(self): return [":TRIGger:STATe?", ":ACQuire:STATE?"]

    # --- status snapshot (read-only)
    # One query set so `status` can describe the instrument in a single
    # connection: on a sandboxed host every extra command is an approval prompt.
    def status_queries(self) -> "dict[str, str]":
        return {
            "timebase_scale": ":TIMebase:SCALe?",
            "timebase_offset": ":TIMebase:OFFSet?",
            "trigger_status": ":TRIGger:STATus?",
            "trigger_mode": ":TRIGger:MODE?",
            "trigger_source": ":TRIGger:EDGE:SOURce?",
            "trigger_level": ":TRIGger:EDGE:LEVel?",
            "trigger_slope": ":TRIGger:EDGE:SLOPe?",
            "trigger_sweep": ":TRIGger:SWEep?",
            "acquire_points": ":ACQuire:POINts?",
            "acquire_type": ":ACQuire:TYPE?",
            "sample_rate": ":ACQuire:SRATe?",
            "system_error": ":SYSTem:ERRor?",
        }

    def channel_status_queries(self, n: int) -> "dict[str, str]":
        return {
            "display": f":{self.ch(n)}:DISPlay?",
            "scale": f":{self.ch(n)}:SCALe?",
            "offset": f":{self.ch(n)}:OFFSet?",
            "coupling": f":{self.ch(n)}:COUPling?",
            "probe": f":{self.ch(n)}:PROBe?",
        }

    # --- waveform transfer
    def waveform_setup(self, n: int, points: int | None) -> list[str]:
        cmds = [f":WAVeform:SOURce {self.wave_source(n)}",
                ":WAVeform:FORMat BYTE"]
        if points:
            cmds.append(f":WAVeform:POINts {int(points)}")
        return cmds

    def wave_source(self, n: int) -> str:
        return f"CHANnel{n}"

    def preamble_query(self) -> str:
        return ":WAVeform:PREamble?"

    def data_query(self) -> str:
        return ":WAVeform:DATA?"

    def parse_preamble(self, text: str) -> dict:
        vals = [v for v in re.split(r"[,]", text.strip()) if v != ""]
        if len(vals) < 10:
            raise ValueError(f"unexpected waveform preamble: {text[:120]}")
        nums = [float(v) for v in vals[:10]]
        return {"format": int(nums[0]), "type": int(nums[1]),
                "points": int(nums[2]), "count": int(nums[3]),
                "xincr": nums[4], "xorig": nums[5], "xref": nums[6],
                "yincr": nums[7], "yorig": nums[8], "yref": nums[9]}

    def measure_query(self, item: str, n: int) -> str | None:
        if item in ("pulse_width", "negative_width"):
            return None          # no portable query; use the captured waveform
        return f":MEASure:{item.upper()}? {self.measure_source(n)}"

    def clean(self, text: str) -> str:
        return text.strip()

    def parse_measure(self, text: str) -> float:
        return float(self.clean(text))

    def measure_source(self, n: int) -> str:
        return f"CHANnel{n}"

    def offset_for_center(self, volts: float) -> float:
        """Translate a desired screen-centre voltage into the offset value."""
        return volts

    # --- screenshot
    def screenshot_queries(self) -> list[str]:
        return [":DISPlay:DATA? PNG", ":DISPlay:DATA? PNG,SCReen,COLor", ":DISPlay:DATA?"]

    def screenshot(self, inst):
        for query in self.screenshot_queries():
            try:
                data = inst.query_block(query)
            except Exception:
                continue
            if data and (data.startswith(b"\x89PNG") or data.startswith(b"\xff\xd8")
                         or data.startswith(b"BM")):
                return query, data
        return None, None

    def acquire(self, inst, ch: int, points: int | None):
        for cmd in self.waveform_setup(ch, points):
            inst.write(cmd)
        text = inst.query(self.preamble_query())
        meta = self.parse_preamble(text)
        raw = inst.query_block(self.data_query())
        return meta, raw

    def to_volts(self, raw, meta: dict) -> list[float]:
        """Scaled samples. Families with an unusual preamble override this."""
        yincr, yorig, yref = meta["yincr"], meta["yorig"], meta["yref"]
        return [(float(b) - yref) * yincr + yorig for b in raw]
