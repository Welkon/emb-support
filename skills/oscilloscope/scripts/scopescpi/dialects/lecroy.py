"""LeCroy MAUI family (WaveRunner/WaveSurfer, BK Precision 2540/2560).

Waveform transfer uses ``C<n>:WF? DAT2``. The reply is a definite-length block
containing a WAVEDESC descriptor followed by signed 8- or 16-bit samples.
Offsets and scaling follow the published LeCroy remote-control format and the
MIT-licensed lecroyparser project.
"""

from __future__ import annotations

import struct

from ..common import fnum
from .base import Dialect


def parse_wavedesc(payload: bytes) -> tuple[dict, list[int]]:
    """Parse a LeCroy WAVEDESC + sample payload into (meta, samples)."""
    pos = payload.find(b"WAVEDESC")
    if pos < 0:
        raise ValueError("no WAVEDESC in payload")
    if len(payload) < pos + 188:
        raise ValueError("truncated WAVEDESC")

    # comm_order is itself read little-endian; 0 means the rest is big-endian.
    order = struct.unpack_from("<h", payload, pos + 34)[0]
    e = ">" if order == 0 else "<"

    def i16(off):
        return struct.unpack_from(e + "h", payload, pos + off)[0]

    def i32(off):
        return struct.unpack_from(e + "i", payload, pos + off)[0]

    def f32(off):
        return struct.unpack_from(e + "f", payload, pos + off)[0]

    def f64(off):
        return struct.unpack_from(e + "d", payload, pos + off)[0]

    comm_type = i16(32)          # 0 = 8-bit samples, otherwise 16-bit
    wave_desc = i32(36)
    user_text = i32(40)
    trig_time = i32(48)
    wave_array_1 = i32(60)       # data array length in bytes
    count = i32(116)
    gain = f32(156)
    voff = f32(160)
    interval = f32(176)
    hoff = f64(180)

    start = pos + wave_desc + user_text + trig_time
    raw = payload[start:start + wave_array_1]
    if comm_type == 0:
        samples = list(struct.unpack(e + f"{len(raw)}b", raw))
    else:
        n = len(raw) // 2
        samples = list(struct.unpack(e + f"{n}h", raw[:n * 2]))
    if count <= 0 or count > len(samples):
        count = len(samples)

    meta = {
        "format": comm_type, "type": 0, "points": count, "count": count,
        "xincr": interval, "xorig": hoff, "xref": 0,
        "yincr": gain, "yorig": -voff, "yref": 0,
    }
    return meta, samples[:count]


class LeCroyDialect(Dialect):
    name = "lecroy"

    def ch(self, n): return f"C{n}"

    def channel_scale(self, n, v): return f"C{n}:VDIV {fnum(v)}"
    def channel_offset(self, n, v): return f"C{n}:OFST {fnum(v)}"
    def channel_coupling(self, n, v): return f"C{n}:CPL {v}"
    def channel_probe(self, n, v): return f"C{n}:ATTN {fnum(v)}"
    def channel_display(self, n, on): return f"C{n}:TRA {'ON' if on else 'OFF'}"

    def timebase_scale(self, v): return f"TDIV {fnum(v)}"
    def timebase_offset(self, v): return f"TIME {fnum(v)}"

    def trigger_level(self, v): return f"TRLV {fnum(v)}"
    def trigger_slope(self, v): return f"TRSL {'POS' if 'RIS' in v.upper() else 'NEG'}"
    def trigger_sweep(self, v):
        v = v.upper()
        return f"TRMD {'NORM' if v.startswith('NORM') else v}"
    def trigger_type(self): return "TRSE EDGE"
    def trigger_source(self, n): return f"TRSE EDGE,SR,C{n},HT,OFF"

    def arm_single(self): return ["TRMD SINGLE"]
    def state_queries(self): return []

    MEAS = {"vpp": "VPP", "vmax": "MAX", "vmin": "MIN", "mean": "MEAN",
            "rms": "RMS", "freq": "FREQ", "period": "PER"}

    def measure_query(self, item, n):
        key = self.MEAS.get(item)
        return f"C{n}:PAVA? {key}" if key else None

    def screenshot_queries(self): return ["SCDP", ":DISPlay:DATA?"]

    def acquire(self, inst, ch, points):
        payload = inst.query_block(f"C{ch}:WF? DAT2")
        return parse_wavedesc(payload)
