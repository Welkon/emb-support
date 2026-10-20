"""Run this CLI on the Windows side of WSL.

A VISA or USBTMC instrument installed for Windows is reachable from Windows but
not from the WSL sandbox, and the hand-written workaround is a throwaway wrapper
script per session.

`scope.py --bridge windows <command>` forwards the command to the same CLI
running on the Windows interpreter, so the transport, dialect and error messages
are one implementation. The child prints the same JSON the native run would.

Only the flags before the command are interpreted here; everything else is
passed through untouched.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .wsl import is_wsl

BRIDGE_FLAG = "--bridge"
BRIDGE_WINDOWS = "windows"


class BridgeError(RuntimeError):
    """The Windows side could not be reached or configured."""


def wants_bridge(argv: list[str]) -> str | None:
    """Return the requested bridge name, or None."""
    for i, arg in enumerate(argv):
        if arg == BRIDGE_FLAG and i + 1 < len(argv):
            return argv[i + 1].lower()
        if arg.startswith(BRIDGE_FLAG + "="):
            return arg.split("=", 1)[1].lower()
    return None


PYPYTHON_FLAG = "--win-python"


def extract_python_flag(argv: list[str]) -> tuple[list[str], str | None]:
    """Pull `--win-python <path>` out: the child must not see a flag it lacks."""
    out: list[str] = []
    value: str | None = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == PYPYTHON_FLAG and i + 1 < len(argv):
            value = argv[i + 1]
            i += 2
            continue
        if arg.startswith(PYPYTHON_FLAG + "="):
            value = arg.split("=", 1)[1]
            i += 1
            continue
        out.append(arg)
        i += 1
    return out, value


def strip_bridge(argv: list[str]) -> list[str]:
    """Drop the bridge flag from an argument list, keeping every other flag."""
    out: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == BRIDGE_FLAG:
            i += 2
            continue
        if arg.startswith(BRIDGE_FLAG + "="):
            i += 1
            continue
        out.append(arg)
        i += 1
    return out


def wsl_view(path: str) -> str:
    """Translate a Windows path to the /mnt/... form execve can use."""
    try:
        conv = subprocess.run(["wslpath", "-u", path], capture_output=True,
                              text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return path
    out = conv.stdout.strip()
    return out if conv.returncode == 0 and out else path


def windows_python(explicit: str | None = None) -> str:
    """Resolve the Windows interpreter: flag, then env, then ask Windows."""
    for candidate in (explicit, os.environ.get("SCOPE_WIN_PYTHON")):
        if candidate:
            return wsl_view(candidate)
    if not shutil.which("powershell.exe"):
        raise BridgeError("powershell.exe is not on PATH; the bridge needs WSL with interop enabled")
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "(Get-Command python -ErrorAction SilentlyContinue).Source"],
            capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise BridgeError(f"could not ask Windows for its python: {exc}") from exc
    found = proc.stdout.strip().splitlines()[-1].strip() if proc.stdout.strip() else ""
    if found:
        # A Windows path only runs through interop when WSL can see the file.
        found = wsl_view(found)
    if not found:
        raise BridgeError(
            "no Windows python found; install one or pass --win-python <path> "
            "(or set SCOPE_WIN_PYTHON)")
    return found


def windows_path(path: Path) -> str:
    """Convert a WSL path to the Windows view of it."""
    try:
        proc = subprocess.run(["wslpath", "-w", str(path)],
                              capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise BridgeError(f"wslpath failed: {exc}") from exc
    out = proc.stdout.strip()
    if proc.returncode != 0 or not out:
        raise BridgeError(f"could not translate {path} to a Windows path: {proc.stderr.strip()}")
    return out


def bridge_command(argv: list[str], python: str | None = None) -> list[str]:
    """Build the Windows-side command line for `argv`."""
    script = Path(__file__).resolve().parents[1] / "scope.py"
    rest, flagged = extract_python_flag(strip_bridge(argv))
    return [windows_python(python or flagged), windows_path(script)] + rest[1:]


def run(argv: list[str], python: str | None = None) -> int:
    """Run the command on Windows, forwarding stdout, stderr and the exit code."""
    if not is_wsl():
        raise BridgeError(
            f"{BRIDGE_FLAG} {BRIDGE_WINDOWS} only makes sense on WSL; "
            "run the CLI directly on this host")
    cmd = bridge_command(argv, python)
    return subprocess.call(cmd, env=dict(os.environ, SCOPE_WIN_BRIDGED="1"))
