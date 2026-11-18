"""One capture: resolve, validate, run, wait for idle, keep the evidence.

The order is the one the vendor manual prescribes:

    device.list -> device.connect -> device.capabilities -> capture.validate
    -> capture.run -> capture.status=idle -> read capture.json -> read .bin

Nothing here guesses a frequency or a duration. ``capabilities.resolve`` picks
from the device's own list and reports every substitution it made.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import capabilities, decode, host, protocol
from .common import (
    TRIGGER_CODES,
    SkillError,
    parse_channels,
    parse_duration_ms,
    parse_frequency,
    parse_percent,
    parse_volts,
)


@dataclass
class Plan:
    mode: str = "buffer"
    frequency_hz: int = 1_000_000
    duration_ms: int = 10
    threshold_volts: float = 1.8
    trigger_position_percent: float = 50.0
    channels: list[dict] = field(default_factory=list)
    format: str = "bin"

    def params(self, output_directory: str) -> dict:
        return {
            "mode": self.mode,
            "frequencyHz": self.frequency_hz,
            "durationMs": self.duration_ms,
            "thresholdVolts": self.threshold_volts,
            "triggerPositionPercent": self.trigger_position_percent,
            "channels": [dict(c) for c in self.channels],
            "format": self.format,
            "outputDirectory": output_directory,
            "noTimestamp": False,
        }

    def cli_args(self, output_directory: str, config_path: str | None = None) -> list[str]:
        args: list[str] = []
        if config_path:
            args += ["--config", config_path]
        args += [
            "--mode", self.mode,
            "--frequency", str(self.frequency_hz),
            "--time", str(self.duration_ms),
            "--threshold", f"{self.threshold_volts:g}",
            "--trigger-position", f"{self.trigger_position_percent:g}",
            "--format", self.format,
            "--output-dir", output_directory,
        ]
        for channel in self.channels:
            args += ["--channel", f"{channel['id']}:{channel['trigger']}"]
        return args

    def copy(self) -> "Plan":
        return dataclasses.replace(self, channels=[dict(c) for c in self.channels])

    def describe(self) -> dict:
        return {
            "mode": self.mode,
            "frequencyHz": self.frequency_hz,
            "durationMs": self.duration_ms,
            "thresholdVolts": self.threshold_volts,
            "triggerPositionPercent": self.trigger_position_percent,
            "channels": [dict(c) for c in self.channels],
            "format": self.format,
        }


def build_plan(args) -> Plan:
    channels = parse_channels(args.ch)
    return Plan(
        mode=args.mode,
        frequency_hz=parse_frequency(args.freq),
        duration_ms=parse_duration_ms(args.time),
        threshold_volts=parse_volts(args.threshold),
        trigger_position_percent=parse_percent(args.position),
        channels=channels,
        format=args.format,
    )


def _timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def _plan_output(invocation, out: Path | None):
    """Choose where the CLI writes and where the evidence finally lives."""
    if out is None:
        out = Path.cwd() / "captures" / f"atk_{_timestamp()}"
    out = out.expanduser().resolve()
    if out.exists():
        raise SkillError(
            "output_conflict",
            f"{out} already exists",
            ["choose a new --out path; the vendor CLI never overwrites a capture"],
        )
    if invocation.windows and not host.is_windows_drive_path(out):
        stage = host.new_staging_dir(invocation, _timestamp())
        stage.mkdir(parents=True, exist_ok=True)
        return {
            "vendor_out": host.to_vendor_path(invocation, stage),
            "stage": stage,
            "control": stage,
            "final": out,
            "staged": True,
        }
    control = host.new_staging_dir(invocation, _timestamp())
    control.mkdir(parents=True, exist_ok=True)
    vendor_out = host.to_vendor_path(invocation, out)
    return {
        "vendor_out": vendor_out,
        "stage": None,
        "control": control,
        "final": out,
        "staged": False,
    }


def _salvage(invocation, staged: dict, error: SkillError) -> None:
    """Copy whatever the device wrote before it failed."""
    stage = staged.get("stage")
    target = Path(staged["final"])
    if not stage or not Path(stage).exists():
        if target.is_dir():
            children = sorted(item for item in target.iterdir() if item.is_dir())
            if children:
                error.details.setdefault("salvaged_to", str(children[-1]))
        return
    try:
        target.mkdir(parents=True, exist_ok=True)
        copied = 0
        for entry in sorted(Path(stage).iterdir()):
            if entry.is_dir():
                shutil.copytree(entry, target, dirs_exist_ok=True)
            else:
                shutil.copy2(entry, target / entry.name)
            copied += 1
        if copied:
            error.details.setdefault("salvaged_to", str(target))
    except OSError:
        return


def _publicate(invocation, staged: dict, vendor_directory: str | None) -> tuple[Path, Path]:
    """Return (final directory, vendor-side directory)."""
    if not vendor_directory:
        raise SkillError(
            "capture_incomplete",
            "the CLI never reported an output directory",
            ["keep the staging directory and the CLI log; replug the analyzer"],
            retryable=True,
        )
    vendor_directory = vendor_directory.rstrip("/\\")
    if not staged["staged"]:
        return Path(host.from_vendor_path(invocation, vendor_directory)), Path(vendor_directory)
    stage = Path(staged["stage"])
    local = Path(host.from_vendor_path(invocation, vendor_directory))
    target = Path(staged["final"])
    if not local.exists():
        raise SkillError(
            "output_missing",
            f"the CLI reported {vendor_directory} but nothing was written there",
            ["check the staging directory and the CLI log"],
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise SkillError("output_conflict", f"{target} already exists")
    shutil.copytree(local, target)
    return target, Path(vendor_directory)


def _cleanup(staged: dict, keep: bool) -> None:
    if keep:
        return
    for key in ("stage", "control"):
        directory = staged.get(key)
        if directory:
            shutil.rmtree(directory, ignore_errors=True)


def _write_config(invocation, plan: Plan, vendor_out: str, control: Path) -> str:
    """Keep the request in a real config file and pass it with ``--config``.

    The vendor supports flags only, but its documented invocation is
    ``capture ... --config FILE [OPTIONS]``; writing the file also makes the run
    reproducible even when the directory is later copied off the Windows side.
    """
    control.mkdir(parents=True, exist_ok=True)
    path = control / "capture-request.json"
    path.write_text(
        json.dumps(plan.params(vendor_out), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return host.to_vendor_path(invocation, path)


def _capture_timeout(plan: Plan, override: float | None) -> float:
    if override:
        return float(override)
    seconds = plan.duration_ms / 1000.0
    # The device needs to upload and the CLI to write; streaming is bounded by
    # USB throughput, buffered mode by the transfer after the trigger.
    return max(120.0, seconds * (2.5 if plan.mode == "stream" else 1.5) + 120.0)


def _channel_view(capture: dict) -> list[dict]:
    channels = []
    for channel in capture.get("channels") or []:
        code = str(channel.get("trigger"))
        channels.append(
            {
                "id": channel.get("id"),
                "trigger": TRIGGER_CODES.get(code, str(channel.get("trigger"))),
            }
        )
    return channels


def _read_meta(directory: Path) -> dict:
    path = directory / "capture.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SkillError(
            "capture_incomplete",
            f"{path} is missing, so the run never produced metadata",
            ["keep the directory and the CLI log"],
            retryable=True,
        )
    except json.JSONDecodeError as exc:
        raise SkillError("invalid_output", f"{path} is not valid JSON: {exc}")


def _usable(devices: list[dict]) -> list[dict]:
    return [device for device in devices if not device.get("bootloader")]


def _choose_device(devices: list[dict], device_id: str | None) -> str:
    """The manual's step 2: list first, then name the device explicitly."""
    usable = _usable(devices)
    if device_id:
        return device_id
    if not usable:
        raise SkillError(
            "device_not_found",
            "no analyzer is available (none enumerated, or only bootloader devices)",
            ["check USB and power, then run doctor", "leave bootloader mode"],
            retryable=True,
            details={"devices": devices},
        )
    if len(usable) > 1:
        raise SkillError(
            "multiple_devices",
            f"{len(usable)} analyzers are attached; name one with --device-id",
            [f"device ids: {', '.join(str(d.get('deviceId')) for d in usable)}"],
            details={"devices": usable},
        )
    return str(usable[0].get("deviceId") or "")


def _check_channels(device: dict, channels: list[dict]) -> None:
    count = int(device.get("channelCount") or 0)
    if not count:
        return
    first = int(device.get("channelOffset") or 0)
    last = first + count - 1
    bad = [channel["id"] for channel in channels if not first <= channel["id"] <= last]
    if bad:
        raise SkillError(
            "invalid_arguments",
            f"channels {bad} are outside this device's usable range {first}-{last}",
            [f"use channel ids {first}-{last}; info reports the real range"],
            details={"usableChannels": f"{first}-{last}"},
        )


def run(invocation, plan: Plan, *, out: Path | None = None, device_id: str | None = None,
        strict: bool = False, one_shot: bool = False, analyze: bool = True,
        keep_stage: bool = False, timeout: float | None = None,
        trigger_timeout: float = 20.0, glitch_ns: float | None = None,
        on_prompt=None, on_event=None) -> dict:
    started = time.monotonic()
    staged = _plan_output(invocation, out)
    device: dict = {}
    validate: dict = {}
    tape = protocol.EventTape()
    mode = "one-shot" if one_shot else "session"

    try:
        if one_shot:
            listing = protocol.run_json(invocation, ["device", "list"], context="device list")
            device_id = _choose_device(listing.get("devices") or [], device_id)
            capability = capabilities.query_one_shot(
                invocation, plan.mode, plan.channels
            )
            device = capability.get("device") or {}
            _check_channels(device, plan.channels)
            resolved = capabilities.resolve(
                capabilities.options_from(capability), plan.frequency_hz, plan.duration_ms, strict
            )
            plan.frequency_hz = resolved["frequencyHz"]
            plan.duration_ms = resolved["durationMs"]
            config = _write_config(invocation, plan, staged["vendor_out"], staged["control"])
            args = ["capture", "validate"] + plan.cli_args(staged["vendor_out"], config)
            validate = protocol.run_json(invocation, args, context="capture validate")
            run_args = (["capture", "run", "--device-id", device_id]
                        + plan.cli_args(staged["vendor_out"], config))
            tape, _tail = protocol.run_events(
                invocation, run_args,
                timeout=_capture_timeout(plan, timeout),
                trigger_timeout=trigger_timeout,
                on_event=on_event, on_prompt=on_prompt,
            )
        else:
            session = protocol.Session(
                invocation, response_timeout=float(max(60, plan.duration_ms / 1000.0 * 2))
            )
            try:
                listing = session.request("device.list")
                device_id = _choose_device(listing.get("devices") or [], device_id)
                connect = session.request("device.connect", {"deviceId": device_id})
                device = connect.get("device") or {}
                _check_channels(device, plan.channels)
                capability = capabilities.query_session(session, plan.mode, plan.channels)
                resolved = capabilities.resolve(
                    capabilities.options_from(capability),
                    plan.frequency_hz, plan.duration_ms, strict,
                )
                plan.frequency_hz = resolved["frequencyHz"]
                plan.duration_ms = resolved["durationMs"]
                params = plan.params(staged["vendor_out"])
                validate = session.request("capture.validate", params)
                tape, accepted = session.capture(
                    params, trigger_timeout=trigger_timeout,
                    on_prompt=on_prompt, on_event=on_event,
                    timeout=_capture_timeout(plan, timeout),
                )
                status = session.status()
                if status.get("state") not in (None, "idle"):
                    raise SkillError(
                        "device_busy",
                        f"capture state is {status.get('state')} after the run",
                        ["wait for idle or reconnect the device"],
                        retryable=True,
                    )
            finally:
                session.close()
    except SkillError as error:
        tape.error = tape.error or {"error": error.to_dict()["error"]}
        _salvage(invocation, staged, error)
        _cleanup(staged, keep_stage)
        raise

    directory, vendor_directory = _publicate(invocation, staged, tape.directory())
    capture = _read_meta(directory)
    elapsed = time.monotonic() - started

    request_record = {
        "requested": plan.describe(),
        "deviceId": device_id,
        "device": device,
        "resolved": {k: resolved[k] for k in ("frequencyHz", "durationMs", "rle", "samplingDepth")},
        "adjustments": resolved["adjustments"],
        "validate": {k: v for k, v in validate.items() if k not in ("_stderr_tail", "_exit_code")},
        "transport": mode,
        "vendorDirectory": str(vendor_directory),
        "finishedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    try:
        (directory / "request.json").write_text(
            json.dumps(request_record, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass

    channels = decode.analyse_capture(
        capture, directory,
        glitch_bits=int(glitch_ns * plan.frequency_hz / 1e9) if glitch_ns else 0,
    )["channels"] if analyze else []

    summary = {
        "directory": str(directory),
        "vendorDirectory": str(vendor_directory),
        "staged": staged["staged"],
        "captureId": capture.get("captureId"),
        "status": capture.get("status"),
        "mode": capture.get("mode") or plan.mode,
        "frequencyHz": capture.get("frequencyHz") or plan.frequency_hz,
        "durationMs": capture.get("durationMs") or plan.duration_ms,
        "thresholdVolts": capture.get("thresholdVolts"),
        "triggerPositionPercent": capture.get("triggerPositionPercent"),
        "rle": bool(capture.get("rle")),
        "samplingDepth": resolved.get("samplingDepth"),
        "format": capture.get("format") or plan.format,
        "device": capture.get("device") or device,
        "channels": _channel_view(capture),
        "atkdl": capture.get("atkdl"),
        "bin": capture.get("bin") or [],
        "actualStopMode": capture.get("actualStopMode"),
        "startedAt": capture.get("startedAt"),
        "finishedAt": capture.get("finishedAt"),
    }
    if channels:
        summary["analysis"] = channels
    _cleanup(staged, keep_stage)

    return {
        "capture": summary,
        "requested": plan.describe(),
        "adjustments": resolved["adjustments"],
        "timing": {
            "seconds": round(elapsed, 2),
            "deviceSeconds": _device_seconds(capture),
        },
        "events": tape.summary(),
        "transport": mode,
    }


def _device_seconds(capture: dict) -> float | None:
    try:
        from datetime import datetime

        start = datetime.fromisoformat(str(capture["startedAt"]))
        end = datetime.fromisoformat(str(capture["finishedAt"]))
    except (KeyError, ValueError):
        return None
    return round((end - start).total_seconds(), 3)
