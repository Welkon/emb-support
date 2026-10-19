"""Hantek DSO2000 series."""

from __future__ import annotations

import struct

from .base import Dialect

CODES_PER_DIV = 25.0   # DSO2000 ADC: 25 codes per vertical division
BLOCK = 2000           # samples are interleaved in per-channel blocks

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
        """Private multi-packet export, reverse-engineered by p96xl/hantek-dso2000-esu-tester."""
        scale = float(inst.query(f":CHANnel{ch}:SCALe?"))
        offset = float(inst.query(f":CHANnel{ch}:OFFSet?"))

        buf = bytearray()
        total = None
        meta = None
        for _ in range(200):
            raw = inst.read_message("PRIVate:WAVeform:DATA:ALL?")
            if len(raw) < 29 or raw[:2] != b"#9":
                if not buf:
                    continue
                raise RuntimeError("short Hantek waveform packet; is the scope acquiring?")
            total = int(raw[11:20])
            off = int(raw[20:29])
            if off == 0:
                meta = raw[29:128]
            elif meta is None:
                raise RuntimeError("joined a Hantek transfer mid-frame; replug USB and retry")
            payload = raw[128:][:max(0, total - off)]
            if len(buf) < off:
                buf.extend(b"\x00" * (off - len(buf)))
            buf[off:off + len(payload)] = payload
            if off + len(payload) >= total:
                break
        if meta is None or total is None:
            raise RuntimeError("Hantek waveform transfer did not start")

        m = struct.unpack("cc 16x 7s7s7s7s cccc 9s 6s 9x 9s 6s 10x", meta)
        enables = m[6:10]
        enabled = [i + 1 for i, e in enumerate(enables) if e not in (b"\x00", b"0")]
        n = len(enabled) or 1
        if ch not in enabled:
            raise RuntimeError(f"CH{ch} is not enabled on the scope (enabled: {enabled})")

        data = list(struct.unpack(f"{len(buf)}b", bytes(buf)))
        ordinal = enabled.index(ch)
        idx = []
        for start in range(ordinal * BLOCK, len(data), BLOCK * n):
            idx.extend(range(start, min(start + BLOCK, len(data))))
        samples = [data[i] for i in idx]

        try:
            dt = float(inst.query(":WAVeform:XINCrement?"))
        except Exception:
            dt = 1.0 / float(inst.query(":ACQuire:SRATe?"))

        meta_out = {
            "points": len(samples), "count": len(samples), "format": 0, "type": 0,
            "xincr": dt, "xorig": 0.0, "xref": 0,
            "yincr": scale / CODES_PER_DIV, "yorig": -offset, "yref": 0,
        }
        return meta_out, samples
