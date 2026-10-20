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


VENV_SKIP_COMMANDS = {"setup", "test"}


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")


def venv_reexec_argv(argv: list[str], env_var: str = "PSU_NO_REEXEC") -> list[str] | None:
    """Return the exec argument list when the skill venv should run this call.

    The CLI needs pyvisa/pyusb, which a bare `python3 psu.py ...` does not
    have. Running the skill venv keeps one interpreter for every command, like
    `dap.py`. `setup` and `test` stay on the active interpreter: setup creates
    the venv, test already resolves it. Returns None when no re-exec is needed.
    """
    if os.environ.get(env_var) == "1":
        return None
    py = venv_python()
    if not py.exists():
        return None
    try:
        if Path(sys.executable).resolve() == py.resolve():
            return None
    except OSError:
        pass
    if len(argv) > 1 and argv[1] in VENV_SKIP_COMMANDS:
        return None
    return [str(py), str(Path(argv[0]).resolve())] + list(argv[1:])


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
