"""Shared configuration, output helpers and framing primitives."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

SKILL_NAME = "scope"


def data_home(env: str = "SCOPE_HOME") -> Path:
    """Resolve the state directory without reaching outside the project.

    An explicit environment variable wins. Otherwise prefer a home inside the
    project (`.emb-agent/bench/scope`) when the project has a `.emb-agent`
    marker: a sandbox that only allows writes under the workspace can then run
    the skill, including its venv, without an approval prompt. An existing
    legacy `~/.local/share/scope` keeps being used so no setup is stranded.
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

# Modules the CLI cannot run without. When the active interpreter already has
# them there is no reason to exec another binary: on a locked-down host that
# exec is exactly what turns every command into an approval prompt.
REQUIRED_MODULES = ("pyvisa",)


# --------------------------------------------------------------------- helpers

def die(msg: str, code: int = 2) -> None:
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False), file=sys.stderr)
    sys.exit(code)


VENV_SKIP_COMMANDS = {"setup", "test"}


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")


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


def venv_reexec_argv(argv: list[str], env_var: str = "SCOPE_NO_REEXEC") -> list[str] | None:
    """Return the exec argument list when the skill venv should run this call.

    Only when the active interpreter lacks a runtime module: if `pyvisa` is
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
