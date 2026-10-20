"""Shared configuration and output helpers."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

SKILL_NAME = "psu"


def data_home(env: str = "PSU_HOME") -> Path:
    """Resolve the state directory without reaching outside the project.

    An explicit environment variable wins. Otherwise prefer a home inside the
    project (`.emb-agent/bench/psu`) when the project has a `.emb-agent` marker:
    a sandbox that only allows writes under the workspace can then run the
    skill, including its venv, without an approval prompt. An existing legacy
    `~/.local/share/psu` keeps being used so no setup is stranded.
    """
    value = os.environ.get(env)
    if value:
        return Path(value).expanduser()
    legacy = Path.home() / ".local/share" / SKILL_NAME
    project = Path.cwd() / ".emb-agent" / "bench" / SKILL_NAME
    if project.exists():
        return project
    if (Path.cwd() / ".emb-agent").is_dir() and not legacy.exists():
        return project
    return legacy


HOME = data_home()
CONFIG = HOME / "config.json"
VENV = HOME / "venv"
IS_WIN = os.name == "nt"

# The DP100 path is hidapi-only. Skip the venv exec when `hid` is importable.
REQUIRED_MODULES = ("hid",)

DEFAULT_MAX_VOLTAGE = 30.0
DEFAULT_MAX_CURRENT = 5.0


def die(msg: str, code: int = 2) -> None:
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False), file=sys.stderr)
    sys.exit(code)


VENV_SKIP_COMMANDS = {"setup", "test"}


def missing_runtime_modules() -> list[str]:
    """Runtime modules the current interpreter cannot import."""
    missing = []
    for name in REQUIRED_MODULES:
        try:
            if importlib.util.find_spec(name) is None:
                missing.append(name)
        except (ImportError, ValueError):
            missing.append(name)
    return missing


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")


def venv_reexec_argv(argv: list[str], env_var: str = "PSU_NO_REEXEC") -> list[str] | None:
    """Return the exec argument list when the skill venv should run this call.

    Only when the active interpreter lacks a runtime module: if `hid` is
    already importable, running the call in place is both faster and avoids
    executing a binary outside the project, which some sandboxes require an
    approval for. `setup` and `test` stay on the active interpreter: setup
    creates the venv, test already resolves it. Returns None when no re-exec is
    needed.
    """
    if os.environ.get(env_var) == "1":
        return None
    if not missing_runtime_modules():
        return None
    py = venv_python()
    if not py.exists():
        return None
    try:
        # Compare the venv prefix, not the executable: `venv/bin/python` is a
        # symlink to the base interpreter, so both resolve to the same file and
        # an executable comparison would always claim we are already inside.
        if Path(sys.prefix).resolve() == VENV.resolve():
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
