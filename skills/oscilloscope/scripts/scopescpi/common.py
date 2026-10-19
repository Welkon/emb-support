"""Shared configuration, output helpers and framing primitives."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

HOME = Path(os.environ.get("SCOPE_HOME", str(Path.home() / ".local/share/scope"))).expanduser()
CONFIG = HOME / "config.json"
VENV = HOME / "venv"
IS_WIN = os.name == "nt"


# --------------------------------------------------------------------- helpers

def die(msg: str, code: int = 2) -> None:
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False), file=sys.stderr)
    sys.exit(code)


def emit(data, human: str | None = None, as_json: bool = False) -> None:
    if as_json or human is None:
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    else:
        print(human)


def load_config() -> dict:
    try:
        return json.loads(CONFIG.read_text())
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=2))


def parse_block(data: bytes) -> bytes:
    """Strip an IEEE-488.2 definite-length block header."""
    if not data:
        return data
    if not data.startswith(b"#"):
        return data
    if len(data) < 2 or not data[1:2].isdigit():
        return data
    ndigits = int(data[1:2])
    if ndigits == 0:
        return data[2:]
    if len(data) < 2 + ndigits:
        return data
    try:
        length = int(data[2:2 + ndigits])
    except ValueError:
        return data
    return data[2 + ndigits:2 + ndigits + length]


def is_block(data: bytes) -> bool:
    return data.startswith(b"#") and len(data) > 2 and data[1:2].isdigit()


# ------------------------------------------------------------------ transports


def fnum(x: float) -> str:
    return f"{x:.10g}"


def _parse_scaled(text: str) -> float:
    m = re.match(r"\s*(-?[0-9.]+)\s*([munp]?)([VAs%])", str(text))
    if not m:
        try:
            return float(text)
        except (TypeError, ValueError):
            return 1.0
    mult = {"": 1, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12}
    return float(m.group(1)) * mult.get(m.group(2), 1)


def _parse_rate(text: str) -> float:
    m = re.search(r"([0-9.]+)\s*([kKmMgG]?)(?:S/s|Sa/s|Hz)", str(text))
    if not m:
        return 0.0
    mult = {"": 1, "k": 1e3, "K": 1e3, "m": 1e6, "M": 1e6, "g": 1e9, "G": 1e9}
    return float(m.group(1)) * mult.get(m.group(2), 1)
