"""Units, parsing, formatting, errors and the one result shape.

The vendor CLI speaks base units only (Hz, ms, V, percent) and never guesses.
The skill accepts bench shorthand (``10m``, ``500us``, ``1.8v``) and records
what it did with it, so a capture stays reproducible.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from typing import Any

TRIGGERS = ("none", "rising", "high", "falling", "low", "both")

# capture.json stores the trigger as the device enum, not as the protocol name.
TRIGGER_CODES = {
    "0": "none",
    "1": "rising",
    "2": "high",
    "3": "falling",
    "4": "low",
    "5": "both",
}

MODES = ("buffer", "stream")
FORMATS = ("bin", "atkdl", "both")

_HZ = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([kmg]?)(?:hz)?\s*$", re.IGNORECASE)
_MS = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*(s|ms|us|ns)?\s*$", re.IGNORECASE)
_V = re.compile(r"^\s*([-+]?[0-9]*\.?[0-9]+)\s*(mv|v)?\s*$", re.IGNORECASE)


class SkillError(Exception):
    """A failure the caller can act on. ``code`` mirrors the vendor's codes."""

    def __init__(
        self,
        code: str,
        message: str,
        suggestions: list[str] | None = None,
        retryable: bool = False,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.suggestions = suggestions or []
        self.retryable = retryable
        self.details = details or {}

    def to_dict(self) -> dict:
        out: dict[str, Any] = {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
                "suggestions": self.suggestions,
            },
        }
        if self.details:
            out["error"]["details"] = self.details
        return out


def vendor_error(obj: dict, context: str = "") -> SkillError:
    """Turn ``{"ok": false, "error": {...}}`` from the CLI into a SkillError."""
    err = obj.get("error") or {}
    code = str(err.get("code") or "vendor_error")
    message = str(err.get("message") or "the ATK CLI reported failure")
    if context:
        message = f"{context}: {message}"
    return SkillError(
        code,
        message,
        suggestions=[str(s) for s in err.get("suggestions") or []],
        retryable=bool(err.get("retryable")),
        details={
            k: err[k] for k in ("nativeCode", "nativeMessage") if k in err
        },
    )


# --------------------------------------------------------------- parsing

def parse_frequency(text: str | int) -> int:
    """``1m``/``2.5MHz``/``1000000`` -> Hz (int)."""
    if isinstance(text, int):
        return text
    match = _HZ.match(str(text))
    if not match:
        raise SkillError(
            "invalid_arguments",
            f"cannot read a frequency from {text!r}",
            ["write Hz or a suffix: 1000000, 1m, 2.5MHz, 100k"],
        )
    value = float(match.group(1)) * {"": 1, "k": 1e3, "m": 1e6, "g": 1e9}[
        match.group(2).lower()
    ]
    hz = int(round(value))
    if hz <= 0:
        raise SkillError("invalid_arguments", "frequency must be greater than zero")
    return hz


def parse_duration_ms(text: str | int | float) -> int:
    """``10``/``10ms``/``1s``/``500us`` -> ms (int, rounded up to 1 ms)."""
    if isinstance(text, (int, float)):
        return max(1, int(round(float(text))))
    match = _MS.match(str(text))
    if not match:
        raise SkillError(
            "invalid_arguments",
            f"cannot read a duration from {text!r}",
            ["write ms or a suffix: 10, 10ms, 1s, 500us"],
        )
    value = float(match.group(1))
    unit = (match.group(2) or "ms").lower()
    value *= {"s": 1000.0, "ms": 1.0, "us": 0.001, "ns": 0.000001}[unit]
    return max(1, int(round(value)))


_SECONDS = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*(s|ms|us|ns)?\s*$", re.IGNORECASE)


def parse_seconds(text: str | float) -> float:
    """``0.5``/``500ms``/``1s`` -> seconds (float). Plain numbers are seconds."""
    if isinstance(text, (int, float)):
        return float(text)
    match = _SECONDS.match(str(text))
    if not match:
        raise SkillError(
            "invalid_arguments",
            f"cannot read a time from {text!r}",
            ["write seconds or a suffix: 0.5, 500ms, 1s"],
        )
    value = float(match.group(1))
    unit = (match.group(2) or "s").lower()
    return value * {"s": 1.0, "ms": 0.001, "us": 0.000001, "ns": 0.000000001}[unit]


def parse_volts(text: str | float) -> float:
    """``1.8``/``1.8v``/``1800mv`` -> V, checked against the device range."""
    if isinstance(text, (int, float)):
        value = float(text)
    else:
        match = _V.match(str(text))
        if not match:
            raise SkillError(
                "invalid_arguments",
                f"cannot read a voltage from {text!r}",
                ["write volts: 1.8, 3.3v, 1800mv"],
            )
        value = float(match.group(1))
        if (match.group(2) or "v").lower() == "mv":
            value /= 1000.0
    if not -5.0 <= value <= 5.0:
        raise SkillError(
            "invalid_arguments",
            f"threshold {value} V is outside the device range [-5, 5]",
            ["use a threshold inside [-5, 5] V"],
        )
    return round(value, 4)


def parse_percent(text: str | float) -> float:
    if isinstance(text, (int, float)):
        value = float(text)
    else:
        raw = str(text).strip().rstrip("%").strip()
        try:
            value = float(raw)
        except ValueError:
            raise SkillError(
                "invalid_arguments",
                f"cannot read a trigger position from {text!r}",
                ["write a percentage: 50 or 50%"],
            )
    if not 0.0 <= value <= 100.0:
        raise SkillError(
            "invalid_arguments",
            f"trigger position {value} is outside [0, 100] percent",
        )
    return value


def parse_trigger(text: str) -> str:
    value = str(text).strip().lower()
    if value not in TRIGGERS:
        raise SkillError(
            "invalid_arguments",
            f"unknown trigger {text!r}",
            [f"use one of {', '.join(TRIGGERS)}"],
        )
    return value


def parse_channel_spec(spec: str) -> dict:
    """``0``, ``0:none``, ``3:rising`` -> {"id": int, "trigger": str}."""
    raw = str(spec).strip()
    if not raw:
        raise SkillError("invalid_arguments", "empty channel specification")
    if ":" in raw:
        head, tail = raw.split(":", 1)
    else:
        head, tail = raw, "none"
    try:
        channel = int(head)
    except ValueError:
        raise SkillError(
            "invalid_arguments",
            f"channel id must be an integer, got {head!r}",
            ["pass --ch 0:none or --ch 3:rising"],
        )
    if channel < 0:
        raise SkillError("invalid_arguments", "channel id must be zero or greater")
    return {"id": channel, "trigger": parse_trigger(tail)}


def parse_channels(specs: list[str] | None) -> list[dict]:
    if not specs:
        raise SkillError(
            "invalid_arguments",
            "no channel selected",
            ["pass at least one --ch, for example --ch 0:rising or --ch 0,1,2"],
        )
    channels: list[dict] = []
    seen: set[int] = set()
    for spec in specs:
        # ``--ch 0,1,2`` is the shorthand for three plain channels.
        parts = [p for p in str(spec).replace(" ", "").split(",") if p]
        for part in parts:
            channel = parse_channel_spec(part)
            if channel["id"] in seen:
                raise SkillError(
                    "invalid_arguments",
                    f"channel {channel['id']} is listed twice",
                )
            seen.add(channel["id"])
            channels.append(channel)
    channels.sort(key=lambda c: c["id"])
    return channels


# ------------------------------------------------------------ formatting

def fmt_hz(value: int | float) -> str:
    value = float(value)
    for suffix, scale in (("GHz", 1e9), ("MHz", 1e6), ("kHz", 1e3)):
        if value >= scale:
            scaled = value / scale
            text = f"{scaled:.4f}".rstrip("0").rstrip(".")
            return f"{text} {suffix}"
    return f"{value:.0f} Hz"


def fmt_ms(value: int | float) -> str:
    value = float(value)
    if value >= 1000:
        return f"{value / 1000:.4g} s"
    if value >= 1:
        return f"{value:.4g} ms"
    return f"{value * 1000:.4g} us"


def fmt_bytes(value: int) -> str:
    value = float(value)
    for suffix in ("B", "kB", "MB", "GB"):
        if value < 1024 or suffix == "GB":
            return f"{value:.0f} {suffix}" if suffix == "B" else f"{value:.1f} {suffix}"
        value /= 1024
    return f"{value:.1f} GB"


def fmt_duration_s(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    return f"{seconds:.2f} s"


# ---------------------------------------------------------------- results

@dataclass
class Result:
    values: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def set(self, key: str, value: Any) -> "Result":
        self.values[key] = value
        return self

    def warn(self, message: str) -> "Result":
        self.warnings.append(message)
        return self

    def to_dict(self) -> dict:
        out = {"ok": True}
        out.update(self.values)
        if self.warnings:
            out["warnings"] = list(self.warnings)
        return out


def dump(payload: dict) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))


def note(message: str, quiet: bool = False) -> None:
    """Human progress for the operator; never on stdout as data."""
    if not quiet:
        print(message, file=sys.stderr, flush=True)
