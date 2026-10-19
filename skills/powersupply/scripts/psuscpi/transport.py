"""Instrument transports: raw SCPI socket, pyvisa, usbtmc and serial."""

from __future__ import annotations

import glob
import os
import socket
import time

from .common import die, load_config


class SocketInstrument:
    def __init__(self, host: str, port: int = 5025, timeout: float = 3.0):
        try:
            self.sock = socket.create_connection((host, port), timeout)
        except OSError as e:
            die(f"cannot connect to {host}:{port}: {e}")
        self.sock.settimeout(timeout)
        self.resource = f"TCPIP::{host}::{port}::SOCKET"
        self.timeout = timeout

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
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            buf += chunk
            if b"\n" in buf:
                break
        return buf

    def query(self, cmd: str) -> str:
        self.write(cmd)
        return self._read().decode(errors="replace").strip()


class VisaInstrument:
    def __init__(self, resource: str, timeout: float = 3.0, backend: str | None = None):
        try:
            import pyvisa
        except ImportError:
            die("pyvisa is required for this resource. Run: psu.py setup")
        if backend is None:
            backend = None if os.name == "nt" else "@py"
        elif backend.lower() == "auto":
            backend = None
        try:
            self.rm = pyvisa.ResourceManager(backend) if backend else pyvisa.ResourceManager()
            self.inst = self.rm.open_resource(resource)
        except Exception as e:
            die(f"cannot open {resource}: {e}")
        self.inst.timeout = int(timeout * 1000)
        for attr in ("read_termination", "write_termination"):
            try:
                setattr(self.inst, attr, "\n")
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

    def query(self, cmd: str) -> str:
        return self.inst.query(cmd).strip()


class UsbtmcInstrument:
    def __init__(self, path: str, timeout: float = 3.0):
        try:
            self.fd = open(path, "r+b", buffering=0)
        except OSError as e:
            die(f"cannot open {path}: {e} (check udev/permissions)")
        self.path = path
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


class SerialInstrument:
    def __init__(self, port: str, baud: int = 9600, timeout: float = 3.0):
        try:
            import serial
        except ImportError:
            die("pyserial is required for --serial. Run: psu.py setup")
        try:
            self.ser = serial.Serial(port, baudrate=baud, timeout=timeout)
        except Exception as e:
            die(f"cannot open serial port {port}: {e}")
        self.resource = f"ASRL::{port}::{baud}"

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass

    def write(self, cmd: str) -> None:
        self.ser.write(cmd.encode() + b"\n")

    def query(self, cmd: str) -> str:
        self.write(cmd)
        return self.ser.readline().decode(errors="replace").strip()


def pick_single_resource(resources: list[str]) -> str | None:
    instruments = [r for r in resources
                   if "::INSTR" in r and ("USB" in r.upper() or "TCPIP" in r.upper())]
    return instruments[0] if len(instruments) == 1 else None


def _list_resources(backend):
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
    timeout = float(getattr(a, "timeout", None) or cfg.get("timeout") or 3.0)
    backend = getattr(a, "backend", None) or cfg.get("backend")
    serial_port = getattr(a, "serial", None) or cfg.get("serial")
    baud = int(getattr(a, "baud", None) or cfg.get("baud") or 9600)

    if getattr(a, "resource", None):
        return VisaInstrument(a.resource, timeout, backend)
    if host:
        return SocketInstrument(host, port, timeout)
    if serial_port:
        return SerialInstrument(serial_port, baud, timeout)
    if resource:
        return VisaInstrument(resource, timeout, backend)

    devices = sorted(glob.glob("/dev/usbtmc*"))
    if devices:
        return UsbtmcInstrument(devices[0], timeout)

    resources = _list_resources(backend)
    picked = pick_single_resource(resources)
    if picked:
        return VisaInstrument(picked, timeout, backend)

    if len(resources) > 1:
        die("multiple VISA instruments found; pass --resource: " + ", ".join(resources))
    die("no instrument selected: pass --host/--resource/--serial, or set a default with config")
