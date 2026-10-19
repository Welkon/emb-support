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


def block_bounds(data: bytes) -> tuple[int, int] | None:
    """Return (header_start, payload_end) for a definite-length block, or None.

    Instruments may prefix the block with a command echo (LeCroy: "C1:WF DAT2,#9...").
    """
    start = data.find(b"#")
    if start < 0 or len(data) < start + 2:
        return None
    nd = data[start + 1:start + 2]
    if not nd.isdigit():
        return None
    ndigits = int(nd)
    if ndigits == 0:
        return None
    if len(data) < start + 2 + ndigits:
        return None
    try:
        length = int(data[start + 2:start + 2 + ndigits])
    except ValueError:
        return None
    end = start + 2 + ndigits + length
    return (start, end) if len(data) >= end else None


def parse_block(data: bytes) -> bytes:
    """Strip an IEEE-488.2 block header (prefix and indefinite #0 tolerated)."""
    start = data.find(b"#")
    if start >= 0 and data[start + 1:start + 2] == b"0":
        return data[start + 2:]
    bounds = block_bounds(data)
    if bounds is None:
        return data
    start, end = bounds
    ndigits = int(data[start + 1:start + 2])
    return data[start + 2 + ndigits:end]


def is_block(data: bytes) -> bool:
    return block_bounds(data) is not None


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
