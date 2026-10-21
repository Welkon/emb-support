"""What a measurement came from, and how coarse it is.

Instrument measurements and waveform-derived measurements are not the same
kind of number. Each one now carries its source, unit, resolution (one ADC
code or one sample interval) and a resolution-based uncertainty, instead of a
bare float the caller has to over-trust.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

VOLTAGE_ITEMS = {"vpp", "vmin", "vmax", "mean", "vavg", "rms"}
TIME_ITEMS = {"period", "pulse_width", "negative_width", "rise", "fall"}
UNITS = {
    "vpp": "V", "vmin": "V", "vmax": "V", "mean": "V", "vavg": "V", "rms": "V",
    "freq": "Hz", "period": "s", "duty": "%",
    "pulse_width": "s", "negative_width": "s", "rise": "s", "fall": "s",
}


@dataclass(frozen=True)
class Measurement:
    value: float
    unit: str
    source: str                  # instrument | waveform
    resolution: float | None = None
    uncertainty: float | None = None
    basis: str | None = None

    def as_dict(self) -> dict:
        out = {"value": self.value, "unit": self.unit, "source": self.source}
        if self.resolution is not None:
            out["resolution"] = self.resolution
        if self.uncertainty is not None:
            out["uncertainty"] = self.uncertainty
        if self.basis:
            out["basis"] = self.basis
        return out


def unit_for(item: str) -> str:
    return UNITS.get(item, "")


def from_instrument(item: str, value: float) -> Measurement:
    """The instrument answered. We do not invent an accuracy figure."""
    return Measurement(value, unit_for(item), "instrument")


def from_waveform(item: str, value: float, meta: dict) -> Measurement:
    """Computed from the record: the ADC code and sample interval bound it."""
    yincr = meta.get("yincr") or None
    xincr = meta.get("xincr") or None
    if item in VOLTAGE_ITEMS:
        uncertainty = None
        if yincr:
            uncertainty = yincr if item in ("vpp", "vmin", "vmax") else yincr / math.sqrt(12)
        return Measurement(value, "V", "waveform", yincr, uncertainty, "ADC code width")
    if item in TIME_ITEMS:
        return Measurement(value, "s", "waveform", xincr, xincr, "sample interval")
    if item == "freq" and value and xincr:
        return Measurement(value, "Hz", "waveform", None, value * value * xincr,
                           "sample interval")
    return Measurement(value, unit_for(item), "waveform")
