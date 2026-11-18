"""Read an ATKDL project: the container the GUI saves.

An ATKDL is a zip of per-channel bit-packed chunks plus two INI files:

    set.ini            session settings; CLI captures add explicit base units
    0/channel.ini      per channel: name, id, valid sample count, ...
    0/0-0.bin ...      consecutive chunks of channel 0, 1 MiB each (padded)

The chunk padding is why ``channel.ini`` matters: the last chunk is filled to a
whole mebibyte, so a decoder that trusts the file size keeps zeros from the pad.
``extract`` concatenates the chunks of the channels that were asked for and
passes the real sample count on, so the rest of the skill can treat a GUI
project exactly like a CLI capture.
"""

from __future__ import annotations

import configparser
import json
import re
import zipfile
from pathlib import Path

from .common import TRIGGER_CODES, SkillError

CHUNK = re.compile(r"^(?P<channel>\d+)-(?P<index>\d+)\.bin$")


def looks_like_atkdl(path: str | Path) -> bool:
    candidate = Path(path)
    if candidate.suffix.lower() == ".atkdl":
        return True
    if not candidate.is_file():
        return False
    try:
        return zipfile.is_zipfile(candidate)
    except OSError:
        return False


def _ini(text: str) -> configparser.ConfigParser:
    """Parse either a sectioned (GUI) or a headerless (CLI) set.ini."""
    def build() -> configparser.ConfigParser:
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.optionxform = str  # keys are case-sensitive in these files
        return parser

    parser = build()
    try:
        parser.read_string(text)
        return parser
    except configparser.Error:
        pass
    parser = build()
    try:
        parser.read_string("[root]\n" + text)
    except configparser.Error:
        pass
    return parser


def _json_value(parser: configparser.ConfigParser, section: str, key: str):
    for candidate in (section, parser.default_section):
        try:
            raw = parser.get(candidate, key)
        except (configparser.NoSectionError, configparser.NoOptionError):
            continue
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return None


def _decoders(settings, section: str) -> list[dict]:
    """The GUI stores decoder *configuration*, not decoded rows.

    ``decodeJson`` holds the protocol, its input channel(s), options and the
    annotation classes it would show. The results themselves live in the GUI
    session or an exported CSV; a project file does not carry them.
    """
    raw = _json_value(settings, section, "decodeJson")
    if not isinstance(raw, list):
        return []
    decoders = []
    for entry in raw:
        blob = (entry or {}).get("decodeJson") or {}
        outer = blob.get("main") or {}
        for key, spec in blob.items():
            if key == "main" or not isinstance(spec, dict):
                continue
            main = spec.get("main") or {}
            decoders.append(
                {
                    "protocol": main.get("name") or spec.get("main", {}).get("id") or key,
                    "channels": outer.get("channelList") or [],
                    "options": {
                        option.get("id"): option.get("value")
                        for option in spec.get("options") or []
                        if isinstance(option, dict)
                    },
                    "annotationRows": [
                        row.get("desc") for row in spec.get("annotation_rows") or []
                    ],
                    "decodeId": outer.get("decodeID"),
                }
            )
    return decoders


def _gui_settings(settings, section: str, vernier_text: str = "") -> dict:
    """Acquisition-side settings that only the GUI knows about."""
    data = _json_value(settings, section, "settingData")
    data = data if isinstance(data, dict) else {}
    stage = _json_value(settings, section, "stageTriggerData")
    stage = stage if isinstance(stage, dict) else {}
    configured_stages = 0
    for entry in stage.get("trigger") or []:
        if not isinstance(entry, dict):
            continue
        patterns = str(entry.get("stageOne") or "") + str(entry.get("stageOne32") or "")
        if patterns.strip("Xx"):
            configured_stages += 1
    serial = _json_value(settings, section, "serialTriggerData")
    serial = serial if isinstance(serial, dict) else {}
    pwm = _json_value(settings, section, "pwmData")
    pwm = pwm if isinstance(pwm, list) else []
    glitch = _json_value(settings, section, "glitchRemoval")
    cursors = []
    for line in vernier_text.splitlines():
        name = line.split(",", 1)[0].strip()
        if name and name.lower() != "trigger":
            cursors.append(name)
    return {
        "rolling": bool(data.get("isRollingMode")),
        "bufferMode": bool(data.get("isBuffer")),
        "rle": bool(data.get("RLE")),
        "triggerPositionIndex": data.get("triggerPosition"),
        "stageTriggerLevels": configured_stages,
        "serialTrigger": bool(
            str(serial.get("startCondition") or "").strip("Xx")
            or str(serial.get("stopCondition") or "").strip("Xx")
        ),
        "pwmOutputs": [
            {"hz": item.get("hz"), "duty": item.get("duty"), "open": bool(item.get("open"))}
            for item in pwm if isinstance(item, dict)
        ],
        "glitchRemoval": glitch if isinstance(glitch, list) else [],
        "cursors": cursors,
    }


def _channel_sample_count(archive: zipfile.ZipFile, channel: int) -> int | None:
    """The stored sample count from channel.ini.

    Line 3 is the sample count (line 2 is a small per-channel number, not a
    length), so read that line and ignore the others.
    """
    name = f"{channel}/channel.ini"
    try:
        text = archive.read(name).decode("utf-8", "replace")
    except KeyError:
        return None
    lines = [line.strip() for line in text.splitlines()]
    if len(lines) >= 3 and lines[2].isdigit():
        value = int(lines[2])
        if value > 0:
            return value
    return None


def inspect(path: str | Path) -> dict:
    """Metadata of an ATKDL project, in the shape ``read`` reports."""
    source = Path(path)
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as exc:
        raise SkillError(
            "invalid_atkdl",
            f"{source} is not a readable ATKDL project: {exc}",
        )
    with archive:
        names = archive.namelist()
        if "set.ini" not in names:
            raise SkillError(
                "invalid_atkdl",
                f"{source} has no set.ini; this is not an ATK DL project",
            )
        settings = _ini(archive.read("set.ini").decode("utf-8", "replace"))
        section = next(iter(settings.sections()), "DEFAULT")

        def setting(key):
            return _json_value(settings, section, key)

        setting_data = setting("settingData") or {}
        if not isinstance(setting_data, dict):
            setting_data = {}
        channel_set = setting("channelsSet") or []
        try:
            vernier_text = archive.read("vernier.ini").decode("utf-8", "replace")
        except KeyError:
            vernier_text = ""

        frequency = setting("SamplingFrequencyHz") or setting_data.get("setHz")
        duration = setting("SamplingTimeMs") or setting_data.get("setTime")
        depth = setting("SamplingDepth")
        threshold = setting("ThresholdVolts")
        if threshold is None:
            threshold = setting_data.get("thresholdLevel")
        position = setting("TriggerPositionPercent")
        mode = setting("CaptureMode")
        if not mode:
            mode = "buffer" if setting_data.get("isBuffer") else "stream"

        chunks: dict[int, list[str]] = {}
        for name in names:
            parts = name.split("/")
            if len(parts) != 2 or not parts[0].isdigit():
                continue
            match = CHUNK.match(parts[1])
            if not match:
                continue
            # The channel id comes from the directory. A CLI capture names its
            # chunk files after the capture's first channel, so `1/0-0.bin` is
            # channel 1, not channel 0.
            channel = int(parts[0])
            chunks.setdefault(channel, []).append(name)
        for channel, entries in chunks.items():
            entries.sort(key=lambda name: int(CHUNK.match(name.split("/")[1]).group("index")))

        enabled = {
            int(channel["id"]): str(TRIGGER_CODES.get(str(channel.get("triggerType")), "none"))
            for channel in channel_set
            if isinstance(channel, dict) and channel.get("enable")
        }
        channels = []
        for channel in sorted(chunks):
            if enabled is not None and channel_set and channel not in enabled:
                continue
            stored = sum(archive.getinfo(name).file_size for name in chunks[channel])
            limits = [stored * 8]
            sample_count = _channel_sample_count(archive, channel)
            if sample_count:
                limits.append(sample_count)
            if depth:
                limits.append(int(depth))
            bits = min(limits)
            channels.append(
                {
                    "id": channel,
                    "trigger": enabled.get(channel, "none"),
                    "bits": bits,
                    "storedBits": stored * 8,
                    "chunks": len(chunks[channel]),
                    "files": chunks[channel],
                }
            )

    return {
        "source": str(source),
        "kind": "atkdl",
        "decoders": _decoders(settings, section),
        "gui": _gui_settings(settings, section, vernier_text),
        "sessionName": setting("SessionName"),
        "mode": mode,
        "frequencyHz": int(frequency) if frequency else None,
        "durationMs": int(duration) if duration else None,
        "thresholdVolts": float(threshold) if threshold is not None else None,
        "triggerPositionPercent": position,
        "rle": bool(setting_data.get("RLE")),
        "channels": channels,
        "native": {
            "settingData": setting_data,
            "hasChannelsSet": bool(channel_set),
        },
    }


def extract(path: str | Path, directory: str | Path, channels: list[int] | None = None) -> dict:
    """Write ``channel_<id>.bin`` for the requested channels and describe them."""
    source = Path(path)
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    info = inspect(source)
    wanted = set(channels) if channels else {channel["id"] for channel in info["channels"]}
    written = []
    with zipfile.ZipFile(source) as archive:
        for channel in info["channels"]:
            if channel["id"] not in wanted:
                continue
            destination = target / f"channel_{channel['id']}.bin"
            with destination.open("wb") as sink:
                for name in channel["files"]:
                    sink.write(archive.read(name))
            written.append(
                {
                    "channel": channel["id"],
                    "trigger": channel["trigger"],
                    "file": str(destination),
                    "validBits": int(channel["bits"]),
                    "bytes": destination.stat().st_size,
                    "storedBits": channel["storedBits"],
                }
            )
    if not written:
        raise SkillError(
            "channel_not_in_capture",
            f"channels {sorted(wanted)} are not in {source}",
            [f"channels in the project: {sorted(c['id'] for c in info['channels'])}"],
        )
    return {"info": info, "channels": written, "directory": str(target)}
