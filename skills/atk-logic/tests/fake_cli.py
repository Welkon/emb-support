#!/usr/bin/env python3
"""A stand-in for ``atk-logic-cli.exe`` so the skill can be tested without a device.

It speaks both shapes the real program does:

* one-shot commands with ``--json`` (``device list``, ``capture run``, ...)
* ``session --stdio --mode ai`` JSONL requests and events

Environment knobs used by the tests:

* ``FAKE_TRIGGER=never``  - the capture waits for a trigger forever (silence)
* ``FAKE_ERROR=code``     - control commands answer ``ok:false`` with that code
* ``FAKE_PROGRESS_SPAM``  - repeat ``output.progress`` like an ATKDL export does
* ``FAKE_DEVICES=2``      - enumerate more than one analyzer
* ``FAKE_ARGV_LOG=file``  - append every invocation's argv, for assertions
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

CLI_VERSION = "9.9.9-fake"

DEVICE = {
    "bootloader": False,
    "channelCount": 16,
    "channelOffset": 0,
    "connected": True,
    "deviceId": "dl16:1",
    "fpgaVersion": 1,
    "hardwareVersion": 1,
    "level": 1,
    "mcuVersion": 1,
    "model": "DL16",
    "port": 1,
    "profileComplete": True,
    "series": 1,
    "usbSpeed": 3,
}

FREQUENCIES = {
    1_000_000: [1, 10, 100, 1000],
    2_000_000: [1, 10, 100],
    500_000: [1, 10, 100, 1000, 5000],
}


def devices() -> list[dict]:
    count = int(os.environ.get("FAKE_DEVICES", "1"))
    listed = []
    for index in range(1, count + 1):
        device = dict(DEVICE)
        device.update({"deviceId": f"dl16:{index}", "port": index, "connected": False})
        listed.append(device)
    return listed


def choose_device(device_id: str | None) -> dict:
    listed = devices()
    if not device_id:
        return listed[0] if len(listed) == 1 else {}
    for device in listed:
        if device["deviceId"] == device_id:
            return device
    return {}


def error(code: str, message: str) -> dict:
    return {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
            "retryable": False,
            "suggestions": ["fake suggestion"],
        },
    }


def capabilities(mode: str, channels: list[dict]) -> dict:
    enabled = max(1, len(channels))
    scale = 1 if enabled <= 2 else 2
    options = [
        {
            "frequencyHz": frequency // scale,
            "timings": [{"durationMs": duration, "rle": duration >= 1000}
                        for duration in durations],
        }
        for frequency, durations in FREQUENCIES.items()
    ]
    return {"ok": True, "device": DEVICE, "mode": mode, "options": options}


def write_capture(directory: Path, params: dict) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    channels = params.get("channels") or [{"id": 0, "trigger": "none"}]
    bits = int(params["frequencyHz"]) * int(params["durationMs"]) // 1000
    bins = []
    for channel in channels:
        identifier = int(channel["id"])
        values = [(index // 5) % 2 for index in range(bits)]
        payload = bytearray((bits + 7) // 8)
        for index, value in enumerate(values):
            if value:
                payload[index // 8] |= 1 << (index % 8)
        name = f"channel_{identifier}.bin"
        (directory / name).write_bytes(bytes(payload))
        bins.append(
            {
                "bytes": len(payload),
                "channel": identifier,
                "file": str(directory / name),
                "validBits": bits,
            }
        )
    meta = {
        "actualStopMode": "natural",
        "bin": bins,
        "captureId": "capture-fake",
        "channels": [
            {"id": int(c["id"]), "trigger": str(c["trigger"])} for c in channels
        ],
        "device": DEVICE,
        "durationMs": params["durationMs"],
        "finishedAt": "2026-01-01T00:00:01.000",
        "format": params.get("format", "bin"),
        "frequencyHz": params["frequencyHz"],
        "mode": params.get("mode", "buffer"),
        "requestedStopMode": "none",
        "rle": bool(params.get("rle")),
        "startedAt": "2026-01-01T00:00:00.000",
        "status": "complete",
        "thresholdVolts": params.get("thresholdVolts", 1.8),
        "triggerPositionPercent": params.get("triggerPositionPercent", 50),
    }
    (directory / "capture.json").write_text(json.dumps(meta, indent=4), encoding="utf-8")
    return meta


def _params_from_flags(argv: list[str]) -> dict:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--mode", default="buffer")
    parser.add_argument("--frequency", type=int, default=1_000_000)
    parser.add_argument("--time", type=int, default=10)
    parser.add_argument("--threshold", type=float, default=1.8)
    parser.add_argument("--trigger-position", type=float, default=50)
    parser.add_argument("--channel", action="append", default=[])
    parser.add_argument("--format", default="bin")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--config", default=None)
    parser.add_argument("--json", action="store_true")
    known, _ = parser.parse_known_args(argv)
    channels = []
    for spec in known.channel:
        head, _, tail = spec.partition(":")
        channels.append({"id": int(head), "trigger": tail or "none"})
    if known.config:
        config = json.loads(Path(known.config).read_text(encoding="utf-8"))
        config.update(
            {
                "mode": known.mode,
                "frequencyHz": known.frequency,
                "durationMs": known.time,
                "thresholdVolts": known.threshold,
                "triggerPositionPercent": known.trigger_position,
                "channels": channels or config.get("channels"),
                "format": known.format,
            }
        )
        return config
    return {
        "mode": known.mode,
        "frequencyHz": known.frequency,
        "durationMs": known.time,
        "thresholdVolts": known.threshold,
        "triggerPositionPercent": known.trigger_position,
        "channels": channels,
        "format": known.format,
        "outputDirectory": known.output_dir,
    }


def emit(obj: dict) -> None:
    print(json.dumps(obj), flush=True)


def run_capture(params: dict, emit_event=emit, pause_before_finish: float = 0.0) -> dict:
    root = Path(str(params.get("outputDirectory") or Path.cwd() / "capture"))
    stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{os.getpid()}"
    directory = root / stamp
    capture_id = "capture-fake"
    emit_event({"captureId": capture_id, "directory": str(directory),
                "event": "capture.started", "rle": False})
    trigger = (params.get("channels") or [{"trigger": "none"}])[0].get("trigger")
    if trigger not in ("none", "high", "low") and os.environ.get("FAKE_TRIGGER") == "never":
        # The real device fills the buffer to the trigger position, then waits.
        emit_event({"captureId": capture_id, "event": "capture.progress",
                    "percent": 50, "state": 1})
        return {}
    emit_event({"captureId": capture_id, "event": "capture.progress", "percent": 100, "state": 1})
    if os.environ.get("FAKE_PROGRESS_SPAM"):
        for _ in range(500):
            emit_event({"captureId": capture_id, "event": "output.progress",
                        "format": "atkdl", "percent": 95, "state": 1})
    if pause_before_finish:
        time.sleep(pause_before_finish)
    meta = write_capture(directory, params)
    emit_event({"captureId": capture_id, "directory": str(directory),
                "event": "capture.finished"})
    emit_event({"captureId": capture_id, "event": "idle"})
    return meta


def one_shot(argv: list[str]) -> int:
    if "--version" in argv:
        print(CLI_VERSION)
        return 0
    command = argv[0]
    force = os.environ.get("FAKE_ERROR")
    if command == "device":
        sub = argv[1]
        if force:
            print(json.dumps(error(force, "fake failure")))
            return 4
        if sub == "list":
            print(json.dumps({"ok": True, "devices": devices()}))
            return 0
        if sub == "connect":
            parser = argparse.ArgumentParser(add_help=False)
            parser.add_argument("--device-id", default=None)
            known, _ = parser.parse_known_args(argv[2:])
            listed = devices()
            if not known.device_id and len(listed) > 1:
                print(json.dumps(error("multiple_devices", "several analyzers")))
                return 4
            chosen = choose_device(known.device_id)
            if not chosen:
                print(json.dumps(error("device_not_found", "no such analyzer")))
                return 4
            print(json.dumps({"ok": True, "device": DEVICE}))
            return 0
        if sub == "status":
            print(json.dumps({"ok": True, "connected": True, "device": DEVICE,
                              "state": "idle"}))
            return 0
        if sub == "capabilities":
            parser = argparse.ArgumentParser(add_help=False)
            parser.add_argument("--mode", default="buffer")
            parser.add_argument("--channels", default="0")
            parser.add_argument("--frequency", type=int)
            parser.add_argument("--time", type=int)
            known, _ = parser.parse_known_args(argv[2:])
            channels = [{"id": int(part)} for part in known.channels.split(",") if part]
            print(json.dumps(capabilities(known.mode, channels)))
            return 0
        print(json.dumps(error("invalid_arguments", f"unknown device command {sub}")))
        return 4
    if command == "capture":
        sub = argv[1]
        params = _params_from_flags(argv[2:])
        if sub == "validate":
            output = params.get("outputDirectory") or str(Path.cwd() / "capture")
            depth = int(params["frequencyHz"]) * int(params["durationMs"]) // 1000
            print(json.dumps({"ok": True, "captureDirectory": output,
                              "durationMs": params["durationMs"],
                              "frequencyHz": params["frequencyHz"],
                              "mode": params["mode"], "rle": False,
                              "samplingDepth": depth}))
            return 0
        if sub == "run":
            meta = run_capture(params)
            if not meta:
                # The real CLI keeps waiting; the skill's timeout ends it.
                while True:
                    time.sleep(1)
            return 0
        print(json.dumps(error("invalid_arguments", f"unknown capture command {sub}")))
        return 4
    print(json.dumps(error("invalid_arguments", f"unknown command {command}")))
    return 4


def session() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}
        if method == "session.close":
            emit({"id": request_id, "ok": True, "state": "closing"})
            return 0
        force = os.environ.get("FAKE_ERROR")
        if force and method in ("device.connect", "capture.run", "capture.validate"):
            emit({"id": request_id, "ok": False,
                  "error": {"code": force, "message": "fake failure",
                            "retryable": False, "suggestions": []}})
            continue
        if method == "device.list":
            emit({"id": request_id, "ok": True, "devices": devices()})
        elif method == "device.connect":
            listed = devices()
            if not params.get("deviceId") and len(listed) > 1:
                emit({"id": request_id, "ok": False,
                      "error": {"code": "multiple_devices", "message": "several analyzers",
                                "retryable": False, "suggestions": []}})
            elif choose_device(params.get("deviceId")):
                emit({"id": request_id, "ok": True, "device": DEVICE})
            else:
                emit({"id": request_id, "ok": False,
                      "error": {"code": "device_not_found", "message": "no such analyzer",
                                "retryable": True, "suggestions": []}})
        elif method == "device.status":
            emit({"id": request_id, "ok": True, "connected": True, "device": DEVICE})
        elif method == "device.disconnect":
            emit({"id": request_id, "ok": True})
        elif method == "device.capabilities":
            answer = capabilities(params.get("mode", "buffer"), params.get("channels") or [])
            answer["id"] = request_id
            emit(answer)
        elif method == "capture.validate":
            depth = int(params["frequencyHz"]) * int(params["durationMs"]) // 1000
            answer = dict(params)
            answer.update({"id": request_id, "ok": True, "captureDirectory":
                           params.get("outputDirectory"), "samplingDepth": depth})
            emit(answer)
        elif method == "capture.run":
            emit({"id": request_id, "ok": True, "accepted": True, "captureId": "capture-fake"})
            meta = run_capture(params)
            if not meta:
                # Silence: the trigger never fired. Wait for capture.stop.
                continue
        elif method == "capture.status":
            emit({"id": request_id, "ok": True, "state": "idle"})
        elif method == "capture.stop":
            emit({"id": request_id, "ok": True, "state": "stopping"})
            emit({"captureId": "capture-fake", "event": "capture.finished"})
            emit({"captureId": "capture-fake", "event": "idle"})
        else:
            emit({"id": request_id, "ok": False,
                  "error": {"code": "invalid_config", "message": method,
                            "retryable": False, "suggestions": []}})
    return 0


def main(argv: list[str]) -> int:
    log = os.environ.get("FAKE_ARGV_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(argv) + "\n")
    if argv and argv[0] == "session":
        return session()
    return one_shot(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
