#!/usr/bin/env python3
"""Generic oscilloscope CLI for LAN and USB instruments.

Transport:
  * raw TCP socket (port 5025) - no dependencies, works on most LAN scopes
  * pyvisa / pyvisa-py - USBTMC, VXI-11, serial, GPIB
  * Linux usbtmc kernel device (/dev/usbtmc*) - USBTMC without pyvisa

Dialects: rigol, keysight, tektronix, siglent, lecroy, rns, gwinstek,
yokogawa, generic. Auto-detected from *IDN?.

All output is JSON when --json is passed; otherwise a short human summary.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

HOME = Path(os.environ.get("SCOPE_HOME", str(Path.home() / ".local/share/scope"))).expanduser()
CONFIG = HOME / "config.json"
VENV = HOME / "venv"
IS_WIN = os.name == "nt"


# --------------------------------------------------------------------- helpers

def die(msg: str, code: int = 2) -> None:
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False), file=sys.stderr)
    sys.exit(code)


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


def parse_block(data: bytes) -> bytes:
    """Strip an IEEE-488.2 definite-length block header."""
    if not data:
        return data
    if not data.startswith(b"#"):
        return data
    if len(data) < 2 or not data[1:2].isdigit():
        return data
    ndigits = int(data[1:2])
    if ndigits == 0:
        return data[2:]
    if len(data) < 2 + ndigits:
        return data
    try:
        length = int(data[2:2 + ndigits])
    except ValueError:
        return data
    return data[2 + ndigits:2 + ndigits + length]


def is_block(data: bytes) -> bool:
    return data.startswith(b"#") and len(data) > 2 and data[1:2].isdigit()


# ------------------------------------------------------------------ transports

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
            if is_block(buf):
                nd = int(buf[1:2])
                if len(buf) >= 2 + nd:
                    try:
                        n = int(buf[2:2 + nd])
                    except ValueError:
                        return buf
                    if len(buf) >= 2 + nd + n:
                        return buf
            elif b"\n" in buf:
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


class VisaInstrument:
    """pyvisa / pyvisa-py backend: USBTMC, VXI-11, serial, GPIB."""

    def __init__(self, resource: str, timeout: float = 5.0, backend: str | None = None):
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
            die(f"cannot open {resource}: {e}")
        self.inst.timeout = int(timeout * 1000)
        try:
            self.inst.read_termination = "\n"
            self.inst.write_termination = "\n"
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


def connect(a):
    cfg = load_config()
    resource = getattr(a, "resource", None) or cfg.get("resource")
    host = getattr(a, "host", None) or cfg.get("host")
    port = int(getattr(a, "port", None) or cfg.get("port") or 5025)
    timeout = float(getattr(a, "timeout", None) or cfg.get("timeout") or 5.0)
    backend = getattr(a, "backend", None) or cfg.get("backend")
    if getattr(a, "resource", None):
        return VisaInstrument(a.resource, timeout, backend)
    if host:
        return SocketInstrument(host, port, timeout)
    if resource:
        return VisaInstrument(resource, timeout, backend)
    devices = sorted(glob.glob("/dev/usbtmc*"))
    if devices:
        return UsbtmcInstrument(devices[0], timeout)
    die("no instrument selected: pass --host, --resource, or set a default with config")


# -------------------------------------------------------------------- dialects

def fnum(x: float) -> str:
    return f"{x:.10g}"


class Dialect:
    """SCPI command builder. Override only what differs per vendor."""

    name = "generic"

    def __init__(self, idn: str = ""):
        self.idn = idn

    # --- channel
    def ch(self, n: int) -> str:
        return f"CHANnel{n}"

    def channel_scale(self, n, v): return f":{self.ch(n)}:SCALe {fnum(v)}"
    def channel_offset(self, n, v): return f":{self.ch(n)}:OFFSet {fnum(v)}"
    def channel_coupling(self, n, v): return f":{self.ch(n)}:COUPling {v}"
    def channel_probe(self, n, v): return f":{self.ch(n)}:PROBe {fnum(v)}"
    def channel_display(self, n, on): return f":{self.ch(n)}:DISPlay {'ON' if on else 'OFF'}"

    # --- timebase
    def timebase_scale(self, v): return f":TIMebase:SCALe {fnum(v)}"
    def timebase_offset(self, v): return f":TIMebase:OFFSet {fnum(v)}"

    # --- acquisition
    def run(self): return ":RUN"
    def stop(self): return ":STOP"
    def single(self): return ":SINGle"
    def autoscale(self): return ":AUToscale"

    # --- trigger
    def trigger_source(self, n): return f":TRIGger:EDGE:SOURce CHANnel{n}"
    def trigger_level(self, v): return f":TRIGger:EDGE:LEVel {fnum(v)}"
    def trigger_slope(self, v): return f":TRIGger:EDGE:SLOPe {v}"
    def trigger_sweep(self, v): return f":TRIGger:SWEep {v}"
    def trigger_type(self): return ":TRIGger:MODE EDGE"
    def trigger_pulse(self, width, polarity="POSitive", when="LESSthan"):
        return []
    def arm_single(self): return [self.single()]
    def state_queries(self): return [":TRIGger:STATe?", ":ACQuire:STATE?"]

    # --- waveform transfer
    def waveform_setup(self, n: int, points: int | None) -> list[str]:
        cmds = [f":WAVeform:SOURce {self.wave_source(n)}",
                ":WAVeform:FORMat BYTE"]
        if points:
            cmds.append(f":WAVeform:POINts {int(points)}")
        return cmds

    def wave_source(self, n: int) -> str:
        return f"CHANnel{n}"

    def preamble_query(self) -> str:
        return ":WAVeform:PREamble?"

    def data_query(self) -> str:
        return ":WAVeform:DATA?"

    def parse_preamble(self, text: str) -> dict:
        vals = [v for v in re.split(r"[,]", text.strip()) if v != ""]
        if len(vals) < 10:
            raise ValueError(f"unexpected waveform preamble: {text[:120]}")
        nums = [float(v) for v in vals[:10]]
        return {"format": int(nums[0]), "type": int(nums[1]),
                "points": int(nums[2]), "count": int(nums[3]),
                "xincr": nums[4], "xorig": nums[5], "xref": nums[6],
                "yincr": nums[7], "yorig": nums[8], "yref": nums[9]}

    def measure_query(self, item: str, n: int) -> str | None:
        return f":MEASure:{item.upper()}? {self.measure_source(n)}"

    def clean(self, text: str) -> str:
        return text.strip()

    def parse_measure(self, text: str) -> float:
        return float(self.clean(text))

    def measure_source(self, n: int) -> str:
        return f"CHANnel{n}"

    # --- screenshot
    def screenshot_queries(self) -> list[str]:
        return [":DISPlay:DATA? PNG", ":DISPlay:DATA? PNG,SCReen,COLor", ":DISPlay:DATA?"]

    def screenshot(self, inst):
        for query in self.screenshot_queries():
            try:
                data = inst.query_block(query)
            except Exception:
                continue
            if data and (data.startswith(b"\x89PNG") or data.startswith(b"\xff\xd8")
                         or data.startswith(b"BM")):
                return query, data
        return None, None

    def acquire(self, inst, ch: int, points: int | None):
        for cmd in self.waveform_setup(ch, points):
            inst.write(cmd)
        text = inst.query(self.preamble_query())
        meta = self.parse_preamble(text)
        raw = inst.query_block(self.data_query())
        return meta, raw


class RigolDialect(Dialect):
    name = "rigol"

    def timebase_scale(self, v): return f":TIMebase:MAIN:SCALe {fnum(v)}"

    def waveform_setup(self, n, points):
        cmds = [f":WAVeform:SOURce {self.wave_source(n)}",
                ":WAVeform:FORMat BYTE", ":WAVeform:MODE NORMal"]
        if points:
            cmds.append(f":WAVeform:POINts {int(points)}")
        return cmds

    def screenshot_queries(self):
        return [":DISPlay:DATA?", ":DISPlay:DATA? PNG"]


class KeysightDialect(Dialect):
    name = "keysight"

    def measure_query(self, item, n):
        mapping = {"vpp": "VPP", "vmax": "VMAX", "vmin": "VMIN", "vavg": "VAV",
                   "vrms": "VRMS", "freq": "FREQ", "period": "PER", "duty": "DUTY"}
        key = mapping.get(item)
        return f":MEASure:{key}? CHANnel{n}" if key else None

    def screenshot_queries(self):
        return [":DISPlay:DATA? PNG,SCReen,COLor", ":DISPlay:DATA? PNG", ":DISPlay:DATA?"]


class SiglentDialect(Dialect):
    name = "siglent"

    def timebase_scale(self, v): return f":TDIV {fnum(v)}"

    def wave_source(self, n): return f"C{n}"

    def measure_source(self, n): return f"C{n}"

    def trigger_source(self, n): return f":TRIGger:EDGE:SOURce C{n}"

    def parse_preamble(self, text):
        vals = [v for v in re.split(r"[,]", text.strip()) if v != ""]
        if len(vals) >= 10:
            return super().parse_preamble(text)
        # Siglent SDS: 5 fields (points, xincr, xorig, yincr, yorig)
        if len(vals) >= 5:
            n, xincr, xorig, yincr, yorig = [float(v) for v in vals[:5]]
            return {"format": 0, "type": 0, "points": int(n), "count": int(n),
                    "xincr": xincr, "xorig": xorig, "xref": 0.0,
                    "yincr": yincr, "yorig": yorig, "yref": 0.0}
        raise ValueError(f"unexpected waveform preamble: {text[:120]}")


TEK_PREAMBLE = {
    "xincr": ("WFMPre:XINcr?", "WFMOutpre:XINcr?", "WFMPRE:XINCR?"),
    "xorig": ("WFMPre:XZEro?", "WFMOutpre:XZEro?", "WFMPRE:XZERO?"),
    "xref": ("WFMPre:PT_Off?", "WFMOutpre:PT_Off?", "WFMPRE:PT_OFF?"),
    "yincr": ("WFMPre:YMUlt?", "WFMOutpre:YMUlt?", "WFMPRE:YMULT?"),
    "yorig": ("WFMPre:YZEro?", "WFMOutpre:YZEro?", "WFMPRE:YZERO?"),
    "yref": ("WFMPre:YOFf?", "WFMOutpre:YOFf?", "WFMPRE:YOFF?"),
    "points": ("WFMOutpre:NR_Pt?", "WFMPre:NR_Pt?"),
}


def _q_first(inst, commands):
    last = None
    for cmd in commands:
        try:
            val = inst.query(cmd).strip()
            if val:
                return val
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"no response for {commands[0]}: {last}")


class TektronixDialect(Dialect):
    """Tektronix TBS/TDS/DPO family.

    Uses the ASCII curve path that is validated on TBS1102B; preamble fields are
    probed with WFMPre/WFMOutpre/WFMPRE fallbacks because the spelling differs
    across firmware generations.
    """

    name = "tektronix"

    def ch(self, n): return f"CH{n}"

    def timebase_scale(self, v): return f":HORizontal:SCAle {fnum(v)}"
    def timebase_offset(self, v): return f":HORizontal:POSition {fnum(v)}"

    def trigger_source(self, n): return f":TRIGger:A:EDGE:SOURce CH{n}"
    def trigger_level(self, v): return f":TRIGger:A:EDGE:LEVel {fnum(v)}"
    def trigger_slope(self, v): return f":TRIGger:A:EDGE:SLOpe {v}"
    def trigger_sweep(self, v): return f":TRIGger:A:MODe {v}"
    def trigger_type(self): return ":TRIGger:A:TYPe EDGE"

    def trigger_pulse(self, width, polarity="POSitive", when="LESSthan"):
        return [":TRIGger:A:TYPe PULSe",
                f":TRIGger:A:PULse:WIDth:WHEn {when}",
                f":TRIGger:A:PULse:WIDth:WIDth {fnum(width)}",
                f":TRIGger:A:PULse:POLarity {polarity}"]

    def arm_single(self):
        return [":ACQuire:STOPAfter SEQuence", ":ACQuire:STATE RUN"]

    def state_queries(self):
        return [":ACQuire:STATE?", ":TRIGger:STATe?"]

    def measure_query(self, item, n): return None

    def screenshot_queries(self):
        return [":SAVE:IMAGe:FILEFormat PNG", ":DISPlay:DATA? PNG"]

    def acquire(self, inst, ch, points):
        inst.write(f"DATa:SOUrce CH{ch}")
        inst.write("DATa:ENCdg ASCII")
        inst.write("DATa:WIDth 1")
        if points:
            inst.write("DATa:STARt 1")
            inst.write(f"DATa:STOP {int(points)}")
        text = inst.query("CURVe?")
        samples = [float(x) for x in re.split(r"[,;\s]+", text.strip()) if x]
        meta = {key: float(_q_first(inst, cmds)) for key, cmds in TEK_PREAMBLE.items()}
        meta.update({"points": len(samples), "count": len(samples),
                     "format": 0, "type": 0})
        return meta, samples


class LeCroyDialect(Dialect):
    name = "lecroy"

    def acquire(self, inst, ch, points):
        raise RuntimeError(
            "LeCroy waveform transfer uses C{n}:WF? DAT2 (WAVEDESC binary); "
            "not implemented. Use measure/scpi or the LeCroy MAUI tools.")

    def timebase_scale(self, v): return f":TIMebase:SCALe {fnum(v)}"

    def measure_query(self, item, n): return None

    def screenshot_queries(self):
        return [":HARDcopy:SETUP? PNG", ":DISPlay:DATA?"]


class RnsDialect(KeysightDialect):
    name = "rns"

    def acquire(self, inst, ch, points):
        raise RuntimeError(
            "R&S RTB/RTO/HMO waveform transfer uses :CHANnel<n>:DATA? with a header "
            "query; not implemented for this dialect yet. Use scpi or the vendor tool.")


class GwInstekDialect(Dialect):
    name = "gwinstek"

    def acquire(self, inst, ch, points):
        raise RuntimeError(
            "GW Instek GDS waveform transfer uses a model-specific command "
            "(:CHANnel<n>:DATA?); not verified for this family. Use scpi.")

    def measure_query(self, item, n):
        mapping = {"vpp": "VPP", "vmax": "VMAX", "vmin": "VMIN", "vavg": "VAV",
                   "vrms": "VRMS", "freq": "FREQ", "period": "PER"}
        key = mapping.get(item)
        return f":MEASure:{key}? CHANnel{n}" if key else None


class OwonDialect(Dialect):
    """Owon / Hanmatek (SDS1104, DOS1104).

    Documented by the SCPI_COMMANDS.md in bushjavier/hanmatek-dos1104-py:
    replies end with "->", waveform payloads are a 4-byte length + data, and
    the screen header is JSON.
    """

    name = "owon"

    def ch(self, n): return f"CH{n}"
    def channel_scale(self, n, v): return f":CH{n}:SCAL {fnum(v)}"
    def channel_offset(self, n, v): return f":CH{n}:OFFS {fnum(v)}"
    def channel_coupling(self, n, v): return f":CH{n}:COUP {v}"
    def channel_probe(self, n, v): return f":CH{n}:PROB {int(v)}X"
    def channel_display(self, n, on): return f":CH{n}:DISP {'ON' if on else 'OFF'}"

    def timebase_scale(self, v): return f":HORIzontal:Scale {fnum(v)}"
    def timebase_offset(self, v): return f":HORIzontal:OFFSET {fnum(v)}"

    def run(self): return ":RUNning RUN"
    def stop(self): return ":RUNning STOP"
    def single(self): return ":TRIGger:SINGle:Sweep SINGLE"
    def arm_single(self): return [":TRIGger:SINGle:Sweep SINGLE", ":RUNning RUN"]
    def state_queries(self): return [":TRIG:STAT?"]

    def trigger_source(self, n): return f":TRIGger:SINGle:SOURce CH{n}"
    def trigger_level(self, v): return f":TRIGger:SINGle:EDGe:LEVel {fnum(v)}"
    def trigger_slope(self, v): return f":TRIGger:SINGle:EDGE {'RISE' if 'RIS' in v.upper() else 'FALL'}"
    def trigger_sweep(self, v): return f":TRIGger:SINGle:Sweep {v}"
    def trigger_type(self): return ":TRIGger:SINGle:MODE EDGE"

    MEAS = {"vpp": "PKPK", "vmax": "MAX", "vmin": "MIN", "mean": "AVER",
            "rms": "CYCRMS", "freq": "FREQ", "period": "PER", "duty": "PDUTY",
            "rise": "RTIME"}

    def measure_query(self, item, n):
        key = self.MEAS.get(item)
        return f":MEAS:CH{n}:{key}?" if key else None

    def clean(self, text):
        return text.strip().removesuffix("->").strip()

    def parse_measure(self, text):
        m = re.search(r"(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*([munp]?V|A|Hz|kHz|MHz|s|ms|us|ns|%)?", self.clean(text))
        if not m:
            raise ValueError(f"cannot parse measurement: {text!r}")
        mult = {"V": 1, "mV": 1e-3, "uV": 1e-6, "nV": 1e-9, "A": 1,
                "Hz": 1, "kHz": 1e3, "MHz": 1e6, "s": 1, "ms": 1e-3,
                "us": 1e-6, "ns": 1e-9, "%": 1}
        return float(m.group(1)) * mult.get(m.group(2) or "V", 1)

    def screenshot_queries(self):
        return [":DATA:WAVE:SCREEN:BMP?"]

    def screenshot(self, inst):
        for query in self.screenshot_queries():
            try:
                data = inst.query_prefixed(query)
            except Exception:
                continue
            if data and data.startswith(b"BM"):
                return query, data
        return None, None

    def acquire(self, inst, ch, points):
        head = inst.query_prefixed(":DATA:WAVE:SCREEN:HEAD?")
        meta_json = json.loads(head.decode(errors="replace"))
        payload = inst.query_prefixed(f":DATA:WAVE:SCREEN:CH{ch}?")
        samples = [int.from_bytes(payload[i:i + 2], "little")
                   for i in range(0, len(payload) - 1, 2)]
        chinfo = next((c for c in meta_json.get("CHANNEL", [])
                       if str(c.get("NAME", "")).upper() == f"CH{ch}"), {})
        vdiv = _parse_scaled(chinfo.get("SCALE", "1V"))
        rate = _parse_rate(meta_json.get("SAMPLE", {}).get("SAMPLERATE", "1kS/s"))
        dt = 1.0 / rate if rate else 1.0
        meta = {"points": len(samples), "count": len(samples), "format": 0, "type": 0,
                "xincr": dt, "xorig": -len(samples) * dt / 2, "xref": 0,
                "yincr": vdiv / 6400.0, "yorig": 0.0, "yref": 0.0}
        return meta, samples


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


class HantekDialect(Dialect):
    """Hantek DSO2000 series (DSO2C50/DOS1104 family).

    Command names follow refs/dso2c50-scpi-commands.md (p96xl/hantek-dso2000-esu-tester).
    Waveform export only works through a private vendor command, so capture is
    rejected with a pointer instead of returning wrong data.
    """

    name = "hantek"

    MEAS = {"vpp": "VPP", "vmax": "VMAX", "vmin": "VMIN", "mean": "VAVG",
            "freq": "FREQ", "period": "PER"}

    def measure_query(self, item, n):
        key = self.MEAS.get(item)
        return f":MEASure:CHANnel{n}:ITEM? {key}" if key else None

    def trigger_slope(self, v):
        return f":TRIGger:EDGe:SLOPe {'RISIng' if 'RIS' in v.upper() else 'FALLing'}"

    def state_queries(self): return [":TRIGger:STATus?"]

    def screenshot_queries(self): return [":DISPlay:DATA?"]

    def acquire(self, inst, ch, points):
        raise RuntimeError(
            "Hantek DSO2000 waveform export is vendor-private "
            "(PRIVate:WAVeform:DATA:ALL?); capture is not implemented. "
            "Use measure/scpi, or export the waveform with the vendor tool.")


class MicsigDialect(Dialect):
    """Micsig MHO series (vendor SCPI manual + tralamazza/micsig-rs)."""

    name = "micsig"

    def ch(self, n): return f"CHANnel{n}"
    def channel_scale(self, n, v): return f":CHANnel{n}:SCALe {fnum(v)}"
    def channel_offset(self, n, v): return f":CHANnel{n}:POSition {fnum(v)}"
    def channel_coupling(self, n, v): return f":CHANnel{n}:COUPle {v}"
    def channel_probe(self, n, v): return f":CHANnel{n}:PROBe {int(v)}"
    def channel_display(self, n, on): return f":CHANnel{n}:DISPlay {'ON' if on else 'OFF'}"

    def timebase_scale(self, v): return f":TIMebase:EXTent {fnum(v)}"
    def timebase_offset(self, v): return f":TIMebase:POSition {fnum(v)}"

    def run(self): return ":MENU:RUN"
    def stop(self): return ":MENU:STOP"
    def single(self): return ":MENU:SINGLE"
    def arm_single(self): return [":MENU:SINGLE", ":MENU:RUN"]
    def state_queries(self): return [":TRIGger:STATus?"]

    def trigger_source(self, n): return f":TRIGger:EDGE:SOURce CH{n}"
    def trigger_level(self, v): return f":TRIGger:EDGE:LEVel {fnum(v)}"
    def trigger_slope(self, v): return f":TRIGger:EDGE:SLOPe {'RISE' if 'RIS' in v.upper() else 'FALL'}"
    def trigger_sweep(self, v):
        v = v.upper()
        return f":TRIGger:MODE {'AUTO' if v.startswith('AUTO') else 'NORMal'}"

    MEAS = {"vpp": "PKPK", "vmax": "MAX", "vmin": "MIN", "mean": "AVER",
            "freq": "FREQ", "period": "PER"}

    def measure_query(self, item, n):
        key = self.MEAS.get(item)
        return f":MEASure:{key}? CH{n}" if key else None

    def waveform_setup(self, n, points):
        cmds = [f":WAVeform:SOURce CH{n}", ":WAVeform:MODE NORMal", ":WAVeform:FORMat BYTE"]
        if points:
            cmds += [":WAVeform:STARt 1", f":WAVeform:STOP {int(points)}"]
        return cmds

    def parse_preamble(self, text):
        vals = [v for v in re.split(r",", text.strip()) if v != ""]
        if len(vals) < 9:
            raise ValueError(f"unexpected waveform preamble: {text[:120]}")
        n = [float(x) for x in vals[:9]]
        count = int(n[2])
        return {"format": int(n[0]), "type": int(n[1]), "points": count, "count": count,
                "xincr": n[3], "xorig": n[4], "xref": n[5],
                "yincr": n[6], "yorig": n[7], "yref": n[8]}

    def screenshot_queries(self): return [":SYS:SCR?"]


class BkPrecisionDialect(Dialect):
    """BK Precision 2540/2560 (LeCroy MAUI command set)."""

    name = "bkprecision"

    def ch(self, n): return f"C{n}"
    def channel_scale(self, n, v): return f"C{n}:VDIV {fnum(v)}"
    def channel_offset(self, n, v): return f"C{n}:OFST {fnum(v)}"
    def channel_coupling(self, n, v): return f"C{n}:CPL {v}"
    def channel_probe(self, n, v): return f"C{n}:ATTN {fnum(v)}"
    def channel_display(self, n, on): return f"C{n}:TRA {'ON' if on else 'OFF'}"

    def timebase_scale(self, v): return f"TDIV {fnum(v)}"
    def timebase_offset(self, v): return f"TIME {fnum(v)}"

    def trigger_level(self, v): return f"TRLV {fnum(v)}"
    def trigger_slope(self, v): return f"TRSL {'POS' if 'RIS' in v.upper() else 'NEG'}"
    def trigger_sweep(self, v):
        v = v.upper()
        return f"TRMD {'NORM' if v.startswith('NORM') else v}"
    def trigger_type(self): return "TRSE EDGE"
    def trigger_source(self, n): return f"TRSE EDGE,SR,C{n},HT,OFF"
    def arm_single(self): return ["TRMD SINGLE"]
    def state_queries(self): return []

    MEAS = {"vpp": "VPP", "vmax": "MAX", "vmin": "MIN", "mean": "MEAN",
            "rms": "RMS", "freq": "FREQ", "period": "PER"}

    def measure_query(self, item, n):
        key = self.MEAS.get(item)
        return f"C{n}:PAVA? {key}" if key else None

    def screenshot_queries(self): return ["SCDP", ":DISPlay:DATA?"]

    def acquire(self, inst, ch, points):
        raise RuntimeError(
            "BK Precision captures use LeCroy's binary WAVEDESC format (C{n}:WF? DAT2); "
            "not implemented. Use measure/scpi or the vendor software.")


class UnitDialect(Dialect):
    """UNI-T UPO series (manual: UPO 3000E & UPO 2000E Programming Manual)."""

    name = "unit"

    def ch(self, n): return f"CHAN{n}"
    def channel_scale(self, n, v): return f":CHAN{n}:SCAL {fnum(v)}"
    def channel_offset(self, n, v): return f":CHAN{n}:OFFS {fnum(v)}"
    def channel_coupling(self, n, v): return f":CHAN{n}:COUP {v}"
    def channel_probe(self, n, v): return f":CHAN{n}:PROB {int(v)}"
    def channel_display(self, n, on): return f":CHAN{n}:DISP {'ON' if on else 'OFF'}"

    def timebase_scale(self, v): return f":TIMebase:SCALe {fnum(v)}"
    def timebase_offset(self, v): return f":TIMebase:OFFSet {fnum(v)}"

    def run(self): return ":RUN"
    def stop(self): return ":STOP"
    def single(self): return ":TRIGger:SWEep SINGle"
    def arm_single(self): return [":TRIGger:SWEep SINGle", ":RUN"] 

    def trigger_type(self): return ":TRIGger:MODE EDGE"
    def trigger_source(self, n): return f":TRIGger:SOURce CHAN{n}"
    def trigger_level(self, v): return f":TRIGger:LEVel {fnum(v)}"
    def trigger_slope(self, v): return f":TRIGger:EDGE:SLOPe {'POSitive' if 'RIS' in v.upper() else 'NEGative'}"
    def trigger_sweep(self, v): return f":TRIGger:SWEep {v}"

    def waveform_setup(self, n, points):
        cmds = [":WAVeform:FORMat BYTE", f":WAVeform:SOURce CHAN{n}"]
        if points:
            cmds.append(f":WAVeform:POINts {int(points)}")
        return cmds

    MEAS = {"vpp": "VPP", "vmax": "VMAX", "vmin": "VMIN", "mean": "VAVerage",
            "rms": "VRMS", "freq": "FREQuency", "period": "PERiod",
            "duty": "PDUTY", "rise": "RISetime", "fall": "FALLtime"}

    def measure_query(self, item, n):
        key = self.MEAS.get(item)
        return f":MEASure:{key}? CHAN{n}" if key else None

    def screenshot_queries(self): return [":DISPlay:DATA?"]


class FlukeDialect(Dialect):
    """Fluke PM3370/PM3380/PM3390 CombiScope (SCPI-99 style manual)."""

    name = "fluke"

    def channel_display(self, n, on):
        return f'SENSe:FUNCtion:{"ON" if on else "OFF"} "XTIMe:VOLTage{n}"'
    def channel_scale(self, n, v): return f"SENSe:VOLTage:RANGe:PTPeak {fnum(v)}"
    def channel_offset(self, n, v): return f"SENSe:VOLTage:RANGe:OFFSet {fnum(v)}"

    def timebase_scale(self, v): return f"SENSe:SWEep:TIME {fnum(v)}"
    def timebase_offset(self, v): return f"SENSe:SWEep:OFFSet:TIME {fnum(v)}"

    def trigger_source(self, n): return f"TRIGger:SOURce INTernal{n}"
    def trigger_level(self, v): return f"TRIGger:LEVel {fnum(v)}"

    def measure_query(self, item, n): return None
    def screenshot_queries(self): return [":DISPlay:DATA?"]

    def acquire(self, inst, ch, points):
        raise RuntimeError(
            "Fluke CombiScope traces use TRACe?/TRACe:POINts with instrument-specific "
            "scaling; capture is not implemented. Use measure/scpi or FlukeView.")


class PeakTechDialect(OwonDialect):
    """PeakTech 13xx series: same protocol as Owon (4-byte length + JSON header)."""

    name = "peaktech"


class AttenDialect(Dialect):
    """ATTEN ADS/AT series: no public SCPI reference found; generic fallback."""

    name = "atten"

    def acquire(self, inst, ch, points):
        raise RuntimeError("ATTEN waveform command is not documented publicly; use scpi.")



class YokogawaDialect(Dialect):
    """Yokogawa DLM series: waveform uses :WAVeform:SEND? / model-specific setup."""

    name = "yokogawa"

    def acquire(self, inst, ch, points):
        raise RuntimeError(
            "Yokogawa DLM waveform transfer uses :WAVeform:SEND? and model-specific "
            "preamble commands; not implemented. Use scpi or the vendor tool.")


class ZlgDialect(Dialect):
    """ZLG ZDS series: no public SCPI reference found; generic fallback."""

    name = "zlg"

    def acquire(self, inst, ch, points):
        raise RuntimeError("ZLG ZDS waveform command is not documented publicly; use scpi.")


FAMILIES = {
    "rigol": RigolDialect,
    "keysight": KeysightDialect,
    "tektronix": TektronixDialect,
    "siglent": SiglentDialect,
    "lecroy": LeCroyDialect,
    "rns": RnsDialect,
    "gwinstek": GwInstekDialect,
    "yokogawa": YokogawaDialect,
    "owon": OwonDialect,
    "hantek": HantekDialect,
    "micsig": MicsigDialect,
    "bkprecision": BkPrecisionDialect,
    "unit": UnitDialect,
    "fluke": FlukeDialect,
    "zlg": ZlgDialect,
    "peaktech": PeakTechDialect,
    "atten": AttenDialect,
    "generic": Dialect,
}


def detect_family(idn: str) -> str:
    u = idn.upper()
    if "RIGOL" in u:
        return "rigol"
    if "KEYSIGHT" in u or "AGILENT" in u or "HEWLETT" in u:
        return "keysight"
    if "TEKTRONIX" in u or u.startswith("TEK") or " TEK" in u:
        return "tektronix"
    if "SIGLENT" in u:
        return "siglent"
    if "LECROY" in u:
        return "lecroy"
    if "ROHDE" in u or "R&S" in u:
        return "rns"
    if "GW INSTEK" in u or "GWINSTEK" in u or "GOOD WILL" in u:
        return "gwinstek"
    if "YOKOGAWA" in u:
        return "yokogawa"
    if "OWON" in u or "HANMATEK" in u:
        return "owon"
    if "HANTEK" in u:
        return "hantek"
    if "MICSIG" in u:
        return "micsig"
    if "B&K" in u or "BK PRECISION" in u or "BKP" in u:
        return "bkprecision"
    if "UNI-T" in u or "UNIT" in u:
        return "unit"
    if "FLUKE" in u:
        return "fluke"
    if "ZLG" in u or "ZHIYUAN" in u:
        return "zlg"
    if "PEAKTECH" in u:
        return "peaktech"
    if "ATTEN" in u:
        return "atten"
    return "generic"


def make_dialect(idn: str, family: str | None) -> Dialect:
    name = family or detect_family(idn)
    if name not in FAMILIES:
        die(f"unknown family '{name}'; choose from: {', '.join(FAMILIES)}")
    return FAMILIES[name](idn)


# ---------------------------------------------------------------- acquisition

def to_volts(raw, meta: dict) -> list[float]:
    yincr, yorig, yref = meta["yincr"], meta["yorig"], meta["yref"]
    return [(float(b) - yref) * yincr + yorig for b in raw]


def to_times(meta: dict, n: int | None = None) -> list[float]:
    n = n or meta["points"]
    return [(i - meta["xref"]) * meta["xincr"] + meta["xorig"] for i in range(n)]


def stats(volts: list[float], times: list[float]) -> dict:
    if not volts:
        return {}
    n = len(volts)
    mean = sum(volts) / n
    rms = math.sqrt(sum(v * v for v in volts) / n)
    vmin, vmax = min(volts), max(volts)
    out = {"points": n, "vmin": vmin, "vmax": vmax, "vpp": vmax - vmin,
           "mean": mean, "rms": rms}
    if n > 2 and times:
        dt = (times[-1] - times[0]) / (n - 1)
        out["dt"] = dt
        mid = (vmin + vmax) / 2
        span = (vmax - vmin) * 0.5
        if span > 0:
            crossings = []
            for i in range(1, n):
                a, b = volts[i - 1], volts[i]
                if (a <= mid < b) or (a < mid <= b):
                    frac = (mid - a) / (b - a) if b != a else 0.0
                    t = times[i - 1] + frac * (times[i] - times[i - 1])
                    if not crossings or t - crossings[-1] > (times[1] - times[0]) * 0.5:
                        crossings.append(t)
            if len(crossings) >= 2:
                periods = [b - a for a, b in zip(crossings, crossings[1:])]
                period = sum(periods) / len(periods)
                if period > 0:
                    out["period"] = period
                    out["freq"] = 1.0 / period
            high = sum(1 for v in volts if v > mid) / n * 100.0
            out["duty_pct"] = high
            out.update(_edges(volts, times, vmin, vmax))
    return out


def _edges(volts, times, vmin, vmax):
    lo, hi = vmin + (vmax - vmin) * 0.1, vmin + (vmax - vmin) * 0.9
    n = len(volts)
    rise = fall = None
    for i in range(1, n):
        if rise is None and volts[i - 1] < lo <= volts[i] and volts[i] != volts[i - 1]:
            t0, v0 = times[i - 1], volts[i - 1]
            rise = t0 + (times[i] - t0) * (lo - v0) / (volts[i] - v0)
        if rise is not None and volts[i - 1] < hi <= volts[i] and volts[i] != volts[i - 1]:
            t0, v0 = times[i - 1], volts[i - 1]
            t1 = t0 + (times[i] - t0) * (hi - v0) / (volts[i] - v0)
            rise = t1 - rise
            break
    for i in range(1, n):
        if fall is None and volts[i - 1] > hi >= volts[i] and volts[i] != volts[i - 1]:
            t0, v0 = times[i - 1], volts[i - 1]
            fall = t0 + (times[i] - t0) * (hi - v0) / (volts[i] - v0)
        if fall is not None and volts[i - 1] > lo >= volts[i] and volts[i] != volts[i - 1]:
            t0, v0 = times[i - 1], volts[i - 1]
            t1 = t0 + (times[i] - t0) * (lo - v0) / (volts[i] - v0)
            fall = t1 - fall
            break
    out = {}
    if rise:
        out["rise_time"] = rise
    if fall:
        out["fall_time"] = fall
    return out


def acquire_channels(inst, dialect, channels, points):
    result = {}
    for ch in channels:
        meta, raw = dialect.acquire(inst, ch, points)
        volts = to_volts(raw, meta)
        times = to_times(meta, len(volts))
        result[ch] = {"times": times, "volts": volts, "meta": meta}
    return result


MEASURE_ITEMS = ["vpp", "vmin", "vmax", "mean", "rms", "freq", "period", "duty", "rise", "fall"]
ITEM_MAP = {"vpp": "vpp", "vmin": "vmin", "vmax": "vmax", "mean": "mean", "rms": "rms",
            "freq": "freq", "period": "period", "duty": "duty_pct", "rise": "rise_time",
            "fall": "fall_time"}


def measure_channel(inst, dialect, ch, items):
    out = {}
    compute = []
    for item in items:
        q = dialect.measure_query(item, ch)
        if q:
            try:
                out[item] = dialect.parse_measure(inst.query(q))
                continue
            except Exception:
                pass
        compute.append(item)
    if compute:
        meta, raw = dialect.acquire(inst, ch, None)
        volts = to_volts(raw, meta)
        times = to_times(meta, len(volts))
        st = stats(volts, times)
        for item in compute:
            key = ITEM_MAP.get(item)
            if key and key in st:
                out[item] = st[key]
    return out


# -------------------------------------------------------------------- commands

def _python_ok() -> bool:
    try:
        import pyvisa  # noqa: F401
        return True
    except Exception:
        return False


def cmd_setup(a) -> None:
    py = os.environ.get("SCOPE_PYTHON") or sys.executable
    if not VENV.exists():
        VENV.parent.mkdir(parents=True, exist_ok=True)
        rc, out, err = subprocess.run([py, "-m", "venv", str(VENV)],
                                      capture_output=True, text=True).returncode, "", ""
        if rc != 0:
            die(f"failed to create venv: {err or out}")
    pip = VENV / ("Scripts/pip.exe" if IS_WIN else "bin/pip")
    pkgs = ["pyvisa", "pyvisa-py", "pyusb", "numpy"]
    if getattr(a, "dev", False):
        pkgs.append("pytest")
    p = subprocess.run([str(pip), "install", "-U", "pip"] + pkgs, capture_output=True, text=True, timeout=900)
    if p.returncode != 0:
        die(f"pip install failed: {(p.stderr or p.stdout)[-1500:]}")
    emit({"ok": True, "venv": str(VENV), "packages": pkgs}, as_json=True)


def cmd_doctor(a) -> None:
    info = {"ok": True, "python": sys.executable, "pyvisa": None, "resources": [],
            "usbtmc": sorted(glob.glob("/dev/usbtmc*")), "socket_test": None, "hints": []}
    try:
        import pyvisa
        info["pyvisa"] = getattr(pyvisa, "__version__", "?")
        rm = pyvisa.ResourceManager("@py")
        info["resources"] = list(rm.list_resources())
    except Exception as e:
        info["pyvisa"] = None
        info["hints"].append(f"pyvisa not available ({e}); run scope.py setup for USB/VXI-11")
    host = getattr(a, "host", None) or load_config().get("host")
    port = int(getattr(a, "port", None) or load_config().get("port") or 5025)
    if host:
        try:
            with socket.create_connection((host, port), 1.5):
                info["socket_test"] = f"{host}:{port} reachable"
        except OSError as e:
            info["socket_test"] = f"{host}:{port} failed: {e}"
            info["hints"].append("check LAN address, firewall, and that SCPI is enabled on the scope")
    if not info["usbtmc"] and not info["resources"]:
        info["hints"].append("no USB instrument visible: check cable, usbtmc module, and udev permissions")
    emit(info, as_json=True)


def cmd_discover(a) -> None:
    found = []
    if a.scan:
        import concurrent.futures as cf
        base = a.scan.rsplit(".", 1)[0]
        port = int(a.port or 5025)

        def probe(i):
            host = f"{base}.{i}"
            try:
                with socket.create_connection((host, port), 0.15) as s:
                    s.sendall(b"*IDN?\n")
                    s.settimeout(0.5)
                    data = s.recv(256).decode(errors="replace").strip()
                    return {"host": host, "idn": data}
            except OSError:
                return None

        with cf.ThreadPoolExecutor(max_workers=64) as ex:
            for r in ex.map(probe, range(1, 255)):
                if r:
                    found.append(r)
    else:
        try:
            import pyvisa
            backend = getattr(a, "backend", None) or load_config().get("backend")
            if backend is None and os.name != "nt":
                backend = "@py"
            rm = pyvisa.ResourceManager(backend) if backend else pyvisa.ResourceManager()
            found = [{"resource": r} for r in rm.list_resources()]
        except Exception as e:
            emit({"ok": False, "error": f"pyvisa unavailable: {e}; use --scan 192.168.1.0/24"},
                 as_json=True)
            return
    emit({"ok": True, "instruments": found}, as_json=True)


def cmd_idn(a) -> None:
    inst = connect(a)
    try:
        idn = inst.query("*IDN?")
        family = a.family or detect_family(idn)
        emit({"ok": True, "resource": inst.resource, "idn": idn,
              "family": family, "families": list(FAMILIES)}, as_json=True)
    finally:
        inst.close()


def cmd_config(a) -> None:
    cfg = load_config()
    if a.config_cmd == "list":
        emit({"ok": True, "config": cfg, "path": str(CONFIG)}, as_json=True)
    elif a.config_cmd == "get":
        emit({"ok": True, "key": a.key, "value": cfg.get(a.key)}, as_json=True)
    elif a.config_cmd == "set":
        if not a.key or a.value is None:
            die("set requires key and value")
        val = int(a.value) if a.key == "port" else (float(a.value) if a.key == "timeout" else a.value)
        cfg[a.key] = val
        save_config(cfg)
        emit({"ok": True, "set": {a.key: val}}, as_json=True)
    else:
        cfg.pop(a.key, None)
        save_config(cfg)
        emit({"ok": True, "removed": a.key}, as_json=True)


def _dialect_for(a, inst):
    idn = ""
    try:
        idn = inst.query("*IDN?")
    except Exception:
        pass
    return make_dialect(idn, getattr(a, "family", None) or load_config().get("family")), idn


def cmd_channel(a) -> None:
    inst = connect(a)
    try:
        d, idn = _dialect_for(a, inst)
        cmds = []
        if a.scale is not None:
            cmds.append(d.channel_scale(a.ch, a.scale))
        if a.offset is not None:
            cmds.append(d.channel_offset(a.ch, a.offset))
        if a.coupling:
            cmds.append(d.channel_coupling(a.ch, a.coupling.upper()))
        if a.probe is not None:
            cmds.append(d.channel_probe(a.ch, a.probe))
        if a.on is not None:
            cmds.append(d.channel_display(a.ch, a.on))
        for c in cmds:
            inst.write(c)
        emit({"ok": True, "idn": idn, "family": d.name, "channel": a.ch, "commands": cmds},
             as_json=True)
    finally:
        inst.close()


def cmd_timebase(a) -> None:
    inst = connect(a)
    try:
        d, idn = _dialect_for(a, inst)
        cmds = []
        if a.scale is not None:
            cmds.append(d.timebase_scale(a.scale))
        if a.offset is not None:
            cmds.append(d.timebase_offset(a.offset))
        for c in cmds:
            inst.write(c)
        emit({"ok": True, "idn": idn, "family": d.name, "commands": cmds}, as_json=True)
    finally:
        inst.close()


def cmd_trigger(a) -> None:
    inst = connect(a)
    try:
        d, idn = _dialect_for(a, inst)
        cmds = [d.trigger_type()]
        if a.source is not None:
            cmds.append(d.trigger_source(a.source))
        if a.level is not None:
            cmds.append(d.trigger_level(a.level))
        if a.slope:
            cmds.append(d.trigger_slope(a.slope.upper()))
        if a.mode:
            cmds.append(d.trigger_sweep(a.mode.upper()))
        for c in cmds:
            inst.write(c)
        emit({"ok": True, "idn": idn, "family": d.name, "commands": cmds}, as_json=True)
    finally:
        inst.close()


def cmd_run(a) -> None:
    inst = connect(a)
    try:
        d, _ = _dialect_for(a, inst)
        cmd = {"run": d.run, "stop": d.stop, "single": d.single, "autoscale": d.autoscale}[a.action]()
        inst.write(cmd)
        emit({"ok": True, "action": a.action, "command": cmd}, as_json=True)
    finally:
        inst.close()


def cmd_capture(a) -> None:
    inst = connect(a)
    try:
        d, idn = _dialect_for(a, inst)
        channels = [int(x) for x in a.channels.split(",") if x.strip()]
        try:
            data = acquire_channels(inst, d, channels, a.points)
        except RuntimeError as e:
            die(str(e))
        summary = {"ok": True, "idn": idn, "family": d.name, "channels": {}}
        for ch, item in data.items():
            st = stats(item["volts"], item["times"])
            summary["channels"][str(ch)] = st
        if a.out:
            path = Path(a.out).expanduser()
            fmt = a.format or path.suffix.lstrip(".").lower() or "csv"
            if fmt == "csv":
                _write_csv(path, data)
            elif fmt == "json":
                path.write_text(json.dumps({str(k): {"times": v["times"], "volts": v["volts"]}
                                            for k, v in data.items()}, indent=2))
            elif fmt == "npz":
                try:
                    import numpy as np
                except ImportError:
                    die("npz output requires numpy; run scope.py setup")
                np.savez(path, **{f"ch{k}_t": v["times"] for k, v in data.items()},
                         **{f"ch{k}_v": v["volts"] for k, v in data.items()})
            else:
                die(f"unsupported output format: {fmt}")
            summary["out"] = str(path)
        if a.json:
            emit(summary, as_json=True)
        else:
            lines = [f"{idn}  [{d.name}]"]
            for ch, st in summary["channels"].items():
                lines.append(f"CH{ch}: {st.get('points')} pts  Vpp={st.get('vpp'):.4g}V "
                             f"mean={st.get('mean'):.4g}V" +
                             (f"  f={st['freq']:.4g}Hz" if "freq" in st else ""))
            if a.out:
                lines.append(f"saved: {a.out}")
            emit(summary, "\n".join(lines))
    finally:
        inst.close()


def _write_csv(path: Path, data: dict) -> None:
    chans = sorted(data)
    n = min(len(data[c]["volts"]) for c in chans)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time"] + [f"ch{c}" for c in chans])
        for i in range(n):
            w.writerow([f"{data[chans[0]]['times'][i]:.12g}"] +
                       [f"{data[c]['volts'][i]:.9g}" for c in chans])


def cmd_measure(a) -> None:
    inst = connect(a)
    try:
        d, idn = _dialect_for(a, inst)
        items = [x.strip().lower() for x in (a.items or "vpp,rms,freq,period").split(",")]
        bad = [x for x in items if x not in MEASURE_ITEMS]
        if bad:
            die(f"unknown measurement(s): {', '.join(bad)}; choose from {', '.join(MEASURE_ITEMS)}")
        values = measure_channel(inst, d, a.channel, items)
        emit({"ok": True, "idn": idn, "family": d.name, "channel": a.channel,
              "measurements": values}, as_json=True)
    finally:
        inst.close()


def cmd_shot(a) -> None:
    inst = connect(a)
    try:
        d, idn = _dialect_for(a, inst)
        used, data = d.screenshot(inst)
        if not data:
            die("screenshot failed: the instrument did not return PNG/JPEG data. "
                "Try the raw command in references/dialects.md")
        out = Path(a.out).expanduser()
        out.write_bytes(data)
        emit({"ok": True, "idn": idn, "family": d.name, "out": str(out),
              "bytes": len(data), "query": used}, as_json=True)
    finally:
        inst.close()


def cmd_scpi(a) -> None:
    inst = connect(a)
    try:
        if a.query:
            val = inst.query(a.command)
            emit({"ok": True, "command": a.command, "response": val}, as_json=True)
        else:
            inst.write(a.command)
            emit({"ok": True, "command": a.command, "response": None}, as_json=True)
    finally:
        inst.close()


# ------------------------------------------------------- monitor / analysis

MONITOR_PRESETS = {
    "glitch-short": {"timebase": 5e-6, "trigger_type": "pulse", "pulse_when": "LESSthan",
                     "pulse_width": 2e-6, "pulse_polarity": "POSitive",
                     "trigger_mode": "NORMAL", "max_events": 5, "auto_rearm": True},
    "power-on-spike": {"timebase": 1e-3, "trigger_type": "edge", "trigger_slope": "RISING",
                       "trigger_mode": "NORMAL", "max_events": 1, "auto_rearm": False},
    "intermittent-noise": {"timebase": 1e-3, "trigger_type": "edge", "trigger_mode": "NORMAL",
                           "max_events": 5, "auto_rearm": True},
    "missing-pulse": {"timebase": 1e-3, "trigger_type": "pulse", "pulse_when": "GREATERthan",
                      "pulse_width": 1e-3, "trigger_mode": "NORMAL",
                      "max_events": 3, "auto_rearm": True},
    "burst-pulse": {"timebase": 100e-6, "trigger_type": "pulse", "pulse_when": "LESSthan",
                    "pulse_width": 5e-6, "pulse_polarity": "POSitive",
                    "trigger_mode": "NORMAL", "max_events": 5, "auto_rearm": True},
}


def apply_preset(a) -> None:
    if not a.preset:
        return
    if a.preset not in MONITOR_PRESETS:
        die(f"unknown preset '{a.preset}'; choose from: {', '.join(sorted(MONITOR_PRESETS))}")
    for key, value in MONITOR_PRESETS[a.preset].items():
        if getattr(a, key, None) in (None, False) or (key == "max_events" and a.max_events == 1):
            setattr(a, key, value)


def monitor_setup(inst, d, a) -> list[str]:
    cmds = []
    ch = a.channels.split(",")[0].strip()
    try:
        chn = int(ch)
    except ValueError:
        chn = 1
    if a.channel_scale is not None:
        cmds.append(d.channel_scale(chn, a.channel_scale))
    if a.channel_offset is not None:
        cmds.append(d.channel_offset(chn, a.channel_offset))
    if a.timebase is not None:
        cmds.append(d.timebase_scale(a.timebase))
    if a.trigger_source is not None:
        cmds.append(d.trigger_source(a.trigger_source))
    if a.trigger_level is not None:
        cmds.append(d.trigger_level(a.trigger_level))
    if a.trigger_slope:
        cmds.append(d.trigger_slope(a.trigger_slope.upper()))
    if a.trigger_mode:
        cmds.append(d.trigger_sweep(a.trigger_mode.upper()))
    if (a.trigger_type or "edge") == "pulse":
        when_raw = (a.pulse_when or "less").lower()
        when = "GREATERthan" if "greater" in when_raw else "LESSthan"
        pulse = d.trigger_pulse(a.pulse_width or 1e-6,
                                (a.pulse_polarity or "positive").upper(),
                                when)
        if not pulse:
            print("[warn] pulse trigger is not mapped for this dialect; using edge",
                  file=sys.stderr)
        else:
            cmds.extend(pulse)
    for cmd in cmds:
        inst.write(cmd)
    return cmds


def query_run_state(inst, d) -> bool | None:
    """True = stopped (event captured), False = running, None = unknown."""
    for q in d.state_queries():
        try:
            val = inst.query(q).strip().upper()
        except Exception:
            continue
        if q.upper().startswith(":TRIG"):
            return val.startswith("STOP")
        return val in ("0", "STOP", "STOPPED", "OFF")
    return None


def cmd_monitor(a) -> None:
    apply_preset(a)
    inst = connect(a)
    try:
        d, idn = _dialect_for(a, inst)
        cmds = monitor_setup(inst, d, a)
        if a.dry_run:
            emit({"ok": True, "idn": idn, "family": d.name, "setup": cmds,
                  "arm": d.arm_single(), "dry_run": True}, as_json=True)
            return
        outdir = Path(a.outdir).expanduser()
        outdir.mkdir(parents=True, exist_ok=True)
        channels = [int(x) for x in a.channels.split(",") if x.strip()]
        deadline = time.time() + a.duration
        events = []
        for i in range(max(1, a.max_events)):
            if time.time() >= deadline:
                break
            for cmd in d.arm_single():
                inst.write(cmd)
            captured = False
            while time.time() < deadline:
                state = query_run_state(inst, d)
                if state is True:
                    captured = True
                    break
                if state is None:
                    time.sleep(a.settle)
                    captured = True
                    break
                time.sleep(a.interval)
            if not captured:
                break
            try:
                data = acquire_channels(inst, d, channels, a.points)
            except RuntimeError as e:
                die(str(e))
            stem = outdir / f"{a.prefix}-{i + 1:02d}"
            _write_csv(stem.with_suffix(".csv"), data)
            summary = {"idn": idn, "family": d.name, "event": i + 1, "channels": {}}
            for ch, item in data.items():
                summary["channels"][str(ch)] = stats(item["volts"], item["times"])
            stem.with_suffix(".json").write_text(json.dumps(summary, indent=2))
            events.append({"event": i + 1, "csv": str(stem.with_suffix(".csv")),
                           "json": str(stem.with_suffix(".json")),
                           "stats": summary["channels"]})
            if not a.auto_rearm:
                break
        emit({"ok": True, "idn": idn, "family": d.name, "events": events,
              "setup": cmds}, as_json=True)
    finally:
        inst.close()


def read_csv_capture(path: Path):
    with path.open(newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        raise ValueError("empty CSV")
    header = rows[0]
    tcol = 0
    vcol = 1 if len(header) > 1 else 0
    times, volts = [], []
    for row in rows[1:]:
        if len(row) <= max(tcol, vcol):
            continue
        times.append(float(row[tcol]))
        volts.append(float(row[vcol]))
    return header, times, volts


def cmd_analyze(a) -> None:
    path = Path(a.csv).expanduser()
    if not path.exists():
        die(f"file not found: {path}")
    header, times, volts = read_csv_capture(path)
    out = stats(volts, times)
    out["file"] = str(path)
    out["columns"] = header
    out["logic_levels"] = _logic_levels(volts)
    emit(out, as_json=True)


def _logic_levels(volts):
    if not volts:
        return None
    vmin, vmax = min(volts), max(volts)
    mid = (vmin + vmax) / 2
    high = [v for v in volts if v > mid]
    low = [v for v in volts if v <= mid]
    if not high or not low:
        return None
    return {"low": sum(low) / len(low), "high": sum(high) / len(high)}


# ---------------------------------------------------------------------- parser

def add_conn(p):
    p.add_argument("--host", help="LAN address (raw socket)")
    p.add_argument("--port", type=int, default=None, help="SCPI port (default 5025)")
    p.add_argument("--resource", help="VISA resource string (USB/VXI-11/serial)")
    p.add_argument("--backend", help="pyvisa backend (@py, auto, or a VISA library path)")
    p.add_argument("--family", choices=sorted(FAMILIES), help="override auto-detected dialect")
    p.add_argument("--timeout", type=float, default=None)
    p.add_argument("--json", action="store_true")


def main() -> None:
    ap = argparse.ArgumentParser(prog="scope.py", description="Generic oscilloscope control (LAN/USB)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("setup", help="create venv and install pyvisa/usb support")
    p.add_argument("--dev", action="store_true")
    p.set_defaults(fn=cmd_setup)

    p = sub.add_parser("doctor", help="environment and connection diagnostics")
    add_conn(p)
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("discover", help="list VISA resources or scan a subnet")
    p.add_argument("--scan", help="subnet, e.g. 192.168.1.0/24")
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_discover)

    p = sub.add_parser("idn", help="identify the instrument and dialect")
    add_conn(p)
    p.set_defaults(fn=cmd_idn)

    p = sub.add_parser("config", help="persistent defaults")
    p.add_argument("config_cmd", choices=["get", "set", "unset", "list"])
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.set_defaults(fn=cmd_config)

    p = sub.add_parser("channel", help="configure a channel")
    add_conn(p)
    p.add_argument("--ch", type=int, default=1)
    p.add_argument("--scale", type=float, help="volts/div")
    p.add_argument("--offset", type=float, help="volts")
    p.add_argument("--coupling", choices=["DC", "AC", "GND", "dc", "ac", "gnd"])
    p.add_argument("--probe", type=float)
    p.add_argument("--on", type=lambda x: x.lower() in ("1", "on", "true"), default=None)
    p.set_defaults(fn=cmd_channel)

    p = sub.add_parser("timebase", help="configure the timebase")
    add_conn(p)
    p.add_argument("--scale", type=float, help="seconds/div")
    p.add_argument("--offset", type=float, help="seconds")
    p.set_defaults(fn=cmd_timebase)

    p = sub.add_parser("trigger", help="configure an edge trigger")
    add_conn(p)
    p.add_argument("--source", type=int)
    p.add_argument("--level", type=float)
    p.add_argument("--slope", choices=["rising", "falling", "either", "RISING", "FALLING", "EITHER"])
    p.add_argument("--mode", choices=["auto", "normal", "single", "AUTO", "NORMAL", "SINGLE"])
    p.set_defaults(fn=cmd_trigger)

    p = sub.add_parser("run", help="run / stop / single / autoscale")
    add_conn(p)
    p.add_argument("action", choices=["run", "stop", "single", "autoscale"])
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("capture", help="acquire waveform data")
    add_conn(p)
    p.add_argument("--channels", default="1", help="comma separated, e.g. 1,2")
    p.add_argument("--points", type=int, help="requested sample count")
    p.add_argument("--out", help="output file (csv/json/npz)")
    p.add_argument("--format", choices=["csv", "json", "npz"])
    p.set_defaults(fn=cmd_capture)

    p = sub.add_parser("measure", help="automatic measurements")
    add_conn(p)
    p.add_argument("--channel", type=int, default=1)
    p.add_argument("--items", default="vpp,rms,freq,period")
    p.set_defaults(fn=cmd_measure)

    p = sub.add_parser("shot", help="save a screenshot")
    add_conn(p)
    p.add_argument("--out", default="scope.png")
    p.set_defaults(fn=cmd_shot)

    p = sub.add_parser("scpi", help="raw SCPI write or query")
    add_conn(p)
    p.add_argument("command")
    p.add_argument("--query", action="store_true")
    p.set_defaults(fn=cmd_scpi)

    p = sub.add_parser("monitor", help="arm, wait for an event, capture evidence")
    add_conn(p)
    p.add_argument("--mode", choices=["trigger", "query"], default="trigger")
    p.add_argument("--channels", default="1")
    p.add_argument("--max-events", type=int, default=1)
    p.add_argument("--duration", type=float, default=30.0)
    p.add_argument("--interval", type=float, default=0.2)
    p.add_argument("--settle", type=float, default=1.0)
    p.add_argument("--outdir", default="captures")
    p.add_argument("--prefix", default="scope")
    p.add_argument("--auto-rearm", action="store_true")
    p.add_argument("--points", type=int)
    p.add_argument("--preset", choices=sorted(MONITOR_PRESETS))
    p.add_argument("--channel-scale", type=float)
    p.add_argument("--channel-offset", type=float)
    p.add_argument("--timebase", type=float)
    p.add_argument("--trigger-source", type=int)
    p.add_argument("--trigger-level", type=float)
    p.add_argument("--trigger-slope", choices=["rising", "falling", "either"])
    p.add_argument("--trigger-mode", choices=["auto", "normal", "single"])
    p.add_argument("--trigger-type", choices=["edge", "pulse"], default=None)
    p.add_argument("--pulse-width", type=float)
    p.add_argument("--pulse-polarity", choices=["positive", "negative"])
    p.add_argument("--pulse-when", choices=["less", "greater", "less-equal", "greater-equal"],
                   help="pulse width comparison")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_monitor)

    p = sub.add_parser("analyze", help="analyze a captured CSV offline")
    p.add_argument("--csv", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_analyze)

    p = sub.add_parser("list", help="list VISA resources")
    p.add_argument("--backend")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_discover, scan=None, port=None)

    p = sub.add_parser("query", help="send one SCPI query (alias)")
    add_conn(p)
    p.add_argument("command")
    p.set_defaults(fn=cmd_scpi, query=True)

    p = sub.add_parser("write", help="send one SCPI write (alias)")
    add_conn(p)
    p.add_argument("command")
    p.set_defaults(fn=cmd_scpi, query=False)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        if os.environ.get("SCOPE_DEBUG"):
            raise
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False),
              file=sys.stderr)
        sys.exit(1)
