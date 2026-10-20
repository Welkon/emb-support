"""Instrument transports: raw SCPI socket, pyvisa, Linux usbtmc."""

from __future__ import annotations

import glob
import os
import socket
import sys
import time

from .common import HOME, block_bounds, die, is_block, load_config, parse_block
from .wsl import ensure_scope_attached, is_wsl

class SocketInstrument:
    """Raw SCPI over TCP (port 5025 on most instruments)."""

    def __init__(self, host: str, port: int = 5025, timeout: float = 5.0):
        self.host, self.port, self.timeout = host, port, timeout
        try:
            self.sock = socket.create_connection((host, port), timeout)
        except OSError as e:
            die(f"cannot connect to {host}:{port}: {e}")
        self.sock.settimeout(timeout)
        self.resource = f"TCPIP::{host}::{port}::SOCKET"

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass

    def write(self, cmd: str) -> None:
        self.sock.sendall(cmd.encode() + b"\n")

    def _read(self) -> bytes:
        buf = b""
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            chunk = self.sock.recv(65536)
            if not chunk:
                break
            buf += chunk
            bounds = block_bounds(buf)
            if bounds is not None:
                return buf[:bounds[1]]
            if b"#" not in buf and b"\n" in buf:
                return buf
        return buf

    def query(self, cmd: str) -> str:
        self.write(cmd)
        raw = parse_block(self._read())
        return raw.decode(errors="replace").strip()

    def query_block(self, cmd: str) -> bytes:
        self.write(cmd)
        raw = self._read()
        return parse_block(raw) if is_block(raw) else raw

    def _read_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                break
            buf += chunk
        return buf

    def query_prefixed(self, cmd: str) -> bytes:
        """Owon-style payload: 4-byte little-endian length, then data."""
        self.write(cmd)
        size = int.from_bytes(self._read_exact(4), "little")
        return self._read_exact(size) if size else b""

    def read_message(self, cmd: str) -> bytes:
        """Read one transport message verbatim (vendor-specific framing)."""
        self.write(cmd)
        old = self.sock.gettimeout()
        self.sock.settimeout(0.3)
        buf = b""
        try:
            while True:
                chunk = self.sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
        except (socket.timeout, TimeoutError):
            pass
        finally:
            self.sock.settimeout(old)
        return buf


class VisaInstrument:
    """pyvisa / pyvisa-py backend: USBTMC, VXI-11, serial, GPIB."""

    def __init__(self, resource: str, timeout: float = 5.0, backend: str | None = None,
                 strict: bool = True):
        try:
            import pyvisa
        except ImportError:
            die("pyvisa is required for this resource. Run: scope.py setup")
        if backend is None:
            # On Windows with the vendor TekVISA runtime, auto-loading lets a 32-bit
            # interpreter find the 32-bit visa32.dll. @py ignores vendor DLLs.
            backend = None if os.name == "nt" else "@py"
        elif backend.lower() == "auto":
            backend = None
        try:
            self.rm = pyvisa.ResourceManager(backend) if backend else pyvisa.ResourceManager()
            self.inst = self.rm.open_resource(resource)
        except Exception as e:
            if strict:
                die(f"cannot open {resource}: {e}")
            raise RuntimeError(str(e))
        self.inst.timeout = int(timeout * 1000)
        try:
            self.inst.read_termination = "\n"
            self.inst.write_termination = "\n"
        except Exception:
            pass
        try:
            self.inst.clear()   # reset a stale USBTMC queue from a previous session
        except Exception:
            pass
        self.resource = resource

    def close(self):
        try:
            self.inst.close()
        except Exception:
            pass

    def write(self, cmd: str) -> None:
        self.inst.write(cmd)

    def _recover(self) -> None:
        """Best-effort cleanup after a failed read: drop a stale queue."""
        for action in ("clear", "close"):
            try:
                getattr(self.inst, action)()
                if action == "close":
                    return
            except Exception:
                continue

    def query(self, cmd: str) -> str:
        try:
            return self.inst.query(cmd).strip()
        except Exception as exc:
            # A timeout is normal for a command the instrument does not answer
            # (for example :SYSTem:ERRor? on a DS1000Z). Fail with a usable
            # message instead of a pyvisa traceback, and leave the queue clean.
            self._recover()
            raise RuntimeError(
                f"no response to {cmd!r}: {exc}. The instrument may not support this "
                f"command; raise --timeout, or send it with scpi --write") from exc

    def query_block(self, cmd: str) -> bytes:
        self.inst.write(cmd)
        return parse_block(bytes(self.inst.read_raw()))

    def query_prefixed(self, cmd: str) -> bytes:
        self.inst.write(cmd)
        try:
            head = bytes(self.inst.read_bytes(4))
        except Exception:
            head = b""
        if len(head) < 4:
            return b""
        size = int.from_bytes(head, "little")
        return bytes(self.inst.read_bytes(size)) if size else b""

    def read_message(self, cmd: str) -> bytes:
        self.inst.write(cmd)
        return bytes(self.inst.read_raw())


class UsbtmcInstrument:
    """Linux usbtmc kernel driver (/dev/usbtmcN), no pyvisa needed."""

    def __init__(self, path: str, timeout: float = 5.0):
        try:
            self.fd = open(path, "r+b", buffering=0)
        except OSError as e:
            die(f"cannot open {path}: {e} (check udev permissions / usbtmc module)")
        self.path, self.timeout = path, timeout
        self.resource = path

    def close(self):
        try:
            self.fd.close()
        except Exception:
            pass

    def write(self, cmd: str) -> None:
        self.fd.write(cmd.encode() + b"\n")

    def query(self, cmd: str) -> str:
        self.write(cmd)
        return self.fd.read(1 << 20).decode(errors="replace").strip()

    def query_block(self, cmd: str) -> bytes:
        self.write(cmd)
        data = self.fd.read(1 << 24)
        return parse_block(data) if is_block(data) else data


_CACHE = HOME / "last_resource"


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


def pick_single_resource(resources: list[str]) -> str | None:
    """Auto-pick only when exactly one VISA instrument is present."""
    instruments = [r for r in resources
                   if "::INSTR" in r and ("USB" in r.upper() or "TCPIP" in r.upper())]
    return instruments[0] if len(instruments) == 1 else None


def _list_resources(backend):
    if backend is None and os.name != "nt":
        backend = "@py"
    try:
        import pyvisa
        rm = pyvisa.ResourceManager(backend) if backend else pyvisa.ResourceManager()
        return list(rm.list_resources())
    except Exception:
        return []


def connect(a):
    cfg = load_config()
    resource = getattr(a, "resource", None) or cfg.get("resource")
    host = getattr(a, "host", None) or cfg.get("host")
    port = int(getattr(a, "port", None) or cfg.get("port") or 5025)
    timeout = float(getattr(a, "timeout", None) or cfg.get("timeout") or 5.0)
    backend = getattr(a, "backend", None) or cfg.get("backend")
    no_auto_attach = (getattr(a, "no_auto_attach", False)
                      or os.environ.get("SCOPE_NO_AUTO_ATTACH") == "1")

    if getattr(a, "resource", None):
        return VisaInstrument(a.resource, timeout, backend)
    if host:
        return SocketInstrument(host, port, timeout)
    if resource:
        return VisaInstrument(resource, timeout, backend)

    devices = sorted(glob.glob("/dev/usbtmc*"))
    if devices:
        return UsbtmcInstrument(devices[0], timeout)

    cached = _cached_resource()
    if cached:
        try:
            return VisaInstrument(cached, timeout, backend, strict=False)
        except Exception:
            pass

    resources = _list_resources(backend)
    picked = pick_single_resource(resources)
    if picked:
        _remember_resource(picked)
        return VisaInstrument(picked, timeout, backend)

    if is_wsl() and not no_auto_attach:
        outcome = ensure_scope_attached()
        devices = sorted(glob.glob("/dev/usbtmc*"))
        if devices:
            return UsbtmcInstrument(devices[0], timeout)
        resources = _list_resources(backend)
        picked = pick_single_resource(resources)
        if picked:
            _remember_resource(picked)
            return VisaInstrument(picked, timeout, backend)
        if outcome.get("status") == "needs-bind":
            hints = "; ".join(
                f'usbipd bind --busid {d["busid"]} (Administrator)' for d in outcome["needs_bind"])
            die(f"WSL: oscilloscope is connected to Windows but not shared. Run: {hints}")
        if outcome.get("status") == "no-device":
            die("WSL: no oscilloscope found on the Windows side. Plug it in, then run doctor --attach-usb")
        die("WSL: usbipd attach ran but no /dev/usbtmc node appeared; run doctor for details")

    if len(resources) > 1:
        die("multiple VISA instruments found; pass --resource: " + ", ".join(resources))
    die("no instrument selected: pass --host, --resource, or set a default with config")


# -------------------------------------------------------------------- dialects
