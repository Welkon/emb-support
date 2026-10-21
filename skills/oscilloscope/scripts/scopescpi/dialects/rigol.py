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
            "acquire_points": ":ACQuire:MDEPth?",
            "acquire_type": ":ACQuire:TYPE?",
            "sample_rate": ":ACQuire:SRATe?",
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

