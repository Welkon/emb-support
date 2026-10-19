"""WSL helpers: detect the Windows side and manage USB passthrough."""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path

SCOPE_VENDORS = {
    "0699": "Tektronix",
    "1ab1": "Rigol",
    "f4ec": "Siglent",
    "0957": "Keysight/Agilent",
    "2a8d": "Keysight",
    "05ff": "LeCroy",
    "0aad": "Rohde & Schwarz",
    "0b21": "Yokogawa",
    "2184": "GW Instek",
    "0493": "Hantek",
    "5345": "Owon",
    "18d1": "Micsig",
}

_LINE = re.compile(
    r"^(?P<busid>\d+-\d+(?:\.\d+)?)\s+"
    r"(?P<vid>[0-9a-fA-F]{4}):(?P<pid>[0-9a-fA-F]{4})\s+"
    r"(?P<desc>.+?)\s{2,}(?P<state>Not shared|Shared|Attached|Not attached)\s*$"
)


def is_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def usbipd_path() -> str | None:
    found = shutil.which("usbipd.exe")
    if found:
        return found
    candidate = Path("/mnt/c/Program Files/usbipd-win/usbipd.exe")
    return str(candidate) if candidate.exists() else None


def parse_usbipd(text: str) -> list[dict]:
    devices = []
    for line in text.splitlines():
        m = _LINE.match(line.strip())
        if not m:
            continue
        vid = m.group("vid").lower()
        devices.append({
            "busid": m.group("busid"),
            "vid": vid,
            "pid": m.group("pid").lower(),
            "vendor": SCOPE_VENDORS.get(vid),
            "description": m.group("desc").strip(),
            "state": m.group("state"),
            "attached": m.group("state") == "Attached",
        })
    return devices


def list_devices(path: str | None = None) -> tuple[list[dict], str | None]:
    exe = path or usbipd_path()
    if not exe:
        return [], "usbipd.exe not found"
    try:
        p = subprocess.run([exe, "list"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as e:
        return [], f"usbipd list failed: {e}"
    return parse_usbipd(p.stdout), None


def attach_hint(device: dict) -> list[str]:
    exe = usbipd_path() or "usbipd.exe"
    if device["attached"]:
        return []
    cmds = []
    if device["state"] == "Not shared":
        cmds.append(f'"{exe}" bind --busid {device["busid"]}   (Administrator)')
    cmds.append(f'"{exe}" attach --wsl --busid {device["busid"]}')
    return cmds


def attach_scope_devices(dry_run: bool = False) -> list[dict]:
    exe = usbipd_path()
    devices, err = list_devices(exe)
    if err:
        return [{"error": err}]
    results = []
    for dev in devices:
        if not dev["vendor"] or dev["attached"]:
            continue
        cmds = attach_hint(dev)
        if dry_run:
            results.append({"busid": dev["busid"], "vendor": dev["vendor"],
                            "commands": cmds, "dry_run": True})
            continue
        p = subprocess.run([exe, "attach", "--wsl", "--busid", dev["busid"]],
                           capture_output=True, text=True, timeout=30)
        results.append({"busid": dev["busid"], "vendor": dev["vendor"],
                        "rc": p.returncode,
                        "stdout": p.stdout.strip()[-400:],
                        "stderr": p.stderr.strip()[-400:],
                        "hint": cmds if p.returncode else []})
    return results


def windows_host_ip() -> str | None:
    """Default gateway of the WSL VM (usually the Windows host in WSL2)."""
    try:
        out = subprocess.run(["ip", "route"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in out.splitlines():
        if line.startswith("default via "):
            return line.split()[2]
    return None


def scope_devices() -> list[dict]:
    devices, _ = list_devices()
    return [d for d in devices if d["vendor"]]


def ensure_scope_attached(wait_seconds: float = 8.0) -> dict:
    """Attach shared scope devices to WSL, then wait for a usbtmc node.

    Never runs `usbipd bind` (that requires Administrator); devices in the
    "Not shared" state are reported with the exact command instead.
    """
    devices, err = list_devices()
    scopes = [d for d in devices if d["vendor"]]
    result = {"devices": scopes, "attached": [], "needs_bind": [], "error": err}
    if not scopes:
        result["status"] = "no-device"
        return result
    if any(d["attached"] for d in scopes):
        result["status"] = "already-attached"
        return result
    exe = usbipd_path()
    for dev in scopes:
        if dev["state"] != "Shared" or exe is None:
            result["needs_bind"].append(dev)
            continue
        p = subprocess.run([exe, "attach", "--wsl", "--busid", dev["busid"]],
                           capture_output=True, text=True, timeout=30)
        entry = {"busid": dev["busid"], "vendor": dev["vendor"],
                 "rc": p.returncode, "stderr": p.stderr.strip()[-300:]}
        result["attached"].append(entry)
    if not result["attached"]:
        result["status"] = "needs-bind"
        return result

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if Path("/dev/usbtmc0").exists() or any(Path("/dev").glob("usbtmc*")):
            break
        time.sleep(0.2)
    result["status"] = "attached" if any(Path("/dev").glob("usbtmc*")) else "attached-no-node"
    return result
