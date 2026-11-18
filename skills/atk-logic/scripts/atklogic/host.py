"""Where the ATK CLI lives, how to call it, and how to cross the WSL boundary.

The vendor ships a Windows console program (``atk-logic-cli.exe``) that talks
to the analyzer through the CYUSB driver. On WSL that program stays on the
Windows side and this skill calls it through interop; the device must therefore
stay attached to Windows, not handed to the distro with ``usbipd attach``.
"""

from __future__ import annotations

import json
import os
import platform
import shlex
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from .common import SkillError

SKILL = "atk-logic"
EXE_NAMES = ("atk-logic-cli.exe", "atk-logic-cli")
DEFAULT_DIRS = (
    Path("/mnt/c/Program Files/ATK-Logic"),
    Path("/mnt/c/Program Files (x86)/ATK-Logic"),
    Path("C:/Program Files/ATK-Logic"),
    Path("C:/Program Files (x86)/ATK-Logic"),
)


def platform_name() -> str:
    if os.name == "nt":
        return "windows"
    if "microsoft" in platform.release().lower() or os.environ.get("WSL_DISTRO_NAME"):
        return "wsl"
    return platform.system().lower() or "linux"


IS_WINDOWS = os.name == "nt"
IS_WSL = platform_name() == "wsl"


# ------------------------------------------------------------------- config

def data_home() -> Path:
    env = os.environ.get("ATK_LOGIC_HOME")
    if env:
        return Path(env).expanduser()
    project = Path.cwd() / ".emb-agent"
    if project.is_dir():
        return project / "bench" / SKILL
    return Path.home() / ".local/share" / SKILL


def config_file() -> Path:
    return data_home() / "config.json"


def load_config() -> dict:
    path = config_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(updates: dict) -> dict:
    data = load_config()
    data.update({k: v for k, v in updates.items() if v is not None})
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return data


# -------------------------------------------------------------- invocation

@dataclass
class Invocation:
    argv: list[str]
    cwd: str
    windows: bool
    source: str
    cli_version: str = ""

    def describe(self) -> dict:
        return {
            "command": " ".join(self.argv),
            "cwd": self.cwd,
            "windows_side": self.windows,
            "source": self.source,
            "version": self.cli_version,
        }


def _command_from(value: str) -> list[str]:
    if value.strip().startswith(("python", "python3", "/")) and " " in value:
        return shlex.split(value)
    return [value]


def _candidate(argv: list[str], windows: bool, source: str) -> Invocation:
    cwd = str(Path.cwd())
    for item in list(argv[1:]) + argv[:1]:
        candidate = Path(item)
        if candidate.is_file():
            cwd = str(candidate.resolve().parent)
            break
    return Invocation(argv=argv, cwd=cwd, windows=windows, source=source)


def resolve_invocation(override: str | None = None) -> Invocation:
    """Find the CLI. ``ATK_LOGIC_CLI`` wins, then the skill config, then install paths."""
    tried: list[str] = []

    explicit = override or os.environ.get("ATK_LOGIC_CLI") or load_config().get("cli")
    if explicit:
        argv = _command_from(str(explicit))
        first = Path(argv[0])
        if not first.exists() and shutil.which(argv[0]) is None:
            raise _cli_not_found(str(explicit), tried)
        return _candidate(argv, first.suffix.lower() == ".exe", "explicit")

    for name in EXE_NAMES:
        found = shutil.which(name)
        if found:
            return _candidate([found], found.lower().endswith(".exe"), "PATH")

    for directory in DEFAULT_DIRS:
        for name in EXE_NAMES:
            candidate = directory / name
            tried.append(str(candidate))
            if candidate.is_file():
                return _candidate([str(candidate)], True, "install directory")

    raise _cli_not_found("atk-logic-cli.exe", tried)


def _cli_not_found(what: str, tried: list[str]) -> SkillError:
    return SkillError(
        "cli_not_found",
        f"cannot find the ATK-Logic CLI ({what})",
        [
            "install ATK-Logic, or set ATK_LOGIC_CLI to the CLI command",
            "on WSL the default is /mnt/c/Program Files/ATK-Logic/atk-logic-cli.exe",
        ],
        details={"tried": tried},
    )


def probe_version(invocation: Invocation, timeout: float = 30.0) -> str:
    if invocation.cli_version:
        return invocation.cli_version
    try:
        completed = subprocess.run(
            invocation.argv + ["--version"],
            cwd=invocation.cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SkillError(
            "cli_not_runnable",
            f"cannot run {invocation.argv[0]}: {exc}",
            ["check ATK_LOGIC_CLI and that the binary exists"],
        )
    lines = [line.strip() for line in (completed.stdout or "").splitlines() if line.strip()]
    invocation.cli_version = lines[-1] if lines else ""
    if completed.returncode != 0 or not invocation.cli_version:
        raise SkillError(
            "cli_not_runnable",
            f"{invocation.argv[0]} --version failed (exit {completed.returncode})",
            ["run the CLI by hand once to see the error"],
        )
    return invocation.cli_version


# ------------------------------------------------------------- path bridge

def is_windows_drive_path(path: Path) -> bool:
    parts = path.resolve().parts
    return len(parts) > 2 and parts[0] == "/" and parts[1] == "mnt" and len(parts[2]) == 1


def to_vendor_path(invocation: Invocation, path: str | Path) -> str:
    """A path the CLI process understands (``C:\\...`` on the Windows side)."""
    text = str(path)
    if not invocation.windows:
        return str(Path(text).resolve())
    if IS_WINDOWS:
        return str(Path(text))
    completed = subprocess.run(
        ["wslpath", "-w", str(Path(text).resolve())],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise SkillError(
            "path_unavailable",
            f"cannot express {text} as a Windows path",
        )
    return completed.stdout.strip()


def from_vendor_path(invocation: Invocation, value: str) -> str:
    """``C:/Users/X/...`` -> ``/mnt/c/Users/X/...`` when running from WSL."""
    if not invocation.windows or IS_WINDOWS:
        return value
    completed = subprocess.run(
        ["wslpath", "-u", value],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return value
    return completed.stdout.strip()


_windows_temp_cache: str | None = None


def windows_temp() -> str:
    global _windows_temp_cache
    if _windows_temp_cache:
        return _windows_temp_cache
    configured = load_config().get("windows_temp")
    if configured:
        _windows_temp_cache = str(configured)
        return _windows_temp_cache
    if IS_WINDOWS:
        _windows_temp_cache = tempfile.gettempdir()
        return _windows_temp_cache
    for command in (["cmd.exe", "/c", "echo", "%TEMP%"],):
        try:
            completed = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=20,
                text=True,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        value = (completed.stdout or "").strip()
        if completed.returncode == 0 and ":" in value and "%" not in value:
            _windows_temp_cache = value
            return value
    return ""


def staging_root(invocation: Invocation) -> Path:
    """A scratch directory inside the CLI's reach.

    On WSL a capture written straight into the Linux filesystem crosses a 9p
    share; that is fine for a short trace and too slow for a large one. Staging
    on the Windows side keeps the acquisition fast, and the result is copied
    back once afterwards.
    """
    configured = os.environ.get("ATK_LOGIC_STAGING") or load_config().get("staging")
    if configured:
        return Path(str(configured)).expanduser()
    if invocation.windows and not IS_WINDOWS:
        temp = windows_temp()
        if temp:
            return Path(from_vendor_path(invocation, temp)) / SKILL
    return Path(tempfile.gettempdir()) / SKILL


def new_staging_dir(invocation: Invocation, stamp: str) -> Path:
    root = staging_root(invocation)
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{stamp}-{uuid.uuid4().hex[:8]}"
