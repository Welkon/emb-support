"""Where the instrument connection comes from, as one ordered chain.

Explicit flags, then saved config, then kernel usbtmc, then the resource cache,
then VISA discovery, then WSL attach. The source travels with the connection so
`status` can say why a command reached this instrument.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass

from .common import HOME, die, load_config, save_config
from .transport import (
    SocketInstrument, UsbtmcInstrument, VisaInstrument, pick_single_resource,
)
from .wsl import ensure_scope_attached, is_wsl

_CACHE = HOME / "last_resource"


@dataclass
class Connected:
    inst: object
    source: str
    detail: str = ""


def _cached_resource() -> str | None:
    try:
        value = _CACHE.read_text().strip()
        return value or None
    except OSError:
        return None


def _remember_resource(resource: str) -> None:
    try:
        HOME.mkdir(parents=True, exist_ok=True)
        _CACHE.write_text(resource + "\n")
    except OSError:
        pass


def _list_resources(backend):
    if backend is None and os.name != "nt":
        backend = "@py"
    try:
        import pyvisa
        manager = pyvisa.ResourceManager(backend) if backend else pyvisa.ResourceManager()
        return list(manager.list_resources())
    except Exception:  # noqa: BLE001
        return []


def _remember_instance(inst) -> None:
    """Persist the connection that worked, so later commands need no flags."""
    resource = getattr(inst, "resource", None) or ""
    if "::SOCKET" in resource:
        parts = resource.split("::")
        try:
            port = int(parts[2])
        except (IndexError, ValueError):
            return
        cfg = load_config()
        cfg.pop("resource", None)
        cfg["host"], cfg["port"] = parts[1], port
    elif "::INSTR" in resource:
        cfg = load_config()
        cfg.pop("host", None)
        cfg.pop("port", None)
        cfg["resource"] = resource
    else:
        return
    try:
        save_config(cfg)
    except OSError:
        pass


def resolve(a) -> Connected:
    cfg = load_config()
    explicit_resource = getattr(a, "resource", None)
    explicit_host = getattr(a, "host", None)
    resource = explicit_resource or cfg.get("resource")
    host = explicit_host or cfg.get("host")
    port = int(getattr(a, "port", None) or cfg.get("port") or 5025)
    timeout = float(getattr(a, "timeout", None) or cfg.get("timeout") or 10.0)
    backend = getattr(a, "backend", None) or cfg.get("backend")
    no_auto_attach = (getattr(a, "no_auto_attach", False)
                      or os.environ.get("SCOPE_NO_AUTO_ATTACH") == "1")

    if explicit_resource:
        return Connected(VisaInstrument(explicit_resource, timeout, backend),
                         "explicit-resource", explicit_resource)
    if explicit_host:
        return Connected(SocketInstrument(explicit_host, port, timeout),
                         "explicit-host", f"{explicit_host}:{port}")
    if resource:
        try:
            return Connected(VisaInstrument(resource, timeout, backend, strict=False),
                             "config-resource", resource)
        except Exception:  # noqa: BLE001
            # The remembered device is gone. Fall through to discovery and
            # WSL attach instead of failing every command until the user
            # remembers to clear the config.
            pass
    if host:
        return Connected(SocketInstrument(host, port, timeout), "config-host", f"{host}:{port}")

    devices = sorted(glob.glob("/dev/usbtmc*"))
    if devices:
        return Connected(UsbtmcInstrument(devices[0], timeout), "usbtmc", devices[0])

    cached = _cached_resource()
    if cached:
        try:
            return Connected(VisaInstrument(cached, timeout, backend, strict=False),
                             "cache", cached)
        except Exception:  # noqa: BLE001
            pass

    resources = _list_resources(backend)
    picked = pick_single_resource(resources)
    if picked:
        _remember_resource(picked)
        return Connected(VisaInstrument(picked, timeout, backend), "discovered", picked)

    if is_wsl() and not no_auto_attach:
        outcome = ensure_scope_attached()
        devices = sorted(glob.glob("/dev/usbtmc*"))
        if devices:
            return Connected(UsbtmcInstrument(devices[0], timeout), "wsl-attach", devices[0])
        resources = _list_resources(backend)
        picked = pick_single_resource(resources)
        if picked:
            _remember_resource(picked)
            return Connected(VisaInstrument(picked, timeout, backend), "wsl-attach", picked)
        if outcome.get("status") == "needs-bind":
            hints = "; ".join(
                f'usbipd bind --busid {d["busid"]} (Administrator)'
                for d in outcome["needs_bind"])
            die(f"WSL: oscilloscope is connected to Windows but not shared. Run: {hints}")
        if outcome.get("status") == "no-device":
            die("WSL: no oscilloscope found on the Windows side. "
                "Plug it in, then run doctor --attach-usb")
        die("WSL: usbipd attach ran but no /dev/usbtmc node appeared; run doctor for details")

    if len(resources) > 1:
        die("multiple VISA instruments found; pass --resource: " + ", ".join(resources))
    die("no instrument selected: pass --host, --resource, or set a default with config")


def connect(a):
    connected = resolve(a)
    _remember_instance(connected.inst)
    setattr(connected.inst, "connection_source", connected.source)
    setattr(connected.inst, "connection_detail", connected.detail)
    return connected.inst
