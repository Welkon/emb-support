"""Fluke PM3370/3380/3390 CombiScope."""

from __future__ import annotations

from ..common import fnum
from .base import Dialect

class FlukeDialect(Dialect):
    """Fluke PM3370/PM3380/PM3390 CombiScope (SCPI-99 style manual)."""

    name = "fluke"

    def channel_display(self, n, on):
        return f'SENSe:FUNCtion:{"ON" if on else "OFF"} "XTIMe:VOLTage{n}"'
    def channel_scale(self, n, v): return f"SENSe:VOLTage:RANGe:PTPeak {fnum(v)}"
    def channel_offset(self, n, v): return f"SENSe:VOLTage:RANGe:OFFSet {fnum(v)}"

    def timebase_scale(self, v): return f"SENSe:SWEep:TIME {fnum(v)}"
    def timebase_offset(self, v): return f"SENSe:SWEep:OFFSet:TIME {fnum(v)}"

    def trigger_source(self, n): return f"TRIGger:SOURce INTernal{n}"
    def trigger_level(self, v): return f"TRIGger:LEVel {fnum(v)}"

    def measure_query(self, item, n): return None
    def screenshot_queries(self): return [":DISPlay:DATA?"]

    def acquire(self, inst, ch, points):
        bits = 16 if (points and points > 8192) else 8
        inst.write(f"FORMat INTeger,{bits}")
        n = int(points or 4096)
        inst.write(f"TRACe:POINts CH{ch},{n}")
        payload = inst.query_block(f"TRACe? CH{ch}")
        if not payload:
            raise RuntimeError("empty Fluke TRACe response")
        fmt = payload[0]
        body = payload[1:]
        if len(body) >= 2:
            body = body[:-2]  # checksum + newline
        if fmt == 16:
            samples = [int.from_bytes(body[i:i + 2], "big") for i in range(0, len(body) - 1, 2)]
            divisor = 51200.0
        else:
            samples = list(body)
            divisor = 200.0

        ptpeak = float(inst.query("SENSe:VOLTage:RANGe:PTPeak?"))
        offset = float(inst.query("SENSe:VOLTage:RANGe:OFFSet?"))
        sweep = float(inst.query("SENSe:SWEep:TIME?"))
        dt = sweep / len(samples) if samples else 1.0
        meta = {
            "points": len(samples), "count": len(samples), "format": fmt, "type": 0,
            "xincr": dt, "xorig": -sweep / 2, "xref": 0,
            "yincr": ptpeak / divisor, "yorig": -offset, "yref": 0,
        }
        return meta, samples
