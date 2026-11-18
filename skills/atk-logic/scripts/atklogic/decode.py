"""Read the vendor's bit-packed BIN files without loading them whole.

Layout, verified against the vendor manual and a real capture: one sample per
bit, least significant bit first.

    采样点 0 -> byte bit 0, 采样点 1 -> byte bit 1, ...

Each channel has its own file, so channels are never interleaved. The unused
high bits of the last byte are zero and ``validBits`` from ``capture.json`` is
the only authority on how many samples are real.
"""

from __future__ import annotations

import heapq
from pathlib import Path

from .common import SkillError

CHUNK_BYTES = 1 << 20
CSV_LIMIT_BITS = 50_000_000

_POPCOUNT = bytes(bin(value).count("1") for value in range(256))
_ONES = _POPCOUNT


class StatsAccumulator:
    def __init__(self, glitch_bits: int = 0) -> None:
        self.bits = 0
        self.ones = 0
        self.edges = 0
        self.rises = 0
        self.falls = 0
        self.first_level: int | None = None
        self.last_level: int | None = None
        self.run_count = 0
        self.min_run: int | None = None
        self.max_run = 0
        self.sum_run = 0
        self.glitches = 0
        self.glitches_by_channel = 0
        self.level = 0
        self.run = 0
        self.started = False
        self.glitch_bits = glitch_bits

    # A level is "closed" when it ends, either at a transition or at the end.
    def _close(self, final: bool = False) -> None:
        if not self.started:
            return
        self.run_count += 1
        self.sum_run += self.run
        self.max_run = max(self.max_run, self.run)
        if self.min_run is None or self.run < self.min_run:
            self.min_run = self.run
        if self.glitch_bits and self.run < self.glitch_bits and not final:
            self.glitches += 1

    def push_bit(self, level: int) -> None:
        self.ones += level
        self.bits += 1
        if not self.started:
            self.started = True
            self.level = level
            self.run = 1
            self.first_level = level
            return
        if level == self.level:
            self.run += 1
        else:
            self.edges += 1
            if level:
                self.rises += 1
            else:
                self.falls += 1
            self._close()
            self.level = level
            self.run = 1

    def push_bytes(self, data: bytes, bit_limit: int) -> None:
        """Consume bytes; ``bit_limit`` caps the bits of the final partial byte."""
        for index, value in enumerate(data):
            remaining = bit_limit - index * 8
            if remaining >= 8:
                if value == 0x00 and self.started and self.level == 0:
                    self.bits += 8
                    self.run += 8
                    continue
                if value == 0xFF and self.started and self.level == 1:
                    self.bits += 8
                    self.ones += 8
                    self.run += 8
                    continue
                for shift in range(8):
                    self.push_bit((value >> shift) & 1)
            else:
                for shift in range(remaining):
                    self.push_bit((value >> shift) & 1)
                break

    def finish(self) -> dict:
        self._close(final=True)
        self.last_level = self.level if self.started else None
        return self.as_dict()

    def as_dict(self) -> dict:
        return {
            "bits": self.bits,
            "ones": self.ones,
            "zeros": self.bits - self.ones,
            "edges": self.edges,
            "rises": self.rises,
            "falls": self.falls,
            "firstLevel": self.first_level,
            "lastLevel": self.last_level,
            "runCount": self.run_count,
            "minRunBits": self.min_run,
            "maxRunBits": self.max_run,
            "meanRunBits": (self.sum_run / self.run_count) if self.run_count else None,
            "glitches": self.glitches,
        }


def _read_bits(path: Path, valid_bits: int):
    """Yield (chunk, bits_in_chunk) for the requested sample range."""
    remaining = valid_bits
    with path.open("rb") as handle:
        while remaining > 0:
            need_bytes = min(CHUNK_BYTES, (remaining + 7) // 8)
            chunk = handle.read(need_bytes)
            if not chunk:
                break
            bits = min(len(chunk) * 8, remaining)
            if bits % 8:
                mask = (1 << (bits % 8)) - 1
                chunk = chunk[:-1] + bytes([chunk[-1] & mask])
            remaining -= bits
            yield chunk, bits


FAST_CHUNK_BYTES = 1 << 22


def _fast_counts(path: Path, valid_bits: int) -> dict:
    """Duty, edges and edge direction for any size, in C-level big-int ops.

    Per chunk: ``D`` is the samples as one integer, bit i = sample i. Then
    ``D ^ (D << 1)`` has a 1 at every sample that differs from its predecessor,
    so a ``bit_count`` answers "how many edges" without touching 25 million
    Python objects.
    """
    remaining = valid_bits
    carry: int | None = None
    ones = edges = rises = falls = 0
    first_level: int | None = None
    last_level = 0
    with path.open("rb") as handle:
        while remaining > 0:
            wanted = min(remaining, FAST_CHUNK_BYTES * 8)
            data = handle.read((wanted + 7) // 8)
            if not data:
                break
            bits = min(len(data) * 8, wanted)
            value = int.from_bytes(data, "little")
            if bits % 8:
                value &= (1 << bits) - 1
            if first_level is None:
                first_level = value & 1
            ones += value.bit_count()
            shifted = (value << 1) | (carry or 0)
            changed = value ^ shifted
            if carry is None:
                changed &= ~1  # the first sample has no predecessor
            changed &= (1 << bits) - 1
            edges += changed.bit_count()
            rises += (value & changed).bit_count()
            falls += ((~value) & changed).bit_count()
            carry = (value >> (bits - 1)) & 1
            last_level = carry
            remaining -= bits
    total = valid_bits - remaining
    return {
        "bits": total,
        "ones": ones,
        "zeros": total - ones,
        "duty": (ones / total) if total else None,
        "edges": edges,
        "rises": rises,
        "falls": falls,
        "firstLevel": first_level,
        "lastLevel": last_level if first_level is not None else None,
    }


def stats(path: str | Path, valid_bits: int, glitch_bits: int = 0,
          pulse_limit: int = 8_000_000) -> dict:
    source = Path(path)
    result = _fast_counts(source, valid_bits)
    if valid_bits <= pulse_limit:
        accumulator = StatsAccumulator(glitch_bits=glitch_bits)
        for chunk, bits in _read_bits(source, valid_bits):
            accumulator.push_bytes(chunk, bits)
        details = accumulator.finish()
        for key in ("runCount", "minRunBits", "maxRunBits", "meanRunBits", "glitches"):
            result[key] = details[key]
        result["meanRunBits"] = details["meanRunBits"]
    else:
        result["runDetailsSkipped"] = (
            f"run lengths need {valid_bits} samples but the limit is {pulse_limit}; "
            "add --run-lengths to spend the time"
        )
    result["validBits"] = valid_bits
    result["fileBits"] = source.stat().st_size * 8
    return result


def runs(path: str | Path, valid_bits: int):
    """Yield ``(level, length)`` runs; cheap for sparse signals."""
    current: int | None = None
    length = 0
    for chunk, bits in _read_bits(Path(path), valid_bits):
        for index in range(bits):
            value = (chunk[index // 8] >> (index % 8)) & 1
            if current is None:
                current, length = value, 1
            elif value == current:
                length += 1
            else:
                yield current, length
                current, length = value, 1
    if current is not None:
        yield current, length


def transitions(path: str | Path, valid_bits: int):
    """Yield ``(bit_index, level)`` at every change, including index 0."""
    position = 0
    for level, length in runs(path, valid_bits):
        yield position, level
        position += length


def slice_levels(path: str | Path, valid_bits: int, start: int = 0, count: int = 1000) -> list[int]:
    start = max(0, min(start, valid_bits))
    count = max(0, min(count, valid_bits - start))
    values: list[int] = []
    if count == 0:
        return values
    with Path(path).open("rb") as handle:
        handle.seek(start // 8)
        block = handle.read((start % 8 + count + 7) // 8)
    for index in range(count):
        bit = start + index
        if bit // 8 >= len(block):
            break
        values.append((block[bit // 8] >> (bit % 8)) & 1)
    return values


def write_csv(out: str | Path, path: str | Path, valid_bits: int, frequency_hz: int,
              start: int = 0, count: int | None = None, transitions_only: bool = False,
              limit_bits: int = CSV_LIMIT_BITS) -> dict:
    """Sample-accurate CSV, or only the edges when the trace is long."""
    produced = valid_bits if count is None else min(count, valid_bits - start)
    if transitions_only and valid_bits > limit_bits:
        raise SkillError(
            "too_many_samples",
            f"{valid_bits} samples is above the CSV limit of {limit_bits}",
            ["slice with --start/--count", "raise --max-bits if you accept the wait"],
        )
    if not transitions_only and produced > limit_bits:
        raise SkillError(
            "too_many_samples",
            f"{produced} samples is above the CSV limit of {limit_bits}",
            ["slice with --start/--count", "raise --max-bits if you accept the wait"],
        )
    bit_ns = 1e9 / frequency_hz
    rows = 0
    with Path(out).open("w", encoding="utf-8") as sink:
        sink.write("bit,time_s,level\n")
        if transitions_only:
            for position, level in transitions(path, valid_bits):
                sink.write(f"{position},{position * bit_ns / 1e9:.9f},{level}\n")
                rows += 1
        else:
            end = valid_bits if count is None else min(valid_bits, start + count)
            values = slice_levels(path, valid_bits, start, end - start)
            for offset, level in enumerate(values):
                position = start + offset
                sink.write(f"{position},{position * bit_ns / 1e9:.9f},{level}\n")
                rows += 1
    return {"file": str(out), "rows": rows, "transitionsOnly": transitions_only}


def write_vcd(out: str | Path, channels: list[dict], frequency_hz: int,
              limit_bits: int = CSV_LIMIT_BITS) -> dict:
    """A VCD any waveform viewer (PulseView, GtkWave) can open."""
    if not channels:
        raise ValueError("no channels for VCD")
    total = sum(int(channel["validBits"]) for channel in channels)
    if total > limit_bits:
        raise SkillError(
            "too_many_samples",
            f"{total} samples is above the VCD limit of {limit_bits}",
            ["select fewer channels with --ch", "slice the capture first"],
        )
    ns_per_bit = 1e9 / frequency_hz
    if ns_per_bit >= 1:
        timescale, ticks_per_bit = "1ns", int(round(ns_per_bit))
    else:
        timescale, ticks_per_bit = "1ps", int(round(1e12 / frequency_hz))
    ticks_per_bit = max(1, ticks_per_bit)

    identifiers = [chr(33 + index) for index in range(min(len(channels), 94))]
    names = [f"ch{channel['id']}" for channel in channels]
    # transitions() is ascending per channel; merge them into one timeline.
    per_channel = [
        ((bit * ticks_per_bit, index, level)
         for bit, level in transitions(channel["file"], channel["validBits"]))
        for index, channel in enumerate(channels)
    ]
    merged = heapq.merge(*per_channel)

    rows = 0
    with Path(out).open("w", encoding="utf-8") as sink:
        sink.write("$date\n  generated by the atk-logic skill\n$end\n")
        sink.write("$version\n  atk-logic\n$end\n")
        sink.write(f"$timescale {timescale} $end\n")
        sink.write("$scope module logic $end\n")
        for identifier, name in zip(identifiers, names):
            sink.write(f"$var wire 1 {identifier} {name} $end\n")
        sink.write("$upscope $end\n$enddefinitions $end\n")
        first = {
            index: (slice_levels(channel["file"], channel["validBits"], 0, 1) or [0])[0]
            for index, channel in enumerate(channels)
        }
        sink.write("#0\n")
        for index, identifier in enumerate(identifiers):
            sink.write(f"{first.get(index, 0)}{identifier}\n")
        current = 0
        for tick, index, level in merged:
            if tick != current:
                sink.write(f"#{tick}\n")
                current = tick
            sink.write(f"{level}{identifiers[index]}\n")
            rows += 1
    return {"file": str(out), "edges": rows, "timescale": timescale}


def analyse_capture(capture: dict, base: Path, glitch_bits: int = 0,
                    max_bits: int = 500_000_000,
                    pulse_limit: int = 8_000_000) -> dict:
    """Per-channel statistics for a finished (or partial) capture."""
    channels = []
    for entry in capture.get("bin") or capture.get("partial") or []:
        name = Path(str(entry.get("file") or f"channel_{entry.get('channel')}.bin")).name
        path = base / name
        if not path.exists() and (base / (name + ".partial")).exists():
            # A stopped or unplugged capture keeps .bin.partial; capture.json
            # may still name the final file. Read what exists, never rename it.
            path = base / (name + ".partial")
        item = {
            "channel": entry.get("channel"),
            "file": str(path),
            "validBits": int(entry.get("validBits") or 0),
            "bytes": int(entry.get("bytes") or (path.stat().st_size if path.exists() else 0)),
        }
        if not path.exists():
            item["note"] = "file missing"
            channels.append(item)
            continue
        if item["validBits"] > max_bits:
            item["note"] = (
                f"{item['validBits']} samples is above the auto-analysis limit "
                f"({max_bits}); run read --max-bits to analyse it"
            )
            channels.append(item)
            continue
        item.update(
            stats(path, item["validBits"], glitch_bits=glitch_bits, pulse_limit=pulse_limit)
        )
        duration = item["validBits"] / capture["frequencyHz"] if capture.get("frequencyHz") else 0
        if duration:
            item["edgeRateHz"] = item["edges"] / duration
            item["cycleRateHz"] = item["rises"] / duration
            item["minPulseUs"] = (item["minRunBits"] / capture["frequencyHz"] * 1e6) if item.get("minRunBits") else None
            item["maxPulseUs"] = (item["maxRunBits"] / capture["frequencyHz"] * 1e6) if item.get("maxRunBits") else None
        item["duty"] = (item["ones"] / item["bits"]) if item["bits"] else None
        item["stuck"] = item.get("edges") == 0
        channels.append(item)
    return {"channels": channels}
