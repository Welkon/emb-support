"""Read a VCD trace (Icarus Verilog, Verilator, Wokwi, ...) as channel samples.

Lets any HDL simulation stand in for real hardware: the trace is sampled at a
chosen rate and written in the capture layout the decoder already understands.
"""

from __future__ import annotations

import re
from pathlib import Path

from .common import SkillError

_SCALE = {"fs": 1e-15, "ps": 1e-12, "ns": 1e-9, "us": 1e-6, "ms": 1e-3, "s": 1.0}


def parse(path: str | Path) -> dict:
    """Return ``{"scale": seconds-per-tick, "signals": {name: [(tick, level)]}}``."""
    text = Path(path).read_text(errors="replace")
    scale = None
    match = re.search(r"\$timescale\s+(?:(\d+)\s*)?(fs|ps|ns|us|ms|s)\s*\$end", text)
    if match:
        scale = int(match.group(1) or 1) * _SCALE[match.group(2)]
    if scale is None:
        scale = 1e-12
    names: dict[str, str] = {}
    for code, name in re.findall(r"\$var\s+\w+\s+\d+\s+(\S+)\s+([^\s$]+)", text):
        names[code] = name
    events: dict[str, list[tuple[float, int]]] = {code: [] for code in names}
    tick = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            tick = int(line[1:])
            continue
        if line[0] in "01xzXZ" and len(line) > 1:
            code = line[1:]
            if code in events:
                events[code].append((tick * scale, 1 if line[0] == "1" else 0))
        elif line[0] in "bB":
            parts = line.split()
            if len(parts) == 2 and parts[1] in events:
                value = parts[0][1:]
                events[parts[1]].append((tick * scale, 1 if value.strip("0") else 0))
    return {"scale": scale, "signals": {names[code]: events[code] for code in names}}


def sample(signals: dict, wanted: dict[str, str], rate_hz: int) -> dict[str, bytes]:
    """Sample the named signals at ``rate_hz`` and pack 8 samples per byte."""
    duration = max((events[-1][0] for events in signals.values() if events), default=0.0)
    count = int(duration * rate_hz)
    if count <= 0:
        raise SkillError("vcd_empty", "the trace has no timestamps",
                         ["check that $dumpvars ran and the testbench advanced time"])
    channels: dict[str, bytes] = {}
    for name, signal in wanted.items():
        events = signals.get(signal)
        if events is None:
            raise SkillError("vcd_signal_missing", f"{signal!r} is not in the trace",
                             [f"available: {', '.join(sorted(signals))}"])
        levels = bytearray((count + 7) // 8)
        position = 0
        for index in range(count):
            moment = index / rate_hz
            while position + 1 < len(events) and events[position + 1][0] <= moment:
                position += 1
            if events[position][1]:
                levels[index // 8] |= 1 << (index % 8)
        channels[name] = bytes(levels)
    return channels
