"""Command surface: one intent per question, JSON on request.

The agent-facing contract is the intent, not the vendor's verb. Every command
prints one JSON object with ``--json`` and a short human answer otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from . import atkdl, capabilities, capture, decode, guicsv, host, pdhost, protocol, usb
from .common import (
    FORMATS,
    MODES,
    TRIGGER_CODES,
    Result,
    SkillError,
    dump,
    fmt_hz,
    fmt_ms,
    parse_channels,
    parse_duration_ms,
    parse_frequency,
    parse_percent,
    parse_seconds,
    parse_volts,
)

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_SKILL = 4


# ---------------------------------------------------------------- helpers

def _invocation(args) -> host.Invocation:
    invocation = host.resolve_invocation(getattr(args, "cli", None))
    host.probe_version(invocation)
    return invocation


def _progress(args):
    quiet = getattr(args, "quiet", False) or getattr(args, "json", False)

    def show(message: str) -> None:
        if not quiet:
            print(f"  {message}", file=sys.stderr, flush=True)

    return show


def _device_id(args, config: dict | None = None) -> str | None:
    explicit = getattr(args, "device_id", None)
    if explicit:
        return explicit
    return (config if config is not None else host.load_config()).get("device_id")


# --------------------------------------------------------------- commands

def cmd_doctor(args) -> dict:
    result = Result()
    platform_name = host.platform_name()
    result.set("platform", platform_name)
    result.set("host", {"os": sys.platform, "python": sys.version.split()[0]})
    result.set("config_file", str(host.config_file()))

    notes: list[str] = []
    errors: list[dict] = []
    try:
        invocation = _invocation(args)
        result.set("cli", invocation.describe())
        staged = host.staging_root(invocation)
        try:
            staged.mkdir(parents=True, exist_ok=True)
            writable = os.access(staged, os.W_OK)
        except OSError:
            writable = False
        result.set("staging", {"path": str(staged), "writable": writable})
        if not writable:
            notes.append(
                "staging is not writable; give --out on a Windows drive or set ATK_LOGIC_STAGING"
            )
        listing = protocol.run_json(invocation, ["device", "list"], timeout=60,
                                    context="device list")
        devices = listing.get("devices") or []
        result.set("devices", devices)
        result.set("deviceCount", len(devices))
        if not devices:
            notes.append("no analyzer enumerated; check USB, power and the driver")
        for device in devices:
            if device.get("bootloader"):
                notes.append(f"{device.get('deviceId')} is in bootloader mode and cannot capture")
        if platform_name == "wsl":
            notes.append(
                "WSL: the CLI runs on Windows through interop; keep the analyzer attached to "
                "Windows and do not usbipd attach it to the distro"
            )
    except SkillError as error:
        errors.append(error.to_dict()["error"])
        result.set("devices", [])
        result.set("deviceCount", 0)
    result.set("errors", errors)
    result.set("notes", notes)
    return result.to_dict()


def cmd_list(args) -> dict:
    invocation = _invocation(args)
    listing = protocol.run_json(invocation, ["device", "list"], context="device list")
    return {
        "ok": True,
        "deviceCount": len(listing.get("devices") or []),
        "devices": listing.get("devices") or [],
        "cli": invocation.cli_version,
    }


def cmd_info(args) -> dict:
    invocation = _invocation(args)
    config = host.load_config()
    device_id = _device_id(args, config)
    params = ["device", "connect"]
    if device_id:
        params += ["--device-id", device_id]
    connected = protocol.run_json(invocation, params, context="device connect")
    device = connected.get("device") or {}
    summary = {
        "deviceId": device.get("deviceId"),
        "model": device.get("model"),
        "channelCount": device.get("channelCount"),
        "channelOffset": device.get("channelOffset"),
        "usbSpeed": device.get("usbSpeed"),
        "level": device.get("level"),
        "port": device.get("port"),
        "mcuVersion": device.get("mcuVersion"),
        "fpgaVersion": device.get("fpgaVersion"),
        "hardwareVersion": device.get("hardwareVersion"),
        "bootloader": device.get("bootloader"),
    }
    first = int(device.get("channelOffset") or 0)
    last = first + int(device.get("channelCount") or 0) - 1
    return {
        "ok": True,
        "device": device,
        "summary": summary,
        "usableChannels": f"{first}-{last}" if device.get("channelCount") else None,
        "cli": invocation.cli_version,
        "notes": [] if device.get("channelCount") else ["device profile incomplete"],
    }


def cmd_caps(args) -> dict:
    invocation = _invocation(args)
    channels = parse_channels(args.ch or ["0"])
    if args.freq is not None and args.time is not None:
        raise SkillError(
            "invalid_arguments",
            "--freq and --time are mutually exclusive in a capability query",
            ["ask for one: the durations at a rate, or the rates for a duration"],
        )
    frequency = parse_frequency(args.freq) if args.freq is not None else None
    duration = parse_duration_ms(args.time) if args.time is not None else None
    payload = capabilities.query_one_shot(
        invocation, args.mode, channels, frequency=frequency, duration=duration
    )
    capture._check_channels(payload.get("device") or {}, channels)
    options = capabilities.options_from(payload)
    result = {
        "ok": True,
        "device": payload.get("device"),
        "mode": args.mode,
        "channels": [channel["id"] for channel in channels],
        "options": options,
    }
    if payload.get("query"):
        result["query"] = {
            "kind": payload["query"],
            "frequencyHz": payload.get("frequencyHz"),
            "durationMs": payload.get("durationMs"),
            "frequenciesHz": payload.get("frequencyOptionsHz"),
            "durationsMs": payload.get("durationOptionsMs"),
        }
    else:
        result.update(capabilities.summarise(options))
    return result


def cmd_capture(args) -> dict:
    invocation = _invocation(args)
    config = host.load_config()
    plan = capture.build_plan(args)
    payload = capture.run(
        invocation,
        plan,
        out=Path(args.out) if args.out else None,
        device_id=_device_id(args, config),
        strict=args.strict,
        one_shot=args.one_shot,
        analyze=not args.no_analyze,
        keep_stage=args.keep_stage,
        timeout=args.timeout,
        trigger_timeout=args.trigger_timeout,
        glitch_ns=args.glitch_ns,
        on_prompt=_progress(args),
    )
    payload["ok"] = True
    return payload


def _gui_csv(args) -> list[dict]:
    return [guicsv.summarise(path) for path in (getattr(args, "gui_csv", None) or [])]


def _pulse_limit(args) -> int:
    if getattr(args, "run_lengths", False) or getattr(args, "glitch_ns", None):
        return int(args.max_bits)
    return 8_000_000


def _read_wanted_channels(args, entries: list[dict]) -> list[dict]:
    if not args.ch:
        return entries
    wanted = {channel["id"] for channel in parse_channels(args.ch)}
    selected = [entry for entry in entries if entry.get("channel") in wanted]
    if not selected:
        raise SkillError(
            "channel_not_in_capture",
            f"channels {sorted(wanted)} are not in this capture",
            [f"available channels: {sorted(entry.get('channel') for entry in entries)}"],
        )
    return selected


def _write_requested_outputs(args, meta: dict, analysis: list[dict]) -> dict:
    outputs: dict = {}
    analysable = [item for item in analysis if "validBits" in item]
    if args.csv:
        if not analysable:
            raise SkillError("nothing_to_write", "no analysable channel for --csv")
        if args.csv_all:
            outputs["csvFiles"] = []
            for entry in analysable:
                path = Path(args.csv)
                target = path.with_name(f"{path.stem}_ch{entry['channel']}{path.suffix or '.csv'}")
                outputs["csvFiles"].append(
                    decode.write_csv(
                        target, entry["file"], entry["validBits"], meta["frequencyHz"],
                        start=args.start, count=args.count,
                        transitions_only=args.csv_transitions,
                    )
                )
        else:
            entry = analysable[0]
            outputs["csv"] = decode.write_csv(
                args.csv, entry["file"], entry["validBits"], meta["frequencyHz"],
                start=args.start, count=args.count, transitions_only=args.csv_transitions,
            )
            if len(analysable) > 1:
                outputs["csvNote"] = (
                    "wrote the first channel only; add --csv-all to write one file per channel"
                )
    if args.vcd:
        channels = [
            {"id": entry["channel"], "file": entry["file"], "validBits": entry["validBits"]}
            for entry in analysable
        ]
        if not channels:
            raise SkillError("nothing_to_write", "no analysable channel for --vcd")
        outputs["vcd"] = decode.write_vcd(args.vcd, channels, meta["frequencyHz"])
    return outputs


def _capture_view(directory: Path, meta: dict) -> dict:
    return {
        "directory": str(directory),
        "status": meta.get("status"),
        "mode": meta.get("mode"),
        "frequencyHz": meta.get("frequencyHz"),
        "durationMs": meta.get("durationMs"),
        "thresholdVolts": meta.get("thresholdVolts"),
        "triggerPositionPercent": meta.get("triggerPositionPercent"),
        "rle": meta.get("rle"),
        "device": meta.get("device"),
        "channels": [
            {
                "id": channel.get("id"),
                "trigger": TRIGGER_CODES.get(str(channel.get("trigger")), channel.get("trigger")),
            }
            for channel in meta.get("channels") or []
        ],
        "atkdl": meta.get("atkdl"),
        "source": meta.get("source", "cli"),
    }


def _read_atkdl(args, source: Path) -> dict:
    info = atkdl.inspect(source)
    if not info.get("frequencyHz"):
        raise SkillError(
            "invalid_atkdl",
            f"{source} does not record its sample rate",
            ["open the project in ATK-Logic and re-save it, or decode the BIN files directly"],
        )
    wanted = None
    if args.ch:
        wanted = [channel["id"] for channel in parse_channels(args.ch)]
    keep = Path(args.extract).expanduser().resolve() if args.extract else None
    workdir = keep or Path(tempfile.mkdtemp(prefix="atk-atkdl-"))
    try:
        extracted = atkdl.extract(source, workdir, channels=wanted)
        meta = {
            "source": "atkdl",
            "status": "complete",
            "mode": info.get("mode"),
            "frequencyHz": info["frequencyHz"],
            "durationMs": info.get("durationMs"),
            "thresholdVolts": info.get("thresholdVolts"),
            "triggerPositionPercent": info.get("triggerPositionPercent"),
            "rle": info.get("rle"),
            "device": {},
            "channels": [
                {"id": entry["channel"], "trigger": entry["trigger"]}
                for entry in extracted["channels"]
            ],
            "bin": extracted["channels"],
            "atkdl": str(source),
        }
        analysis = decode.analyse_capture(
            meta, workdir,
            glitch_bits=int(args.glitch_ns * meta["frequencyHz"] / 1e9) if args.glitch_ns else 0,
            max_bits=args.max_bits,
            pulse_limit=_pulse_limit(args),
        )["channels"]
        outputs = _write_requested_outputs(args, meta, analysis)
        csv_summaries = _gui_csv(args)
        if csv_summaries:
            outputs["guiCsv"] = csv_summaries
    finally:
        if keep is None:
            shutil.rmtree(workdir, ignore_errors=True)
    return {
        "ok": True,
        "capture": _capture_view(Path(args.extract).expanduser().resolve() if keep else source.parent, meta),
        "project": {
            "file": str(source),
            "sessionName": info.get("sessionName"),
            "extractedTo": str(keep) if keep else None,
            "channels": [
                {"id": channel["id"], "bits": channel["bits"], "chunks": channel["chunks"]}
                for channel in info["channels"]
            ],
            "decoders": info.get("decoders") or [],
            "gui": info.get("gui") or {},
            "decodersNote": (
                "a project stores the decoder configuration only; the decoded rows live "
                "in the GUI or in an exported CSV (pass --gui-csv)"
                if info.get("decoders")
                else None
            ),
        },
        "analysis": analysis,
        "outputs": outputs,
    }


def cmd_read(args) -> dict:
    target = Path(args.directory).expanduser().resolve()
    if target.is_file() and atkdl.looks_like_atkdl(target):
        return _read_atkdl(args, target)
    directory = target.parent if target.is_file() else target
    meta_path = directory / "capture.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SkillError(
            "capture_not_found",
            f"{meta_path} does not exist",
            [
                "point read at a capture directory produced by capture, or at an .atkdl project",
            ],
        )
    except json.JSONDecodeError as exc:
        raise SkillError("invalid_output", f"{meta_path} is not valid JSON: {exc}")

    meta = dict(meta)
    meta["bin"] = _read_wanted_channels(args, meta.get("bin") or [])

    analysis = decode.analyse_capture(
        meta, directory,
        glitch_bits=int(args.glitch_ns * meta["frequencyHz"] / 1e9) if args.glitch_ns else 0,
        max_bits=args.max_bits,
        pulse_limit=_pulse_limit(args),
    )["channels"]
    outputs = _write_requested_outputs(args, meta, analysis)
    csv_summaries = _gui_csv(args)
    if csv_summaries:
        outputs["guiCsv"] = csv_summaries
    return {
        "ok": True,
        "capture": _capture_view(directory, meta),
        "analysis": analysis,
        "outputs": outputs,
    }


def _open_source(target: Path, extract_dir: Path | None = None,
                  wanted: list[int] | None = None) -> dict:
    """Open a capture directory or an .atkdl project as (meta, base, cleanup)."""
    target = target.expanduser()
    if target.is_file() and atkdl.looks_like_atkdl(target):
        info = atkdl.inspect(target)
        if not info.get("frequencyHz"):
            raise SkillError(
                "invalid_atkdl",
                f"{target} does not record its sample rate",
                ["re-save the project with ATK-Logic, or decode the BIN files directly"],
            )
        keep = extract_dir
        workdir = keep or Path(tempfile.mkdtemp(prefix="atk-source-"))
        extracted = atkdl.extract(target, workdir, channels=wanted)
        meta = {
            "source": "atkdl",
            "status": "complete",
            "mode": info.get("mode"),
            "frequencyHz": info["frequencyHz"],
            "durationMs": info.get("durationMs"),
            "thresholdVolts": info.get("thresholdVolts"),
            "triggerPositionPercent": info.get("triggerPositionPercent"),
            "rle": info.get("rle"),
            "device": {},
            "channels": [
                {"id": entry["channel"], "trigger": entry["trigger"]}
                for entry in extracted["channels"]
            ],
            "bin": extracted["channels"],
            "atkdl": str(target),
        }
        return {"meta": meta, "base": workdir, "cleanup": None if keep else workdir,
                "project": info, "input": str(target)}
    directory = target.parent if target.is_file() else target
    meta_path = directory / "capture.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SkillError(
            "capture_not_found",
            f"{meta_path} does not exist",
            ["point at a capture directory, its capture.json, or an .atkdl project"],
        )
    except json.JSONDecodeError as exc:
        raise SkillError("invalid_output", f"{meta_path} is not valid JSON: {exc}")
    if wanted is not None:
        meta = dict(meta)
        meta["bin"] = [
            entry for entry in (meta.get("bin") or [])
            if entry.get("channel") in set(wanted)
        ]
    return {"meta": meta, "base": directory, "cleanup": None,
            "project": None, "input": str(directory)}


def _window_samples(args, frequency_hz: int, valid_bits: int) -> dict:
    """Resolve --window/--max-samples into (start, count, truncated)."""
    limit = int(args.max_samples)
    start, end = 0, None
    if args.window:
        text = str(args.window)
        head, _, tail = text.partition(":")
        start = int(round(parse_seconds(head or "0") * frequency_hz))
        if tail.strip():
            end = int(round(parse_seconds(tail) * frequency_hz))
    if start >= valid_bits:
        raise SkillError(
            "window_out_of_range",
            f"the window starts at sample {start} but the capture has {valid_bits}",
            [f"choose a start below {valid_bits / max(1, frequency_hz):.6g} s"],
        )
    available = valid_bits - start
    count = None if end is None else max(0, end - start)
    truncated = False
    if count is None:
        if available > limit:
            count = limit
            truncated = True
        else:
            count = available
    elif count > limit:
        count = limit
        truncated = True
    return {"start": start, "count": max(1, count), "truncated": truncated,
            "available": available}


def _channel_map(args, info) -> dict:
    """``--ch scl=7 --ch sda=6`` -> {pd channel index: capture channel id}."""
    declared = [str(item.get("id")) for item in info.channels]
    optional = [str(item.get("id")) for item in info.optional_channels]
    known = declared + optional
    mapping: dict[str, int] = {}
    raw = args.ch or []
    if not raw:
        raise SkillError(
            "invalid_arguments",
            f"{info.id} needs a channel mapping",
            [f"pass --ch <name>=<capture channel>, names: {', '.join(known)}"],
        )
    for spec in raw:
        text = str(spec).strip()
        if "=" in text:
            name, _, value = text.partition("=")
            name = name.strip()
        elif len(raw) == 1 and len(known) == 1:
            name, value = known[0], text
        else:
            raise SkillError(
                "invalid_arguments",
                f"cannot tell which decoder channel {text!r} is",
                [f"write --ch <name>=<id>, names: {', '.join(known)}"],
            )
        if name not in known:
            raise SkillError(
                "invalid_arguments",
                f"{info.id} has no channel {name!r}",
                [f"channels: {', '.join(known)}"],
            )
        try:
            mapping[name] = int(value)
        except ValueError:
            raise SkillError("invalid_arguments", f"channel id {value!r} is not an integer")
    missing = [name for name in declared if name not in mapping]
    if missing:
        raise SkillError(
            "invalid_arguments",
            f"{info.id} requires channel(s) {missing}",
            [f"pass --ch {name}=<capture channel>" for name in missing],
        )
    ordered = [str(item.get("id")) for item in info.channels] + optional
    indices = {name: ordered.index(name) for name in mapping}
    return {indices[name]: channel_id for name, channel_id in mapping.items()}


def _parse_option(key: str, raw: str, info) -> object:
    declared = next((item for item in info.options if item.get("id") == key), None)
    if declared is None:
        raise SkillError(
            "invalid_arguments",
            f"{info.id} has no option {key!r}",
            [f"options: {', '.join(str(item.get('id')) for item in info.options)}"],
        )
    default = declared.get("default")
    if isinstance(default, bool):
        value = raw.lower() in ("1", "yes", "true", "on")
    elif isinstance(default, int):
        try:
            value = int(raw, 0)
        except ValueError:
            raise SkillError("invalid_arguments", f"{key} expects an integer, got {raw!r}")
    elif isinstance(default, float):
        try:
            value = float(raw)
        except ValueError:
            raise SkillError("invalid_arguments", f"{key} expects a number, got {raw!r}")
    else:
        value = raw
    allowed = declared.get("values")
    if allowed is not None and value not in allowed:
        raise SkillError(
            "invalid_arguments",
            f"{key}={value!r} is not one of {list(allowed)}",
            [f"values: {', '.join(str(item) for item in allowed)}"],
        )
    return value


def _chain_options(specs, infos: list) -> list[dict]:
    """``--option baudrate=115200`` -> level 0; ``--option modbus.framegap=30`` -> that level."""
    by_id = {info.id: index for index, info in enumerate(infos)}
    options = [dict() for _ in infos]
    for spec in specs or []:
        text = str(spec)
        if "=" not in text:
            raise SkillError("invalid_arguments", f"--option expects key=value, got {text!r}")
        key, _, raw = text.partition("=")
        key, raw = key.strip(), raw.strip()
        level = 0
        if "." in key:
            prefix, _, rest = key.partition(".")
            if prefix not in by_id:
                raise SkillError(
                    "invalid_arguments",
                    f"unknown decoder level {prefix!r} in --option",
                    [f"levels: {', '.join(by_id)}; write level.option=value, "
                     "or just option=value for the logic level"],
                )
            level, key = by_id[prefix], rest
        options[level][key] = _parse_option(key, raw, infos[level])
    return options


def _decoder_dir(args) -> Path:
    if getattr(args, "decoders", None):
        return Path(args.decoders).expanduser()
    return pdhost.default_decoder_dir()


def cmd_decoders(args) -> dict:
    directory = _decoder_dir(args)
    found = pdhost.catalog(directory, getattr(args, "search", None))
    return {
        "ok": True,
        "directory": str(directory),
        "count": len(found),
        "direct": sum(1 for info in found if info.direct),
        "decoders": [info.to_dict() for info in found],
    }


def _write_gui_csv(path: str, annotations: list[dict], frequency: int) -> dict:
    """Write the same CSV shape the GUI exports, so either tool can read it."""
    rows = 0
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as sink:
        sink.write("序号,开始,时间,名称,数值,\n")
        for index, item in enumerate(annotations):
            start = item["start"] / frequency
            duration = max(0, item["end"] - item["start"]) / frequency
            text = (item["texts"][0] if item["texts"] else "").replace(",", ";")
            sink.write(
                f"{index},{start * 1e6:.6f} us,{duration * 1e6:.6f} us,{item['class']},{text},\n"
            )
            rows += 1
    return {"file": str(target), "rows": rows}


def cmd_decode(args) -> dict:
    directory = _decoder_dir(args)
    level_ids = [part.strip() for part in str(args.protocol).split("+") if part.strip()]
    if not level_ids:
        raise SkillError("invalid_arguments", "empty --protocol")
    infos = [pdhost.describe(directory, level_id) for level_id in level_ids]
    options = _chain_options(args.option, infos)
    logic = infos[0]
    if not logic.direct:
        raise SkillError(
            "decoder_needs_stacking",
            f"{logic.id} consumes {list(logic.inputs)}, not raw logic",
            ["put a logic decoder first: --protocol uart+" + logic.id],
        )
    mapping = _channel_map(args, logic)
    source = _open_source(Path(args.source), wanted=sorted(set(mapping.values())))
    try:
        meta = source["meta"]
        frequency = int(meta.get("frequencyHz") or 0)
        if not frequency:
            raise SkillError(
                "invalid_capture",
                "the capture has no sample rate, so time cannot be decoded",
            )
        entries = {entry.get("channel"): entry for entry in meta.get("bin") or []}
        missing = [channel for channel in mapping.values() if channel not in entries]
        if missing:
            raise SkillError(
                "channel_not_in_capture",
                f"capture channels {sorted(missing)} were not captured",
                [f"captured channels: {sorted(entries)}"],
            )
        valid = min(int(entries[channel].get("validBits") or 0) for channel in mapping.values())
        window = _window_samples(args, frequency, valid)
        paths = {}
        lengths = {}
        for index, channel in mapping.items():
            name = Path(str(entries[channel]["file"])).name
            path = source["base"] / name
            if not path.exists() and (source["base"] / (name + ".partial")).exists():
                path = source["base"] / (name + ".partial")
            if not path.exists():
                raise SkillError("capture_incomplete", f"{path} is missing")
            paths[index] = path
            lengths[index] = valid
        result = pdhost.run_chain(
            directory,
            [{"id": level_id, "options": level_option}
             for level_id, level_option in zip(level_ids, options)],
            paths, lengths, frequency,
            start=window["start"], count=window["count"],
            max_edges=int(args.max_edges), annotation_limit=int(args.max_annotations),
        )
    finally:
        if source["cleanup"] is not None:
            shutil.rmtree(source["cleanup"], ignore_errors=True)

    level_payloads = []
    for level in result["levels"]:
        info = level["info"]
        names = [str(item[0]) for item in info.annotations]
        row_of_class: dict[int, str] = {}
        for row in info.annotation_rows:
            if len(row) < 3:
                continue
            for number in row[2]:
                row_of_class[int(number)] = str(row[0])
        annotations = []
        by_class: dict[str, int] = {}
        by_row: dict[str, int] = {}
        for item in level["host"].annotations:
            number = int(item["class"])
            label = names[number] if 0 <= number < len(names) else f"annotation {number}"
            row = row_of_class.get(number, "other")
            by_class[label] = by_class.get(label, 0) + 1
            by_row[row] = by_row.get(row, 0) + 1
            annotations.append(
                {
                    "start": item["start"] + window["start"],
                    "end": item["end"] + window["start"],
                    "class": label,
                    "row": row,
                    "texts": item["texts"],
                }
            )
        annotations.sort(key=lambda item: (item["start"], item["end"]))
        level_payloads.append(
            {
                "id": info.id,
                "name": info.name,
                "license": info.license,
                "options": {key: value for key, value in level["options"].items()
                            if isinstance(key, str)},
                "failure": level["failure"],
                "counts": {
                    "annotations": len(level["host"].annotations),
                    "byClass": by_class,
                    "byRow": by_row,
                    "pythonEvents": len(level["host"].python_events),
                    "binaryEvents": len(level["host"].binary_events),
                    "droppedAnnotations": level["host"].dropped_annotations,
                },
                "annotations": annotations,
            }
        )

    last = level_payloads[-1]
    combined = list(logic.channels) + list(logic.optional_channels)
    payload = {
        "protocol": {
            "id": last["id"],
            "name": last["name"],
            "longname": infos[-1].longname,
            "license": last["license"],
            "chain": level_ids,
        },
        "capture": {
            "input": source["input"],
            "directory": str(source["base"]),
            "frequencyHz": frequency,
            "mode": meta.get("mode"),
            "status": meta.get("status"),
        },
        "channels": {
            str(combined[index].get("id")): channel_id
            for index, channel_id in mapping.items()
        },
        "options": last["options"],
        "window": {
            "startSample": window["start"],
            "samples": window["count"],
            "seconds": window["count"] / frequency,
            "truncated": window["truncated"],
        },
        "levels": [
            {
                "id": level["id"],
                "name": level["name"],
                "options": level["options"],
                "failure": level["failure"],
                "counts": level["counts"],
            }
            for level in level_payloads
        ],
        "counts": last["counts"],
        "annotations": last["annotations"],
    }
    if args.all_levels and len(level_payloads) > 1:
        payload["annotations"] = [
            dict(item, level=level["id"])
            for level in level_payloads for item in level["annotations"]
        ]
        payload["annotations"].sort(key=lambda item: item["start"])
    wanted_rows = set(args.row or [])
    if wanted_rows:
        known_rows = {
            str(row[0]) for info in infos for row in info.annotation_rows if len(row) >= 3
        }
        unknown = wanted_rows - known_rows
        if unknown:
            raise SkillError(
                "invalid_arguments",
                f"no row(s) {sorted(unknown)} in {', '.join(level_ids)}",
                [f"rows: {', '.join(sorted(known_rows))}"],
            )
        payload["annotations"] = [
            item for item in payload["annotations"] if item["row"] in wanted_rows
        ]
        payload["rows"] = sorted(wanted_rows)
    if args.csv and payload["annotations"]:
        payload["guiCsv"] = _write_gui_csv(args.csv, payload["annotations"], frequency)
    for level in level_payloads:
        if level["failure"] and not level["counts"]["annotations"]:
            raise SkillError(
                "decoder_failed",
                f"{level['id']} stopped before producing output: {level['failure']}",
                [
                    "check the channel mapping and the sample rate",
                    "some decoders need an option (baudrate, polarity, ...); see decoders --search",
                ],
                details={"failure": level["failure"], "options": level["options"]},
            )
    if last["failure"]:
        payload["failure"] = last["failure"]
    if not payload["annotations"] and not payload.get("failure"):
        payload["warnings"] = [
            "the decoder produced no annotations: check the channel mapping, the "
            "decoder options, and that the captured line actually toggles in the window"
        ]
    logs = [line for level in result["levels"] for line in level["host"].logs]
    if logs:
        payload["log"] = logs[:20]
    payload["ok"] = True
    return payload


def cmd_sim(args) -> dict:
    """Turn a VCD trace into a capture directory the decoder can read."""
    import json

    from . import vcd

    wanted = {"scl": args.scl, "sda": args.sda}
    if args.name:
        wanted = {"name": args.name}
    trace = vcd.parse(args.vcd)
    rate = parse_frequency(args.rate)
    channels = vcd.sample(trace["signals"], wanted, rate)
    target = Path(args.out).expanduser()
    target.mkdir(parents=True, exist_ok=True)
    entries = []
    for index, (name, data) in enumerate(channels.items()):
        path = target / f"channel_{index}.bin"
        path.write_bytes(data)
        entries.append({"channel": index, "file": str(path),
                        "validBits": len(data) * 8, "bytes": len(data)})
    (target / "capture.json").write_text(
        json.dumps({"frequencyHz": rate, "bin": entries}, indent=1))
    return {"ok": True, "directory": str(target), "frequencyHz": rate,
            "signals": {name: len(data) * 8 for name, data in channels.items()}}


def _parse_stages(specs) -> list[dict]:
    from . import find as find_mod

    stages = []
    for spec in specs or []:
        channel, _, state = str(spec).partition(":")
        state = state or "rising"
        if not channel.strip().isdigit():
            raise SkillError("invalid_stage", f"stage {spec!r} needs CHANNEL:STATE")
        if state not in find_mod.STATES:
            raise SkillError("invalid_stage", f"unknown state {state!r}",
                             [f"use one of: {', '.join(find_mod.STATES)}"])
        stages.append({"channel": int(channel), "state": state})
    if not stages:
        raise SkillError("invalid_stage", "pass at least one --stage CHANNEL:STATE")
    return stages


def cmd_bursts(args) -> dict:
    """Measure each burst of activity in a capture (PWM/LED workflows)."""
    from . import bursts as bursts_mod

    source = _open_source(Path(args.source), wanted=[args.channel])
    try:
        frequency = int(source["meta"].get("frequencyHz") or 0)
        if not frequency:
            raise SkillError("invalid_capture", "the capture has no sample rate")
        entries = {entry.get("channel"): entry for entry in source["meta"].get("bin") or []}
        if args.channel not in entries:
            raise SkillError("channel_not_in_capture",
                             f"channel {args.channel} was not captured",
                             [f"captured: {sorted(entries)}"])
        entry = entries[args.channel]
        name = Path(str(entry.get("file") or f"channel_{args.channel}.bin")).name
        path = source["base"] / name
        if not path.exists() and (source["base"] / (name + ".partial")).exists():
            path = source["base"] / (name + ".partial")
        gap = int(parse_duration_ms(args.min_gap) / 1000 * frequency)
        result = bursts_mod.measure(path, int(entry.get("validBits") or 0),
                                    max(1, gap), frequency, limit=args.limit)
    finally:
        if source["cleanup"] is not None:
            shutil.rmtree(source["cleanup"], ignore_errors=True)
    return {"ok": True, "channel": args.channel, "frequencyHz": frequency, **result}


def cmd_find(args) -> dict:
    """Resolve staged conditions inside an existing capture."""
    from . import find as find_mod

    stages = _parse_stages(args.stage)
    wanted = sorted({stage["channel"] for stage in stages})
    source = _open_source(Path(args.source), wanted=wanted)
    try:
        meta = source["meta"]
        frequency = int(meta.get("frequencyHz") or 0)
        entries = {entry.get("channel"): entry for entry in meta.get("bin") or []}
        traces = {}
        for channel in wanted:
            if channel not in entries:
                raise SkillError("channel_not_in_capture",
                                 f"channel {channel} was not captured",
                                 [f"captured: {sorted(entries)}"])
            entry = entries[channel]
            name = Path(str(entry.get("file") or f"channel_{channel}.bin")).name
            path = source["base"] / name
            if not path.exists() and (source["base"] / (name + ".partial")).exists():
                path = source["base"] / (name + ".partial")
            traces[channel] = find_mod.Trace(path, int(entry.get("validBits") or 0))
        within = parse_duration_ms(args.within) / 1000 * frequency if args.within else None
        hits = find_mod.search(traces, stages, within=int(within) if within else None,
                               limit=args.limit)
    finally:
        if source["cleanup"] is not None:
            shutil.rmtree(source["cleanup"], ignore_errors=True)
    for hit in hits:
        hit["startSeconds"] = hit["start"] / frequency if frequency else None
        hit["endSeconds"] = hit["end"] / frequency if frequency else None
    return {"ok": True, "frequencyHz": frequency, "stages": stages,
            "hitCount": len(hits), "hits": hits}


def cmd_watch(args) -> dict:
    """Summarise GUI projects as they appear in a directory."""
    import time

    directory = Path(args.dir).expanduser()
    if not directory.is_dir():
        raise SkillError("watch_dir_missing", f"{directory} is not a directory",
                         ["pass an existing directory with --dir"])
    seen: set[Path] = set()
    while True:
        found = sorted(p for p in directory.rglob("*.atkdl") if atkdl.looks_like_atkdl(p))
        fresh = [p for p in found if p not in seen]
        for path in fresh:
            seen.add(path)
            try:
                project = atkdl.inspect(path)
            except SkillError as error:
                print(f"{path}: {error.code}", flush=True)
                continue
            print(f"{path}: {project.get('samples')} samples, "
                  f"{len(project.get('channels', []))} channels, "
                  f"{project.get('frequencyHz')} Hz", flush=True)
        if args.once:
            return {"ok": True, "scanned": len(found), "new": len(fresh)}
        time.sleep(args.interval)


def cmd_usb(args) -> dict:
    if args.action == "find":
        import tempfile

        from . import find as find_mod

        stages = _parse_stages(args.stage)
        result = usb.capture_native(
            parse_frequency(args.freq), parse_duration_ms(args.time),
            parse_volts(args.threshold), parse_percent(args.position),
            {item["id"]: item["trigger"] for item in parse_channels(args.ch)},
            collect_type=args.ct, read_seconds=args.read_seconds,
            glitch_width=args.remove_glitches, include_packed=True,
        )
        frequency = parse_frequency(args.freq)
        hits = []
        with tempfile.TemporaryDirectory() as directory:
            traces = {}
            for channel, packed in result["packed"].items():
                path = Path(directory) / f"channel_{channel}.bin"
                path.write_bytes(packed)
                traces[channel] = find_mod.Trace(path, len(packed) * 8)
            missing = [stage["channel"] for stage in stages if stage["channel"] not in traces]
            if missing:
                raise SkillError("channel_not_in_capture",
                                 f"channels {sorted(set(missing))} carried no data",
                                 [f"captured: {sorted(traces)}"])
            within = (parse_duration_ms(args.within) / 1000 * frequency) if args.within else None
            hits = find_mod.search(traces, stages, within=int(within) if within else None,
                                   limit=args.limit)
        for hit in hits:
            hit["startSeconds"] = hit["start"] / frequency
            hit["endSeconds"] = hit["end"] / frequency
        samples = max((len(packed) * 8 for packed in result["packed"].values()), default=0)
        return {"ok": True, "bytes": result["bytes"], "samples": samples,
                "frequencyHz": frequency, "hitCount": len(hits), "hits": hits}

    if args.action == "capture":  # noqa: SIM116
        result = usb.capture_native(
            parse_frequency(args.freq), parse_duration_ms(args.time),
            parse_volts(args.threshold), parse_percent(args.position),
            {item["id"]: item["trigger"] for item in parse_channels(args.ch)},
            collect_type=args.ct, read_seconds=args.read_seconds,
            glitch_width=args.remove_glitches, include_packed=args.save is not None,
        )
        if args.save:
            import json as _json

            target = Path(args.save).expanduser()
            target.mkdir(parents=True, exist_ok=True)
            entries = []
            for channel, packed in sorted(result.pop("packed").items()):
                path = target / f"channel_{channel}.bin"
                path.write_bytes(bytes(packed))
                entries.append({"channel": channel, "file": str(path),
                                "validBits": len(packed) * 8, "bytes": len(packed)})
            (target / "capture.json").write_text(_json.dumps(
                {"frequencyHz": parse_frequency(args.freq), "bin": entries}, indent=1))
            result["directory"] = str(target)
        return {"ok": True, **result}
    if args.action == "config":
        transport = usb.open_transport()
        try:
            result = usb.apply_config(
                transport,
                parse_frequency(args.freq), parse_duration_ms(args.time),
                parse_volts(args.threshold), parse_percent(args.position),
                {item["id"]: item["trigger"] for item in parse_channels(args.ch)},
                only=args.only,
            )
        finally:
            transport.close()
        return {"ok": True, **result}
    if args.action == "info":
        transport = usb.open_transport()
        try:
            info = usb.read_only_info(transport)
        finally:
            transport.close()
        info["usb"] = [f"{vid:04x}:{pid:04x}" for vid, pid in usb.VID_PID]
        return {"ok": True, **info}
    # Offline: show the exact bytes the native transport would send.
    if args.action == "frame":
        if args.command == "parameter":
            payload = usb.parameter_payload(
                parse_frequency(args.freq), parse_duration_ms(args.time),
                parse_volts(args.threshold), parse_percent(args.position),
                buffer_mode=args.mode == "buffer", rle=args.rle,
            )
            command = usb.CMD_PARAMETERS
        elif args.command == "trigger":
            states = {item["id"]: item["trigger"] for item in parse_channels(args.ch)}
            payload = usb.simple_trigger_payload(states)
            command = usb.CMD_TRIGGER_SIMPLE
        elif args.command == "hello":
            payload, command = b"", usb.CMD_HELLO
        else:
            payload, command = b"", usb.CMD_DEVICE_DATA
        return {
            "ok": True,
            "command": command,
            "payloadHex": payload.hex(),
            "framedHex": usb.frame(command, payload).hex(),
        }
    raise SkillError("invalid_arguments", f"unknown usb action {args.action!r}")


def cmd_series(args) -> dict:
    invocation = _invocation(args)
    config = host.load_config()
    plan = capture.build_plan(args)
    interval = float(args.interval or 0)
    runs = []
    started = time.monotonic()
    for index in range(int(args.count)):
        if index and interval:
            time.sleep(interval)
        payload = capture.run(
            invocation, plan.copy(),
            out=Path(args.out) / f"{index + 1:03d}" if args.out else None,
            device_id=_device_id(args, config),
            strict=args.strict,
            one_shot=args.one_shot,
            analyze=not args.no_analyze,
            keep_stage=args.keep_stage,
            timeout=args.timeout,
            trigger_timeout=args.trigger_timeout,
            glitch_ns=args.glitch_ns,
            on_prompt=_progress(args),
        )
        runs.append(
            {
                "index": index + 1,
                "directory": payload["capture"]["directory"],
                "status": payload["capture"]["status"],
                "frequencyHz": payload["capture"]["frequencyHz"],
                "durationMs": payload["capture"]["durationMs"],
                "channels": payload["capture"].get("analysis") or [],
            }
        )
        if payload["capture"].get("status") != "complete":
            break
    return {
        "ok": True,
        "count": len(runs),
        "requested": plan.describe(),
        "runs": runs,
        "timing": {"seconds": round(time.monotonic() - started, 2)},
    }


def cmd_config(args) -> dict:
    config = host.load_config()
    changes: dict = {}
    for item in args.set or []:
        if "=" not in item:
            raise SkillError("invalid_arguments", f"--set expects key=value, got {item!r}")
        key, value = item.split("=", 1)
        changes[key.strip()] = value.strip()
    for key in args.unset or []:
        changes[key] = None
    if changes:
        config = host.save_config(changes)
    return {
        "ok": True,
        "configFile": str(host.config_file()),
        "config": config,
        "keys": ["cli", "device_id", "staging", "windows_temp", "output_root", "decoders"],
    }


def cmd_raw(args) -> dict:
    invocation = _invocation(args)
    cli_args = [item for item in args.cli_args if item != "--json"]
    payload = protocol.run_json(invocation, cli_args, context=" ".join(cli_args[:2]))
    for key in list(payload):
        if key.startswith("_"):
            payload.pop(key)
    payload["ok"] = payload.get("ok", True)
    return payload


# ---------------------------------------------------------------- printing

def _time_label(sample: int, frequency: int) -> str:
    return fmt_ms(sample / frequency * 1000)


def _print_decoders(payload: dict) -> None:
    print(f"{payload['count']} decoders in {payload['directory']} "
          f"({payload['direct']} take logic directly)")
    direct = [item for item in payload["decoders"] if item["direct"]]
    stacked = [item for item in payload["decoders"] if not item["direct"]]
    for title, group in (("logic", direct), ("stacked (needs an upstream decoder)", stacked)):
        if not group:
            continue
        print(f"  {title}:")
        for item in group[:80]:
            channels = ",".join(str(channel.get("id")) for channel in item["channels"])
            print(f"    {item['id']:<16} {item['name']:<28} ch: {channels:<18} {item['desc'][:52]}")
        if len(group) > 80:
            print(f"    ... {len(group) - 80} more")


def _print_decode(payload: dict) -> None:
    protocol = payload["protocol"]
    window = payload["window"]
    capture = payload["capture"]
    chain = protocol.get("chain") or [protocol["id"]]
    label = " + ".join(chain) if len(chain) > 1 else protocol["name"]
    print(f"{label} on {capture['input']}")
    channels = ", ".join(f"{name}=ch{channel}" for name, channel in payload["channels"].items())
    print(f"  {channels}  {fmt_hz(capture['frequencyHz'])}  "
          f"window {window['startSample']}..{window['startSample'] + window['samples']} "
          f"({fmt_ms(window['seconds'] * 1000)})")
    counts = payload["counts"]
    if len(payload.get("levels") or []) > 1:
        per_level = ", ".join(
            f"{level['id']}={level['counts']['annotations']}" for level in payload["levels"]
        )
        print(f"  levels: {per_level}")
    rows = ", ".join(f"{name}={number}" for name, number in counts["byRow"].items())
    print(f"  annotations {counts['annotations']}"
          + (f", dropped {counts['droppedAnnotations']}" if counts.get("droppedAnnotations") else "")
          + (f"  rows: {rows}" if rows else ""))
    for item in payload["annotations"][:40]:
        seconds = item["start"] / capture["frequencyHz"]
        text = item["texts"][0] if item["texts"] else ""
        print(f"    {seconds * 1000:10.4f} ms  {item['row']:<14} {text}")
    if len(payload["annotations"]) > 40:
        print(f"    ... {len(payload['annotations']) - 40} more (use --json or --row)")
    if payload.get("failure"):
        print(f"  decoder stopped: {payload['failure']}")
    if window["truncated"]:
        print("  window truncated; raise --max-samples or narrow --window")
    for line in payload.get("warnings") or []:
        print(f"  warning: {line}")
    if not payload["annotations"] and not payload.get("warnings"):
        print("  no annotations in this window")


def _print_capture(payload: dict) -> None:
    data = payload["capture"]
    print(
        f"{data.get('mode')} capture {data.get('status')}  "
        f"{fmt_hz(data.get('frequencyHz') or 0)} x {fmt_ms(data.get('durationMs') or 0)}  "
        f"{(data.get('device') or {}).get('model', '')} {data.get('device', {}).get('deviceId', '')}".strip()
    )
    for channel in data.get("channels") or []:
        line = f"  ch{channel.get('id'):<2} trigger {channel.get('trigger'):<8}"
        stats = next(
            (item for item in data.get("analysis") or [] if item.get("channel") == channel.get("id")),
            None,
        )
        if stats and stats.get("bits"):
            duty = (stats.get("duty") or 0) * 100
            line += (
                f" duty {duty:5.1f}%  edges {stats.get('edges'):>8} "
                f"cycle {stats.get('cycleRateHz') or 0:>12.0f} Hz"
            )
            if stats.get("stuck"):
                line += "  (constant)"
        print(line)
    if data.get("rle"):
        print("  RLE was enabled by the device")
    print(f"  directory {data.get('directory')}")
    for adjustment in payload.get("adjustments") or []:
        print(f"  adjusted: {adjustment}")
    if data.get("staged"):
        print(f"  staged on Windows as {data.get('vendorDirectory')}")
    print(f"  {payload.get('timing', {}).get('seconds', 0)} s wall")


def _print_read(payload: dict) -> None:
    data = payload["capture"]
    print(
        f"{data.get('status')}  {fmt_hz(data.get('frequencyHz') or 0)} x "
        f"{fmt_ms(data.get('durationMs') or 0)}  {data.get('directory')}"
    )
    for item in payload["analysis"]:
        if not item.get("bits"):
            print(f"  ch{item.get('channel')}: {item.get('note', 'no data')}")
            continue
        duty = (item.get("duty") or 0) * 100
        print(
            f"  ch{item['channel']:<2} {item['bits']:>12} samples  duty {duty:5.1f}%  "
            f"edges {item['edges']:>8}  min pulse {item.get('minRunBits')} bits  "
            f"max run {item.get('maxRunBits')} bits"
        )
    gui = (payload.get("project") or {}).get("gui") or {}
    if gui:
        notes = []
        if gui.get("stageTriggerLevels"):
            notes.append(f"{gui['stageTriggerLevels']}-level stage trigger")
        if gui.get("serialTrigger"):
            notes.append("serial trigger")
        if any(item.get("open") for item in gui.get("pwmOutputs") or []):
            notes.append("PWM output on")
        if gui.get("glitchRemoval"):
            notes.append(f"glitch removal ({len(gui['glitchRemoval'])})")
        if gui.get("rolling"):
            notes.append("rolling mode")
        if gui.get("cursors"):
            notes.append("cursors " + ",".join(gui["cursors"]))
        if notes:
            print("  GUI acquisition: " + "; ".join(notes))
    for kind, value in (payload.get("outputs") or {}).items():
        if kind == "guiCsv":
            for item in value:
                print(f"  gui csv {item['file']}: {item['rows']} rows")
                for entry in item["kinds"][:6]:
                    stats = ""
                    if entry.get("min") is not None:
                        stats = (f" {entry['min']:.6g}..{entry['max']:.6g} {entry['unit']}"
                                 f" (mean {entry['mean']:.6g})")
                    print(f"    {entry['name']}: {entry['count']} rows{stats}")
        elif isinstance(value, dict):
            print(f"  {kind}: {value.get('file')}")
        elif isinstance(value, list):
            print(f"  {kind}: {len(value)} files")


def _print_series(payload: dict) -> None:
    print(f"{payload['count']} capture(s), {payload['timing']['seconds']} s")
    for run in payload["runs"]:
        line = f"  #{run['index']:<3} {run['status']:<8}"
        for stats in run["channels"]:
            if stats.get("bits"):
                line += (
                    f" ch{stats['channel']} duty {(stats.get('duty') or 0) * 100:5.1f}%"
                    f" edges {stats['edges']:>8}"
                )
        print(line)
        print(f"       {run['directory']}")


def _print_caps(payload: dict) -> None:
    if payload.get("query"):
        query = payload["query"]
        kind = query["kind"]
        print(f"{payload['mode']} mode, channels {payload['channels']}")
        if kind == "durationOptions":
            values = query.get("durationsMs") or []
            print(f"  at {fmt_hz(query['frequencyHz'])}: {', '.join(fmt_ms(v) for v in values[:40])}")
            if len(values) > 40:
                print(f"  ... {len(values) - 40} more")
        else:
            values = query.get("frequenciesHz") or []
            print(f"  at {fmt_ms(query['durationMs'])}: {', '.join(fmt_hz(v) for v in values)}")
        return
    print(f"{payload['mode']} mode, channels {payload['channels']}")
    for row in payload.get("options") or []:
        rle = f", RLE from {fmt_ms(row['rleDurationsMs'][0])}" if row.get("rleDurationsMs") else ""
        print(
            f"  {fmt_hz(row['frequencyHz']):>10}  {row['durationCount']:>2} durations  "
            f"{fmt_ms(row['minDurationMs'])} .. {fmt_ms(row['maxDurationMs'])}{rle}"
        )


def _print_info(payload: dict) -> None:
    device = payload["device"]
    print(
        f"{device.get('model')} {device.get('deviceId')}  "
        f"{device.get('channelCount')} channels ({payload.get('usableChannels')})  "
        f"USB {device.get('usbSpeed')}  level {device.get('level')}"
    )
    print(
        f"  mcu {device.get('mcuVersion')}  fpga {device.get('fpgaVersion')}  "
        f"hardware {device.get('hardwareVersion')}  port {device.get('port')}"
    )


def _print_doctor(payload: dict) -> None:
    print(f"host: {payload.get('platform')}  python {payload['host']['python']}")
    cli = payload.get("cli")
    if cli:
        print(f"cli:  {cli['command']}  (v{cli['version']}, {cli['source']})")
    staging = payload.get("staging")
    if staging:
        print(f"staging: {staging['path']} writable={staging['writable']}")
    print(f"config: {payload.get('config_file')}")
    devices = payload.get("devices") or []
    print(f"devices: {len(devices)}")
    for device in devices:
        print(
            f"  {device.get('deviceId')} {device.get('model')} port {device.get('port')} "
            f"bootloader={device.get('bootloader')} profileComplete={device.get('profileComplete')}"
        )
    for error in payload.get("errors") or []:
        print(f"  error {error.get('code')}: {error.get('message')}")
    for line in payload.get("notes") or []:
        print(f"  note: {line}")


# ----------------------------------------------------------------- parsing

def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    parser.add_argument("--cli", help="CLI command (defaults to ATK_LOGIC_CLI or the install path)")
    parser.add_argument("--quiet", action="store_true", help="no progress on stderr")


def _capture_args(parser: argparse.ArgumentParser, channels_required: bool = True) -> None:
    parser.add_argument("--ch", action="append", metavar="ID[:TRIGGER]",
                        required=channels_required,
                        help="channel and its simple trigger, e.g. 0:rising (repeatable; 0,1 is shorthand)")
    parser.add_argument("--freq", default="1m", help="sample rate (Hz or 1m/2.5mhz), default 1m")
    parser.add_argument("--time", default="10ms", help="capture time (ms or 1s/500us), default 10ms")
    parser.add_argument("--threshold", default="1.8", help="trigger threshold in volts, default 1.8")
    parser.add_argument("--position", default="50", help="trigger position in percent, default 50")
    parser.add_argument("--mode", choices=MODES, default="buffer")
    parser.add_argument("--format", choices=FORMATS, default="bin",
                        help="bin (default), atkdl for the GUI project, or both")
    parser.add_argument("--out", help="output directory (default captures/atk_<stamp>)")
    parser.add_argument("--strict", action="store_true",
                        help="refuse a frequency or duration the device does not offer")
    parser.add_argument("--one-shot", action="store_true",
                        help="one CLI process per step instead of a JSONL session")
    parser.add_argument("--no-analyze", action="store_true", help="skip per-channel statistics")
    parser.add_argument("--keep-stage", action="store_true", help="keep the Windows staging dir")
    parser.add_argument("--timeout", type=float, help="capture timeout in seconds")
    parser.add_argument("--trigger-timeout", type=float, default=20.0,
                        help="stop after this many seconds without a capture event, "
                             "e.g. when the trigger never fires (0 = wait forever)")
    parser.add_argument("--glitch-ns", type=float, help="count pulses shorter than this as glitches")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="atkla.py",
        description="ATK-Logic logic analyzer: find the device, capture a legal combination, read the bits.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="check the CLI, the staging path and the device")
    _common(doctor)
    doctor.set_defaults(func=cmd_doctor, printer=_print_doctor)

    listing = subparsers.add_parser("list", help="enumerate analyzers")
    _common(listing)
    listing.set_defaults(func=cmd_list)

    info = subparsers.add_parser("info", help="connect and report the device profile")
    _common(info)
    info.add_argument("--device-id", help="dl16:<port> or dl32:<port>")
    info.set_defaults(func=cmd_info, printer=_print_info)

    caps = subparsers.add_parser("caps", help="legal frequency/duration combinations")
    _common(caps)
    caps.add_argument("--mode", choices=MODES, default="buffer")
    caps.add_argument("--ch", action="append", metavar="ID[:TRIGGER]",
                      help="channels that will be enabled, e.g. 0,1 or 0:rising (default 0)")
    caps.add_argument("--freq", help="list the durations legal at this rate")
    caps.add_argument("--time", help="list the rates legal for this duration")
    caps.set_defaults(func=cmd_caps, printer=_print_caps)

    one = subparsers.add_parser("capture", help="one capture: resolve, validate, run, analyse")
    _common(one)
    one.add_argument("--device-id", help="dl16:<port> or dl32:<port>")
    _capture_args(one)
    one.set_defaults(func=cmd_capture, printer=_print_capture)

    read = subparsers.add_parser("read", help="decode a capture directory: statistics, CSV, VCD")
    _common(read)
    read.add_argument("directory", help="capture directory (or its capture.json)")
    read.add_argument("--ch", action="append", metavar="ID[:TRIGGER]",
                      help="limit to these channels, e.g. 0,2")
    read.add_argument("--csv", help="write a sample or transition CSV")
    read.add_argument("--csv-all", action="store_true", help="one CSV per channel")
    read.add_argument("--csv-transitions", action="store_true",
                      help="write edges only instead of every sample")
    read.add_argument("--vcd", help="write a VCD for PulseView or GtkWave")
    read.add_argument("--start", type=int, default=0, help="first sample for --csv")
    read.add_argument("--count", type=int, help="samples for --csv")
    read.add_argument("--max-bits", type=int, default=1_000_000_000,
                      help="refuse to analyse files above this many samples")
    read.add_argument("--glitch-ns", type=float, help="count pulses shorter than this as glitches")
    read.add_argument("--gui-csv", action="append", metavar="FILE",
                      help="summarise a CSV exported by the GUI's protocol decoder (repeatable)")
    read.add_argument("--run-lengths", action="store_true",
                      help="also compute pulse widths and glitches on a large capture (slow)")
    read.add_argument("--extract", metavar="DIR",
                      help="unpack the .atkdl chunks into DIR and keep them")
    read.set_defaults(func=cmd_read, printer=_print_read)

    series = subparsers.add_parser("series", help="repeat the same capture N times and compare")
    _common(series)
    series.add_argument("--device-id")
    _capture_args(series)
    series.add_argument("--count", type=int, default=5)
    series.add_argument("--interval", type=float, default=0, help="seconds between captures")
    series.set_defaults(func=cmd_series, printer=_print_series)

    decoders = subparsers.add_parser(
        "decoders", help="list the protocol decoders the GUI ships (sigrok collection)")
    _common(decoders)
    decoders.add_argument("--search", help="filter by id, name, description or licence")
    decoders.add_argument("--decoders", metavar="DIR", help="decoder directory")
    decoders.set_defaults(func=cmd_decoders, printer=_print_decoders)

    decoding = subparsers.add_parser(
        "decode", help="run a protocol decoder over a capture (UART, I2C, SPI, IR NEC, ...)")
    _common(decoding)
    decoding.add_argument("source", help="capture directory, capture.json or .atkdl project")
    decoding.add_argument("--protocol", required=True,
                          help="decoder id, or a chain: uart+modbus, spi+spiflash")
    decoding.add_argument("--ch", action="append", metavar="NAME=ID",
                          help="map a decoder channel to a capture channel, e.g. scl=7")
    decoding.add_argument("--option", action="append", metavar="KEY=VALUE",
                          help="decoder option, e.g. baudrate=115200 or polarity=active-high")
    decoding.add_argument("--window", metavar="START:END",
                          help="time window in seconds or with units, e.g. 0:10ms, 1s:2s")
    decoding.add_argument("--max-samples", type=int, default=50_000_000,
                          help="decode at most this many samples unless --window says otherwise")
    decoding.add_argument("--max-edges", type=int, default=4_000_000,
                          help="refuse a window with more edges than this")
    decoding.add_argument("--row", action="append", metavar="ROW",
                          help="only these annotation rows, e.g. packets or rx-data-vals")
    decoding.add_argument("--max-annotations", type=int, default=5000)
    decoding.add_argument("--all-levels", action="store_true",
                          help="include the upstream levels' annotations too")
    decoding.add_argument("--csv", metavar="FILE",
                          help="write the annotations as the GUI's decode CSV")
    decoding.add_argument("--decoders", metavar="DIR", help="decoder directory")
    decoding.set_defaults(func=cmd_decode, printer=_print_decode)

    usb_cmd = subparsers.add_parser(
        "usb", help="native USB transport (read-only info, protocol frames)")
    _common(usb_cmd)
    usb_cmd.add_argument("action", choices=("info", "config", "capture", "frame", "find"))
    usb_cmd.add_argument("--stage", action="append", metavar="CH:STATE",
                         help="staged condition, repeatable (usb find)")
    usb_cmd.add_argument("--within", help="max time from the first stage, e.g. 4us")
    usb_cmd.add_argument("--limit", type=int, default=5)
    usb_cmd.add_argument("--save", metavar="DIR",
                         help="write capture.json and channel_N.bin (usb capture)")
    usb_cmd.add_argument("--ct", type=int, default=2, help="0x12 collect type (2 = real data)")
    usb_cmd.add_argument("--read-seconds", type=float, default=3.0)
    usb_cmd.add_argument("--remove-glitches", type=int, default=0,
                         help="absorb pulses shorter than N samples before stats")
    usb_cmd.add_argument("--only", default="", help="send one config step only")
    usb_cmd.add_argument("--command", choices=("parameter", "trigger", "hello", "device"),
                         default="device")
    usb_cmd.add_argument("--ch", action="append", metavar="ID[:TRIGGER]")
    usb_cmd.add_argument("--freq", default="1m")
    usb_cmd.add_argument("--time", default="10ms")
    usb_cmd.add_argument("--threshold", default="1.8")
    usb_cmd.add_argument("--position", default="50")
    usb_cmd.add_argument("--mode", choices=("buffer", "stream"), default="buffer")
    usb_cmd.add_argument("--rle", action="store_true")
    usb_cmd.set_defaults(func=cmd_usb)

    bursts_cmd = subparsers.add_parser(
        "bursts", help="measure each burst of activity in a capture")
    bursts_cmd.add_argument("source", help="capture directory, capture.json or .atkdl")
    bursts_cmd.add_argument("--ch", dest="channel", type=int, default=0)
    bursts_cmd.add_argument("--min-gap", default="1ms",
                            help="silence that separates two bursts (default 1ms)")
    bursts_cmd.add_argument("--limit", type=int, default=20)
    _common(bursts_cmd)
    bursts_cmd.set_defaults(func=cmd_bursts)

    find_cmd = subparsers.add_parser(
        "find", help="search a capture for staged conditions (software trigger)")
    find_cmd.add_argument("source", help="capture directory, capture.json or .atkdl project")
    find_cmd.add_argument("--stage", action="append", required=True,
                          metavar="CH:STATE", help="e.g. 2:rising, then 2:high (repeatable)")
    find_cmd.add_argument("--within", help="max time from the first stage, e.g. 10ms")
    find_cmd.add_argument("--limit", type=int, default=5)
    _common(find_cmd)
    find_cmd.set_defaults(func=cmd_find)

    sim_cmd = subparsers.add_parser("sim", help="turn a VCD trace into a capture directory")
    sim_cmd.add_argument("--vcd", required=True)
    sim_cmd.add_argument("--scl", default="scl")
    sim_cmd.add_argument("--sda", default="sda")
    sim_cmd.add_argument("--name", help="single signal to export instead of scl/sda")
    sim_cmd.add_argument("--rate", default="10m", help="sample rate, e.g. 10m")
    sim_cmd.add_argument("--out", required=True)
    _common(sim_cmd)
    sim_cmd.set_defaults(func=cmd_sim)

    watch_cmd = subparsers.add_parser("watch", help="report new GUI projects in a directory")
    watch_cmd.add_argument("--dir", required=True)
    watch_cmd.add_argument("--interval", type=float, default=5.0)
    watch_cmd.add_argument("--once", action="store_true", help="scan once and exit")
    watch_cmd.add_argument("--decode", action="store_true", help="print decode hints")
    _common(watch_cmd)
    watch_cmd.set_defaults(func=cmd_watch)

    config = subparsers.add_parser("config", help="show or change saved defaults")
    _common(config)
    config.add_argument("--set", action="append", metavar="KEY=VALUE")
    config.add_argument("--unset", action="append", metavar="KEY")
    config.set_defaults(func=cmd_config)

    raw = subparsers.add_parser("raw", help="pass a command line straight to the vendor CLI")
    _common(raw)
    raw.add_argument("cli_args", nargs=argparse.REMAINDER)
    raw.set_defaults(func=cmd_raw)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = args.func(args)
    except SkillError as error:
        payload = error.to_dict()
        if getattr(args, "json", False):
            dump(payload)
        else:
            print(f"{error.code}: {error.message}", file=sys.stderr)
            for suggestion in error.suggestions:
                print(f"  - {suggestion}", file=sys.stderr)
        return EXIT_SKILL
    except KeyboardInterrupt:
        print("interrupted; the device connection was closed", file=sys.stderr)
        return 130

    if getattr(args, "json", False):
        dump(payload)
    else:
        printer = getattr(args, "printer", None)
        if printer:
            printer(payload)
        else:
            dump(payload)
    return EXIT_OK
