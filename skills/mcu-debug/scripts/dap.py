#!/usr/bin/env python3
"""dap.py - DAPLink / CMSIS-DAP toolbox for agents (pyOCD backend).

Capability surface mirrors a full CMSIS-DAP MCP server:
  probes, target info, connect/status, halt/resume/step, breakpoints, watchpoints,
  memory + core registers, SVD peripherals + bit fields, flash/erase/verify,
  option bytes (explicit address), DP register access, RTT, GDB server.

Design notes:
  * pyOCD does the work (probe enumeration, flash algorithms, CMSIS-Packs, SVD,
    RTT, gdbserver). This file normalises commands and emits JSON.
  * Sessions are opened with blocking=False so a missing probe fails in <1s
    instead of hanging an agent.
  * Hardware breakpoints survive between invocations (they live in the FPB), so
    `bp set` followed by `wait` works without a long-running daemon.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from dap_debug import (
    CfiUnwinder,
    DwarfReader,
    ElfInfo,
    Val,
    _tref,
    eval_expr,
)


def _data_home() -> Path:
    for env in ("MCU_DEBUG_HOME", "DAPLINK_HOME"):
        value = os.environ.get(env)
        if value:
            return Path(value).expanduser()
    new = Path.home() / ".local/share/mcu-debug"
    old = Path.home() / ".local/share/daplink"
    return old if (old.exists() and not new.exists()) else new


HOME = _data_home()
VENV = HOME / "venv"
CONFIG = HOME / "config.json"
BP_REGISTRY = HOME / "breakpoints.json"
IS_WIN = os.name == "nt"


# ---------------------------------------------------------------- bootstrapping

def die(msg: str, code: int = 2) -> None:
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False), file=sys.stderr)
    sys.exit(code)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")


def venv_bin(name: str) -> Path:
    return VENV / ("Scripts" if IS_WIN else "bin") / (name + (".exe" if IS_WIN else ""))


def have_pyocd() -> bool:
    try:
        import pyocd  # noqa: F401
        return True
    except Exception:
        return False


def ensure_runtime() -> None:
    if have_pyocd():
        return
    py = venv_python()
    if py.exists() and Path(sys.executable).resolve() != py.resolve():
        os.execv(str(py), [str(py), str(Path(__file__).resolve())] + sys.argv[1:])
    die("pyOCD is not available. Run: dap.py setup")


def pyocd() -> str:
    cached = venv_bin("pyocd")
    if cached.exists():
        return str(cached)
    found = shutil.which("pyocd")
    if found:
        return found
    die("pyocd executable not found. Run: dap.py setup")


def run(cmd: list[str], timeout: int = 120) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        err = (e.stderr or b"").decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
        return 124, out, err + f"\n[timeout after {timeout}s]"
    except FileNotFoundError as e:
        return 127, "", str(e)


def pj(cmd: list[str], timeout: int = 60) -> dict:
    rc, out, err = run([pyocd()] + cmd, timeout)
    if rc != 0:
        die(f"pyocd {' '.join(cmd)} failed (rc={rc}): {(err or out).strip()[:800]}")
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        die(f"pyocd {' '.join(cmd)} returned non-JSON: {out[:400]}")


# --------------------------------------------------------------------- output

def emit(data, human: str | None = None, as_json: bool = False) -> None:
    if as_json or human is None:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(human)


HINTS = [
    (r"no.*(probe|debugger).*(found|available)|No available debug probes",
     "Probe not visible: check USB/power; on WSL run usbipd attach --wsl; on Linux check udev. See troubleshooting.md#probe-not-visible"),
    (r"permission denied|access denied|LIBUSB_ERROR_ACCESS",
     "Permission denied: install the udev rule, then replug the probe."),
    (r"target.*(not found|unknown)|no target.*(found|selected)|TARGET_NOT_FOUND",
     "Unknown target: run dap.py pack install <part>, or use targets --search."),
    (r"flash.*(timeout|failed|error)|Failed to (erase|program)|programming failed",
     "Flash failed: lower --frequency 1000000, try --connect under-reset, or erase --chip."),
    (r"transfer.*(error|failed)|SWD.*(error|fault)|WAIT|FAULT",
     "Unstable SWD: lower the clock, share ground, shorten wires, connect under reset."),
    (r"no memory region|Memory region.*not found",
     "Address outside the known memory map: check the linker script or --base."),
    (r"SVDFile|SVD.*(error|parse|invalid)|No such file",
     "Invalid SVD file or path; pass a CMSIS-SVD XML with --svd <file>."),
]


def explain(stderr: str) -> None:
    for pat, hint in HINTS:
        if re.search(pat, stderr, re.I):
            print(f"\n[hint] {hint}", file=sys.stderr)
            return


# --------------------------------------------------------------------- config

def load_config() -> dict:
    try:
        return json.loads(CONFIG.read_text())
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=2))


def apply_defaults(a) -> None:
    cfg = load_config()
    for key, arg in (("target", "target"), ("probe", "probe"), ("frequency", "frequency"),
                     ("pack", "pack"), ("elf", "elf"), ("engine", "engine"), ("chip", "chip")):
        if getattr(a, arg, None) in (None, "") and cfg.get(key) not in (None, ""):
            setattr(a, arg, cfg[key])


def common_session_opts(a) -> list[str]:
    opts = []
    if getattr(a, "target", None):
        opts += ["-t", a.target]
    if getattr(a, "probe", None):
        opts += ["-u", a.probe]
    if getattr(a, "frequency", None):
        opts += ["-f", str(a.frequency)]
    if getattr(a, "pack", None):
        opts += ["--pack", a.pack]
    if getattr(a, "connect", None):
        opts += ["-O", f"connect_mode={a.connect}"]
    return opts


# ------------------------------------------------------------------- sessions

def _open_session(a, halt: bool = True):
    from pyocd.core.helpers import ConnectHelper
    mode = getattr(a, "connect", None) or ("halt" if halt else "attach")
    return ConnectHelper.session_with_chosen_probe(
        unique_id=getattr(a, "probe", None),
        target_override=getattr(a, "target", None),
        frequency=getattr(a, "frequency", None),
        pack=getattr(a, "pack", None),
        blocking=False,
        return_first=True,
        connect_mode=mode,
    )


def wsl_auto_enabled(a) -> bool:
    if getattr(a, "wsl_auto_attach", True) is False:
        return False
    if os.environ.get("DAP_WSL_AUTO_ATTACH", "1") == "0":
        return False
    return load_config().get("wsl_auto_attach") is not False


def wsl_auto_attach(verbose: bool = True) -> list[str]:
    """Attach already-shared Windows probes to WSL. Returns attached busids."""
    exe = usbipd_exe()
    if not exe:
        return []
    attached: list[str] = []
    for d in usbipd_devices():
        if not d["probe"] or d["state"].lower() == "attached":
            continue
        if d["state"].lower() != "shared":
            if verbose:
                print(f"[wsl] {d['busid']} {d['probe']} is '{d['state']}'; "
                      f"run elevated once: usbipd bind --busid {d['busid']}", file=sys.stderr)
            continue
        if verbose:
            print(f"[wsl] attaching {d['busid']} {d['probe']} to WSL", file=sys.stderr)
        rc, out, err = run([exe, "attach", "--wsl", "--busid", d["busid"]], 60)
        if rc == 0:
            attached.append(d["busid"])
        elif verbose:
            print(f"[wsl] attach {d['busid']} failed: {(err or out).strip()[:200]}", file=sys.stderr)
    return attached


def _session(a, halt: bool = True):
    session = _open_session(a, halt)
    if session is None and is_wsl() and wsl_auto_enabled(a):
        attached = wsl_auto_attach()
        for _ in range(10 if attached else 0):
            time.sleep(0.5)
            session = _open_session(a, halt)
            if session is not None:
                break
    if session is None:
        hint = wsl_probe_hint()
        die("No usable probe (or it is busy). Run dap.py doctor" + (f"\n{hint}" if hint else ""))
    return session


def _state_name(t) -> str:
    try:
        return t.get_state().name
    except Exception:
        return "UNKNOWN"


def _halt_reason(t) -> str | None:
    try:
        return t.get_halt_reason().name
    except Exception:
        return None


# ---------------------------------------------------------------- symbols/ELF

def load_symbols(path: str | None) -> dict[str, int]:
    if not path:
        return {}
    p = Path(path).expanduser()
    if not p.exists():
        return {}
    try:
        from elftools.elf.elffile import ELFFile
    except Exception:
        return {}
    out: dict[str, int] = {}
    try:
        with open(p, "rb") as f:
            elf = ELFFile(f)
            for sec in elf.iter_sections():
                if sec["sh_type"] not in ("SHT_SYMTAB", "SHT_DYNSYM"):
                    continue
                for sym in sec.iter_symbols():
                    st = sym["st_info"]["type"]
                    if sym.name and st in ("STT_FUNC", "STT_OBJECT", "STT_NOTYPE") and sym["st_value"]:
                        out.setdefault(sym.name, sym["st_value"] & ~1)
    except Exception:
        return {}
    return out


def resolve_addr(a, value: str, symbols: dict[str, int] | None = None) -> int:
    v = value.strip()
    if re.fullmatch(r"0x[0-9a-fA-F]+|\d+", v):
        return int(v, 0)
    syms = symbols if symbols is not None else load_symbols(getattr(a, "elf", None))
    if v in syms:
        return syms[v]
    hits = {k: x for k, x in syms.items() if v in k}
    if len(hits) == 1:
        return next(iter(hits.values()))
    if len(hits) > 1:
        die(f"Symbol {v} matches multiple names: {', '.join(list(hits)[:8])}; use the full name")
    die(f"Cannot resolve address or symbol: {v} (requires --elf or config elf)")


# ----------------------------------------------------------------------- SVD

def load_svd(path: str):
    from pyocd.debug.svd.loader import SVDFile
    f = SVDFile(path)
    f.load()
    if not f.device:
        die(f"Failed to parse SVD: {path}")
    return f.device


def svd_path(a) -> str:
    p = getattr(a, "svd", None) or load_config().get("svd")
    if not p:
        die("No SVD configured: run dap.py svd attach <file.svd> or pass --svd <file>")
    if not Path(p).expanduser().exists():
        die(f"SVD file not found: {p}")
    return str(Path(p).expanduser())


def find_peripheral(dev, name: str):
    for p in dev.peripherals:
        if p.name.lower() == name.lower():
            return p
    hits = [p for p in dev.peripherals if name.lower() in p.name.lower()]
    if len(hits) == 1:
        return hits[0]
    die(f"Peripheral {name} not found; available: {', '.join(p.name for p in dev.peripherals[:20])}")


def iter_registers(periph):
    """SVDPeripheral.registers already expands register arrays."""
    regs = list(getattr(periph, "registers", []) or [])
    for cluster in getattr(periph, "clusters", []) or []:
        regs.extend(getattr(cluster, "registers", []) or [])
    return regs


def find_register(periph, name: str):
    regs = iter_registers(periph)
    for r in regs:
        if r.name.lower() == name.lower():
            return r
    hits = [r for r in regs if name.lower() in r.name.lower()]
    if len(hits) == 1:
        return hits[0]
    die(f"Register {name} not found; available: {', '.join(r.name for r in regs[:20])}")


def reg_addr(periph, reg) -> int:
    return periph.base_address + reg.address_offset


def reg_size(reg) -> int:
    return int((reg.size or 32) // 8)


def field_value(raw: int, fld) -> int:
    return (raw >> fld.bit_offset) & ((1 << fld.bit_width) - 1)


def decode_fields(raw: int, reg) -> list[dict]:
    out = []
    for fld in getattr(reg, "fields", []) or []:
        val = field_value(raw, fld)
        item = {"name": fld.name, "value": val, "bits": f"{fld.bit_offset}+{fld.bit_width}"}
        for ev in getattr(fld, "enumerated_values", []) or []:
            if ev.value == val:
                item["meaning"] = ev.name
                break
        out.append(item)
    return out


# ------------------------------------------------------------------- commands

def cmd_setup(a) -> None:
    py = _find_python()
    if not venv_python().exists():
        print(f"creating venv at {VENV} using {py}", file=sys.stderr)
        VENV.parent.mkdir(parents=True, exist_ok=True)
        rc, out, err = run([py, "-m", "venv", str(VENV)], timeout=180)
        if rc != 0:
            die(f"Failed to create venv: {err or out}")
    pip = venv_bin("pip")
    pyocd_pkg = os.environ.get("DAPLINK_PYOCD", "pyocd==0.46.0")
    print(f"installing {pyocd_pkg} into {VENV} (network required)...", file=sys.stderr)
    rc, out, err = run([str(pip), "install", "-U", "pip", pyocd_pkg], timeout=600)
    if rc != 0:
        die(f"pip install failed: {(err or out)[-1500:]}")
    if getattr(a, "dev", False):
        rc2, out2, err2 = run([str(pip), "install", "-U", "pytest"], timeout=600)
        if rc2 != 0:
            die(f"pytest install failed: {(err2 or out2)[-1500:]}")
    rc, out, _ = run([str(venv_bin("pyocd")), "--version"], timeout=60)
    hints = []
    if sys.platform.startswith("linux"):
        hints.append("If the probe reports a permission error, install the udev rule -> references/troubleshooting.md#permissions")
    if Path("/proc/version").exists() and "microsoft" in Path("/proc/version").read_text().lower():
        hints.append("WSL: run `usbipd attach --wsl --busid <id>` on Windows")
    emit({"ok": True, "venv": str(VENV), "pyocd": out.strip(), "hints": hints}, as_json=True)


def _find_python() -> str:
    explicit = os.environ.get("DAPLINK_PYTHON")
    if explicit:
        return explicit
    if (3, 10) <= sys.version_info < (3, 14):
        return sys.executable
    for v in ("3.13", "3.12", "3.11", "3.10"):
        p = shutil.which(f"python{v}")
        if p:
            return p
    import glob
    for p in sorted(glob.glob(str(Path.home() / ".local/share/mise/installs/python/*/bin/python3")), reverse=True):
        m = re.search(r"python/(3\.\d+)", p)
        if m and (3, 10) <= tuple(int(x) for x in m.group(1).split(".")) < (3, 14):
            return p
    return sys.executable


# ------------------------------------------------------------------------ WSL

WSL_PROBE_VIDS = {
    "0d28": "DAPLink/CMSIS-DAP",
    "0483": "ST-Link",
    "1366": "J-Link",
    "1209": "CMSIS-DAP (pid.codes)",
    "1fc9": "NXP LPC-Link",
    "2e8a": "Raspberry Pi",
    "04d8": "Microchip",
    "03eb": "Atmel",
}


def is_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except Exception:
        return bool(os.environ.get("WSL_DISTRO_NAME"))


def usbipd_exe() -> str | None:
    for cand in (shutil.which("usbipd.exe"),
                 "/mnt/c/Program Files/usbipd-win/usbipd.exe",
                 "/mnt/c/Program Files/usbipd-win/usbipd"):
        if cand and Path(cand).exists():
            return cand
    return None


def usbipd_devices() -> list[dict]:
    """Parse `usbipd.exe list` into devices, flagging known debug probes."""
    exe = usbipd_exe()
    if not exe:
        return []
    rc, out, _ = run([exe, "list"], 25)
    if rc != 0:
        return []
    devices = []
    for raw in out.splitlines():
        line = raw.replace("\r", "").strip()
        m = re.match(r"^(\d+-\d+)\s+([0-9a-fA-F]{4}):([0-9a-fA-F]{4})\s+(.+?)\s{2,}(\S.*)$", line)
        if not m:
            continue
        busid, vid, pid, desc, state = m.groups()
        low = state.lower()
        if not (low.startswith(("not shared", "shared", "attached", "not attached"))
                or "\u5171\u4eab" in state or "\u8fde\u63a5" in state):  # localized: shared / attached
            continue
        devices.append({"busid": busid, "vid": vid.lower(), "pid": pid.lower(),
                        "device": desc.strip(), "state": state.strip(),
                        "probe": WSL_PROBE_VIDS.get(vid.lower())})
    return devices


def wsl_probe_hint() -> str:
    if not is_wsl():
        return ""
    pending = [d for d in usbipd_devices() if d["probe"] and d["state"].lower() != "attached"]
    if not pending:
        return ""
    d = pending[0]
    if d["state"].lower() == "shared":
        return (f"Windows sees {d['probe']} at busid {d['busid']} ({d['state']}); "
                f"auto-attach will try on the next connect (or run: dap.py wsl attach --busid {d['busid']})")
    return (f"Windows sees {d['probe']} at busid {d['busid']} ({d['state']}); "
            f"run elevated once: usbipd bind --busid {d['busid']}, then retry")


def cmd_wsl(a) -> None:
    if not is_wsl():
        emit({"ok": False, "error": "not running in WSL"}, as_json=True)
        return
    exe = usbipd_exe()
    devices = usbipd_devices()
    probes = [d for d in devices if d["probe"]]
    if a.action in (None, "status"):
        emit({"ok": True, "usbipd": exe, "devices": devices, "probes": probes,
              "hint": wsl_probe_hint() or None}, as_json=True)
        return
    if not exe:
        die("usbipd.exe not found; install usbipd-win on Windows")
    targets = [d for d in devices if d["busid"] == a.busid] if a.busid else probes
    if not targets:
        die("no matching USB device" + (f" with busid {a.busid}" if a.busid else " (known probe VID)"))
    d = targets[0]
    state = d["state"].lower()
    if a.action == "attach":
        if state == "attached":
            emit({"ok": True, "already_attached": True, "device": d}, as_json=True)
            return
        if state != "shared":
            die(f"{d['busid']} is '{d['state']}'. Run once in an elevated PowerShell: "
                f"usbipd bind --busid {d['busid']}")
        args = [exe, "attach", "--wsl", "--busid", d["busid"]]
        if getattr(a, "dry_run", False):
            emit({"ok": True, "dry_run": True, "command": args, "device": d}, as_json=True)
            return
        rc, out, err = run(args, 60)
        emit({"ok": rc == 0, "rc": rc, "device": d, "stdout": out.strip(), "stderr": err.strip()},
             as_json=True)
        sys.exit(rc)
    if a.action == "detach":
        args = [exe, "detach", "--busid", d["busid"]]
        if getattr(a, "dry_run", False):
            emit({"ok": True, "dry_run": True, "command": args, "device": d}, as_json=True)
            return
        rc, out, err = run(args, 60)
        emit({"ok": rc == 0, "rc": rc, "device": d, "stdout": out.strip(), "stderr": err.strip()},
             as_json=True)
        sys.exit(rc)


def cmd_doctor(a) -> None:
    ensure_runtime()
    info: dict = {"python": sys.executable, "pyocd_module": None, "pyocd_cli": None,
                  "wsl": False, "probes": [], "targets_cached": 0, "problems": [], "hints": []}
    import pyocd as _m
    info["pyocd_module"] = getattr(_m, "__version__", "?")
    rc, out, _ = run([pyocd(), "--version"], timeout=30)
    info["pyocd_cli"] = out.strip() if rc == 0 else None
    if is_wsl():
        info["wsl"] = True
        exe = usbipd_exe()
        devices = usbipd_devices()
        probes = [d for d in devices if d["probe"]]
        info["windows"] = {"interop": bool(shutil.which("powershell.exe") or shutil.which("pwsh.exe")),
                           "usbipd": exe, "probes": probes,
                           "attached": [d["busid"] for d in probes if d["state"].lower() == "attached"]}
        hints = wsl_probe_hint()
        if hints:
            info["hints"].append(hints)
            if getattr(a, "attach", False):
                pending = [d for d in probes if d["state"].lower() != "attached"]
                target = (pending[0]["busid"] if pending else None)
                if target:
                    wslns = argparse.Namespace(action="attach", busid=target, dry_run=False)
                    cmd_wsl(wslns)
        elif probes:
            info["hints"].append("Windows probes are already attached to WSL")
        else:
            info["hints"].append("WSL: no known debug probe found on the Windows side (usbipd)")
    try:
        info["probes"] = pj(["json", "-p"], timeout=30).get("probes", [])
    except SystemExit:
        info["problems"].append("probe enumeration failed (permission problem?)")
    if not info["probes"]:
        info["hints"].append("No probe found: check cable/power; WSL needs usbipd; Linux needs udev rules")
    try:
        info["targets_cached"] = len(pj(["json", "-t"], timeout=90).get("targets", []))
    except SystemExit:
        info["problems"].append("target list failed")
    if info["targets_cached"] == 0:
        info["hints"].append("Empty built-in target list is normal; install device packs with pack install")
    info["ok"] = bool(info["pyocd_cli"]) and not info["problems"]
    prs = probe_rs_path()
    info["engines"] = {"pyocd": bool(info["pyocd_cli"]),
                       "probe-rs": {"available": bool(prs), "path": prs}}
    emit(info, as_json=True)


def cmd_probes(a) -> None:
    eng = getattr(a, "engine", None) or load_config().get("engine") or "pyocd"
    if eng == "probe-rs":
        rc, out, err = _prs(["list"], 30)
        if a.json:
            emit({"ok": rc == 0, "engine": "probe-rs",
                  "probes": [ln for ln in out.splitlines() if ln.strip()]}, as_json=True)
        else:
            sys.stdout.write(out)
            sys.stderr.write(err)
        return
    ensure_runtime()
    data = pj(["json", "-p"], timeout=30).get("probes", [])
    if a.json:
        emit(data, as_json=True)
        return
    if not data:
        if is_wsl():
            win = [d for d in usbipd_devices() if d["probe"]]
            if a.json:
                emit({"linux": [], "windows": win, "hint": wsl_probe_hint() or None}, as_json=True)
                return
            if win:
                for d in win:
                    print(f"windows  {d['busid']}  {d['vid']}:{d['pid']}  {d['device']}  [{d['state']}]")
                print(f"\n{wsl_probe_hint()}")
                return
        print("no probes found")
        return
    for p in data:
        print(f"{p.get('unique_id','?'):24}  {p.get('board_name') or p.get('product_name') or '?'}"
              f"  target={p.get('target_override') or '-'}")


def cmd_targets(a) -> None:
    eng = getattr(a, "engine", None) or load_config().get("engine") or "pyocd"
    if eng == "auto":
        eng = "pyocd"
    if eng != "probe-rs":
        ensure_runtime()
    if eng == "probe-rs":
        rc, out, err = _prs(["chip", "list"], 120)
        if rc != 0:
            die((err or out).strip()[:800])
        lines = out.splitlines()
        if getattr(a, "search", None):
            q = a.search.lower()
            lines = [ln for ln in lines if q in ln.lower()]
        if a.json:
            emit({"ok": True, "engine": "probe-rs", "chips": [ln.strip() for ln in lines if ln.strip()]}, as_json=True)
        else:
            print("\n".join(lines))
        return
    data = pj(["json", "-t"], timeout=120).get("targets", [])
    if a.search:
        q = a.search.lower()
        data = [t for t in data if q in json.dumps(t).lower()]
    data.sort(key=lambda t: (t.get("vendor") or "", t.get("name") or ""))
    if a.limit:
        data = data[: a.limit]
    if a.json:
        emit(data, as_json=True)
        return
    print(f"{len(data)} target(s)")
    for t in data:
        print(f"{t.get('name','?'):24} {(t.get('vendor') or '-'):16} {(t.get('part_number') or '-'):16} {t.get('source','')}")


def cmd_pack(a) -> None:
    ensure_runtime()
    args = ["pack", a.action]
    if a.action in ("search", "install", "find") and a.query:
        args.append(a.query)
    rc, out, err = run([pyocd()] + args, timeout=600)
    sys.stdout.write(out)
    sys.stderr.write(err)
    sys.exit(rc)


def cmd_flash(a) -> None:
    f = Path(a.file).expanduser()
    if not f.exists():
        die(f"File not found: {f}")
    engine = _engine(a)
    if engine == "probe-rs":
        args = ["download", str(f)] + _prs_common(a) + ["--binary-format", _fw_format(f, a.format), "--verify"]
        if a.erase == "chip":
            args.append("--chip-erase")
        if a.base:
            args += ["--base-address", a.base]
        if not a.no_reset:
            args.append("--reset")
        rc, out, err = _prs(args, a.timeout)
        emit({"ok": rc == 0, "op": "flash", "engine": "probe-rs", "file": str(f),
              "rc": rc, "stdout": out.strip()[-4000:], "stderr": err.strip()[-4000:]}, as_json=True)
        if rc != 0:
            explain(err or out)
            sys.exit(rc)
        return
    ensure_runtime()
    if not a.target and not a.pack:
        die("Requires -t <target> (see targets --search) or --pack")
    args = ["load", "-W", str(f)] + common_session_opts(a)
    if a.base:
        args += ["-a", a.base]
    if a.erase:
        args += ["-e", a.erase]
    if a.no_reset:
        args += ["--no-reset"]
    if a.format:
        args += ["--format", a.format]
    rc, out, err = run([pyocd()] + args, timeout=a.timeout)
    emit({"ok": rc == 0, "op": "flash", "engine": "pyocd", "file": str(f), "target": a.target, "rc": rc,
          "stdout": out.strip()[-4000:], "stderr": err.strip()[-4000:]}, as_json=True)
    if rc != 0:
        explain(err or out)
        sys.exit(rc)


def cmd_verify(a) -> None:
    """Compare a firmware file against target memory without writing."""
    f = Path(a.file).expanduser()
    if not f.exists():
        die(f"File not found: {f}")
    if _engine(a) == "probe-rs":
        args = ["verify", str(f)] + _prs_common(a) + ["--binary-format", _fw_format(f, None)]
        if a.base:
            args += ["--base-address", a.base]
        rc, out, err = _prs(args, a.timeout)
        emit({"ok": rc == 0, "op": "verify", "engine": "probe-rs", "file": str(f),
              "rc": rc, "stdout": out.strip()[-4000:], "stderr": err.strip()[-4000:]}, as_json=True)
        sys.exit(rc)
    ensure_runtime()
    segments: list[tuple[int, bytes]] = []
    suffix = f.suffix.lower()
    if suffix in (".elf", ".axf"):
        from elftools.elf.elffile import ELFFile
        with open(f, "rb") as fh:
            elf = ELFFile(fh)
            for seg in elf.iter_segments():
                if seg["p_type"] == "PT_LOAD" and seg["p_filesz"] > 0:
                    segments.append((seg["p_paddr"], seg.data()))
    elif suffix in (".hex", ".ihx"):
        from intelhex import IntelHex
        ih = IntelHex(str(f))
        for start, end in ih.segments():
            segments.append((start, bytes(ih.tobinarray(start=start, size=end - start))))
    elif suffix == ".bin":
        if not a.base:
            die(".bin verification requires --base 0x08000000")
        segments.append((int(a.base, 0), f.read_bytes()))
    else:
        die(f"Unsupported format: {suffix}")

    s = _session(a)
    mismatches = []
    total = 0
    CHUNK = 4096
    with s:
        t = _core(s.target, a)
        for addr, data in segments:
            total += len(data)
            for off in range(0, len(data), CHUNK):
                chunk = data[off:off + CHUNK]
                mem = bytes(t.read_memory_block8(addr + off, len(chunk)))
                if mem != chunk:
                    for i, (x, y) in enumerate(zip(mem, chunk)):
                        if x != y:
                            mismatches.append({"addr": hex(addr + off + i), "target": hex(x), "file": hex(y)})
                            if len(mismatches) >= a.max_report:
                                break
                if len(mismatches) >= a.max_report:
                    break
            if len(mismatches) >= a.max_report:
                break
    result = {"ok": not mismatches, "op": "verify", "engine": "pyocd", "file": str(f), "bytes": total,
              "segments": len(segments), "mismatches": mismatches}
    emit(result, as_json=True)
    if mismatches:
        sys.exit(1)


def cmd_erase(a) -> None:
    if _engine(a) != "probe-rs":
        ensure_runtime()
    if _engine(a) == "probe-rs":
        if a.range:
            die("probe-rs can only erase the whole chip; use --engine pyocd for sector ranges")
        rc, out, err = _prs(["erase"] + _prs_common(a), a.timeout)
        emit({"ok": rc == 0, "op": "erase", "engine": "probe-rs", "rc": rc,
              "stdout": out.strip()[-2000:], "stderr": err.strip()[-2000:]}, as_json=True)
        sys.exit(rc)
    args = ["erase", "-W"] + common_session_opts(a)
    if a.chip:
        args += ["--chip"]
    elif a.range:
        args += ["-a", a.range]
    rc, out, err = run([pyocd()] + args, timeout=a.timeout)
    emit({"ok": rc == 0, "op": "erase", "engine": "pyocd", "rc": rc, "stdout": out.strip()[-2000:],
          "stderr": err.strip()[-2000:]}, as_json=True)
    if rc != 0:
        explain(err or out)
        sys.exit(rc)


def cmd_reset(a) -> None:
    if _engine(a) != "probe-rs":
        ensure_runtime()
    if _engine(a) == "probe-rs":
        args = ["reset"] + _prs_common(a)
        if str(getattr(a, "core", "0") or "0").isdigit():
            args += ["--core", str(a.core or 0)]
        rc, out, err = _prs(args, a.timeout)
        emit({"ok": rc == 0, "op": "reset", "engine": "probe-rs", "rc": rc,
              "stdout": out.strip()[-2000:], "stderr": err.strip()[-2000:]}, as_json=True)
        sys.exit(rc)
    args = ["reset", "-W"] + common_session_opts(a)
    if a.halt:
        args.append("--halt")
    rc, out, err = run([pyocd()] + args, timeout=a.timeout)
    emit({"ok": rc == 0, "op": "reset", "engine": "pyocd", "rc": rc, "stdout": out.strip()[-2000:],
          "stderr": err.strip()[-2000:]}, as_json=True)
    if rc != 0:
        explain(err or out)
        sys.exit(rc)


def cmd_info(a) -> None:
    if _engine(a) != "probe-rs":
        ensure_runtime()
    if _engine(a) == "probe-rs":
        rc, out, err = _prs(["info"] + _prs_common(a), a.timeout)
        sys.stdout.write(out)
        sys.stderr.write(err)
        sys.exit(rc)
    rc, out, err = run([pyocd(), "info", "-W"] + common_session_opts(a), timeout=a.timeout)
    sys.stdout.write(out)
    sys.stderr.write(err)
    sys.exit(rc)


# ----------------------------------------------------------- live target state

def cmd_connect(a) -> None:
    ensure_runtime()
    s = _session(a)
    with s:
        t = _core(s.target, a)
        info = {"ok": True, "probe": s.probe.unique_id, "target": t.part_number or a.target,
                "state": _state_name(t), "halt_reason": _halt_reason(t)}
        try:
            info["pc"] = hex(t.read_core_register("pc"))
        except Exception:
            pass
    emit(info, as_json=True)


def cmd_status(a) -> None:
    ensure_runtime()
    s = _session(a, halt=False)
    with s:
        t = _core(s.target, a)
        out = {"ok": True, "state": _state_name(t), "halt_reason": _halt_reason(t)}
        try:
            out["pc"] = hex(t.read_core_register("pc"))
        except Exception:
            pass
    emit(out, as_json=True)


def cmd_halt(a) -> None:
    ensure_runtime()
    s = _session(a)
    with s:
        t = _core(s.target, a)
        t.halt()
        emit({"ok": True, "op": "halt", "state": _state_name(t),
              "pc": hex(t.read_core_register("pc"))}, as_json=True)


def cmd_resume(a) -> None:
    ensure_runtime()
    s = _session(a)
    with s:
        t = _core(s.target, a)
        t.resume()
        emit({"ok": True, "op": "resume", "state": _state_name(t)}, as_json=True)


def cmd_step(a) -> None:
    ensure_runtime()
    ei = ElfInfo(elf_path(a)) if a.line else None
    s = _session(a)
    with s:
        t = _core(s.target, a)
        pc_before = t.read_core_register("pc") & ~1
        if a.over:
            size, is_call = _insn(t, pc_before)
            if is_call:
                _run_to(t, pc_before + size, a.timeout)
            else:
                t.step(disable_interrupts=not a.allow_interrupts)
                t.halt()
        elif a.out:
            lr = t.read_core_register("lr") & ~1
            if not lr:
                die("LR is 0; cannot step out")
            _run_to(t, lr, a.timeout)
        elif a.line and ei is not None:
            cur = ei.line_for(pc_before)
            target = None
            for addr, name, line in ei.lines:
                if addr <= pc_before:
                    continue
                if cur and name != cur[0] and line:
                    continue
                if cur and line == cur[1]:
                    continue
                target = addr
                break
            if target is None:
                die("No next line found (build with -g debug info)")
            _run_to(t, target, a.timeout)
        else:
            for _ in range(max(1, a.count)):
                t.step(disable_interrupts=not a.allow_interrupts)
            t.halt()
        out = {"ok": True, "op": "step", "mode": "over" if a.over else "out" if a.out else "line" if a.line else "in",
               "from": hex(pc_before), "state": _state_name(t)}
        pc = t.read_core_register("pc")
        out["pc"] = hex(pc)
        if ei:
            out["symbol"] = ei.frame_name(pc & ~1)
            ln = ei.line_for(pc & ~1)
            if ln:
                out["file"], out["line"] = ln
        emit(out, as_json=True)


def _exec_on_hit(t, script: str, ei, dr, read) -> tuple[bool, list[str]]:
    """Execute a semicolon-separated on-hit script. Returns (continue?, output)."""
    cont = False
    out: list[str] = []
    regs = _read_regs(t)
    pc = regs.get("pc", 0) & ~1
    fr = None
    for raw in script.split(";"):
        cmd = raw.strip()
        if not cmd:
            continue
        low = cmd.lower()
        if low in ("continue", "cont", "c"):
            cont = True
        elif low == "stop":
            cont = False
        elif low == "silent":
            pass
        elif low == "bt":
            if ei:
                if fr is None:
                    fr = _bt_frames(t, ei, 8, 256)[1]
                for i, f in enumerate(fr):
                    loc = f" ({f['file']}:{f['line']})" if f.get("file") else ""
                    out.append(f"#{i} {f.get('symbol', '?')} 0x{f['pc']:08x}{loc}")
            else:
                out.append("bt: needs --elf")
        elif low.startswith(("print ", "p ", "log ")):
            expr = cmd.split(None, 1)[1]
            if dr:
                env = _env(dr, regs, pc)
                try:
                    out.append(str(_fmt_val(eval_expr(dr, expr, env, read), dr, read)))
                except Exception as exc:
                    out.append(f"print error: {exc}")
            else:
                out.append("print: needs --elf")
        else:
            out.append(f"unknown on-hit command: {cmd}")
    return cont, out


def cmd_wait(a) -> None:
    """Resume and poll until halt; supports conditional breakpoints and logging."""
    ensure_runtime()
    hits = 0
    logs: list[dict] = []
    registry = {int(b["addr"], 0): b for b in _bp_load() if b.get("cond") or b.get("on_hit")}
    ei = ElfInfo(elf_path(a)) if (getattr(a, "elf", None) or load_config().get("elf")) else None
    dr = DwarfReader(elf_path(a)) if ei else None
    s = _session(a)
    with s:
        t = _core(s.target, a)
        if not a.no_resume:
            t.resume()
        deadline = time.time() + a.timeout
        state = _state_name(t)
        while time.time() < deadline:
            state = _state_name(t)
            if state == "RUNNING":
                time.sleep(0.02)
                continue
            entry = registry.get(t.read_core_register("pc") & ~1, {})
            cond = getattr(a, "cond", None) or entry.get("cond")
            ok = True
            if cond:
                try:
                    ok = eval_cond(t, cond)
                except SystemExit:
                    raise
                except Exception:
                    ok = False
            if ok:
                hits += 1
                entry = {"hit": hits, "pc": hex(t.read_core_register("pc")),
                         "halt_reason": _halt_reason(t)}
                if getattr(a, "log", None):
                    entry["log"] = _value_of(t, a.log) if not a.log.startswith("pc") else t.read_core_register("pc")
                    if isinstance(entry["log"], int):
                        entry["log"] = hex(entry["log"])
                script = getattr(a, "on_hit", None) or entry.get("on_hit")
                if script:
                    cont, lines = _exec_on_hit(t, script, ei, dr,
                                               lambda addr, n: _read(t, addr, n))
                    entry["on_hit_output"] = lines
                    for line in lines:
                        print(line)
                    if cont:
                        t.resume()
                        if a.max_hits is not None and hits >= a.max_hits:
                            break
                        continue
                logs.append(entry)
                if not a.continue_after and (a.max_hits is None or hits >= a.max_hits):
                    break
            # condition failed or continue-after-hit: keep running
            t.resume()
            if a.max_hits is not None and hits >= a.max_hits:
                break
        state = _state_name(t)
        out = {"ok": state != "RUNNING", "op": "wait", "state": state,
               "halt_reason": _halt_reason(t), "hits": hits, "events": logs,
               "elapsed_s": round(a.timeout - (deadline - time.time()), 2)}
        try:
            out["pc"] = hex(t.read_core_register("pc"))
            out["lr"] = hex(t.read_core_register("lr"))
            out["sp"] = hex(t.read_core_register("sp"))
        except Exception:
            pass
        if state == "RUNNING":
            try:
                t.halt()
                out["halted_by_tool"] = True
            except Exception:
                pass
    if getattr(a, "_bp_note", None):
        out["breakpoint"] = a._bp_note
    emit(out, as_json=True)


def cmd_regs(a) -> None:
    ensure_runtime()
    s = _session(a)
    with s:
        t = _core(s.target, a)
        out = {}
        for name in CORE_REGS:
            try:
                out[name] = t.read_core_register(name)
            except Exception:
                pass
        if a.json:
            emit({k: hex(v) for k, v in out.items()}, as_json=True)
        else:
            for k, v in out.items():
                print(f"{k:10} 0x{v:08x}")


CORE_REGS = ["r0", "r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9", "r10",
             "r11", "r12", "sp", "lr", "pc", "xpsr", "msp", "psp", "control",
             "primask", "basepri", "faultmask"]


def cmd_state(a) -> None:
    """Core registers + ARMv7-M fault status decode + exception stack frame."""
    ensure_runtime()
    s = _session(a, halt=False)
    with s:
        t = _core(s.target, a)
        halted_by_tool = False
        if _state_name(t) == "RUNNING":
            try:
                t.halt()
                halted_by_tool = True
            except Exception:
                pass
        regs = {}
        for name in ("r0", "r1", "r2", "r3", "r12", "lr", "pc", "xpsr", "sp", "msp", "psp"):
            try:
                regs[name] = t.read_core_register(name)
            except Exception:
                pass
        fault = {}
        for name, addr in (("CFSR", 0xE000ED28), ("HFSR", 0xE000ED2C), ("DFSR", 0xE000ED30),
                           ("MMFAR", 0xE000ED34), ("BFAR", 0xE000ED38)):
            try:
                fault[name] = t.read32(addr)
            except Exception:
                pass
        decode = decode_faults(fault)
        frame = None
        lr = regs.get("lr")
        if lr is not None and (lr & 0xF0000000) == 0xF0000000:
            frame = unwind_exception_frame(t, lr, regs)
        out = {"state": _state_name(t), "halt_reason": _halt_reason(t),
               "halted_by_tool": halted_by_tool,
               "registers": {k: hex(v) for k, v in regs.items()},
               "fault": {k: hex(v) for k, v in fault.items()},
               "fault_decode": decode, "exception_frame": frame}
        emit(out, as_json=True)


def decode_faults(f: dict[str, int]) -> list[str]:
    out: list[str] = []
    cfsr = f.get("CFSR", 0)
    hfsr = f.get("HFSR", 0)
    mm = ["IACCVIOL", "DACCVIOL", None, "MUNSTKERR", "MSTKERR", None, None, "MMARVALID"]
    bus = ["IBUSERR", "PRECISERR", "IMPRECISERR", "UNSTKERR", "STKERR", None, None, "BFARVALID"]
    usg = ["UNDEFINSTR", "INVSTATE", "INVPC", "NOCP", None, None, None, None, "UNALIGNED", "DIVBYZERO"]
    for label, bits, names in (("MemManage", (cfsr >> 0) & 0xFF, mm),
                               ("BusFault", (cfsr >> 8) & 0xFF, bus),
                               ("UsageFault", (cfsr >> 16) & 0x3FF, usg)):
        for i, name in enumerate(names):
            if name and bits & (1 << i):
                out.append(f"{label}:{name}")
    if hfsr & (1 << 1):
        out.append("HardFault:VECTTBL")
    if hfsr & (1 << 30):
        out.append("HardFault:FORCED")
    if hfsr & (1 << 31):
        out.append("Debug:DEBUGEVT")
    if "BusFault:BFARVALID" in out:
        out.append(f"BFAR={hex(f.get('BFAR', 0))}")
    if "MemManage:MMARVALID" in out:
        out.append(f"MMFAR={hex(f.get('MMFAR', 0))}")
    return out


def unwind_exception_frame(t, lr: int, regs: dict[str, int]) -> dict:
    """Decode the 8-word Cortex-M exception stack frame (basic FPU-less case)."""
    use_psp = bool(lr & 0x4)
    sp = regs.get("psp" if use_psp else "msp") or regs.get("sp")
    if not sp:
        return {"error": "no stack pointer"}
    try:
        words = [t.read32(sp + 4 * i) for i in range(8)]
    except Exception as e:
        return {"error": f"cannot read stack: {e}"}
    names = ["r0", "r1", "r2", "r3", "r12", "lr", "pc", "xpsr"]
    frame = {n: hex(v) for n, v in zip(names, words)}
    frame["sp_used"] = "PSP" if use_psp else "MSP"
    frame["sp"] = hex(sp)
    frame["faulting_pc"] = hex(words[6] & ~1)
    frame["faulting_lr"] = hex(words[5])
    return frame


# ---------------------------------------------------------------- ELF context



def elf_path(a) -> str:
    p = getattr(a, "elf", None) or load_config().get("elf")
    if not p:
        die("Requires --elf <file.elf> or dap.py config set elf <file>")
    p = str(Path(p).expanduser())
    if not Path(p).exists():
        die(f"ELF not found: {p}")
    return p


def _insn(t, pc: int):
    """Decode one Thumb instruction: (size, is_call)."""
    from capstone import CS_ARCH_ARM, CS_GRP_CALL, CS_MODE_THUMB, Cs
    code = bytes(t.read_memory_block8(pc, 4))
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    for ins in md.disasm(code, pc):
        return ins.size, ins.group(CS_GRP_CALL)
    return 2, False


def _run_to(t, addr: int, timeout: float = 5.0) -> str:
    """Set a temporary HW breakpoint, run, return the resulting state."""
    from pyocd.core.target import Target
    t.set_breakpoint(addr, Target.BreakpointType.HW)
    try:
        t.resume()
        deadline = time.time() + timeout
        while time.time() < deadline and _state_name(t) == "RUNNING":
            time.sleep(0.01)
        return _state_name(t)
    finally:
        try:
            t.remove_breakpoint(addr)
        except Exception:
            pass


def _read(t, addr: int, size: int):
    try:
        return bytes(t.read_memory_block8(addr, size))
    except Exception:
        return None


def _bt_frames(t, ei: ElfInfo, limit: int, max_stack: int) -> tuple[int, list[dict]]:
    """CFI-based unwinding; falls back to frame-pointer/stack scan when CFI is absent."""
    if _state_name(t) == "RUNNING":
        t.halt()
    pc = t.read_core_register("pc") & ~1
    sp = t.read_core_register("sp")
    regs = {}
    for name in ("r0", "r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9",
                 "r10", "r11", "r12", "sp", "lr", "pc"):
        try:
            regs[name] = t.read_core_register(name)
        except Exception:
            pass

    def rd(addr):
        try:
            return t.read32(addr)
        except Exception:
            return None

    frames: list[dict] = []
    if ei is not None:
        try:
            uw = CfiUnwinder(ei.path)
            for f in uw.unwind(pc, regs, rd, limit):
                frames.append({"pc": f["pc"], "via": "cfi" if f["exact"] else "cfi?",
                               "exact": bool(f["exact"]), "regs": f["regs"], "cfa": f["cfa"]})
        except Exception:
            frames = []

    exact_count = sum(1 for f in frames if f["exact"])
    if exact_count < 2:
        seen = {f["pc"] for f in frames} or {pc}
        fp = None
        for reg in ("r7", "r11"):
            try:
                cand = regs.get(reg, 0)
                if sp <= cand < sp + 0x10000 and cand % 4 == 0:
                    fp = cand
                    break
            except Exception:
                pass
        while fp and len(frames) < limit:
            try:
                next_fp = t.read32(fp)
                ret = t.read32(fp + 4) & ~1
            except Exception:
                break
            if not (fp < next_fp <= fp + 0x1000) or ret == 0 or ret in seen:
                break
            if ei and ei.in_code(ret):
                frames.append({"pc": ret, "via": "fp", "exact": False, "regs": None, "cfa": fp + 8})
                seen.add(ret)
            fp = next_fp
        off = 0
        while off < max_stack and len(frames) < limit:
            try:
                word = t.read32(sp + off)
            except Exception:
                break
            cand = word & ~1
            if cand and cand not in seen and ei and ei.in_code(cand):
                if not ei.frame_name(cand).startswith("0x"):
                    frames.append({"pc": cand, "via": f"stack+0x{off:x}", "exact": False,
                                   "regs": None, "cfa": sp + off})
                    seen.add(cand)
            off += 4

    for f in frames:
        f["symbol"] = ei.frame_name(f["pc"]) if ei else hex(f["pc"])
        if ei:
            ln = ei.line_for(f["pc"])
            if ln:
                f["file"], f["line"] = ln
    return sp, frames


def cmd_bt(a) -> None:
    """Backtrace: frame-pointer walk plus a code-address stack scan."""
    ensure_runtime()
    ei = ElfInfo(elf_path(a))
    s = _session(a, halt=False)
    with s:
        sp, frames = _bt_frames(s.target, ei, a.limit, a.max_stack)
    for f in frames:
        f.pop("regs", None)
    exact = sum(1 for f in frames if f.get("exact"))
    emit({"ok": True, "op": "bt", "sp": hex(sp), "frames": frames,
          "exact_frames": exact, "heuristic": exact < len(frames),
          "note": "via=cfi is exact DWARF CFI unwinding; via=fp/stack is heuristic and for reference only"}, as_json=True)


def cmd_fault(a) -> None:
    """One-shot post-mortem: fault status, exception frame, backtrace, stack usage."""
    ensure_runtime()
    ei = ElfInfo(elf_path(a)) if (getattr(a, "elf", None) or load_config().get("elf")) else None
    s = _session(a, halt=False)
    with s:
        t = _core(s.target, a)
        if _state_name(t) == "RUNNING":
            t.halt()
        regs = {}
        for name in ("r0", "r1", "r2", "r3", "r12", "lr", "pc", "xpsr", "sp", "msp", "psp"):
            try:
                regs[name] = t.read_core_register(name)
            except Exception:
                pass
        fault = {}
        for name, addr in (("CFSR", 0xE000ED28), ("HFSR", 0xE000ED2C), ("DFSR", 0xE000ED30),
                           ("MMFAR", 0xE000ED34), ("BFAR", 0xE000ED38), ("SHCSR", 0xE000ED24)):
            try:
                fault[name] = t.read32(addr)
            except Exception:
                pass
        frame = None
        lr = regs.get("lr")
        if lr is not None and (lr & 0xF0000000) == 0xF0000000:
            frame = unwind_exception_frame(t, lr, regs)
        stack = {}
        try:
            init_sp = t.read32(0) & ~3
            stack = {"initial_sp": hex(init_sp), "sp": hex(regs.get("sp", 0)),
                     "used": init_sp - regs.get("sp", 0)}
            try:
                for region in t.memory_map:
                    if region.start <= init_sp < region.end:
                        stack["region"] = f"{region.name or 'RAM'} {hex(region.start)}-{hex(region.end)}"
                        if regs.get("sp", 0) < region.start:
                            stack["overflow"] = True
                        break
            except Exception:
                pass
        except Exception:
            pass
        btframes = _bt_frames(t, ei, a.limit, a.max_stack)[1] if ei else []
        for f in btframes:
            f.pop("regs", None)
        state = _state_name(t)
        reason = _halt_reason(t)
    emit({"ok": True, "op": "fault", "state": state, "halt_reason": reason,
          "registers": {k: hex(v) for k, v in regs.items()},
          "fault": {k: hex(v) for k, v in fault.items()},
          "fault_decode": decode_faults(fault), "exception_frame": frame,
          "stack": stack, "backtrace": btframes}, as_json=True)


def _read_regs(t) -> dict:
    out = {}
    for name in ("r0", "r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9",
                 "r10", "r11", "r12", "sp", "lr", "pc", "xpsr"):
        try:
            out[name] = t.read_core_register(name)
        except Exception:
            pass
    return out


def _env(dr, regs: dict, pc: int | None = None, cfa: int | None = None) -> dict:
    env = {k: Val(v=v) for k, v in regs.items()}
    for name, (die, cu, addr) in dr.globals_env().items():
        env[name] = Val(tr=_tref(dr, DwarfReader._type(die, cu), cu), addr=addr, cu=cu)
    if pc is not None:
        for name, (die, cu, addr) in dr.locals_env(pc, regs, cfa).items():
            env[name] = Val(tr=_tref(dr, DwarfReader._type(die, cu), cu), addr=addr, cu=cu)
    return env


def cmd_vars(a) -> None:
    """DWARF variables: globals, locals at a frame, or print an expression."""
    ensure_runtime()
    dr = DwarfReader(elf_path(a))
    ei = ElfInfo(elf_path(a))
    s = _session(a, halt=False)
    with s:
        t = _core(s.target, a)
        read = lambda addr, n: _read(t, addr, n)  # noqa: E731
        if a.action == "globals":
            items = dr.globals_at(read)
            if a.value:
                items = [i for i in items if a.value.lower() in i["name"].lower()]
            emit({"ok": True, "globals": items}, as_json=True)
            return
        frames = _bt_frames(t, ei, 16, 512)[1]
        idx = a.frame or 0
        if idx >= len(frames):
            die(f"Only {len(frames)} frame(s) available (--frame 0..{max(0, len(frames) - 1)})")
        fr = frames[idx]
        regs = dict(fr.get("regs") or {})
        if not regs:
            regs = _read_regs(t)
        pc = fr["pc"]
        cfa = fr.get("cfa")
        if a.action == "locals":
            items = dr.locals_at(pc, regs, read, cfa)
            die_, _ = dr.die_for_pc(pc)
            func = DwarfReader._name(die_) if die_ else None
            emit({"ok": True, "function": func, "frame": idx, "exact": bool(fr.get("exact")),
                  "locals": items,
                  "note": "outer frames rely on CFA/registers rebuilt from DWARF CFI; estimated when CFI is absent"}, as_json=True)
            return
        if not a.value:
            die("vars print requires an expression")
        env = _env(dr, regs, pc, cfa)
        try:
            val = eval_expr(dr, a.value, env, read)
        except ValueError as e:
            die(f"Expression error: {e}")
        emit({"ok": True, "expression": a.value, "frame": idx,
              "result": _fmt_val(val, dr, read)}, as_json=True)


def cmd_watch(a) -> None:
    """Sample an expression over time (live watch)."""
    ensure_runtime()
    dr = DwarfReader(elf_path(a))
    ei = ElfInfo(elf_path(a))
    s = _session(a, halt=False)
    samples = []
    with s:
        t = _core(s.target, a)
        read = lambda addr, n: _read(t, addr, n)  # noqa: E731
        halted = _state_name(t) != "RUNNING"
        frames = _bt_frames(t, ei, 4, 64)[1] if halted else []
        for i in range(a.count):
            regs = _read_regs(t)
            pc = regs.get("pc", 0) & ~1
            cfa = frames[0].get("cfa") if frames else None
            env = _env(dr, regs, pc if halted else None, cfa if halted else None)
            try:
                val = _fmt_val(eval_expr(dr, a.expr, env, read), dr, read)
            except ValueError as e:
                die(f"Expression error: {e}")
            samples.append({"t": round(i * a.interval, 3), "value": val})
            if i + 1 < a.count:
                time.sleep(a.interval)
    nums = [x["value"] for x in samples if isinstance(x["value"], (int, float))]
    out = {"ok": True, "op": "watch", "expression": a.expr, "samples": samples,
           "changed": len(set(map(str, nums))) > 1 if nums else False}
    if nums:
        out.update(min=min(nums), max=max(nums))
    emit(out, as_json=True)


def cmd_snapshot(a) -> None:
    """Save / load / diff a memory region."""
    ensure_runtime()
    addr = int(a.addr, 0)
    path = Path(a.file).expanduser()
    s = _session(a)
    with s:
        t = _core(s.target, a)
        if a.snapshot_cmd == "save":
            if not a.len:
                die("save requires --len")
            data = _read(t, addr, a.len)
            if data is None:
                die("Failed to read memory")
            path.write_bytes(data)
            emit({"ok": True, "saved": str(path), "bytes": len(data)}, as_json=True)
            return
        if not path.exists():
            die(f"File not found: {path}")
        want = path.read_bytes()
        if a.snapshot_cmd == "load":
            t.write_memory_block8(addr, want)
            emit({"ok": True, "loaded": str(path), "bytes": len(want), "addr": hex(addr)}, as_json=True)
            return
        have = _read(t, addr, len(want)) or b""
        diffs = [{"addr": hex(addr + i), "target": hex(y), "file": hex(x)}
                 for i, (x, y) in enumerate(zip(want, have)) if x != y][: a.max_report]
        emit({"ok": not diffs, "diff": diffs, "bytes": len(want)}, as_json=True)


def _reg_names() -> set[str]:
    return {f"r{i}" for i in range(13)} | {"sp", "lr", "pc", "xpsr"}


def _value_of(t, token: str) -> int:
    token = token.strip()
    if token.startswith("[") and token.endswith("]"):
        inner = token[1:-1]
        width = 4
        if ":" in inner:
            inner, w = inner.split(":", 1)
            width = int(w)
        total = 0
        for part in inner.split("+"):
            total += _value_of(t, part)
        raw = _read(t, total, width)
        if raw is None:
            die(f"Cannot read address {hex(total)}")
        return int.from_bytes(raw, "little")
    if token.lower() in _reg_names():
        return t.read_core_register(token.lower())
    return int(token, 0)


def eval_cond(t, expr: str) -> bool:
    m = re.match(r"^(.+?)\s*(==|!=|>=|<=|>|<)\s*(.+)$", expr.strip())
    if not m:
        die(f"Unsupported condition syntax: {expr} (example: r0 == 1 / [0x20000000] != 0)")
    lhs = _value_of(t, m.group(1))
    rhs = _value_of(t, m.group(3))
    op = m.group(2)
    return {"==": lhs == rhs, "!=": lhs != rhs, ">=": lhs >= rhs,
            "<=": lhs <= rhs, ">": lhs > rhs, "<": lhs < rhs}[op]


def cmd_disasm(a) -> None:
    ensure_runtime()
    from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs
    ei = ElfInfo(elf_path(a)) if (getattr(a, "elf", None) or load_config().get("elf")) else None
    s = _session(a, halt=False)
    with s:
        t = _core(s.target, a)
        if a.symbol:
            if ei is None:
                die("disasm needs --elf to resolve symbols")
            start = ei.symbols.get(a.symbol)
            if start is None:
                die(f"Symbol not found: {a.symbol}")
        elif a.at:
            start = int(a.at, 0)
        else:
            if _state_name(t) == "RUNNING":
                t.halt()
            start = t.read_core_register("pc") & ~1
        mode = CS_MODE_ARM if a.mode == "arm" else CS_MODE_THUMB
        code = bytes(t.read_memory_block8(start, a.count * 4))
        lines = []
        for ins in Cs(CS_ARCH_ARM, mode).disasm(code, start):
            item = {"addr": hex(ins.address), "bytes": ins.bytes.hex(),
                    "mnemonic": ins.mnemonic, "op_str": ins.op_str}
            if ei:
                item["symbol"] = ei.frame_name(ins.address)
            lines.append(item)
            if len(lines) >= a.count:
                break
    if a.json:
        emit({"ok": True, "start": hex(start), "instructions": lines}, as_json=True)
    else:
        for it in lines:
            sym = f"  ; {it['symbol']}" if it.get("symbol") else ""
            print(f"{it['addr']}  {it['bytes']:10} {it['mnemonic']:8} {it['op_str']}{sym}")


def cmd_sym(a) -> None:
    ensure_runtime()
    ei = ElfInfo(elf_path(a))
    if a.action == "list":
        items = [(n, addr) for n, addr in ei.symbols.items()]
        if a.value:
            items = [x for x in items if a.value.lower() in x[0].lower()]
        items.sort(key=lambda x: x[1])
        items = items[: a.limit]
        emit({"ok": True, "symbols": [{"name": n, "addr": hex(v)} for n, v in items]}, as_json=True)
    elif a.action == "find":
        if not a.value:
            die("sym find requires a symbol name")
        hits = [{"name": n, "addr": hex(v)} for n, v in ei.symbols.items() if a.value.lower() in n.lower()]
        emit({"ok": bool(hits), "query": a.value, "hits": hits[: a.limit]}, as_json=True)
    else:
        if not a.value:
            die("sym addr requires an address")
        addr = int(a.value, 0)
        ln = ei.line_for(addr)
        emit({"ok": True, "addr": hex(addr), "symbol": ei.frame_name(addr),
              "file": ln[0] if ln else None, "line": ln[1] if ln else None}, as_json=True)


def cmd_regset(a) -> None:
    ensure_runtime()
    value = int(a.value, 0)
    s = _session(a)
    with s:
        t = _core(s.target, a)
        t.write_core_register(a.name, value)
        emit({"ok": True, "register": a.name, "wrote": hex(value)}, as_json=True)


def cmd_rtos(a) -> None:
    """List RTOS threads using pyOCD's plugins (FreeRTOS/RTX5/ThreadX/Zephyr)."""
    ensure_runtime()
    from pyocd.debug.symbols import SymbolProvider
    from pyocd.rtos import RTOS

    class DictSymbols(SymbolProvider):
        def __init__(self, syms):
            self.syms = syms

        def get_symbol_value(self, name):
            return self.syms.get(name)

    ei = ElfInfo(elf_path(a))
    s = _session(a, halt=False)
    with s:
        t = _core(s.target, a)
        if _state_name(t) == "RUNNING":
            t.halt()
        try:
            from pyocd.debug.elf.elf import ELFBinaryFile
            t.elf = ELFBinaryFile(ei.path)
        except Exception:
            pass
        wanted = (a.rtos or "auto").lower()
        provider = None
        tried = []
        for name, cls in RTOS.items():
            if wanted != "auto" and name.lower() != wanted:
                continue
            tried.append(name)
            try:
                p = cls(t)
                if p.init(DictSymbols(ei.symbols)):
                    provider = p
                    break
            except Exception:
                continue
        if provider is None:
            die(f"Failed to load RTOS plugin (tried: {', '.join(tried) or wanted}). Check that the ELF has symbols and the firmware really uses that RTOS")
        threads = []
        for th in provider.get_threads():
            item = {"id": th.unique_id, "name": th.name, "description": th.description,
                    "current": getattr(th, "is_current", False)}
            for attr in ("priority", "state"):
                try:
                    item[attr] = getattr(th, attr)
                except Exception:
                    pass
            try:
                item["sp"] = hex(th.get_stack_pointer())
            except Exception:
                pass
            threads.append(item)
        emit({"ok": True, "rtos": provider.__class__.__name__, "threads": threads}, as_json=True)


def _find_gdb() -> str | None:
    for cand in (os.environ.get("DAP_GDB"), "arm-none-eabi-gdb", "gdb-multiarch", "gdb"):
        if cand:
            p = shutil.which(cand)
            if p:
                return p
    return None


def cmd_gdb_batch(a) -> None:
    """Full GDB power (DWARF, expressions, conditionals) in one shot."""
    ensure_runtime()
    gdb = _find_gdb()
    if not gdb:
        die("No GDB found. Install gdb-multiarch or arm-none-eabi-gdb, or set DAP_GDB=/path/to/gdb")
    _session(a)  # fast fail when no probe
    if a.port:
        port = a.port
    else:
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            port = sk.getsockname()[1]
    args = [pyocd(), "gdbserver"] + common_session_opts(a) + ["-p", str(port)]
    server = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), 0.2):
                    break
            except OSError:
                if server.poll() is not None:
                    die("gdbserver failed to start (check probe/target)")
                time.sleep(0.1)
        else:
            die("gdbserver port not ready")
        cmd = [gdb, "-batch", "-nx"]
        if a.elf:
            cmd.append(a.elf)
        cmd += ["-ex", "set pagination off", "-ex", "set confirm off",
                "-ex", f"target extended-remote 127.0.0.1:{port}"]
        for ex in (a.ex or ["bt"]):
            cmd += ["-ex", ex]
        rc, out, err = run(cmd, timeout=a.timeout)
        emit({"ok": rc == 0, "op": "gdb-batch", "gdb": gdb, "port": port, "rc": rc,
              "stdout": out[-20000:], "stderr": err[-4000:]}, as_json=True)
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:
            server.kill()


# ---------------------------------------------------------------- DWARF types













# ------------------------------------------------------- CFI + expressions





# ---- DWARF type model -------------------------------------------------------











def _fmt_val(val: Val, dr, read) -> object:
    if val.addr is not None and val.tr and val.tr.get("die") is not None:
        try:
            return dr.fmt(val.tr["die"], val.tr["cu"], val.addr, read)
        except Exception:
            pass
    if val.tr and val.tr.get("kind") == "ptr":
        v = val.load(read)
        return None if v is None else hex(v)
    return val.load(read)









# ------------------------------------------------------------ memory & DP regs

def cmd_mem(a) -> None:
    ensure_runtime()
    s = _session(a)
    with s:
        t = _core(s.target, a)
        if a.mem_cmd == "read":
            n = a.count * (a.width // 8)
            data = bytes(t.read_memory_block8(a.address, n))
            if a.json:
                emit({"ok": True, "address": hex(a.address), "width": a.width, "count": a.count,
                      "hex": data.hex(), "bytes": list(data)}, as_json=True)
            else:
                for i in range(a.count):
                    off = i * a.width // 8
                    chunk = data[off:off + a.width // 8]
                    print(f"0x{a.address + off:08x}: {int.from_bytes(chunk, 'little'):0{a.width // 4}x}")
        else:
            if not a.values:
                die("write requires at least one value")
            data = b"".join(int(v, 0).to_bytes(a.width // 8, "little") for v in a.values)
            t.write_memory_block8(a.address, data)
            emit({"ok": True, "op": "mem_write", "address": hex(a.address), "wrote": len(data)}, as_json=True)


def cmd_dapreg(a) -> None:
    """Raw Debug Port register access (read_dap / write_dap equivalent)."""
    ensure_runtime()
    addr = int(a.addr, 0)
    s = _session(a)
    with s:
        dp = s.target.dp
        if a.dap_cmd == "read":
            val = dp.read_reg(addr)
            emit({"ok": True, "dp_reg": hex(addr), "value": hex(val)}, as_json=True)
        else:
            if a.value is None:
                die("write requires a value")
            dp.write_reg(addr, int(a.value, 0))
            emit({"ok": True, "dp_reg": hex(addr), "wrote": hex(int(a.value, 0))}, as_json=True)


def cmd_option(a) -> None:
    """Option-byte access with an explicit address (no chip magic)."""
    ensure_runtime()
    addr = int(a.addr, 0)
    width = a.width // 8
    s = _session(a)
    with s:
        t = _core(s.target, a)
        if a.option_cmd == "read":
            data = bytes(t.read_memory_block8(addr, width * a.count))
            emit({"ok": True, "address": hex(addr), "hex": data.hex(),
                  "words": [hex(int.from_bytes(data[i:i + width], "little"))
                            for i in range(0, len(data), width)]}, as_json=True)
        else:
            if not a.yes:
                die("Writing option bytes requires --yes (irreversible, may brick the chip)")
            if a.value is None:
                die("write requires --value")
            t.write_memory_block8(addr, int(a.value, 0).to_bytes(width, "little"))
            emit({"ok": True, "address": hex(addr), "wrote": hex(int(a.value, 0))}, as_json=True)


# ------------------------------------------------------- breakpoints/watchpoints

def _bp_load() -> list[dict]:
    try:
        return json.loads(BP_REGISTRY.read_text())
    except Exception:
        return []


def _bp_save(bps: list[dict]) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    BP_REGISTRY.write_text(json.dumps(bps, indent=2))


def _resolve_bp_target(a, value: str) -> int:
    """Accept 0xADDR, SYMBOL, or file.c:LINE."""
    m = re.fullmatch(r"(.+):(\d+)", value.strip())
    if m and not re.fullmatch(r"0x[0-9a-fA-F]+:\d+", value.strip()):
        fname, line = m.group(1), int(m.group(2))
        ei = ElfInfo(elf_path(a))
        hits = [addr for addr, f, ln in ei.lines if f.endswith(fname) and ln == line]
        if not hits:
            die(f"Cannot find an instruction address for {fname}:{line} (build with -g and check the path)")
        return min(hits)
    return resolve_addr(a, value)


def cmd_bp(a) -> None:
    ensure_runtime()
    from pyocd.core.target import Target
    kinds = {"hw": Target.BreakpointType.HW, "sw": Target.BreakpointType.SW, "auto": Target.BreakpointType.AUTO}
    if a.bp_cmd == "list":
        merged = _bp_load() + list(_fbp_load().values())
        emit({"ok": True, "breakpoints": merged}, as_json=True)
        return
    if a.bp_cmd == "clear":
        reg = _bp_load()
        if a.all:
            s = _session(a)
            with s:
                t = _core(s.target, a)
                for b in reg:
                    try:
                        t.remove_breakpoint(int(b["addr"], 0))
                    except Exception:
                        pass
                for faddr in list(_fbp_load()):
                    try:
                        _flash_bp_clear(t, int(faddr, 0))
                    except Exception:
                        pass
            _bp_save([])
            emit({"ok": True, "cleared": "all"}, as_json=True)
            return
        if not a.addr:
            die("clear requires an address or --all")
        addr = _resolve_bp_target(a, a.addr)
        s = _session(a)
        with s:
            t = _core(s.target, a)
            if _flash_bp_clear(t, addr):
                _bp_save([b for b in reg if int(b["addr"], 0) != addr])
                emit({"ok": True, "cleared": hex(addr), "type": "flash"}, as_json=True)
                return
            t.remove_breakpoint(addr)
        _bp_save([b for b in reg if int(b["addr"], 0) != addr])
        emit({"ok": True, "cleared": hex(addr)}, as_json=True)
        return
    # set
    addr = _resolve_bp_target(a, a.addr)
    if a.type == "flash":
        if not getattr(a, "yes", False):
            die("Flash breakpoints rewrite a whole sector; pass --yes to confirm")
        s = _session(a)
        with s:
            t = _core(s.target, a)
            entry = _flash_bp_set(t, addr)
        emit({"ok": True, "breakpoint": hex(addr), "type": "flash",
              "sector": entry["start"], "warning": "flash modified; restore with bp clear"}, as_json=True)
        return
    s = _session(a)
    with s:
        ok = s.target.set_breakpoint(addr, kinds[a.type])
        if ok:
            reg = [b for b in _bp_load() if int(b["addr"], 0) != addr]
            entry = {"addr": hex(addr), "type": a.type}
            if getattr(a, "cond", None):
                entry["cond"] = a.cond
            if getattr(a, "on_hit", None):
                entry["on_hit"] = a.on_hit
            if getattr(a, "log", None):
                entry["log"] = a.log
            reg.append(entry)
            _bp_save(reg)
    info = {"breakpoint": hex(addr), "type": a.type, "cond": getattr(a, "cond", None)}
    if a.wait:
        a.timeout = a.wait
        a.no_resume = False
        a._bp_note = info
        cmd_wait(a)
        return
    emit({"ok": bool(ok), **info}, as_json=True)


def cmd_wp(a) -> None:
    ensure_runtime()
    from pyocd.core.target import Target
    kinds = {"r": Target.WatchpointType.READ, "w": Target.WatchpointType.WRITE,
             "rw": Target.WatchpointType.READ_WRITE}
    if a.wp_cmd == "list":
        emit({"ok": True, "watchpoints": [b for b in _bp_load() if b.get("wp")]}, as_json=True)
        return
    if not a.addr:
        die("requires an address")
    addr = resolve_addr(a, a.addr)
    if a.wp_cmd == "set":
        s = _session(a)
        with s:
            ok = s.target.set_watchpoint(addr, a.size, kinds[a.type])
        if ok:
            reg = _bp_load()
            reg.append({"addr": hex(addr), "wp": True, "size": a.size, "type": a.type})
            _bp_save(reg)
        emit({"ok": bool(ok), "watchpoint": hex(addr), "size": a.size, "type": a.type}, as_json=True)
        return
    s = _session(a)
    with s:
        s.target.remove_watchpoint(addr, a.size, kinds[a.type])
    _bp_save([b for b in _bp_load() if int(b["addr"], 0) != addr])
    emit({"ok": True, "cleared": hex(addr)}, as_json=True)


# ------------------------------------------------------------------------ SVD

def cmd_svd(a) -> None:
    ensure_runtime()
    if a.svd_cmd == "attach":
        src = a.reg or a.file
        if not src:
            die("svd attach requires a .svd path")
        dev = load_svd(src)
        cfg = load_config()
        cfg["svd"] = str(Path(src).expanduser())
        save_config(cfg)
        emit({"ok": True, "svd": cfg["svd"], "device": dev.name,
              "peripherals": len(dev.peripherals)}, as_json=True)
        return
    dev = load_svd(svd_path(a))
    if a.svd_cmd == "list":
        data = [{"name": p.name, "base": hex(p.base_address),
                 "registers": len(iter_registers(p))} for p in dev.peripherals]
        if a.search:
            data = [d for d in data if a.search.lower() in d["name"].lower()]
        emit({"ok": True, "device": dev.name, "peripherals": data}, as_json=True)
        return

    if not a.reg:
        die("Requires PERIPH or PERIPH.REG")
    parts = a.reg.split(".")
    periph_name = parts[0]
    reg_name = parts[1] if len(parts) > 1 else None
    periph = find_peripheral(dev, periph_name)

    s = _session(a)
    with s:
        t = _core(s.target, a)
        if a.svd_cmd == "read":
            if not reg_name:
                out = {}
                for r in iter_registers(periph):
                    addr = reg_addr(periph, r)
                    try:
                        raw = int.from_bytes(t.read_memory_block8(addr, reg_size(r)), "little")
                        out[r.name] = {"value": hex(raw), "fields": decode_fields(raw, r)}
                    except Exception as e:
                        out[r.name] = {"error": str(e)}
                emit({"ok": True, "peripheral": periph.name, "base": hex(periph.base_address),
                      "registers": out}, as_json=True)
            else:
                r = find_register(periph, reg_name)
                raw = int.from_bytes(t.read_memory_block8(reg_addr(periph, r), reg_size(r)), "little")
                emit({"ok": True, "peripheral": periph.name, "register": r.name,
                      "address": hex(reg_addr(periph, r)), "value": hex(raw),
                      "fields": decode_fields(raw, r)}, as_json=True)
            return

        if a.svd_cmd == "write":
            if not reg_name:
                die("write requires PERIPH.REG")
            r = find_register(periph, reg_name)
            val = int(a.value, 0)
            t.write_memory_block8(reg_addr(periph, r), val.to_bytes(reg_size(r), "little"))
            emit({"ok": True, "register": r.name, "address": hex(reg_addr(periph, r)),
                  "wrote": hex(val)}, as_json=True)
            return

        # field get/set
        if not reg_name or len(parts) < 3:
            die("field requires PERIPH.REG.FIELD")
        fname = ".".join(parts[2:])
        r = find_register(periph, reg_name)
        fld = None
        for f in getattr(r, "fields", []) or []:
            if f.name.lower() == fname.lower():
                fld = f
                break
        if fld is None:
            die(f"Field {fname} not found; available: {', '.join(f.name for f in (r.fields or []))}")
        addr = reg_addr(periph, r)
        size = reg_size(r)
        raw = int.from_bytes(t.read_memory_block8(addr, size), "little")
        if a.value is None:
            emit({"ok": True, "field": fld.name, "value": field_value(raw, fld),
                  "bits": f"{fld.bit_offset}+{fld.bit_width}", "register": hex(raw)}, as_json=True)
        else:
            mask = ((1 << fld.bit_width) - 1) << fld.bit_offset
            new = (raw & ~mask) | ((int(a.value, 0) << fld.bit_offset) & mask)
            t.write_memory_block8(addr, new.to_bytes(size, "little"))
            emit({"ok": True, "field": fld.name, "wrote": int(a.value, 0),
                  "register": hex(new)}, as_json=True)


# --------------------------------------------------------------------- config

def cmd_config(a) -> None:
    cfg = load_config()
    if a.config_cmd == "list":
        emit({"ok": True, "config": cfg, "path": str(CONFIG)}, as_json=True)
        return
    if a.config_cmd == "get":
        emit({"ok": True, "key": a.key, "value": cfg.get(a.key)}, as_json=True)
        return
    if a.config_cmd == "set":
        if a.value is None:
            die("set requires key value")
        val: object = a.value
        if a.key == "frequency":
            val = int(a.value, 0)
        cfg[a.key] = val
        save_config(cfg)
        emit({"ok": True, "set": {a.key: val}}, as_json=True)
        return
    if a.config_cmd == "unset":
        cfg.pop(a.key, None)
        save_config(cfg)
        emit({"ok": True, "removed": a.key}, as_json=True)


# ------------------------------------------------------------------ RTT / GDB

def cmd_rtt(a) -> None:
    if _engine(a) != "probe-rs":
        ensure_runtime()
    if _engine(a) == "probe-rs":
        if a.address or a.size or a.mode:
            die("--address/--size/--mode are pyOCD-only; probe-rs locate RTT via the ELF control block")
        elf = getattr(a, "elf", None) or load_config().get("elf")
        args = ["attach"] + ([str(elf)] if elf else []) + _prs_common(a)
        print(f"[rtt/probe-rs] {' '.join(args)}", file=sys.stderr)
        try:
            subprocess.run([probe_rs_bin()] + args, timeout=a.duration, text=True)
        except subprocess.TimeoutExpired:
            print(f"\n[rtt] stopped after {a.duration}s", file=sys.stderr)
        return
    args = ["rtt", "-W"] + common_session_opts(a)
    if a.address:
        args += ["-a", a.address]
    if a.size:
        args += ["-s", str(a.size)]
    if a.log:
        args += ["-d", a.log]
    if a.mode:
        args += ["-M", a.mode]
    print(f"[rtt] {' '.join(args)}", file=sys.stderr)
    try:
        subprocess.run([pyocd()] + args, timeout=a.duration, text=True)
    except subprocess.TimeoutExpired:
        print(f"\n[rtt] stopped after {a.duration}s", file=sys.stderr)
    if a.log and Path(a.log).exists():
        print(Path(a.log).read_text()[-20000:])


def cmd_gdb(a) -> None:
    if _engine(a) != "probe-rs":
        ensure_runtime()
    if _engine(a) == "probe-rs":
        elf = getattr(a, "elf", None) or load_config().get("elf")
        args = (["gdb", "--gdb-connection-string", f"127.0.0.1:{a.port}"]
                + ([str(elf)] if elf else []) + _prs_common(a))
        print(f"[gdb/probe-rs] {' '.join(args)}", file=sys.stderr)
        if a.detach:
            log = Path(a.log or (HOME / "gdbserver.log"))
            log.parent.mkdir(parents=True, exist_ok=True)
            fh = open(log, "ab")
            p = subprocess.Popen([probe_rs_bin()] + args, stdout=fh, stderr=fh, start_new_session=True)
            emit({"ok": True, "engine": "probe-rs", "pid": p.pid, "port": a.port, "log": str(log)}, as_json=True)
            return
        rc, out, err = _prs(args, a.timeout)
        sys.stdout.write(out)
        sys.stderr.write(err)
        sys.exit(rc)
    args = ["gdbserver", "-W"] + common_session_opts(a) + ["-p", str(a.port)]
    if a.persist:
        args.append("--persist")
    print(f"[gdb] {' '.join(args)}", file=sys.stderr)
    print(f"[gdb] arm-none-eabi-gdb -ex 'target extended-remote :{a.port}' <elf>", file=sys.stderr)
    if a.detach:
        log = Path(a.log or (HOME / "gdbserver.log"))
        log.parent.mkdir(parents=True, exist_ok=True)
        fh = open(log, "ab")
        p = subprocess.Popen([pyocd()] + args, stdout=fh, stderr=fh, start_new_session=True)
        emit({"ok": True, "pid": p.pid, "port": a.port, "log": str(log)}, as_json=True)
        return
    rc, out, err = run([pyocd()] + args, timeout=a.timeout)
    sys.stdout.write(out)
    sys.stderr.write(err)
    sys.exit(rc)


# ---------------------------------------------------------------------- parser

# ------------------------------------------------------- fault diagnosis / report

def _reg_or_none(t, name):
    try:
        return t.read_core_register(name)
    except Exception:
        return None


def _snapshot_fault(a, ei: ElfInfo | None, dr: DwarfReader | None) -> dict:
    """Capture everything a post-mortem needs in one session."""
    import datetime
    s = _session(a, halt=False)
    with s:
        t = _core(s.target, a)
        if _state_name(t) == "RUNNING":
            try:
                t.halt()
            except Exception:
                pass
        regs = {}
        for name in ("r0", "r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9",
                     "r10", "r11", "r12", "sp", "lr", "pc", "xpsr", "msp", "psp",
                     "control", "primask", "basepri", "faultmask"):
            v = _reg_or_none(t, name)
            if v is not None:
                regs[name] = v
        fault = {}
        for name, addr in (("CFSR", 0xE000ED28), ("HFSR", 0xE000ED2C), ("DFSR", 0xE000ED30),
                           ("MMFAR", 0xE000ED34), ("BFAR", 0xE000ED38), ("SHCSR", 0xE000ED24),
                           ("ICSR", 0xE000ED04), ("CPUID", 0xE000ED00)):
            try:
                fault[name] = t.read32(addr)
            except Exception:
                pass
        regions = []
        try:
            for r in t.memory_map:
                regions.append({"name": getattr(r, "name", "") or "",
                                "start": r.start, "end": r.end,
                                "type": getattr(getattr(r, "type", None), "name", "")})
        except Exception:
            pass
        stack_words = []
        sp = regs.get("sp", 0)
        for i in range(96):
            w = None
            try:
                w = t.read32(sp + 4 * i)
            except Exception:
                break
            stack_words.append({"addr": sp + 4 * i, "value": w})
        frame = None
        lr = regs.get("lr")
        if lr is not None and (lr & 0xF0000000) == 0xF0000000:
            frame = unwind_exception_frame(t, lr, regs)
        pc = regs.get("pc", 0) & ~1
        center = pc
        if frame and isinstance(frame.get("faulting_pc"), str):
            try:
                center = int(frame["faulting_pc"], 16) & ~1
            except Exception:
                pass
        disasm = []
        try:
            from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
            start = max(0, center - 16)
            code = _read(t, start, 24 * 4) or b""
            for ins in Cs(CS_ARCH_ARM, CS_MODE_THUMB).disasm(code, start):
                disasm.append({"addr": ins.address, "bytes": ins.bytes.hex(),
                               "mnemonic": ins.mnemonic, "op_str": ins.op_str})
                if len(disasm) >= 24:
                    break
        except Exception:
            pass
        btframes = _bt_frames(t, ei, 16, 512)[1] if ei else []
        init_sp = None
        try:
            init_sp = t.read32(0) & ~3
        except Exception:
            pass
        stack = {"initial_sp": init_sp, "sp": sp,
                 "used": (init_sp - sp) if init_sp else None}
        try:
            for r in regions:
                if init_sp is not None and r["start"] <= init_sp < r["end"]:
                    stack["region"] = f"{r['name']} {hex(r['start'])}-{hex(r['end'])}"
                    stack["overflow"] = sp < r["start"]
                    break
        except Exception:
            pass
        snap = {
            "captured_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "elf": ei.path if ei else None,
            "target": getattr(t, "part_number", None) or a.target,
            "state": _state_name(t), "halt_reason": _halt_reason(t),
            "registers": regs, "fault": fault, "stack": stack,
            "fault_pc": center,
            "exception_frame": frame, "backtrace": btframes,
            "regions": regions, "disasm": disasm, "stack_words": stack_words,
        }
    return snap


FAULT_BITS = {
    "IACCVIOL": "instruction access violation: jumped into a non-executable region (bad function pointer or smashed PC)",
    "DACCVIOL": "data access violation: touched an MPU-protected region",
    "MUNSTKERR": "fault while unstacking on exception return: stack pointer corrupted",
    "MSTKERR": "fault while stacking: stack out of bounds or invalid SP",
    "MMARVALID": "MMFAR is valid",
    "IBUSERR": "instruction bus error: PC points at an invalid address",
    "PRECISERR": "precise bus error: the faulting instruction is the current PC",
    "IMPRECISERR": "imprecise bus error: write buffer reported late, PC is not the culprit",
    "UNSTKERR": "bus error while unstacking on exception return: stack corrupted",
    "STKERR": "bus error while stacking: stack overflow or SP out of range",
    "BFARVALID": "BFAR is valid",
    "UNDEFINSTR": "undefined instruction: executed data or a corrupt instruction stream",
    "INVSTATE": "invalid state: Thumb bit corrupted (bad function pointer or return address)",
    "INVPC": "invalid PC: exception return address is not valid",
    "NOCP": "no coprocessor: FPU instruction executed while the FPU is disabled",
    "UNALIGNED": "unaligned access: packed struct or a bad pointer cast",
    "DIVBYZERO": "division by zero",
    "VECTTBL": "vector table read failed: vector table address or contents corrupted",
    "FORCED": "escalated from MemManage/BusFault/UsageFault (see CFSR bits)",
    "LOCKUP": "core is in LOCKUP: usually the HardFault handler faulted again",
    "DEBUGEVT": "debug event caused the HardFault",
}


def _region_of(addr: int, regions: list[dict]) -> dict | None:
    for r in regions:
        if r["start"] <= addr < r["end"]:
            return r
    return None


def _classify_addr(addr: int, regions: list[dict]) -> str:
    if addr < 0x1000:
        return f"near NULL (0x{addr:x}): a struct/object pointer was NULL when accessed"
    r = _region_of(addr, regions)
    if r:
        kind = r.get("type") or ""
        if kind == "RAM":
            return f"inside RAM ({r['name']}): out-of-bounds array or wild pointer, not a peripheral issue"
        if kind in ("FLASH", "ROM"):
            return "inside Flash/ROM: write to a read-only region, or a data value used as a pointer"
        if kind == "DEVICE":
            return f"peripheral/device region ({r['name']}): peripheral clock disabled, wrong offset, or wrong access width"
        return f"memory region {r['name']} ({kind})"
    if 0x40000000 <= addr < 0x60000000:
        return "peripheral region (not in the memory map): typically a disabled clock or a wrong base address"
    if 0x08000000 <= addr < 0x10000000:
        return "Flash region: write protection, or a constant used as a pointer"
    if 0x20000000 <= addr < 0x40000000:
        return "SRAM region (not in the map): wild pointer or stack overrun"
    if addr >= 0xE0000000:
        return "system/private peripheral region: out-of-range SCB/NVIC/SysTick access"
    return "unmapped address: wild or corrupted pointer"


def analyze_fault(snap: dict, ei: ElfInfo | None = None) -> list[dict]:
    """Rule engine -> ranked root-cause hypotheses with evidence."""
    hyps: list[dict] = []
    regs = snap.get("registers", {})
    fault = snap.get("fault", {})
    regions = snap.get("regions", [])
    stack = snap.get("stack", {})
    frame = snap.get("exception_frame") or {}
    bt = snap.get("backtrace", [])
    pc = regs.get("pc", 0) & ~1
    sp = regs.get("sp", 0)
    cfsr = fault.get("CFSR", 0)
    hfsr = fault.get("HFSR", 0)

    def add(score, category, cause, evidence, nxt):
        hyps.append({"score": score, "category": category, "cause": cause,
                     "evidence": evidence, "next": nxt})

    # 1. exception frame / stacked PC tells the real location for synchronous faults
    # 2. fault bit decode
    bits = []
    for name, desc in FAULT_BITS.items():
        if name in ("FORCED", "MMARVALID", "BFARVALID"):
            continue
        if name in ("LOCKUP",):
            if snap.get("state") == "LOCKUP":
                bits.append((name, desc))
            continue
        if name in ("VECTTBL",):
            if hfsr & (1 << 1):
                bits.append((name, desc))
            continue
        if name == "DEBUGEVT":
            if hfsr & (1 << 31):
                bits.append((name, desc))
            continue
        # CFSR bit positions
        pos = {"IACCVIOL": 0, "DACCVIOL": 1, "MUNSTKERR": 3, "MSTKERR": 4,
               "IBUSERR": 8, "PRECISERR": 9, "IMPRECISERR": 10, "UNSTKERR": 11, "STKERR": 12,
               "UNDEFINSTR": 16, "INVSTATE": 17, "INVPC": 18, "NOCP": 19,
               "UNALIGNED": 24, "DIVBYZERO": 25}.get(name)
        if pos is not None and cfsr & (1 << pos):
            bits.append((name, desc))

    if hfsr & (1 << 30) and not bits:
        add(0.55, "unknown", "HardFault with CFSR=0: possible double fault or failed exception return",
            [f"HFSR=0x{hfsr:08x}"], ["check whether the stack was corrupted", "inspect exception_frame", "single-step to catch the original exception"])

    for name, desc in bits:
        if name == "IMPRECISERR":
            continue  # handled below with more context
        score = 0.9 if name in ("PRECISERR", "STKERR", "MSTKERR", "IBUSERR", "UNDEFINSTR",
                                "INVSTATE", "INVPC", "DIVBYZERO", "UNALIGNED", "NOCP") else 0.75
        add(score, name, desc, [f"CFSR bit {name}"], [])

    # 3. PC sanity
    exec_regions = []
    if ei:
        exec_regions = ei.exec_ranges
    pc_in_code = any(lo <= pc < hi for lo, hi in exec_regions) if exec_regions else True
    if pc == 0 or pc == 0xFFFFFFFF:
        add(0.98, "pc", "PC is 0/all ones: jumped to a null address or erased flash",
            [f"PC=0x{pc:08x}"],
            ["check the jump table / function pointer init", "verify the first vector table entry", "use faulting_pc to find the real fault site"])
    elif exec_regions and not pc_in_code:
        add(0.93, "pc", "PC is outside every executable segment: executing data or stack contents",
            [f"PC=0x{pc:08x}", f"exec ranges: {[hex(a) for a, _ in exec_regions][:4]}"],
            ["check function pointers, callback tables, and stack-smashed return addresses", "verify the linker script"])
    elif pc & 1 and snap.get("registers", {}).get("pc", 0) & 1:
        add(0.6, "pc", "PC bit0=1: corrupted Thumb state bit", [f"PC=0x{pc:08x}"], ["check indirect jump targets"])

    # 4. stacked frame coherence
    if frame.get("error"):
        add(0.85, "stack", f"Cannot read the exception frame: {frame['error']}", [f"SP=0x{sp:08x}"],
            ["verify SP is inside RAM", "check for stack overflow"])
    elif frame.get("faulting_pc"):
        ev = [f"faulting_pc={frame['faulting_pc']}", f"stacked_lr={frame.get('faulting_lr')}"]
        cause = "the exception frame points at the real fault address"
        if ei:
            try:
                fa = int(frame["faulting_pc"], 16) & ~1
                if ei.in_code(fa):
                    sym = ei.frame_name(fa)
                    ln = ei.line_for(fa)
                    cause = f"fault site: {sym}" + (f" ({ln[0]}:{ln[1]})" if ln else "")
                    ev.append(f"symbol={sym}")
                else:
                    cause = "faulting PC in the exception frame is not in an executable segment (data/invalid address)"
            except Exception:
                pass
        add(0.78, "frame", cause, ev,
            ["use disasm --at <faulting_pc> to inspect the faulting instruction", "check the pointer/array access there"])

    # 5. fault address classification
    for regname, valid_bit, bitname in (("BFAR", "BFARVALID", "BusFault"), ("MMFAR", "MMARVALID", "MemManage")):
        valid = bool((cfsr >> (15 if regname == "BFAR" else 7)) & 1)
        addr = fault.get(regname, 0)
        if addr and (valid or addr < 0x1000 or _region_of(addr, regions) is not None):
            add(0.9 if valid else 0.72, "address",
                f"{bitname} accessed 0x{addr:08x}: {_classify_addr(addr, regions)}",
                [f"{regname}=0x{addr:08x}", f"{valid_bit}={'set' if valid else 'clear (inferred from address)'}"],
                ["trace back which object/peripheral owns that address", "for peripherals: check the RCC clock enable and register offset", "use snapshot diff to find who corrupted the region"])

    # 6. stack
    if stack.get("overflow"):
        add(0.97, "stack", "SP is outside the RAM region: stack overflow",
            [f"SP=0x{sp:08x}", str(stack.get("region"))],
            ["increase the stack / shrink large locals", "check for recursion", "place a sentinel at the stack bottom"])
    elif stack.get("used") is not None and stack.get("initial_sp"):
        if stack["used"] > 0 and stack["used"] > 0x3000:
            add(0.7, "stack", f"Stack already uses {stack['used']} bytes, close to or beyond a typical budget",
                [f"initial_sp=0x{stack['initial_sp']:08x}", f"SP=0x{sp:08x}"],
                ["use snapshot to compare stack depth across paths", "check for large local arrays"])
    if sp == 0 or sp == 0xFFFFFFFF:
        add(0.96, "stack", "SP is 0/all ones: stack pointer completely destroyed", [f"SP=0x{sp:08x}"],
            ["check for stack overflow or a wild pointer write"])

    # 7. backtrace hints
    names = [f.get("symbol", "") for f in bt]
    joined = " | ".join(names)
    for marker, cause in (("__stack_chk_fail", "stack protector fired: buffer overflow"),
                          ("abort", "abort()/assertion failure"),
                          ("malloc", "heap corruption (malloc/free metadata damaged)"),
                          ("HardFault_Handler", "already inside the HardFault handler")):
        if marker in joined:
            add(0.65, "backtrace", cause, [f"backtrace contains {marker}"], ["inspect the code near that frame"])

    # 8. register-value oddities that commonly mean corruption
    if regs.get("lr", 0) & 1 and regs.get("lr", 0) not in (0xFFFFFFFF,):
        pass
    if regs.get("xpsr") is not None and (regs["xpsr"] >> 9) & 1:
        pass

    # 9. imprecise bus fault caveat
    if cfsr & (1 << 10):
        add(0.8, "imprecise", "imprecise bus error: the real write may have happened earlier",
            ["CFSR.IMPRECISERR=1"],
            ["disable the write buffer / add DSB to reproduce", "use snapshot diff to find the corrupted address", "check DMA destination addresses"])

    if not hyps:
        add(0.2, "unknown", "no definitive fault flag matched",
            [f"state={snap.get('state')}", f"CFSR=0x{cfsr:08x}", f"HFSR=0x{hfsr:08x}"],
            ["confirm the target is really crashed (it may just be sleeping or at a breakpoint)", "use bt / disasm to see where it is", "read the tail of the RTT log"])

    hyps.sort(key=lambda h: -h["score"])
    # dedupe by cause text
    seen, out = set(), []
    for h in hyps:
        if h["cause"] in seen:
            continue
        seen.add(h["cause"])
        out.append(h)
    return out[:8]


def _fmt_addr(v):
    return f"0x{v:08x}" if isinstance(v, int) else str(v)


def render_fault_text(snap: dict, hyps: list[dict], ei: ElfInfo | None) -> str:
    L = []
    L.append("=" * 66)
    L.append(f" Fault diagnosis  {snap.get('target') or ''}   state={snap.get('state')}  "
             f"halt={snap.get('halt_reason')}")
    L.append("=" * 66)
    for i, h in enumerate(hyps):
        bar = "#" * max(1, int(h["score"] * 20))
        L.append(f"[{i + 1}] {int(h['score'] * 100):3d}% {bar}")
        L.append(f"    {h['cause']}")
        for e in h["evidence"]:
            L.append(f"      - {e}")
        if h["next"]:
            L.append(f"      -> {'; '.join(h['next'])}")
    regs = snap.get("registers", {})
    L.append("-" * 66)
    L.append(" PC=%s  LR=%s  SP=%s  xPSR=%s" % (_fmt_addr(regs.get("pc")), _fmt_addr(regs.get("lr")),
                                               _fmt_addr(regs.get("sp")), _fmt_addr(regs.get("xpsr"))))
    fl = snap.get("fault", {})
    L.append(" CFSR=%s HFSR=%s BFAR=%s MMFAR=%s" % (_fmt_addr(fl.get("CFSR")), _fmt_addr(fl.get("HFSR")),
                                                    _fmt_addr(fl.get("BFAR")), _fmt_addr(fl.get("MMFAR"))))
    if snap.get("stack", {}).get("used") is not None:
        L.append(f" stack used: {snap['stack']['used']} bytes (initial_sp={_fmt_addr(snap['stack'].get('initial_sp'))})")
    if ey := snap.get("exception_frame"):
        L.append(f" exception frame: {ey.get('sp_used')} faulting_pc={ey.get('faulting_pc')} lr={ey.get('faulting_lr')}")
    if snap.get("backtrace"):
        L.append("-" * 66)
        L.append(" Backtrace:")
        for i, f in enumerate(snap["backtrace"][:12]):
            loc = f" ({f['file']}:{f['line']})" if f.get("file") else ""
            L.append(f"   #{i:<2} {f.get('symbol', '?'):<40} {_fmt_addr(f.get('pc'))}{loc}  via {f.get('via')}")
    L.append("=" * 66)
    return "\n".join(L)


HTML_CSS = """
:root{--bg:#0f1115;--panel:#171a21;--line:#262b36;--fg:#e6e9ef;--dim:#8b93a7;
--red:#ff5d5d;--amber:#ffb454;--green:#59d98e;--blue:#5da9ff;--purple:#c792ea}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.wrap{max-width:1180px;margin:0 auto;padding:28px 22px 60px}
h1{font-size:20px;margin:0 0 4px;font-weight:600;letter-spacing:.02em}
.sub{color:var(--dim);font-size:12px;margin-bottom:22px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin-bottom:16px}
.card h2{font-size:12px;text-transform:uppercase;letter-spacing:.12em;color:var(--dim);margin:0 0 12px;font-weight:600}
.hyp{border-left:3px solid var(--red);padding:10px 14px;margin:10px 0;background:#1b1f27;border-radius:0 8px 8px 0}
.hyp.med{border-color:var(--amber)}.hyp.low{border-color:var(--dim)}
.hyp .cause{font-size:15px;margin-bottom:6px}
.hyp .ev{color:var(--dim);font-size:12px}
.pct{float:right;font-weight:700;color:var(--red)}.med .pct{color:var(--amber)}.low .pct{color:var(--dim)}
.bar{height:4px;background:#242a35;border-radius:2px;margin:8px 0 2px;overflow:hidden}
.bar>i{display:block;height:100%;background:linear-gradient(90deg,var(--red),var(--amber))}
table{width:100%;border-collapse:collapse;font-size:12.5px}
td,th{padding:5px 8px;text-align:left;border-bottom:1px solid #20242e;white-space:nowrap}
th{color:var(--dim);font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:.08em}
tr.hit td{background:#3a1618;color:#ffd7d7}
tr.pc td{background:#2a2312;color:#ffe3a8}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 16px;font-size:13px}
.kv b{color:var(--dim);font-weight:400}
.tag{display:inline-block;padding:1px 7px;border-radius:99px;font-size:11px;border:1px solid var(--line);color:var(--dim)}
.mrow{display:grid;grid-template-columns:170px 1fr;gap:12px;align-items:center;margin:7px 0}
.mrow .nm{font-size:12px;color:var(--fg)}.mrow .nm span{color:var(--dim);font-size:10px}
.track{position:relative;height:26px;background:#12151b;border:1px solid var(--line);border-radius:6px;overflow:hidden}
.track.fault{border-color:#5a2a2d;background:#1a1114}
.track .fill{position:absolute;inset:0;opacity:.22}
.track .mk{position:absolute;top:0;bottom:0;width:2px}
.track .mk b{position:absolute;top:-15px;left:50%;transform:translateX(-50%);font-size:9px;font-weight:600;letter-spacing:.04em}
.legend{font-size:10.5px;color:var(--dim);margin-top:8px}
.legend i{display:inline-block;width:8px;height:8px;border-radius:2px;margin:0 4px 0 12px}
.hex{font-size:12px;color:var(--dim)}.hex b{color:var(--fg)}.hex .ra{color:var(--green)}
pre{background:#12151b;border:1px solid var(--line);border-radius:8px;padding:12px;overflow:auto;font-size:12px}
.foot{color:var(--dim);font-size:11px;margin-top:26px}
"""


def _hexdump(words: list[dict], frames: list[dict], base: int) -> str:
    frame_addrs = {int(f["pc"]) for f in frames if f.get("pc") is not None}
    out = []
    for i in range(0, len(words), 2):
        chunk = words[i:i + 2]
        cells = []
        for w in chunk:
            val = w["value"]
            cls = "ra" if (val & ~1) in frame_addrs else ""
            cells.append(f'<span class="{cls}">0x{val:08x}</span>')
        out.append(f'<span class="hex">{_fmt_addr(chunk[0]["addr"])} &nbsp; {" &nbsp; ".join(cells)}</span>')
    return "<br>".join(out)


def _bt_row(i: int, f: dict) -> str:
    import html as H
    loc = f"{f.get('file')}:{f.get('line')}" if f.get("file") else ""
    return (f"<tr><td>#{i}</td><td>{H.escape(str(f.get('symbol', '?')))}</td>"
            f"<td>{_fmt_addr(f.get('pc'))}</td><td>{H.escape(loc)}</td>"
            f"<td>{H.escape(str(f.get('via')))}</td></tr>")


def render_fault_html(snap: dict, hyps: list[dict], path: Path) -> None:
    import html as H
    regs = snap.get("registers", {})
    fault = snap.get("fault", {})
    frames = snap.get("backtrace", [])
    disasm = snap.get("disasm", [])
    regions = snap.get("regions", [])
    fault_pc = snap.get("fault_pc") or regs.get("pc", 0)
    pc = regs.get("pc", 0)

    cards = []
    for h in hyps:
        cls = "" if h["score"] >= 0.85 else ("med" if h["score"] >= 0.6 else "low")
        ev = "".join(f"<div class='ev'>· {H.escape(str(e))}</div>" for e in h["evidence"])
        nxt = "".join(f"<div class='ev'>→ {H.escape(str(x))}</div>" for x in h["next"])
        cards.append(f"<div class='hyp {cls}'><span class='pct'>{int(h['score'] * 100)}%</span>"
                     f"<div class='cause'>{H.escape(h['cause'])}</div>"
                     f"<div class='bar'><i style='width:{int(h['score'] * 100)}%'></i></div>{ev}{nxt}</div>")

    # memory map: one row per region, markers inside their own region
    colors = {"RAM": "#2f6f4f", "FLASH": "#2f4f7f", "ROM": "#2f4f7f", "DEVICE": "#6f4f2f"}
    markers = [("PC", regs.get("pc"), "#ff5d5d"), ("SP", regs.get("sp"), "#5da9ff")]
    for k, c in (("BFAR", "#ffb454"), ("MMFAR", "#c792ea")):
        if (snap.get("fault") or {}).get(k):
            markers.append((k, snap["fault"][k], c))
    if snap.get("fault_pc"):
        markers.append(("FAULT", snap["fault_pc"], "#ff5d5d"))
    rows, used = [], set()
    for r in regions:
        pos_marks = []
        faulted = False
        for name, addr, color in markers:
            if addr and r["start"] <= addr < r["end"]:
                pos = (addr - r["start"]) / max(1, r["end"] - r["start"]) * 100
                pos_marks.append(f"<div class='mk' style='left:{pos:.2f}%;background:{color}' title='{name} {_fmt_addr(addr)}'></div>")
                used.add(name)
                if name in ("BFAR", "MMFAR", "FAULT"):
                    faulted = True
        fill = colors.get(r.get("type") or "", "#3a4150")
        rows.append(f"<div class='mrow'><div class='nm'>{H.escape(r['name'] or r.get('type') or '-')}"
                    f"<br><span>{_fmt_addr(r['start'])} - {_fmt_addr(r['end'])} ({r.get('type') or '?'})</span></div>"
                    f"<div class='track{' fault' if faulted else ''}'>"
                    f"<div class='fill' style='background:{fill}'></div>{''.join(pos_marks)}</div></div>")
    outside = [(n, a, c) for n, a, c in markers if a and n not in used]
    if outside:
        marks = "".join(f"<div class='mk' style='left:{10 + i * 18}%;background:{c}' title='{n} {_fmt_addr(a)}'></div>"
                        for i, (n, a, c) in enumerate(outside))
        rows.append("<div class='mrow'><div class='nm'>unmapped<br><span>outside every known region</span></div>"
                    f"<div class='track fault'><div class='fill' style='background:#3a2026'></div>{marks}</div></div>")
    legend = ("<div class='legend'>" +
              "".join(f"<i style='background:{c}'></i>{n}" for n, _, c in
                      [("PC/FAULT", 0, "#ff5d5d"), ("SP", 0, "#5da9ff"), ("BFAR", 0, "#ffb454"), ("MMFAR", 0, "#c792ea")]) +
              "</div>")
    memmap = "".join(rows) + legend

    reg_rows = "".join(f"<tr><td>{k}</td><td>{_fmt_addr(v)}</td></tr>" for k, v in regs.items())
    fl_rows = "".join(f"<tr><td>{k}</td><td>{_fmt_addr(v)}</td></tr>" for k, v in fault.items())
    fl_notes = "".join(f"<tr><td>{H.escape(n)}</td><td>{H.escape(d)}</td></tr>"
                       for n, d in FAULT_BITS.items() if _bit_active(n, fault))
    bt_rows = "".join(_bt_row(i, f) for i, f in enumerate(frames))
    dis_rows = "".join(
        f"<tr class='{'pc' if ins['addr'] == (fault_pc & ~1) else ''}'>"
        f"<td>{_fmt_addr(ins['addr'])}</td><td>{ins['bytes']}</td>"
        f"<td>{H.escape(ins['mnemonic'])}</td><td>{H.escape(ins['op_str'])}</td></tr>" for ins in disasm)
    frame = snap.get("exception_frame") or {}
    stack = snap.get("stack", {})
    rtt = snap.get("rtt_tail") or []
    rtt_html = "<pre>" + H.escape("\n".join(rtt[-40:])) + "</pre>" if rtt else ""
    verdict = H.escape(hyps[0]["cause"]) if hyps else "unknown"

    doc = f"""<!doctype html><html lang="zh"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fault report - {H.escape(str(snap.get('target') or 'target'))}</title>
<style>{HTML_CSS}</style><div class="wrap">
<h1>Fault report <span class="tag">{H.escape(str(snap.get('target') or 'unknown'))}</span>
<span class="tag">{H.escape(str(snap.get('state')))}</span></h1>
<div class="sub">{H.escape(snap.get('captured_at', ''))} · ELF: {H.escape(str(snap.get('elf') or '-'))} · halt: {H.escape(str(snap.get('halt_reason')))}</div>
<div class="card"><h2>Summary</h2><div style="font-size:17px;margin-bottom:10px">{verdict}</div>
<div class="kv"><b>Fault PC</b><span>{_fmt_addr(fault_pc)}</span><b>Current PC</b><span>{_fmt_addr(pc)}</span><b>LR</b><span>{_fmt_addr(regs.get('lr'))}</span>
<b>SP</b><span>{_fmt_addr(regs.get('sp'))}</span><b>Stack used</b><span>{stack.get('used', '?')} bytes</span></div></div>
<div class="card"><h2>Address space</h2>{memmap}</div>
<div class="card"><h2>Root causes (ranked)</h2>{''.join(cards)}</div>
<div class="grid"><div class="card"><h2>Exception frame</h2>
<div class="kv"><b>Stack used</b><span>{H.escape(str(frame.get('sp_used', '-')))}</span>
<b>faulting PC</b><span>{H.escape(str(frame.get('faulting_pc', '-')))}</span>
<b>stacked LR</b><span>{H.escape(str(frame.get('faulting_lr', '-')))}</span></div>
</div><div class="card"><h2>Fault flags</h2><table><tr><th>Bit</th><th>Meaning</th></tr>{fl_notes or '<tr><td>-</td><td>none</td></tr>'}</table></div></div>
<div class="card"><h2>Backtrace</h2><table><tr><th>#</th><th>Symbol</th><th>PC</th><th>Location</th><th>Via</th></tr>{bt_rows or '<tr><td colspan=5>-</td></tr>'}</table></div>
<div class="card"><h2>Disassembly at fault</h2><table><tr><th>Address</th><th>Bytes</th><th>Insn</th><th>Operands</th></tr>{dis_rows or '<tr><td colspan=4>- requires --elf</td></tr>'}</table></div>
<div class="card"><h2>Stack (green = plausible return address)</h2>{_hexdump(snap.get('stack_words', []), frames, regs.get('sp', 0)) or '-'}</div>
<div class="grid"><div class="card"><h2>Core registers</h2><table>{reg_rows}</table></div>
<div class="card"><h2>Fault registers</h2><table>{fl_rows}</table></div></div>
{rtt_html}
<div class="foot">generated by dap.py diagnose - via=stack frames are heuristic - frames/locals may be inexact at -O2</div>
</div></html>"""
    path.write_text(doc)


def _bit_active(name: str, fault: dict) -> bool:
    cfsr = fault.get("CFSR", 0)
    hfsr = fault.get("HFSR", 0)
    if name == "VECTTBL":
        return bool(hfsr & (1 << 1))
    if name == "FORCED":
        return bool(hfsr & (1 << 30))
    if name == "DEBUGEVT":
        return bool(hfsr & (1 << 31))
    if name in ("MMARVALID", "BFARVALID"):
        return bool(cfsr & ((1 << 7) if name == "MMARVALID" else (1 << 15)))
    pos = {"IACCVIOL": 0, "DACCVIOL": 1, "MUNSTKERR": 3, "MSTKERR": 4, "IBUSERR": 8,
           "PRECISERR": 9, "IMPRECISERR": 10, "UNSTKERR": 11, "STKERR": 12, "UNDEFINSTR": 16,
           "INVSTATE": 17, "INVPC": 18, "NOCP": 19, "UNALIGNED": 24, "DIVBYZERO": 25}.get(name)
    return bool(pos is not None and cfsr & (1 << pos))


def cmd_diagnose(a) -> None:
    if a.snapshot:
        py = venv_python()
        if py.exists() and Path(sys.executable).resolve() != py.resolve():
            os.execv(str(py), [str(py), str(Path(__file__).resolve())] + sys.argv[1:])
    else:
        ensure_runtime()
    if a.snapshot:
        snap = json.loads(Path(a.snapshot).read_text())
    else:
        ei = ElfInfo(elf_path(a)) if (getattr(a, "elf", None) or load_config().get("elf")) else None
        snap = _snapshot_fault(a, ei, None)
        if a.rtt_log and Path(a.rtt_log).exists():
            snap["rtt_tail"] = Path(a.rtt_log).read_text(errors="replace").splitlines()[-60:]
        if a.save:
            Path(a.save).write_text(json.dumps(snap, indent=2))
    ei = None
    if snap.get("elf") and Path(snap["elf"]).exists():
        try:
            ei = ElfInfo(snap["elf"])
        except Exception:
            ei = None
    hyps = analyze_fault(snap, ei)
    if a.html:
        render_fault_html(snap, hyps, Path(a.html).expanduser())
        snap["html"] = str(Path(a.html).expanduser())
    if a.json:
        emit({"ok": True, "op": "diagnose", "snapshot": snap, "hypotheses": hyps}, as_json=True)
    else:
        print(render_fault_text(snap, hyps, ei))
        if a.html:
            print(f"\nHTML report: {Path(a.html).expanduser()}")
    if a.open and a.html:
        import shutil as _sh
        opener = "explorer.exe" if _sh.which("explorer.exe") else ("xdg-open" if _sh.which("xdg-open") else None)
        if opener:
            subprocess.Popen([opener, str(Path(a.html).expanduser())],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cmd_selfcheck(a) -> None:
    """Non-destructive hardware validation: connect, registers, memory, breakpoints, CFI."""
    ensure_runtime()
    checks: list[dict] = []

    def record(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)})

    ei = ElfInfo(elf_path(a)) if (getattr(a, "elf", None) or load_config().get("elf")) else None
    s = _session(a, halt=False)
    with s:
        t = _core(s.target, a)
        record("probe", True, getattr(s, "probe", None) and s.probe.unique_id or "")
        record("target", bool(getattr(t, "part_number", None)), getattr(t, "part_number", ""))
        state = _state_name(t)
        record("core_state", state in ("RUNNING", "HALTED", "SLEEPING", "LOCKUP"), state)
        if state == "RUNNING":
            t.halt()
        regs = _read_regs(t)
        record("registers", "pc" in regs and "sp" in regs, f"pc=0x{regs.get('pc', 0):08x}")
        data = _read(t, 0, 8)
        record("memory", data is not None and len(data) == 8, (data or b"").hex())
        record("vector_table", data is not None and data[:4] != b"\x00\x00\x00\x00",
               (data or b"")[:4].hex())
        sp = regs.get("sp", 0)
        record("stack_pointer", sp != 0 and sp != 0xFFFFFFFF, f"sp=0x{sp:08x}")
        try:
            from pyocd.core.target import Target
            pc = regs.get("pc", 0) & ~1
            ok = t.set_breakpoint(pc, Target.BreakpointType.HW)
            if ok:
                t.remove_breakpoint(pc)
            record("hw_breakpoint", bool(ok), hex(pc))
        except Exception as exc:
            record("hw_breakpoint", False, exc)
        if ei:
            _, frames = _bt_frames(t, ei, 8, 256)
            exact = sum(1 for f in frames if f.get("exact"))
            record("cfi_unwind", exact > 0, f"frames={len(frames)} exact={exact}")
            dr = DwarfReader(ei.path)
            ln = ei.line_for(regs.get("pc", 0) & ~1)
            record("line_info", ln is not None, f"{ln[0]}:{ln[1]}" if ln else "")
            record("dwarf_locals", bool(dr.die_for_pc(regs.get("pc", 0) & ~1)[0]),
                   "subprogram found" if dr.die_for_pc(regs.get("pc", 0) & ~1)[0] else "")
        try:
            caps = [str(c.name) for c in s.probe.capabilities]
            record("probe_caps", True, ",".join(caps))
        except Exception:
            pass

    ok = all(c["ok"] for c in checks)
    if a.json:
        emit({"ok": ok, "op": "selfcheck", "engine": "pyocd", "checks": checks}, as_json=True)
    else:
        width = max(len(c["name"]) for c in checks)
        for c in checks:
            print(f"{'PASS' if c['ok'] else 'FAIL'}  {c['name']:<{width}}  {c['detail']}")
        print(f"\n{'ALL PASS' if ok else 'SOME CHECKS FAILED'}")


def cmd_semi(a) -> None:
    """Service ARM semihosting (SYS_WRITE0 etc.) while the target runs."""
    ensure_runtime()
    from pyocd.debug.context import DebugContext
    from pyocd.debug.semihost import ConsoleIOHandler, InternalSemihostIOHandler, SemihostAgent

    class _TextConsole:
        def __init__(self, stream):
            self.stream = stream

        def write(self, data):
            if isinstance(data, (bytes, bytearray)):
                data = bytes(data).decode(errors="replace")
            self.stream.write(data)
            self.stream.flush()

        def flush(self):
            self.stream.flush()

    s = _session(a, halt=False)
    handled = 0
    with s:
        t = _core(s.target, a)
        ctx = DebugContext(t)
        agent = SemihostAgent(ctx, io_handler=InternalSemihostIOHandler(),
                              console=ConsoleIOHandler(sys.stdin, _TextConsole(sys.stdout)))
        if _state_name(t) != "RUNNING":
            t.resume()
        deadline = time.time() + a.duration
        while time.time() < deadline:
            if _state_name(t) == "RUNNING":
                time.sleep(0.01)
                continue
            try:
                served = agent.check_and_handle_semihost_request()
            except Exception as exc:
                if os.environ.get("DAP_DEBUG"):
                    print(f"semihost error: {type(exc).__name__}: {exc}", file=sys.stderr)
                served = False
            if served:
                handled += 1
                t.resume()
                continue
            break  # a real halt (breakpoint, fault, ...)
        if _state_name(t) == "RUNNING":
            t.halt()
        state = _state_name(t)
    emit({"ok": True, "op": "semihost", "handled": handled, "state": state,
          "note": "stops on the first non-semihosting halt"}, as_json=True)


# ---------------------------------------------------------- multicore / trace

FLASH_BPS = HOME / "flash_bp.json"


def _core(t, a):
    """Select a core when the target is multi-core and --core was given."""
    idx = getattr(a, "core", None)
    if idx in (None, ""):
        return t
    cores = getattr(t, "cores", None) or {}
    if not cores:
        return t
    keys = list(cores.keys())
    try:
        n = int(idx)
        if 0 <= n < len(keys):
            return cores[keys[n]]
    except ValueError:
        if idx in cores:
            return cores[idx]
    die(f"core {idx} does not exist; available: {keys} (or 0..{len(keys) - 1})")


def cmd_cores(a) -> None:
    ensure_runtime()
    s = _session(a, halt=False)
    with s:
        t = _core(s.target, a)
        cores = getattr(t, "cores", None) or {}
        out = [{"index": i, "name": name,
                "state": _state_name(c) if c is not t else _state_name(t)}
               for i, (name, c) in enumerate(cores.items())] if cores else []
        emit({"ok": True, "target": getattr(t, "part_number", None), "cores": out,
              "multicore": bool(cores)}, as_json=True)


DWT_CTRL = 0xE0001000
DWT_CYCCNT = 0xE0001004


def cmd_cycles(a) -> None:
    ensure_runtime()
    s = _session(a, halt=False)
    with s:
        t = _core(s.target, a)
        if a.enable:
            t.write32(DWT_CTRL, t.read32(DWT_CTRL) | 1)
        if a.reset:
            t.write32(DWT_CYCCNT, 0)
        val = t.read32(DWT_CYCCNT)
        ctrl = t.read32(DWT_CTRL)
        out = {"ok": True, "cyccnt": val, "enabled": bool(ctrl & 1)}
        if a.hz:
            out["seconds"] = val / a.hz
        emit(out, as_json=True)


def cmd_profile(a) -> None:
    """Approximate PC sampling profiler (halts between samples)."""
    if _engine(a) != "probe-rs":
        ensure_runtime()
    if _engine(a) == "probe-rs":
        args = ["profile", "--duration", str(a.duration), elf_path(a), "flat"] + _prs_common(a)
        rc, out, err = _prs(args, int(a.duration) + 60)
        sys.stdout.write(out)
        sys.stderr.write(err)
        sys.exit(rc)
    ei = ElfInfo(elf_path(a)) if (getattr(a, "elf", None) or load_config().get("elf")) else None
    s = _session(a, halt=False)
    samples = []
    with s:
        t = _core(s.target, a)
        was_running = _state_name(t) == "RUNNING"
        if was_running:
            t.resume()
        end = time.time() + a.duration
        try:
            while time.time() < end:
                try:
                    t.halt()
                    pc = t.read_core_register("pc") & ~1
                    samples.append(pc)
                except Exception:
                    break
                if was_running:
                    t.resume()
                time.sleep(a.interval)
        finally:
            if was_running:
                try:
                    t.halt()
                except Exception:
                    pass
    counts = {}
    for pc in samples:
        key = ei.frame_name(pc) if ei else hex(pc)
        counts[key] = counts.get(key, 0) + 1
    total = len(samples)
    top = sorted(({"symbol": k, "samples": v, "pct": round(v * 100 / total, 1)}
                  for k, v in counts.items()), key=lambda x: -x["samples"])[: a.top]
    emit({"ok": True, "op": "profile", "samples": total, "duration": a.duration,
          "note": "sampling halts the core each time, so results are conservative; use swo/ETM for lossless profiling",
          "top": top}, as_json=True)


def cmd_swo(a) -> None:
    """Live SWO/ITM trace (pyOCD SWV, or probe-rs ITM)."""
    if _engine(a) != "probe-rs":
        ensure_runtime()
    if _engine(a) == "probe-rs":
        if a.raw:
            die("--raw is pyOCD-only; probe-rs itm swo writes to stdout")
        args = ["itm", "swo", str(int(a.duration * 1000)), str(a.cpu_freq), str(a.swo_freq)] + _prs_common(a)
        rc, out, err = _prs(args, int(a.duration) + 60)
        sys.stdout.write(out)
        sys.stderr.write(err)
        sys.exit(rc)
    from pyocd.trace.swv import SWVReader
    s = _session(a, halt=False)
    with s:
        if a.raw:
            s.options["swv_raw_enable"] = True
            s.options["swv_raw_file"] = str(Path(a.raw).expanduser())
        core_num = int(a.core) if str(a.core or "0").isdigit() else 0
        reader = SWVReader(s, core_num)
        if not reader.init(a.cpu_freq, a.swo_freq, sys.stdout):
            die("SWO init failed: the probe does not support SWO, or the target has no ITM/TPIU. "
                "DAPLink v2 / ST-Link support it; CMSIS-DAP v1 HID usually does not.")
        print(f"[swo] {a.duration}s @ cpu={a.cpu_freq} swo={a.swo_freq}", file=sys.stderr)
        try:
            time.sleep(a.duration)
        finally:
            reader.stop()


# ------------------------------------------------------------ flash breakpoints

def _flash_region(t, addr: int):
    try:
        region = t.memory_map.get_region_for_address(addr)
    except Exception:
        region = None
    if region is None or getattr(region, "flash", None) is None:
        die(f"0x{addr:08x} is not inside a writable flash region")
    return region


def _flash_read_sector(t, addr: int, region) -> tuple[int, bytes]:
    size = region.blocksize
    start = addr - (addr % size)
    data = _read(t, start, size)
    if data is None:
        die("Failed to read the flash sector")
    return start, data


def _flash_write_sector(t, start: int, data: bytes, region) -> None:
    page = getattr(region, "page_size", None) or region.blocksize
    region.flash.init(region.flash.Operation.ERASE)
    region.flash.erase_sector(start)
    region.flash.init(region.flash.Operation.PROGRAM)
    erased = bytes([getattr(region, "erased_byte_value", 0xFF)])
    for off in range(0, len(data), page):
        chunk = data[off:off + page]
        if len(chunk) < page:
            chunk = chunk + erased * (page - len(chunk))
        region.flash.program_page(start + off, chunk)
    region.flash.uninit()


def _fbp_load() -> dict:
    try:
        return json.loads(FLASH_BPS.read_text())
    except Exception:
        return {}


def _fbp_save(d: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    FLASH_BPS.write_text(json.dumps(d, indent=2))


def _flash_bp_set(t, addr: int) -> dict:
    region = _flash_region(t, addr)
    start, orig = _flash_read_sector(t, addr, region)
    buf = bytearray(orig)
    off = addr - start
    if off + 2 > len(buf):
        die("Address out of range")
    buf[off:off + 2] = b"\x00\xbe"  # BKPT #0
    _flash_write_sector(t, start, bytes(buf), region)
    entry = {"addr": hex(addr), "start": hex(start), "size": region.blocksize,
             "orig": orig.hex(), "type": "flash"}
    reg = _fbp_load()
    reg[hex(addr)] = entry
    _fbp_save(reg)
    return entry


def _flash_bp_clear(t, addr: int) -> bool:
    reg = _fbp_load()
    entry = reg.get(hex(addr))
    if not entry:
        return False
    region = _flash_region(t, addr)
    _flash_write_sector(t, int(entry["start"], 0), bytes.fromhex(entry["orig"]), region)
    reg.pop(hex(addr), None)
    _fbp_save(reg)
    return True


def cmd_repl(a) -> None:
    """Persistent session REPL: one connection, GDB-like command loop."""
    ensure_runtime()
    path = None
    if getattr(a, "elf", None) or load_config().get("elf"):
        path = elf_path(a)
    ei = ElfInfo(path) if path else None
    dr = DwarfReader(path) if path else None
    s = _session(a)
    bps: dict[int, dict] = {}
    wps: dict[int, int] = {}
    help_text = """commands:
  run|r [timeout]        resume and wait for halt
  halt | resume | reset  core control
  s|step [n]             step into n instructions
  n|next [n]             step over (calls executed to completion)
  fin|finish             run until current function returns
  line [n]               run to next source line
  bp <sym|0xaddr|f.c:42> [hw|sw] [if EXPR] [do "print r0; continue"]
  bp list | bp del <addr|#> | bp clear
  wp <expr> [size]       data watchpoint on an lvalue
  wp list | wp clear
  bt                     backtrace (DWARF CFI)
  p|print <expr>         C expression
  locals [frame] | globals [filter]
  regs | regs r0=1
  x|mem <addr> [len]     hex dump
  d|disasm [addr|sym] [n]
  fault                  fault decode + backtrace + stack
  watch <expr> [n] [interval]
  core [n]               list or switch core
  source <file>          execute a command file
  quit"""
    state = {"t": _core(s.target, a)}
    with s:
        def read(addr, n):
            return _read(state["t"], addr, n) if addr is not None else None

        def regs_now():
            return _read_regs(state["t"])

        def frames_now(limit=8):
            return _bt_frames(state["t"], ei, limit, 256)[1] if ei else []

        def env_at(pc=None):
            regs = regs_now()
            if pc is None:
                pc = regs.get("pc", 0) & ~1
            fr = frames_now(2)
            cfa = fr[0].get("cfa") if fr else None
            return _env(dr, regs, pc, cfa), regs, pc

        def info(pc=None, prefix=""):
            t = state["t"]
            pc = pc if pc is not None else (t.read_core_register("pc") & ~1)
            line = f"{prefix}{_state_name(t)} pc=0x{pc:08x}"
            if ei:
                line += f" {ei.frame_name(pc)}"
                ln = ei.line_for(pc)
                if ln:
                    line += f" ({ln[0]}:{ln[1]})"
            print(line)

        def stopped():
            t = state["t"]
            info(prefix="stopped: ")
            reason = _halt_reason(t)
            if reason and reason not in ("DEBUG", "USER"):
                print(f"  reason: {reason}")
            if _state_name(t) == "LOCKUP":
                print("  !! LOCKUP: run fault for a full report")

        def do_run(timeout):
            t = state["t"]
            t.resume()
            end = time.time() + timeout
            while time.time() < end:
                if _state_name(t) != "RUNNING":
                    pc = t.read_core_register("pc") & ~1
                    hit = bps.get(pc)
                    if hit and hit.get("cond") and dr:
                        env, _, _ = env_at(pc)
                        try:
                            ok = eval_expr(dr, hit["cond"], env, read).load(read)
                        except Exception:
                            ok = True
                        if not ok:
                            t.resume()
                            continue
                    script = hit.get("on_hit") if hit else None
                    if script:
                        cont, lines = _exec_on_hit(t, script, ei, dr, read)
                        for line in lines:
                            print(line)
                        if cont:
                            t.resume()
                            continue
                    print(f"hit: {ei.frame_name(pc) if ei else hex(pc)}" if hit else "halted")
                    stopped()
                    return
                time.sleep(0.02)
            t.halt()
            print(f"timeout after {timeout}s")

        def step_over(n):
            t = state["t"]
            for _ in range(n):
                pc = t.read_core_register("pc") & ~1
                size, is_call = _insn(t, pc)
                if is_call:
                    _run_to(t, pc + size, 10)
                else:
                    t.step()
                    t.halt()

        def step_line(n):
            t = state["t"]
            if not ei:
                print("error: requires --elf")
                return
            for _ in range(n):
                pc = t.read_core_register("pc") & ~1
                cur = ei.line_for(pc)
                target = None
                for addr, name, line in ei.lines:
                    if addr <= pc:
                        continue
                    if cur and name != cur[0]:
                        continue
                    if cur and line == cur[1]:
                        continue
                    target = addr
                    break
                if target is None:
                    print("error: no next line found")
                    return
                _run_to(t, target, 10)

        def hexdump(addr, length):
            t = state["t"]
            data = _read(t, addr, length)
            if data is None:
                print("error: read failed")
                return
            for i in range(0, len(data), 16):
                chunk = data[i:i + 16]
                hx = " ".join(f"{b:02x}" for b in chunk)
                asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
                print(f"{addr + i:08x}  {hx:<47}  {asc}")

        def exec_line(raw):
            line = raw.strip()
            if not line or line.startswith("#"):
                return True
            import shlex
            try:
                parts = shlex.split(line)
            except ValueError as e:
                print("error:", e)
                return True
            cmd = parts[0]
            args = parts[1:]
            t = state["t"]
            if cmd in ("q", "quit", "exit"):
                return False
            if cmd in ("help", "?"):
                print(help_text)
            elif cmd == "status":
                info()
            elif cmd == "halt":
                t.halt()
                stopped()
            elif cmd in ("resume", "go"):
                t.resume()
                print("running")
            elif cmd == "reset":
                t.reset()
                info(prefix="reset: ")
            elif cmd in ("run", "r", "c", "continue"):
                do_run(float(args[0]) if args else 10)
            elif cmd in ("s", "step"):
                for _ in range(int(args[0]) if args else 1):
                    t.step()
                    t.halt()
                info(prefix="stepped: ")
            elif cmd in ("n", "next"):
                step_over(int(args[0]) if args else 1)
                info(prefix="stepped: ")
            elif cmd in ("fin", "finish"):
                lr = t.read_core_register("lr") & ~1
                if not lr:
                    print("error: LR is 0")
                else:
                    _run_to(t, lr, 10)
                    stopped()
            elif cmd == "line":
                step_line(int(args[0]) if args else 1)
                info(prefix="line: ")
            elif cmd == "bt":
                for i, f in enumerate(frames_now(int(args[0]) if args else 12)):
                    loc = f" ({f['file']}:{f['line']})" if f.get("file") else ""
                    print(f"  #{i:<2} {f.get('symbol', '?'):<34} 0x{f['pc']:08x}{loc}  via {f.get('via')}")
            elif cmd in ("p", "print"):
                if not dr:
                    print("error: requires --elf")
                else:
                    expr = line.split(None, 1)[1] if len(line.split(None, 1)) > 1 else ""
                    env, _, _ = env_at()
                    try:
                        print(_fmt_val(eval_expr(dr, expr, env, read), dr, read))
                    except Exception as e:
                        print("error:", e)
            elif cmd == "locals":
                if not dr:
                    print("error: requires --elf")
                else:
                    idx = int(args[0]) if args else 0
                    fr = frames_now(idx + 1)
                    if idx >= len(fr):
                        print("error: frame out of range")
                    else:
                        regs = fr[idx].get("regs") or regs_now()
                        for item in dr.locals_at(fr[idx]["pc"], regs, read, fr[idx].get("cfa")):
                            print(f"  {item['name']:<20} {item['value']!r}")
            elif cmd == "globals":
                if not dr:
                    print("error: requires --elf")
                else:
                    flt = args[0].lower() if args else ""
                    for item in dr.globals_at(read):
                        if flt in item["name"].lower():
                            print(f"  {item['name']:<24} {item['value']!r}")
            elif cmd == "regs":
                if not args:
                    for k, v in regs_now().items():
                        print(f"  {k:<6} 0x{v:08x}")
                else:
                    for item in args:
                        if "=" in item:
                            k, v = item.split("=", 1)
                            t.write_core_register(k, int(v, 0))
                            print(f"  {k} <- {int(v, 0):#x}")
            elif cmd in ("x", "mem"):
                if not args:
                    print("usage: x <addr> [len]")
                else:
                    hexdump(int(args[0], 0), int(args[1], 0) if len(args) > 1 else 64)
            elif cmd in ("d", "disasm"):
                if not ei:
                    print("error: requires --elf")
                else:
                    if args and not args[0].startswith("0x"):
                        start = ei.symbols.get(args[0])
                        if start is None:
                            print("error: unknown symbol")
                            return True
                    else:
                        start = int(args[0], 0) if args else (t.read_core_register("pc") & ~1)
                    n = int(args[1]) if len(args) > 1 else 10
                    from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
                    code = _read(t, start, n * 4) or b""
                    for ins in Cs(CS_ARCH_ARM, CS_MODE_THUMB).disasm(code, start):
                        print(f"  {ins.address:08x}  {ins.bytes.hex():<9} {ins.mnemonic:<7} {ins.op_str}")
            elif cmd == "bp":
                if not args or args[0] == "list":
                    if not bps and not _fbp_load():
                        print("no breakpoints")
                    for addr, b in bps.items():
                        print(f"  {addr:#010x} {b.get('type', 'auto')} {('if ' + b['cond']) if b.get('cond') else ''}")
                    for addr, b in _fbp_load().items():
                        print(f"  {addr} flash")
                elif args[0] in ("clear", "del", "delete"):
                    if args[0] == "clear" or len(args) < 2:
                        for addr in list(bps):
                            try:
                                t.remove_breakpoint(addr)
                            except Exception:
                                pass
                        bps.clear()
                        print("cleared")
                    else:
                        if args[1].startswith("#") and args[1][1:].isdigit():
                            idx = int(args[1][1:])
                            addrs = list(bps)
                            if not (0 <= idx < len(addrs)):
                                print("error: breakpoint index out of range")
                                return True
                            addr = addrs[idx]
                        else:
                            addr = _resolve_bp_target(a, args[1])
                        try:
                            t.remove_breakpoint(addr)
                        except Exception:
                            pass
                        bps.pop(addr, None)
                        print(f"deleted {addr:#010x}")
                else:
                    kind = "auto"
                    rest = list(args)
                    if rest and rest[-1] in ("hw", "sw") and not rest[-1].startswith("0x"):
                        kind = rest.pop()
                    cond = None
                    on_hit = None
                    if "do" in rest:
                        i = rest.index("do")
                        on_hit = " ".join(rest[i + 1:])
                        rest = rest[:i]
                    if "if" in rest:
                        i = rest.index("if")
                        cond = " ".join(rest[i + 1:])
                        rest = rest[:i]
                    addr = _resolve_bp_target(a, rest[0])
                    from pyocd.core.target import Target
                    bt = {"hw": Target.BreakpointType.HW, "sw": Target.BreakpointType.SW,
                          "auto": Target.BreakpointType.AUTO}[kind]
                    if t.set_breakpoint(addr, bt):
                        bps[addr] = {"type": kind, "cond": cond, "on_hit": on_hit}
                        extra = (f" if {cond}" if cond else "") + (f" do {on_hit}" if on_hit else "")
                        print(f"breakpoint at {addr:#010x}{extra}")
                    else:
                        print("error: could not set the breakpoint")
            elif cmd == "wp":
                if not args or args[0] == "list":
                    if not wps:
                        print("no watchpoints")
                    for addr, size in wps.items():
                        print(f"  {addr:#010x} size {size}")
                elif args[0] == "clear":
                    from pyocd.core.target import Target
                    for addr, size in list(wps.items()):
                        try:
                            t.remove_watchpoint(addr, size, Target.WatchpointType.WRITE)
                        except Exception:
                            pass
                    wps.clear()
                    print("watchpoints cleared")
                else:
                    if not dr:
                        print("error: requires --elf")
                    else:
                        env, _, _ = env_at()
                        val = eval_expr(dr, args[0], env, read)
                        if val.addr is None:
                            print("error: a watchpoint needs an lvalue expression")
                        else:
                            size = int(args[1]) if len(args) > 1 else 4
                            from pyocd.core.target import Target
                            ok = t.set_watchpoint(val.addr, size, Target.WatchpointType.WRITE)
                            if ok:
                                wps[val.addr] = size
                            print(f"watchpoint at {val.addr:#010x} size {size}: {ok}")
            elif cmd == "fault":
                a2 = argparse.Namespace(**{k: getattr(a, k, None) for k in
                                           ("elf", "target", "probe", "frequency", "pack",
                                            "timeout", "core", "limit", "max_stack")})
                a2.limit = a2.limit or 12
                a2.max_stack = a2.max_stack or 512
                snap = _snapshot_fault(a2, ei, dr)
                for h in analyze_fault(snap, ei)[:5]:
                    print(f"  [{int(h['score'] * 100):3d}%] {h['cause']}")
            elif cmd == "watch":
                if not dr or not args:
                    print("error: requires --elf and an expression")
                else:
                    n = int(args[1]) if len(args) > 1 else 10
                    iv = float(args[2]) if len(args) > 2 else 0.2
                    for _ in range(n):
                        env, _, _ = env_at()
                        print(f"  {time.strftime('%H:%M:%S')} {_fmt_val(eval_expr(dr, args[0], env, read), dr, read)!r}")
                        time.sleep(iv)
            elif cmd == "core":
                cores = getattr(s.target, "cores", None) or {}
                if not args:
                    print("  " + (", ".join(f"{i}:{n}" for i, n in enumerate(cores)) or "single core"))
                elif cores:
                    state["t"] = _core(s.target, argparse.Namespace(core=args[0]))
                    print(f"core -> {args[0]}")
            elif cmd == "source":
                if not args:
                    print("usage: source <file>")
                else:
                    for sub in Path(args[0]).expanduser().read_text().splitlines():
                        if not exec_line(sub):
                            return False
            else:
                print(f"error: unknown command {cmd} (see help)")
            return True

        lines = []
        if a.cmd:
            lines = list(a.cmd)
        elif not sys.stdin.isatty():
            lines = sys.stdin.read().splitlines()
        def safe(raw):
            try:
                return exec_line(raw)
            except SystemExit:
                print("error: command failed")
                return True
            except Exception as e:
                print(f"error: {type(e).__name__}: {e}")
                return True

        if lines:
            for raw in lines:
                if not safe(raw):
                    break
        else:
            info(prefix="connected: ")
            while True:
                try:
                    raw = input("(dap) ")
                except (EOFError, KeyboardInterrupt):
                    break
                if not safe(raw):
                    break


# --------------------------------------------------------------- probe-rs engine

def probe_rs_path() -> str | None:
    for cand in (os.environ.get("DAP_PROBE_RS"), shutil.which("probe-rs")):
        if cand and Path(cand).exists():
            return cand
    local = HOME / "bin" / "probe-rs"
    return str(local) if local.exists() else None


def probe_rs_bin() -> str:
    path = probe_rs_path()
    if not path:
        die("probe-rs not found. Install from https://probe.rs/docs/getting-started/installation "
            "or set DAP_PROBE_RS=/path/to/probe-rs")
    return path


_PRS_CHIPS: list[str] | None = None


def _prs_chips() -> list[str]:
    global _PRS_CHIPS
    if _PRS_CHIPS is None:
        path = probe_rs_path()
        if not path:
            _PRS_CHIPS = []
        else:
            rc, out, _ = run([path, "chip", "list"], 60)
            _PRS_CHIPS = [ln.strip() for ln in out.splitlines() if ln.strip()] if rc == 0 else []
    return _PRS_CHIPS


def _resolve_chip(a) -> str | None:
    """Resolve a probe-rs chip name from --chip, config, or the pyOCD target name."""
    explicit = getattr(a, "chip", None) or load_config().get("chip")
    if explicit:
        return str(explicit)
    target = getattr(a, "target", None) or load_config().get("target")
    if not target:
        return None
    chips = _prs_chips()
    low = str(target).lower()
    exact = next((c for c in chips if c.lower() == low), None)
    if exact:
        return exact
    pref = [c for c in chips if c.lower().startswith(low)]
    return pref[0] if len(pref) == 1 else None


def _engine(a) -> str:
    eng = (getattr(a, "engine", None) or load_config().get("engine") or "auto").lower()
    if eng == "auto":
        return "probe-rs" if (probe_rs_path() and _resolve_chip(a)) else "pyocd"
    if eng == "probe-rs" and not probe_rs_path():
        probe_rs_bin()
    return eng


def _prs_common(a) -> list[str]:
    chip = _resolve_chip(a)
    if not chip:
        die("Cannot map this target to a probe-rs chip. Pass --chip <CHIP> "
            "(see: dap.py targets --engine probe-rs --search <part>)")
    out = ["--chip", str(chip), "--non-interactive"]
    if getattr(a, "probe", None):
        out += ["--probe", str(a.probe)]
    freq = getattr(a, "frequency", None)
    if freq:
        out += ["--speed", str(max(1, int(freq) // 1000))]
    if getattr(a, "connect", None) == "under-reset":
        out.append("--connect-under-reset")
    return out


def _prs(args: list[str], timeout: int = 300) -> tuple[int, str, str]:
    return run([probe_rs_bin()] + args, timeout)


def _fw_format(path: Path, explicit: str | None) -> str:
    if explicit:
        return "elf" if explicit == "axf" else explicit
    suffix = path.suffix.lower()
    return {".elf": "elf", ".axf": "elf", ".hex": "hex", ".bin": "bin"}.get(suffix, "target")


def cmd_engines(a) -> None:
    py = venv_python()
    if py.exists() and Path(sys.executable).resolve() != py.resolve():
        os.execv(str(py), [str(py), str(Path(__file__).resolve())] + sys.argv[1:])
    out: dict = {}
    try:
        import pyocd as _pyocd
        cli = venv_bin("pyocd")
        cli_path = str(cli) if cli.exists() else shutil.which("pyocd")
        out["pyocd"] = {"available": True, "version": getattr(_pyocd, "__version__", "?"),
                        "path": cli_path, "cli": bool(cli_path)}
    except Exception as exc:
        out["pyocd"] = {"available": False, "error": str(exc)}
    prs = probe_rs_path()
    entry = {"available": prs is not None, "path": prs}
    if prs:
        rc, o, _ = run([prs, "--version"], 15)
        entry["version"] = o.strip() if rc == 0 else "?"
    out["probe-rs"] = entry
    out["default"] = load_config().get("engine") or "pyocd"
    emit(out, as_json=True)


def main() -> None:
    ap = argparse.ArgumentParser(prog="dap.py", description="DAPLink/CMSIS-DAP toolbox (pyOCD backend)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def sess(p, timeout=180, connect=False):
        p.add_argument("--target", "-t")
        p.add_argument("--probe", "-u")
        p.add_argument("--frequency", "-f", type=int)
        p.add_argument("--pack")
        p.add_argument("--engine", choices=["auto", "pyocd", "probe-rs"])
        p.add_argument("--chip", help="probe-rs chip name (e.g. STM32F103RC)")
        p.add_argument("--core", help="core index or name for multi-core targets")
        p.add_argument("--no-wsl-auto-attach", dest="wsl_auto_attach", action="store_false",
                       default=True, help="do not auto-attach Windows probes when running under WSL")
        p.add_argument("--elf", help="ELF for symbol resolution")
        p.add_argument("--connect", choices=["halt", "pre-reset", "under-reset", "attach"])
        p.add_argument("--timeout", type=int, default=timeout)

    p = sub.add_parser("setup", help="create venv and install pyOCD")
    p.add_argument("--dev", action="store_true", help="also install pytest for the test suite")
    p.set_defaults(fn=cmd_setup)
    p = sub.add_parser("doctor", help="environment + probe diagnostics")
    p.add_argument("--attach", action="store_true", help="attach the first Windows-side probe automatically (WSL)")
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("probes"); p.add_argument("--json", action="store_true")
    p.add_argument("--engine", choices=["auto", "pyocd", "probe-rs"]); p.set_defaults(fn=cmd_probes)
    p = sub.add_parser("targets"); p.add_argument("--search", "-s"); p.add_argument("--limit", "-n", type=int, default=0)
    p.add_argument("--engine", choices=["auto", "pyocd", "probe-rs"]); p.add_argument("--chip")
    p.add_argument("--json", action="store_true"); p.set_defaults(fn=cmd_targets)

    p = sub.add_parser("pack"); p.add_argument("action", choices=["search", "install", "list", "find", "update"])
    p.add_argument("query", nargs="?"); p.set_defaults(fn=cmd_pack)

    p = sub.add_parser("flash"); p.add_argument("file"); p.add_argument("--base", "-a")
    p.add_argument("--erase", "-e", choices=["auto", "chip", "sector"]); p.add_argument("--format", choices=["bin", "hex", "elf"])
    p.add_argument("--no-reset", action="store_true"); sess(p, 300); p.set_defaults(fn=cmd_flash)

    p = sub.add_parser("verify"); p.add_argument("file"); p.add_argument("--base", "-a")
    p.add_argument("--max-report", type=int, default=10); sess(p, 300); p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("erase")
    p.add_argument("--chip-erase", "--mass", dest="chip", action="store_true", help="erase the whole chip")
    p.add_argument("--range")
    sess(p); p.set_defaults(fn=cmd_erase)

    p = sub.add_parser("reset"); p.add_argument("--halt", action="store_true"); sess(p, 60); p.set_defaults(fn=cmd_reset)

    p = sub.add_parser("connect"); sess(p, 60, connect=True); p.set_defaults(fn=cmd_connect)
    p = sub.add_parser("status"); sess(p, 60); p.set_defaults(fn=cmd_status)
    p = sub.add_parser("halt"); sess(p, 60); p.set_defaults(fn=cmd_halt)
    p = sub.add_parser("resume"); sess(p, 60); p.set_defaults(fn=cmd_resume)

    p = sub.add_parser("step"); p.add_argument("--count", "-n", type=int, default=1)
    p.add_argument("--over", action="store_true", help="step over calls")
    p.add_argument("--out", action="store_true", help="run until return from current function")
    p.add_argument("--line", action="store_true", help="run to next source line (needs --elf with -g)")
    p.add_argument("--allow-interrupts", action="store_true"); sess(p, 60); p.set_defaults(fn=cmd_step)

    p = sub.add_parser("bt", help="backtrace with symbols + source lines")
    p.add_argument("--limit", "-n", type=int, default=16); p.add_argument("--max-stack", type=int, default=512)
    sess(p, 60); p.set_defaults(fn=cmd_bt)

    p = sub.add_parser("disasm", help="disassemble around PC/address/symbol")
    p.add_argument("--at", "-a"); p.add_argument("--symbol", "-s"); p.add_argument("--count", "-n", type=int, default=16)
    p.add_argument("--mode", choices=["thumb", "arm"], default="thumb"); p.add_argument("--json", action="store_true")
    sess(p, 60); p.set_defaults(fn=cmd_disasm)

    p = sub.add_parser("sym", help="inspect ELF symbols / address->line")
    p.add_argument("action", choices=["list", "find", "addr"]); p.add_argument("value", nargs="?")
    p.add_argument("--limit", "-n", type=int, default=40); p.add_argument("--elf"); p.set_defaults(fn=cmd_sym)

    p = sub.add_parser("regset", help="write a core register")
    p.add_argument("name"); p.add_argument("value"); sess(p, 60); p.set_defaults(fn=cmd_regset)

    p = sub.add_parser("rtos", help="list RTOS threads (FreeRTOS/RTX5/ThreadX/Zephyr)")
    p.add_argument("--rtos", choices=["auto", "freertos", "rtx5", "threadx", "zephyr"], default="auto")
    sess(p, 60); p.set_defaults(fn=cmd_rtos)

    p = sub.add_parser("fault", help="post-mortem: fault decode + exception frame + backtrace + stack")
    p.add_argument("--limit", "-n", type=int, default=12); p.add_argument("--max-stack", type=int, default=512)
    sess(p, 60); p.set_defaults(fn=cmd_fault)

    p = sub.add_parser("vars", help="DWARF variables: globals / locals / print expression")
    p.add_argument("action", choices=["globals", "locals", "print"])
    p.add_argument("value", nargs="?", help="filter for globals, or a C expression for print")
    p.add_argument("--frame", "-F", type=int, default=0, help="stack frame index for locals")
    sess(p, 60); p.set_defaults(fn=cmd_vars)

    p = sub.add_parser("watch", help="sample an expression over time (live watch)")
    p.add_argument("expr"); p.add_argument("--interval", type=float, default=0.2)
    p.add_argument("--count", "-n", type=int, default=20)
    sess(p, 60); p.set_defaults(fn=cmd_watch)

    p = sub.add_parser("diagnose", aliases=["postmortem"], help="fault triage: root causes + optional HTML report")
    p.add_argument("--snapshot", "--from", dest="snapshot", help="analyze a saved snapshot JSON (offline)")
    p.add_argument("--save", help="write the captured snapshot JSON")
    p.add_argument("--html", help="write a self-contained HTML report")
    p.add_argument("--rtt-log", help="attach the tail of an RTT log")
    p.add_argument("--open", action="store_true", help="open the HTML report")
    p.add_argument("--json", action="store_true")
    sess(p, 60); p.set_defaults(fn=cmd_diagnose)

    p = sub.add_parser("snapshot", help="save/load/diff a memory region")
    p.add_argument("snapshot_cmd", choices=["save", "load", "diff"])
    p.add_argument("file"); p.add_argument("--addr", required=True); p.add_argument("--len", type=int)
    p.add_argument("--max-report", type=int, default=10); sess(p, 120); p.set_defaults(fn=cmd_snapshot)

    p = sub.add_parser("gdb-batch", help="run GDB commands in batch (needs a gdb binary)")
    p.add_argument("-ex", action="append", help="GDB command (repeatable, default: bt)")
    p.add_argument("--port", type=int); sess(p, 120); p.set_defaults(fn=cmd_gdb_batch)

    p = sub.add_parser("wait"); p.add_argument("--no-resume", action="store_true")
    p.add_argument("--cond", help='evaluate after each stop; resume if false. Example: "r0==1" / "[0x20000000]!=0"')
    p.add_argument("--log", help='expression recorded on each hit, e.g. "[0x20000000]"')
    p.add_argument("--max-hits", type=int); p.add_argument("--continue", dest="continue_after", action="store_true")
    p.add_argument("--on-hit", help='semicolon script: "print r0; bt; continue"')
    sess(p, 10); p.set_defaults(fn=cmd_wait)

    p = sub.add_parser("mem"); p.add_argument("mem_cmd", choices=["read", "write"])
    p.add_argument("address", type=lambda x: int(x, 0)); p.add_argument("values", nargs="*")
    p.add_argument("--width", type=int, default=32, choices=[8, 16, 32]); p.add_argument("--count", type=int, default=1)
    p.add_argument("--json", action="store_true"); sess(p, 60, connect=True); p.set_defaults(fn=cmd_mem)

    p = sub.add_parser("regs"); p.add_argument("--json", action="store_true")
    sess(p, 60, connect=True); p.set_defaults(fn=cmd_regs)

    p = sub.add_parser("state"); sess(p, 60); p.set_defaults(fn=cmd_state)

    p = sub.add_parser("dapreg"); p.add_argument("dap_cmd", choices=["read", "write"])
    p.add_argument("addr"); p.add_argument("value", nargs="?"); sess(p, 60); p.set_defaults(fn=cmd_dapreg)

    p = sub.add_parser("option"); p.add_argument("option_cmd", choices=["read", "write"])
    p.add_argument("--addr", required=True); p.add_argument("--width", type=int, default=32, choices=[8, 16, 32])
    p.add_argument("--count", type=int, default=1); p.add_argument("--value"); p.add_argument("--yes", action="store_true")
    sess(p, 60); p.set_defaults(fn=cmd_option)

    p = sub.add_parser("bp"); p.add_argument("bp_cmd", choices=["set", "list", "clear"])
    p.add_argument("addr", nargs="?", help="0xADDR | SYMBOL | file.c:LINE")
    p.add_argument("--type", choices=["hw", "sw", "auto", "flash"], default="auto")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--all", action="store_true"); p.add_argument("--wait", type=int, metavar="SECONDS")
    p.add_argument("--cond"); p.add_argument("--log"); p.add_argument("--max-hits", type=int)
    p.add_argument("--on-hit", help='semicolon script: "print r0; bt; continue"')
    p.add_argument("--continue", dest="continue_after", action="store_true")
    sess(p, 60); p.set_defaults(fn=cmd_bp)

    p = sub.add_parser("wp"); p.add_argument("wp_cmd", choices=["set", "list", "clear"])
    p.add_argument("addr", nargs="?"); p.add_argument("--size", type=int, default=4)
    p.add_argument("--type", choices=["r", "w", "rw"], default="w"); sess(p, 60); p.set_defaults(fn=cmd_wp)

    p = sub.add_parser("svd"); p.add_argument("svd_cmd", choices=["attach", "list", "read", "write", "field"])
    p.add_argument("reg", nargs="?", help="PERIPH or PERIPH.REG or PERIPH.REG.FIELD")
    p.add_argument("value", nargs="?"); p.add_argument("--file"); p.add_argument("--svd")
    p.add_argument("--search", "-s"); sess(p, 60); p.set_defaults(fn=cmd_svd)

    p = sub.add_parser("config"); p.add_argument("config_cmd", choices=["get", "set", "unset", "list"])
    p.add_argument("key", nargs="?"); p.add_argument("value", nargs="?"); p.set_defaults(fn=cmd_config)

    p = sub.add_parser("rtt"); p.add_argument("--address", "-a"); p.add_argument("--size", "-s", type=int)
    p.add_argument("--mode", "-M", choices=["attach", "rescan"]); p.add_argument("--log", "-d")
    p.add_argument("--duration", type=int, default=15); sess(p, 60); p.set_defaults(fn=cmd_rtt)

    p = sub.add_parser("gdb"); p.add_argument("--port", "-p", type=int, default=3333)
    p.add_argument("--persist", action="store_true"); p.add_argument("--detach", action="store_true")
    p.add_argument("--log"); sess(p, 600); p.set_defaults(fn=cmd_gdb)

    p = sub.add_parser("wsl", help="WSL: inspect/attach Windows-side USB probes via usbipd")
    p.add_argument("action", nargs="?", choices=["status", "attach", "detach"], default="status")
    p.add_argument("--busid"); p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_wsl)

    p = sub.add_parser("engines", help="show available backends")
    p.set_defaults(fn=cmd_engines)

    p = sub.add_parser("cores", help="list cores of a multi-core target")
    sess(p, 60); p.set_defaults(fn=cmd_cores)

    p = sub.add_parser("cycles", help="DWT cycle counter")
    p.add_argument("--enable", action="store_true"); p.add_argument("--reset", action="store_true")
    p.add_argument("--hz", type=int); sess(p, 60); p.set_defaults(fn=cmd_cycles)

    p = sub.add_parser("profile", help="approximate PC-sampling profiler")
    p.add_argument("--duration", type=float, default=3.0); p.add_argument("--interval", type=float, default=0.01)
    p.add_argument("--top", type=int, default=15); sess(p, 120); p.set_defaults(fn=cmd_profile)

    p = sub.add_parser("selfcheck", help="non-destructive hardware validation")
    p.add_argument("--json", action="store_true")
    sess(p, 60); p.set_defaults(fn=cmd_selfcheck)

    p = sub.add_parser("semi", help="service ARM semihosting while running")
    p.add_argument("--duration", type=float, default=10.0)
    sess(p, 60); p.set_defaults(fn=cmd_semi)

    p = sub.add_parser("swo", help="live SWO/ITM trace (needs probe SWO support)")
    p.add_argument("--cpu-freq", type=int, default=72000000); p.add_argument("--swo-freq", type=int, default=2000000)
    p.add_argument("--duration", type=float, default=5.0); p.add_argument("--raw", help="also write raw SWO bytes")
    sess(p, 60); p.set_defaults(fn=cmd_swo)

    p = sub.add_parser("repl", help="persistent session REPL / batch")
    p.add_argument("-c", "--cmd", action="append", help="command to run (repeatable)")
    p.add_argument("--json", action="store_true"); sess(p, 600); p.set_defaults(fn=cmd_repl)

    p = sub.add_parser("info"); sess(p, 60); p.set_defaults(fn=cmd_info)

    a = ap.parse_args()
    if hasattr(a, "target"):
        apply_defaults(a)
    a.fn(a)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:  # keep agent-facing output machine-readable
        if os.environ.get("DAP_DEBUG"):
            raise
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False),
              file=sys.stderr)
        sys.exit(1)
