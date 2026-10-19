"""Shared configuration and output helpers."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HOME = Path(os.environ.get("PSU_HOME", str(Path.home() / ".local/share/psu"))).expanduser()
CONFIG = HOME / "config.json"
VENV = HOME / "venv"
IS_WIN = os.name == "nt"

DEFAULT_MAX_VOLTAGE = 30.0
DEFAULT_MAX_CURRENT = 5.0


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


def fnum(value: float) -> str:
    return f"{value:.6g}"
