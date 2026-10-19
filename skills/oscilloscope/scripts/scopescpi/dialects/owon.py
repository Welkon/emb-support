"""Owon / Hanmatek / PeakTech (shared protocol)."""

from __future__ import annotations

import json
import re

from ..common import fnum, _parse_rate, _parse_scaled
from .base import Dialect

class OwonDialect(Dialect):
    """Owon / Hanmatek (SDS1104, DOS1104).

    Documented by the SCPI_COMMANDS.md in bushjavier/hanmatek-dos1104-py:
    replies end with "->", waveform payloads are a 4-byte length + data, and
    the screen header is JSON.
    """

    name = "owon"

    def ch(self, n): return f"CH{n}"
    def channel_scale(self, n, v): return f":CH{n}:SCAL {fnum(v)}"
    def channel_offset(self, n, v): return f":CH{n}:OFFS {fnum(v)}"
    def channel_coupling(self, n, v): return f":CH{n}:COUP {v}"
    def channel_probe(self, n, v): return f":CH{n}:PROB {int(v)}X"
    def channel_display(self, n, on): return f":CH{n}:DISP {'ON' if on else 'OFF'}"

    def timebase_scale(self, v): return f":HORIzontal:Scale {fnum(v)}"
    def timebase_offset(self, v): return f":HORIzontal:OFFSET {fnum(v)}"

    def run(self): return ":RUNning RUN"
    def stop(self): return ":RUNning STOP"
    def single(self): return ":TRIGger:SINGle:Sweep SINGLE"
    def arm_single(self): return [":TRIGger:SINGle:Sweep SINGLE", ":RUNning RUN"]
    def state_queries(self): return [":TRIG:STAT?"]
    def autoset(self): return ":AUTOset on"

    def trigger_source(self, n): return f":TRIGger:SINGle:SOURce CH{n}"
    def trigger_level(self, v): return f":TRIGger:SINGle:EDGe:LEVel {fnum(v)}"
    def trigger_slope(self, v): return f":TRIGger:SINGle:EDGE {'RISE' if 'RIS' in v.upper() else 'FALL'}"
    def trigger_sweep(self, v): return f":TRIGger:SINGle:Sweep {v}"
    def trigger_type(self): return ":TRIGger:SINGle:MODE EDGE"

    MEAS = {"vpp": "PKPK", "vmax": "MAX", "vmin": "MIN", "mean": "AVER",
            "rms": "CYCRMS", "freq": "FREQ", "period": "PER", "duty": "PDUTY",
            "rise": "RTIME"}

    def measure_query(self, item, n):
        key = self.MEAS.get(item)
        return f":MEAS:CH{n}:{key}?" if key else None

    def clean(self, text):
        return text.strip().removesuffix("->").strip()

    def parse_measure(self, text):
        m = re.search(r"(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*([munp]?V|A|Hz|kHz|MHz|s|ms|us|ns|%)?", self.clean(text))
        if not m:
            raise ValueError(f"cannot parse measurement: {text!r}")
        mult = {"V": 1, "mV": 1e-3, "uV": 1e-6, "nV": 1e-9, "A": 1,
                "Hz": 1, "kHz": 1e3, "MHz": 1e6, "s": 1, "ms": 1e-3,
                "us": 1e-6, "ns": 1e-9, "%": 1}
        return float(m.group(1)) * mult.get(m.group(2) or "V", 1)

    def screenshot_queries(self):
        return [":DATA:WAVE:SCREEN:BMP?"]

    def screenshot(self, inst):
        for query in self.screenshot_queries():
            try:
                data = inst.query_prefixed(query)
            except Exception:
                continue
            if data and data.startswith(b"BM"):
                return query, data
        return None, None

    def acquire(self, inst, ch, points):
        head = inst.query_prefixed(":DATA:WAVE:SCREEN:HEAD?")
        meta_json = json.loads(head.decode(errors="replace"))
        payload = inst.query_prefixed(f":DATA:WAVE:SCREEN:CH{ch}?")
        samples = [int.from_bytes(payload[i:i + 2], "little")
                   for i in range(0, len(payload) - 1, 2)]
        chinfo = next((c for c in meta_json.get("CHANNEL", [])
                       if str(c.get("NAME", "")).upper() == f"CH{ch}"), {})
        vdiv = _parse_scaled(chinfo.get("SCALE", "1V"))
        rate = _parse_rate(meta_json.get("SAMPLE", {}).get("SAMPLERATE", "1kS/s"))
        dt = 1.0 / rate if rate else 1.0
        meta = {"points": len(samples), "count": len(samples), "format": 0, "type": 0,
                "xincr": dt, "xorig": -len(samples) * dt / 2, "xref": 0,
                "yincr": vdiv / 6400.0, "yorig": 0.0, "yref": 0.0}
        return meta, samples


class PeakTechDialect(OwonDialect):
    """PeakTech 13xx series: same protocol as Owon (4-byte length + JSON header)."""

    name = "peaktech"
