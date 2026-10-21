"""Rigol DS/MSO/DHO."""

from __future__ import annotations

from ..common import fnum
from .base import Dialect

class RigolDialect(Dialect):
    name = "rigol"

    def state_queries(self):
        # DS1000Z uses STATus. ACQuire:STATE? does not exist on these models.
        return [":TRIGger:STATus?"]

    def status_queries(self):
        # DS1000Z has :ACQuire:MDEPth?, not :ACQuire:POINts?. Asking for POINts
        # makes the USB session die ("Invalid session handle").
        return {
            "timebase_scale": ":TIMebase:MAIN:SCALe?",
            "timebase_offset": ":TIMebase:MAIN:OFFSet?",
            "trigger_status": ":TRIGger:STATus?",
            "trigger_mode": ":TRIGger:MODE?",
            "trigger_source": ":TRIGger:EDGE:SOURce?",
            "trigger_level": ":TRIGger:EDGE:LEVel?",
            "trigger_slope": ":TRIGger:EDGE:SLOPe?",
            "trigger_sweep": ":TRIGger:SWEep?",
            "trigger_holdoff": ":TRIGger:HOLDoff?",
            "acquire_points": ":ACQuire:MDEPth?",
            "acquire_type": ":ACQuire:TYPE?",
            "acquire_averages": ":ACQuire:AVERages?",
            "sample_rate": ":ACQuire:SRATe?",
            "system_error": ":SYSTem:ERRor?",
        }

    def acquire(self, inst, ch, points):
        meta, raw = super().acquire(inst, ch, points)
        # DS1000Z reports YORigin in ADC counts, and its offset sign is
        # inverted: offset -2.3 V puts the screen centre at +2.3 V. Read the
        # offset rather than guessing. Verified on DS1202Z-E fw 00.06.04:
        # the result matches the instrument's own VMIN/VMAX/VAVG.
        try:
            meta["ycenter"] = -float(inst.query(f":CHANnel{ch}:OFFSet?"))
        except Exception:  # noqa: BLE001
            meta["ycenter"] = meta["yorig"]
        return meta, raw

    def to_volts(self, raw, meta):
        center = meta.get("ycenter", meta["yorig"])
        return [(float(b) - meta["yref"]) * meta["yincr"] + center for b in raw]

    def offset_for_center(self, volts: float) -> float:
        # Rigol's offset sign is inverted: -2.3 V puts the screen centre at +2.3 V.
        return -volts

    def channel_invert(self, n, on):
        return f":CHANnel{n}:INVert {'ON' if on else 'OFF'}"

    def channel_bw_limit(self, n, value):
        return f":CHANnel{n}:BWLimit {'20M' if str(value).lower() in ('20m', 'on') else 'OFF'}"

    _ACQ_MODES = {"normal": "NORMal", "average": "AVERages",
                  "peak": "PEAK", "hires": "HRESolution"}

    def acquire_mode(self, mode):
        return [f":ACQuire:TYPE {self._ACQ_MODES[mode.lower()]}"]

    def acquire_averages(self, n):
        return [f":ACQuire:AVERages {int(n)}"]

    def acquire_depth(self, depth):
        return [f":ACQuire:MDEPth {depth}"]

    def trigger_holdoff(self, seconds):
        return [f":TRIGger:HOLDoff {fnum(seconds)}"]

    def trigger_slope_setup(self, n, slope, level_a, level_b):
        commands = [":TRIGger:MODE SLOPe", f":TRIGger:SLOPe:SOURce CHANnel{n}"]
        if slope:
            commands.append(":TRIGger:SLOPe:SLOPe " +
                            ("POSitive" if slope.lower().startswith("ris") else "NEGative"))
        if level_a is not None:
            commands.append(f":TRIGger:SLOPe:LEVelA {fnum(level_a)}")
        if level_b is not None:
            commands.append(f":TRIGger:SLOPe:LEVelB {fnum(level_b)}")
        return commands

    def trigger_video_setup(self, n, polarity, standard, line):
        commands = [":TRIGger:MODE VIDeo", f":TRIGger:VIDeo:SOURce CHANnel{n}"]
        if polarity:
            commands.append(f":TRIGger:VIDeo:POLarity {polarity.upper()}")
        if standard:
            commands.append(f":TRIGger:VIDeo:STANdard {standard.upper()}")
        if line is not None:
            commands += [":TRIGger:VIDeo:MODE LINE", f":TRIGger:VIDeo:LINE {int(line)}"]
        return commands

    def measure_query(self, item, n):
        # Rigol wants the ITEM form and long item names; FREQ alone is not
        # recognised and the instrument then never answers (USB timeout).
        names = {"mean": "VAVG", "vavg": "VAVG", "freq": "FREQuency",
                 "period": "PERiod", "duty": "PDUTy", "rise": "RTIMe",
                 "fall": "FTIMe", "pulse_width": "PWIDth",
                 "negative_width": "NWIDth"}
        return f":MEASure:ITEM? {names.get(item, item.upper())},{self.measure_source(n)}"

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

