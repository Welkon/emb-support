"""Run the vendor's protocol decoders without libsigrokdecode.

The ATK-Logic GUI ships the sigrok decoder collection as plain Python
(`<install>/decoders/*/pd.py`, api_version 3) and embeds libsigrokdecode in the
GUI executable. There is no reusable DLL and no documented headless entry
point, so this module provides the small part of `sigrokdecode` the decoders
actually use, and feeds them samples from a capture.

The decoders stay where the vendor installed them: nothing is copied into this
repository, and they keep their own licence. This module is only a host.

The vendor fork differs from upstream sigrokdecode in two ways, both verified
against the shipped decoders:

* `self.wait(cond)` returns the signal levels at the matched sample, so
  decoders unpack it (`(can_rx,) = self.wait({0: 'f'})`).
* `self.matched` has one entry per condition of the wait list, not one per
  channel, so a decoder can tell which alternative of an OR fired.
"""

from __future__ import annotations

import importlib
import sys
import types
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from .common import SkillError

SRD_CONF_SAMPLERATE = 6
OUTPUT_ANN = 0
OUTPUT_PYTHON = 1
OUTPUT_BINARY = 2
OUTPUT_LOGIC = 3
OUTPUT_META = 4

_BITS = tuple(tuple(i for i in range(8) if byte & (1 << i)) for byte in range(256))
CHUNK_BYTES = 1 << 21


class EndOfStream(Exception):
    """The decoder asked for a sample past the end of the window."""


class Host:
    """Sample source plus the callback surface a decoder sees."""

    def __init__(self, channels: dict[int, tuple[int, list[int]]], length: int,
                 samplerate: int, channel_count: int) -> None:
        self.first = {pin: first for pin, (first, _changes) in channels.items()}
        self.changes = {pin: changes for pin, (_first, changes) in channels.items()}
        self.length = length
        self.samplerate = samplerate
        self.channel_count = channel_count
        self.outputs: dict[int, int] = {}
        self.annotations: list[dict] = []
        self.python_events: list[dict] = []
        self.binary_events: list[dict] = []
        self.logs: list[str] = []
        self.annotation_limit = 5000
        self.dropped_annotations = 0

    # ------------------------------------------------------------ samples
    def level(self, pin: int, index: int) -> int:
        changes = self.changes.get(pin)
        if not changes:
            return self.first.get(pin, 0)
        import bisect

        return self.first.get(pin, 0) ^ (bisect.bisect_right(changes, index) & 1)

    def next_change(self, pin: int, after: int):
        import bisect

        changes = self.changes.get(pin) or []
        k = bisect.bisect_right(changes, after)
        return changes[k] if k < len(changes) else None

    def signal_at(self, index: int) -> tuple:
        return tuple(self.level(pin, index) for pin in range(self.channel_count))

    def matches(self, index: int, pins: dict) -> bool:
        for pin, want in pins.items():
            level = self.level(pin, index)
            if want == 'h' and level != 1:
                return False
            if want == 'l' and level != 0:
                return False
            if want in ('r', 'f', 'e'):
                if index == 0:
                    return False
                previous = self.level(pin, index - 1)
                if previous == level:
                    return False
                if want == 'r' and level != 1:
                    return False
                if want == 'f' and level != 0:
                    return False
        return True

    @staticmethod
    def _pins(cond) -> dict:
        return {key: value for key, value in (cond or {}).items() if isinstance(key, int)}

    def _iter_candidates(self, current: int, cond):
        """Ascending sample indices at which ``cond`` could become true.

        A candidate is always an event: the next sample, the next change of a
        pin named in the condition, or the skip target. That keeps an OR list
        cheap when one alternative rarely fires.
        """
        if cond is None or cond == {}:
            index = current + 1
            if index < self.length:
                yield index
            return
        if 'skip' in cond:
            index = current + int(cond['skip'])
            if index < self.length:
                yield index
            return
        pins = self._pins(cond)
        if not pins:
            index = current + 1
            if index < self.length:
                yield index
            return
        has_edge = any(value in ('e', 'r', 'f') for value in pins.values())
        start = current + 1
        if not has_edge:
            if start < self.length:
                yield start
        position = current if has_edge else start - 1
        while True:
            changes = [
                change for change in (self.next_change(pin, position) for pin in pins)
                if change is not None
            ]
            if not changes:
                return
            candidate = min(changes)
            if candidate >= self.length:
                return
            yield candidate
            position = candidate

    def wait(self, current: int, cond):
        """Return ``(index, matched, signal)``; ``matched`` is per condition."""
        if isinstance(cond, (list, tuple)):
            generators = [self._iter_candidates(current, option) for option in cond]
            heads = [next(generator, None) for generator in generators]
            while True:
                live = [index for index, head in enumerate(heads) if head is not None]
                if not live:
                    raise EndOfStream
                sample = min(heads[index] for index in live)
                hit = None
                for position in live:
                    if heads[position] != sample:
                        continue
                    option = cond[position]
                    pins = self._pins(option)
                    if (option is None or option == {} or 'skip' in option
                            or not pins or self.matches(sample, pins)):
                        hit = position
                        break
                    heads[position] = next(generators[position], None)
                if hit is not None:
                    matched = [False] * len(cond)
                    matched[hit] = True
                    return sample, tuple(matched), self.signal_at(sample)
        for sample in self._iter_candidates(current, cond):
            pins = self._pins(cond)
            if (cond is None or cond == {} or 'skip' in cond or not pins
                    or self.matches(sample, pins)):
                matched = (False,) if cond in (None, {}) else (True,)
                return sample, matched, self.signal_at(sample)
        raise EndOfStream

    # ----------------------------------------------------------- outputs
    def register(self, output_type: int) -> int:
        output_id = len(self.outputs)
        self.outputs[output_id] = output_type
        return output_id

    def put(self, output_id: int, startsample: int, endsample: int, data) -> None:
        output_type = self.outputs.get(output_id)
        if startsample < 0:
            return
        if output_type == OUTPUT_ANN:
            if len(self.annotations) >= self.annotation_limit:
                self.dropped_annotations += 1
                return
            number, texts = data[0], data[1]
            self.annotations.append(
                {"start": startsample, "end": endsample, "class": number,
                 "texts": [str(text) for text in texts]}
            )
        elif output_type == OUTPUT_PYTHON:
            if len(self.python_events) < self.annotation_limit:
                self.python_events.append(
                    {"start": startsample, "end": endsample, "data": data}
                )
        elif output_type == OUTPUT_BINARY:
            if len(self.binary_events) < self.annotation_limit:
                self.binary_events.append(
                    {"start": startsample, "end": endsample, "data": data}
                )


def _srd_module() -> types.ModuleType:
    module = sys.modules.get("sigrokdecode")
    if module is not None and getattr(module, "_atk_host", False):
        return module

    class Decoder:
        def __init__(self):
            pass

        def register(self, output_type, **kwargs):
            return self._host.register(output_type)

        def put(self, startsample, endsample, output_id, data):
            self._host.put(output_id, startsample, endsample, data)

        def wait(self, cond=None):
            index, matched, signal = self._host.wait(self.samplenum, cond)
            self.samplenum = index
            self.matched = matched
            return signal

        def has_channel(self, index):
            return index in self._host.changes or index in self._host.first

        def metadata(self, key, value):
            pass

        def log(self, level, msg):
            self._host.logs.append(f"{level}: {msg}")

        def warn(self, msg):
            self._host.logs.append(f"warning: {msg}")

    module = types.ModuleType("sigrokdecode")
    module._atk_host = True
    module.Decoder = Decoder
    module.OUTPUT_ANN = OUTPUT_ANN
    module.OUTPUT_PYTHON = OUTPUT_PYTHON
    module.OUTPUT_BINARY = OUTPUT_BINARY
    module.OUTPUT_LOGIC = OUTPUT_LOGIC
    module.OUTPUT_META = OUTPUT_META
    module.SRD_CONF_SAMPLERATE = SRD_CONF_SAMPLERATE
    module.SRD_CONF_NUM_PROBES = 1
    module.SRD_CONF_PROBE_NAMES = 2
    sys.modules["sigrokdecode"] = module
    return module


def default_decoder_dir() -> Path:
    import os

    from . import host

    for candidate in (
        os.environ.get("SIGROKDECODE_DIR"),
        host.load_config().get("decoders"),
        "/mnt/c/Program Files/ATK-Logic/decoders",
        "C:/Program Files/ATK-Logic/decoders",
        "/usr/share/libsigrokdecode/decoders",
        "/usr/local/share/libsigrokdecode/decoders",
    ):
        if candidate and (Path(candidate) / "uart" / "pd.py").is_file():
            return Path(candidate)
    raise SkillError(
        "decoders_not_found",
        "no protocol decoder directory was found",
        [
            "install ATK-Logic (the GUI ships the sigrok decoders)",
            "or point SIGROKDECODE_DIR / --decoders at a decoders directory",
        ],
    )


@dataclass
class DecoderInfo:
    id: str
    name: str
    longname: str
    desc: str
    license: str
    inputs: list
    channels: list
    optional_channels: list
    options: list
    annotations: list
    annotation_rows: list
    outputs: list = field(default_factory=list)

    @property
    def direct(self) -> bool:
        return "logic" in [str(item) for item in self.inputs]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "longname": self.longname,
            "desc": self.desc,
            "license": self.license,
            "inputs": list(self.inputs),
            "channels": [dict(item) for item in self.channels],
            "optionalChannels": [dict(item) for item in self.optional_channels],
            "options": [dict(item) for item in self.options],
            "annotations": list(self.annotations),
            "annotationRows": [
                {"id": row[0], "name": row[1], "classes": list(row[2])}
                for row in self.annotation_rows
                if len(row) >= 3
            ],
            "direct": self.direct,
        }


_cache: dict[tuple[str, str], object] = {}


def _import_decoder(decoder_dir: Path, pd_id: str):
    _srd_module()
    key = (str(decoder_dir), pd_id)
    if key in _cache:
        return _cache[key]
    directory = str(decoder_dir)
    if directory not in sys.path:
        sys.path.insert(0, directory)
    root = "_atk_decoders"
    package = sys.modules.get(root)
    if package is None or directory not in getattr(package, "__path__", []):
        package = types.ModuleType(root)
        package.__path__ = [directory]
        sys.modules[root] = package
        if directory not in package.__path__:
            package.__path__.append(directory)
    if not (Path(decoder_dir) / pd_id / "pd.py").is_file():
        raise SkillError(
            "decoder_not_found",
            f"no decoder {pd_id!r} in {decoder_dir}",
            ["run decoders --search to see what is installed"],
        )
    with warnings.catch_warnings():
        # The shipped decoders are Python-3.7 era; some contain escape
        # sequences that Python warns about. They still run.
        warnings.simplefilter("ignore")
        try:
            module = importlib.import_module(f"{root}.{pd_id}.pd")
        except Exception as exc:  # noqa: BLE001 - a broken PD is a normal answer
            raise SkillError(
                "decoder_unusable",
                f"{pd_id}/pd.py could not be imported: {type(exc).__name__}: {exc}",
                ["check the decoder directory", "the GUI may use a patched decoder"],
            )
    _cache[key] = module
    return module


def describe(decoder_dir: Path, pd_id: str) -> DecoderInfo:
    module = _import_decoder(Path(decoder_dir), pd_id)
    cls = getattr(module, "Decoder", None)
    if cls is None:
        raise SkillError(
            "invalid_decoder",
            f"{pd_id}/pd.py has no Decoder class",
            ["check the decoder directory; this may not be a sigrok PD"],
        )
    api_version = getattr(cls, "api_version", None)
    if api_version != 3:
        raise SkillError(
            "unsupported_decoder_api",
            f"{pd_id} declares api_version {api_version!r}, this host supports 3",
            ["use the decoders installed with ATK-Logic"],
        )
    return DecoderInfo(
        id=getattr(cls, "id", pd_id),
        name=getattr(cls, "name", pd_id),
        longname=getattr(cls, "longname", ""),
        desc=getattr(cls, "desc", ""),
        license=getattr(cls, "license", ""),
        inputs=list(getattr(cls, "inputs", ()) or ()),
        channels=[dict(item) for item in getattr(cls, "channels", ()) or ()],
        optional_channels=[
            dict(item) for item in getattr(cls, "optional_channels", ()) or ()
        ],
        options=[dict(item) for item in getattr(cls, "options", ()) or ()],
        annotations=list(getattr(cls, "annotations", ()) or ()),
        annotation_rows=list(getattr(cls, "annotation_rows", ()) or ()),
        outputs=list(getattr(cls, "outputs", ()) or ()),
    )


def catalog(decoder_dir: Path, search: str | None = None) -> list[DecoderInfo]:
    directory = Path(decoder_dir)
    if not directory.is_dir():
        raise SkillError(
            "decoders_not_found", f"{directory} is not a decoder directory"
        )
    found = []
    for entry in sorted(directory.iterdir()):
        if not (entry / "pd.py").is_file():
            continue
        try:
            info = describe(directory, entry.name)
        except SkillError:
            continue
        if search:
            needle = search.lower()
            haystack = f"{info.id} {info.name} {info.longname} {info.desc} {info.license}".lower()
            if needle not in haystack:
                continue
        found.append(info)
    return found


def channel_changes(path: Path, valid_bits: int, start: int = 0,
                    count: int | None = None, max_edges: int = 4_000_000):
    """Return ``(first_level, change_positions)`` for a sample window.

    One transition costs one big-int XOR per chunk; the positions come out of
    the changed bytes with a lookup table, so a quiet line stays cheap.
    """
    end = min(valid_bits, valid_bits if count is None else start + count)
    bits = max(0, end - start)
    if bits == 0:
        return 0, []
    first_level: int | None = None
    last_level = 0
    changes: list[int] = []
    with path.open("rb") as handle:
        handle.seek(start // 8)
        skip = start % 8
        read_bits = 0
        remaining = bits
        while remaining > 0:
            wanted = min(remaining, CHUNK_BYTES * 8)
            data = handle.read((skip + wanted + 7) // 8)
            if not data:
                break
            value = int.from_bytes(data, "little") >> skip
            usable = min(wanted, len(data) * 8 - skip)
            if usable <= 0:
                break
            if usable % 8:
                value &= (1 << usable) - 1
            if first_level is None:
                first_level = value & 1
                shifted = value << 1          # no predecessor: carry in zero
                changed = (value ^ shifted) & ~1
            else:
                shifted = (value << 1) | last_level
                changed = value ^ shifted
            changed &= (1 << usable) - 1
            if changed:
                base = read_bits
                raw = changed.to_bytes((usable + 7) // 8, "little")
                for index, byte in enumerate(raw):
                    if not byte:
                        continue
                    for bit in _BITS[byte]:
                        position = base + index * 8 + bit
                        if position < bits:
                            changes.append(position)
                if len(changes) > max_edges:
                    raise SkillError(
                        "too_many_edges",
                        f"the window has more than {max_edges} edges",
                        ["narrow --window", "raise --max-edges if you accept the time"],
                    )
            last_level = (value >> (usable - 1)) & 1
            read_bits += usable
            remaining -= usable
            skip = 0
    return (0 if first_level is None else first_level), changes


def _default_options(info: DecoderInfo) -> dict:
    return {option["id"]: option.get("default") for option in info.options}


def run_chain(decoder_dir: Path, levels: list[dict], channels: dict[int, Path],
              lengths: dict[int, int], samplerate: int, start: int = 0,
              count: int | None = None, max_edges: int = 4_000_000,
              annotation_limit: int = 5000) -> dict:
    """Run a stack: a logic decoder first, then decoders that consume its stream.

    Stacked decoders are callback style — ``decode(ss, es, data)`` per upstream
    packet — so no sample source is needed after the first level. Each level's
    OUTPUT_PYTHON packets become the next level's input, and the level order is
    checked against the decoders' ``inputs``/``outputs``.
    """
    if not levels:
        raise SkillError("invalid_arguments", "no decoder in the chain")
    first = levels[0]
    result = run(decoder_dir, first["id"], channels, lengths, samplerate,
                 options=first.get("options") or {}, start=start, count=count,
                 max_edges=max_edges, annotation_limit=annotation_limit)
    level_results = [{
        "id": result["decoder"].id,
        "name": result["decoder"].name,
        "host": result["host"],
        "failure": result["failure"],
        "options": result["options"],
        "info": result["decoder"],
    }]
    packets = [(event["start"], event["end"], event["data"])
               for event in result["host"].python_events]
    window = result["window"]["samples"]
    for level in levels[1:]:
        info = describe(Path(decoder_dir), level["id"])
        if info.direct:
            raise SkillError(
                "decoder_chain_mismatch",
                f"{info.id} takes logic directly and cannot follow {level_results[-1]['id']}",
                ["put the logic decoder first in the chain"],
            )
        upstream = level_results[-1]["info"]
        if not set(map(str, info.inputs)) & set(map(str, upstream.outputs)):
            raise SkillError(
                "decoder_chain_mismatch",
                f"{info.id} consumes {list(info.inputs)} but {upstream.id} produces "
                f"{list(upstream.outputs)}",
                ["check the chain order; run decoders to see inputs/outputs"],
            )
        host = Host({}, window, samplerate, 0)
        host.annotation_limit = annotation_limit
        module = _import_decoder(Path(decoder_dir), info.id)
        decoder = module.Decoder()
        merged = _default_options(info)
        merged.update(level.get("options") or {})
        merged[SRD_CONF_SAMPLERATE] = samplerate
        decoder.options = merged
        decoder.channels = []
        decoder._host = host
        decoder.samplenum = -1
        decoder.matched = ()
        failure = None
        try:
            decoder.metadata(SRD_CONF_SAMPLERATE, samplerate)
            decoder.start()
            for startsample, endsample, data in packets:
                decoder.decode(startsample, endsample, data)
        except Exception as exc:  # noqa: BLE001 - a decoder error is a result
            failure = f"{type(exc).__name__}: {exc}"
        level_results.append({
            "id": info.id, "name": info.name, "host": host,
            "failure": failure, "options": merged, "info": info,
        })
        packets = [(event["start"], event["end"], event["data"])
                   for event in host.python_events]
    return {
        "levels": level_results,
        "window": result["window"],
        "failure": level_results[-1]["failure"],
    }


def run(decoder_dir: Path, pd_id: str, channels: dict[int, Path], lengths: dict[int, int],
        samplerate: int, options: dict | None = None, start: int = 0,
        count: int | None = None, max_edges: int = 4_000_000,
        annotation_limit: int = 5000) -> dict:
    """Run one decoder over a capture window and return what it emitted."""
    info = describe(decoder_dir, pd_id)
    if not info.direct:
        raise SkillError(
            "decoder_needs_stacking",
            f"{pd_id} consumes {', '.join(map(str, info.inputs))}, not raw logic",
            [
                "run the upstream decoder first (for example --protocol uart) and read its rows",
                "stacked decoders are not supported by this host yet",
            ],
        )
    signals = {}
    for pin, path in channels.items():
        first, changes = channel_changes(path, lengths[pin], start=start,
                                         count=count, max_edges=max_edges)
        signals[pin] = (first, changes)
    window = min(lengths[pin] for pin in channels)
    window = window - start if count is None else min(window - start, count)

    declared = len(info.channels)
    optional = len(info.optional_channels)
    host = Host(signals, window, samplerate,
                channel_count=max(declared, optional, max(channels) + 1))
    host.annotation_limit = annotation_limit

    module = _import_decoder(Path(decoder_dir), pd_id)
    decoder = module.Decoder()
    merged = _default_options(info)
    for key, value in (options or {}).items():
        merged[key] = value
    merged[SRD_CONF_SAMPLERATE] = samplerate
    decoder.options = merged
    decoder.channels = [1 if index in channels else 0
                        for index in range(host.channel_count)]
    decoder._host = host
    decoder.samplenum = -1
    decoder.matched = ()
    failure = None
    try:
        decoder.metadata(SRD_CONF_SAMPLERATE, samplerate)
        decoder.start()
        decoder.decode()
    except EndOfStream:
        pass
    except Exception as exc:  # noqa: BLE001 - a decoder error is a result, not a crash
        failure = f"{type(exc).__name__}: {exc}"
    return {
        "decoder": info,
        "host": host,
        "window": {"start": start, "samples": window},
        "failure": failure,
        "options": {key: value for key, value in merged.items() if isinstance(key, str)},
    }
