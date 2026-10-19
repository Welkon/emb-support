"""Hantek DSO2000 series."""

from __future__ import annotations

from .base import Dialect

class HantekDialect(Dialect):
    """Hantek DSO2000 series (DSO2C50/DOS1104 family).

    Command names follow refs/dso2c50-scpi-commands.md (p96xl/hantek-dso2000-esu-tester).
    Waveform export only works through a private vendor command, so capture is
    rejected with a pointer instead of returning wrong data.
    """

    name = "hantek"

    MEAS = {"vpp": "VPP", "vmax": "VMAX", "vmin": "VMIN", "mean": "VAVG",
            "freq": "FREQ", "period": "PER"}

    def measure_query(self, item, n):
        key = self.MEAS.get(item)
        return f":MEASure:CHANnel{n}:ITEM? {key}" if key else None

    def trigger_slope(self, v):
        return f":TRIGger:EDGe:SLOPe {'RISIng' if 'RIS' in v.upper() else 'FALLing'}"

    def state_queries(self): return [":TRIGger:STATus?"]

    def screenshot_queries(self): return [":DISPlay:DATA?"]

    def acquire(self, inst, ch, points):
        raise RuntimeError(
            "Hantek DSO2000 waveform export is vendor-private "
            "(PRIVate:WAVeform:DATA:ALL?); capture is not implemented. "
            "Use measure/scpi, or export the waveform with the vendor tool.")
