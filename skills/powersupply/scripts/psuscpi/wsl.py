"""WSL helpers: detect the Windows side, attach USB supplies, open a browser."""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path

# USB vendors seen on bench supplies.
PSU_VENDORS = {
    "1ab1": "Rigol",
    "f4ec": "Siglent",
    "0957": "Keysight/Agilent",
    "2a8d": "Keysight",
    "0aad": "Rohde & Schwarz",
    "2184": "GW Instek",
    "0493": "Hantek",
    "5345": "Owon",
    "1a86": "Korad/CH340",
    "2e3c": "ALIENTEK/FNIRSI",
    "05ff": "LeCroy/B&K",
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
    out = []
    for line in text.splitlines():
        m = _LINE.match(line.strip())
        if not m:
            continue
        vid = m.group("vid").lower()
        out.append({"busid": m.group("busid"), "vid": vid, "pid": m.group("pid").lower(),
                    "vendor": PSU_VENDORS.get(vid), "description": m.group("desc").strip(),
                    "state": m.group("state"), "attached": m.group("state") == "Attached"})
    return out


def list_devices() -> tuple[list[dict], str | None]:
    exe = usbipd_path()
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


def ensure_supply_attached(wait_seconds: float = 8.0) -> dict:
    devices, err = list_devices()
    supplies = [d for d in devices if d["vendor"]]
    result = {"devices": supplies, "attached": [], "needs_bind": [], "error": err}
    if not supplies:
        result["status"] = "no-device"
        return result
    if any(d["attached"] for d in supplies):
        result["status"] = "already-attached"
        return result
    exe = usbipd_path()
    for dev in supplies:
        if dev["state"] != "Shared" or exe is None:
            result["needs_bind"].append(dev)
            continue
        p = subprocess.run([exe, "attach", "--wsl", "--busid", dev["busid"]],
                           capture_output=True, text=True, timeout=30)
        result["attached"].append({"busid": dev["busid"], "vendor": dev["vendor"],
                                   "rc": p.returncode, "stderr": p.stderr.strip()[-300:]})
    if not result["attached"]:
        result["status"] = "needs-bind"
        return result
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if any(Path("/dev").glob("hidraw*")) or any(Path("/dev").glob("usbtmc*")):
            break
        time.sleep(0.2)
    result["status"] = "attached"
    return result


def windows_host_ip() -> str | None:
    try:
        out = subprocess.run(["ip", "route"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in out.splitlines():
        if line.startswith("default via "):
            return line.split()[2]
    return None


def open_browser(url: str) -> bool:
    """Open a URL with the Windows browser when running inside WSL."""
    if is_wsl():
        for cmd in (["cmd.exe", "/c", "start", "", url],
                    ["powershell.exe", "-NoProfile", "-Command", f"Start-Process '{url}'"]):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except OSError:
                continue
    try:
        import webbrowser
        return webbrowser.open(url)
    except Exception:
        return False
