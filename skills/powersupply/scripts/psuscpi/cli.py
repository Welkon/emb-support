"""Power-supply CLI commands and argument parser."""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from .common import (
    CONFIG, DEFAULT_MAX_CURRENT, DEFAULT_MAX_VOLTAGE, HOME, VENV,
    die, emit, fnum, load_config, save_config,
)
from .dialects import FAMILIES, detect_family, make_dialect
from .transport import (
    SerialInstrument, SocketInstrument, UsbtmcInstrument, VisaInstrument, connect,
)


def _dialect(inst, a):
    idn = inst.query("*IDN?")
    family = getattr(a, "family", None) or load_config().get("family")
    try:
        return make_dialect(idn, family), idn
    except ValueError as e:
        die(str(e))


def _select(inst, d, n: int) -> None:
    cmd = d.select(n)
    if cmd:
        inst.write(cmd)


def _limits(a):
    cfg = load_config()
    mv = getattr(a, "max_voltage", None) or cfg.get("max_voltage") or DEFAULT_MAX_VOLTAGE
    mi = getattr(a, "max_current", None) or cfg.get("max_current") or DEFAULT_MAX_CURRENT
    return float(mv), float(mi)


def _check_limits(a, voltage, current):
    mv, mi = _limits(a)
    if voltage is not None and voltage > mv:
        die(f"voltage {voltage} V exceeds the safety limit {mv} V "
            f"(raise with --max-voltage or config set max_voltage)")
    if current is not None and current > mi:
        die(f"current {current} A exceeds the safety limit {mi} A "
            f"(raise with --max-current or config set max_current)")


def _q_float(inst, cmd):
    try:
        text = inst.query(cmd).strip()
        return float(text) if text else None
    except Exception:
        return None


def cmd_setup(a) -> None:
    py = os.environ.get("PSU_PYTHON") or sys.executable
    if not VENV.exists():
        VENV.parent.mkdir(parents=True, exist_ok=True)
        p = subprocess.run([py, "-m", "venv", str(VENV)], capture_output=True, text=True)
        if p.returncode != 0:
            die(f"failed to create venv: {p.stderr[-800:]}")
    pip = VENV / ("Scripts/pip.exe" if os.name == "nt" else "bin/pip")
    pkgs = ["pyvisa", "pyvisa-py", "pyusb", "pyserial"]
    if getattr(a, "dev", False):
        pkgs.append("pytest")
    p = subprocess.run([str(pip), "install", "-U", "pip"] + pkgs,
                       capture_output=True, text=True, timeout=900)
    if p.returncode != 0:
        die(f"pip install failed: {(p.stderr or p.stdout)[-1200:]}")
    emit({"ok": True, "venv": str(VENV), "packages": pkgs}, as_json=True)


def cmd_doctor(a) -> None:
    info = {"ok": True, "python": sys.executable, "pyvisa": None,
            "resources": [], "usbtmc": sorted(glob.glob("/dev/usbtmc*")),
            "serial": sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")),
            "hints": []}
    try:
        import pyvisa
        info["pyvisa"] = getattr(pyvisa, "__version__", "?")
        backend = getattr(a, "backend", None) or load_config().get("backend")
        if backend is None and os.name != "nt":
            backend = "@py"
        rm = pyvisa.ResourceManager(backend) if backend else pyvisa.ResourceManager()
        info["resources"] = list(rm.list_resources())
    except Exception as e:
        info["hints"].append(f"pyvisa not available ({e}); run psu.py setup for USB/VISA")
    host = getattr(a, "host", None) or load_config().get("host")
    if host:
        port = int(getattr(a, "port", None) or load_config().get("port") or 5025)
        try:
            with socket.create_connection((host, port), 1.5):
                info["socket_test"] = f"{host}:{port} reachable"
        except OSError as e:
            info["socket_test"] = f"{host}:{port} failed: {e}"
            info["hints"].append("check LAN address, firewall, and SCPI/LAN enable")
    if Path("/proc/version").exists() and "microsoft" in Path("/proc/version").read_text().lower():
        info["hints"].append("WSL: attach USB instruments with usbipd before use")
    if not info["resources"] and not info["usbtmc"] and not info["serial"]:
        info["hints"].append("no instrument found: check cable, driver/udev, and SCPI mode")
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
                    return {"host": host, "idn": s.recv(256).decode(errors="replace").strip()}
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
        family = getattr(a, "family", None) or detect_family(idn)
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
        if a.key in ("port", "baud"):
            val = int(a.value)
        elif a.key in ("timeout", "max_voltage", "max_current"):
            val = float(a.value)
        elif a.key == "safe_off":
            val = a.value.lower() in ("1", "true", "yes", "on")
        else:
            val = a.value
        cfg[a.key] = val
        save_config(cfg)
        emit({"ok": True, "set": {a.key: val}}, as_json=True)
    else:
        cfg.pop(a.key, None)
        save_config(cfg)
        emit({"ok": True, "removed": a.key}, as_json=True)


def cmd_channels(a) -> None:
    inst = connect(a)
    try:
        d, idn = _dialect(inst, a)
        emit({"ok": True, "idn": idn, "family": d.name,
              "channels": list(d.channels),
              "capabilities": {
                  "output_state": d.output_state(1) is not None,
                  "ovp": d.ovp(1, 1) is not None,
                  "ocp": d.ocp(1, 1) is not None,
                  "power": d.measure_power(1) is not None,
              }}, as_json=True)
    finally:
        inst.close()


def _validate_channel(d, n):
    if n not in d.channels:
        die(f"channel {n} not available; this model has {list(d.channels)}")


def cmd_set(a) -> None:
    inst = connect(a)
    voltage = getattr(a, "voltage", None)
    current = getattr(a, "current", None)
    if voltage is None and current is None:
        die("set requires --voltage and/or --current")
    _check_limits(a, voltage, current)
    try:
        d, idn = _dialect(inst, a)
        _validate_channel(d, a.ch)
        _select(inst, d, a.ch)
        if voltage is not None:
            inst.write(d.set_voltage(a.ch, voltage))
        if current is not None:
            inst.write(d.set_current(a.ch, current))
        out = {"ok": True, "idn": idn, "family": d.name, "channel": a.ch,
               "voltage": voltage, "current": current}
        if a.verify:
            got_v = _q_float(inst, d.get_voltage(a.ch))
            got_i = _q_float(inst, d.get_current(a.ch))
            out["readback"] = {"voltage": got_v, "current": got_i}
            if voltage is not None and got_v is not None and abs(got_v - voltage) > 0.02 * max(1, abs(voltage)) + 0.01:
                out["warning"] = f"voltage readback {got_v} differs from setpoint {voltage}"
        emit(out, as_json=True)
    finally:
        inst.close()


def cmd_get(a) -> None:
    inst = connect(a)
    try:
        d, idn = _dialect(inst, a)
        _validate_channel(d, a.ch)
        _select(inst, d, a.ch)
        emit({"ok": True, "idn": idn, "family": d.name, "channel": a.ch,
              "voltage": _q_float(inst, d.get_voltage(a.ch)),
              "current": _q_float(inst, d.get_current(a.ch))}, as_json=True)
    finally:
        inst.close()


def cmd_measure(a) -> None:
    inst = connect(a)
    try:
        d, idn = _dialect(inst, a)
        _validate_channel(d, a.ch)
        _select(inst, d, a.ch)
        items = [x.strip().lower() for x in (a.items or "voltage,current,power").split(",")]
        values = {}
        if "voltage" in items:
            values["voltage"] = _q_float(inst, d.measure_voltage(a.ch))
        if "current" in items:
            values["current"] = _q_float(inst, d.measure_current(a.ch))
        if "power" in items:
            q = d.measure_power(a.ch)
            p = _q_float(inst, q) if q else None
            if p is None and values.get("voltage") is not None and values.get("current") is not None:
                p = values["voltage"] * values["current"]
            values["power"] = p
        emit({"ok": True, "idn": idn, "family": d.name, "channel": a.ch,
              "measurements": values}, as_json=True)
    finally:
        inst.close()


def cmd_output(a) -> None:
    if a.state == "on" and not a.yes:
        die("turning the output ON requires --yes (safety interlock)")
    inst = connect(a)
    try:
        d, idn = _dialect(inst, a)
        _validate_channel(d, a.ch)
        _select(inst, d, a.ch)
        inst.write(d.output(a.ch, a.state == "on"))
        out = {"ok": True, "idn": idn, "family": d.name, "channel": a.ch, "state": a.state}
        q = d.output_state(a.ch)
        if q:
            out["readback"] = inst.query(q)
        emit(out, as_json=True)
    finally:
        inst.close()


def cmd_all_off(a) -> None:
    inst = connect(a)
    try:
        d, idn = _dialect(inst, a)
        done = []
        for ch in d.channels:
            try:
                _select(inst, d, ch)
                inst.write(d.output(ch, False))
                done.append(ch)
            except Exception:
                pass
        emit({"ok": True, "idn": idn, "family": d.name, "outputs_off": done}, as_json=True)
    finally:
        inst.close()


def cmd_protect(a) -> None:
    inst = connect(a)
    try:
        d, idn = _dialect(inst, a)
        _validate_channel(d, a.ch)
        _select(inst, d, a.ch)
        cmds = []
        if a.ovp is not None:
            c = d.ovp(a.ch, a.ovp)
            if not c:
                die("OVP is not supported by this dialect")
            cmds.append(c)
        if a.ocp is not None:
            c = d.ocp(a.ch, a.ocp)
            if not c:
                die("OCP is not supported by this dialect")
            cmds.append(c)
        if not cmds:
            die("protect requires --ovp and/or --ocp")
        for c in cmds:
            inst.write(c)
        emit({"ok": True, "idn": idn, "family": d.name, "channel": a.ch,
              "commands": cmds}, as_json=True)
    finally:
        inst.close()


def cmd_ramp(a) -> None:
    if not a.yes:
        die("ramp changes the output while it may be enabled; pass --yes")
    _check_limits(a, a.to, None)
    inst = connect(a)
    safe = load_config().get("safe_off", True)
    try:
        d, idn = _dialect(inst, a)
        _validate_channel(d, a.ch)
        _select(inst, d, a.ch)
        start = a.start if a.start is not None else _q_float(inst, d.get_voltage(a.ch))
        if start is None:
            die("cannot read the current voltage; pass --start")
        step = abs(a.step) or 0.1
        direction = 1 if a.to >= start else -1
        v = start
        trail = []
        try:
            while (direction > 0 and v < a.to) or (direction < 0 and v > a.to):
                v = min(a.to, v + step) if direction > 0 else max(a.to, v - step)
                _check_limits(a, v, None)
                inst.write(d.set_voltage(a.ch, round(v, 4)))
                trail.append(round(v, 4))
                time.sleep(max(0.0, a.delay))
        except BaseException:
            if safe:
                try:
                    _select(inst, d, a.ch)
                    inst.write(d.output(a.ch, False))
                except Exception:
                    pass
            raise
        emit({"ok": True, "idn": idn, "channel": a.ch, "from": start, "to": a.to,
              "steps": len(trail), "safe_off": safe}, as_json=True)
    finally:
        inst.close()


def cmd_sequence(a) -> None:
    if not a.yes:
        die("sequence changes the output; pass --yes")
    path = Path(a.file).expanduser()
    if not path.exists():
        die(f"file not found: {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        die(f"invalid JSON: {e}")
    steps = data.get("steps", data) if isinstance(data, dict) else data
    if not isinstance(steps, list):
        die("sequence must be a list, or an object with a 'steps' list")
    inst = connect(a)
    safe = load_config().get("safe_off", True)
    try:
        d, idn = _dialect(inst, a)
        _validate_channel(d, a.ch)
        _select(inst, d, a.ch)
        applied = []
        for i, step in enumerate(steps):
            v, cur = step.get("voltage"), step.get("current")
            _check_limits(a, v, cur)
            if v is not None:
                inst.write(d.set_voltage(a.ch, v))
            if cur is not None:
                inst.write(d.set_current(a.ch, cur))
            applied.append({"step": i + 1, "voltage": v, "current": cur})
            time.sleep(max(0.0, float(step.get("delay", 0))))
        emit({"ok": True, "idn": idn, "channel": a.ch, "steps": applied,
              "safe_off": safe}, as_json=True)
    except BaseException:
        if safe:
            try:
                _select(inst, d, a.ch)
                inst.write(d.output(a.ch, False))
            except Exception:
                pass
        raise
    finally:
        inst.close()


def cmd_log(a) -> None:
    inst = connect(a)
    out_path = Path(a.out).expanduser()
    rows = []
    try:
        d, idn = _dialect(inst, a)
        _validate_channel(d, a.ch)
        _select(inst, d, a.ch)
        end = time.time() + a.duration
        while time.time() < end:
            v = _q_float(inst, d.measure_voltage(a.ch))
            i = _q_float(inst, d.measure_current(a.ch))
            p = v * i if (v is not None and i is not None) else None
            rows.append([time.time(), v, i, p])
            time.sleep(max(0.0, a.interval))
    finally:
        inst.close()
    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "voltage", "current", "power"])
        w.writerows(rows)
    emit({"ok": True, "samples": len(rows), "out": str(out_path),
          "duration": a.duration, "interval": a.interval}, as_json=True)


def cmd_scpi(a) -> None:
    inst = connect(a)
    try:
        if a.query:
            emit({"ok": True, "command": a.command, "response": inst.query(a.command)},
                 as_json=True)
        else:
            inst.write(a.command)
            emit({"ok": True, "command": a.command, "response": None}, as_json=True)
    finally:
        inst.close()


def add_conn(p):
    p.add_argument("--host", help="LAN address (raw socket)")
    p.add_argument("--port", type=int, default=None, help="SCPI port (default 5025)")
    p.add_argument("--resource", help="VISA resource string")
    p.add_argument("--serial", help="serial port for Korad-style supplies")
    p.add_argument("--baud", type=int, default=None)
    p.add_argument("--backend", help="pyvisa backend")
    p.add_argument("--family", choices=sorted(FAMILIES))
    p.add_argument("--timeout", type=float, default=None)
    p.add_argument("--max-voltage", type=float, default=None)
    p.add_argument("--max-current", type=float, default=None)
    p.add_argument("--json", action="store_true")


def main() -> None:
    ap = argparse.ArgumentParser(prog="psu.py", description="Generic programmable power supply CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("setup", help="create venv and install pyvisa/pyserial")
    p.add_argument("--dev", action="store_true")
    p.set_defaults(fn=cmd_setup)

    p = sub.add_parser("doctor", help="environment and connection diagnostics")
    add_conn(p)
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("discover", help="list VISA resources or scan a subnet")
    p.add_argument("--scan")
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--backend")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_discover)

    p = sub.add_parser("idn", help="identify the supply and dialect")
    add_conn(p)
    p.set_defaults(fn=cmd_idn)

    p = sub.add_parser("config", help="persistent defaults and safety limits")
    p.add_argument("config_cmd", choices=["get", "set", "unset", "list"])
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.set_defaults(fn=cmd_config)

    p = sub.add_parser("channels", help="list channels and capabilities")
    add_conn(p)
    p.set_defaults(fn=cmd_channels)

    p = sub.add_parser("set", help="set voltage/current setpoints")
    add_conn(p)
    p.add_argument("--ch", type=int, default=1)
    p.add_argument("--voltage", type=float)
    p.add_argument("--current", type=float)
    p.add_argument("--verify", action="store_true", help="read setpoints back")
    p.set_defaults(fn=cmd_set)

    p = sub.add_parser("get", help="read voltage/current setpoints")
    add_conn(p)
    p.add_argument("--ch", type=int, default=1)
    p.set_defaults(fn=cmd_get)

    p = sub.add_parser("measure", help="measure voltage/current/power")
    add_conn(p)
    p.add_argument("--ch", type=int, default=1)
    p.add_argument("--items", default="voltage,current,power")
    p.set_defaults(fn=cmd_measure)

    p = sub.add_parser("output", help="turn a channel output on/off")
    add_conn(p)
    p.add_argument("--ch", type=int, default=1)
    p.add_argument("state", choices=["on", "off"])
    p.add_argument("--yes", action="store_true", help="required to turn ON")
    p.set_defaults(fn=cmd_output)

    p = sub.add_parser("all-off", help="turn every channel output off")
    add_conn(p)
    p.set_defaults(fn=cmd_all_off)

    p = sub.add_parser("protect", help="set OVP/OCP")
    add_conn(p)
    p.add_argument("--ch", type=int, default=1)
    p.add_argument("--ovp", type=float)
    p.add_argument("--ocp", type=float)
    p.set_defaults(fn=cmd_protect)

    p = sub.add_parser("ramp", help="software voltage ramp")
    add_conn(p)
    p.add_argument("--ch", type=int, default=1)
    p.add_argument("--to", type=float, required=True)
    p.add_argument("--start", type=float)
    p.add_argument("--step", type=float, default=0.1)
    p.add_argument("--delay", type=float, default=0.2)
    p.add_argument("--yes", action="store_true")
    p.set_defaults(fn=cmd_ramp)

    p = sub.add_parser("sequence", help="apply a JSON sequence of setpoints")
    add_conn(p)
    p.add_argument("file")
    p.add_argument("--ch", type=int, default=1)
    p.add_argument("--yes", action="store_true")
    p.set_defaults(fn=cmd_sequence)

    p = sub.add_parser("log", help="log measured V/I/P to CSV")
    add_conn(p)
    p.add_argument("--ch", type=int, default=1)
    p.add_argument("--duration", type=float, default=10.0)
    p.add_argument("--interval", type=float, default=0.5)
    p.add_argument("--out", default="psu-log.csv")
    p.set_defaults(fn=cmd_log)

    p = sub.add_parser("scpi", help="raw SCPI write or query")
    add_conn(p)
    p.add_argument("command")
    p.add_argument("--query", action="store_true")
    p.set_defaults(fn=cmd_scpi)

    p = sub.add_parser("query", help="raw SCPI query (alias)")
    add_conn(p)
    p.add_argument("command")
    p.set_defaults(fn=cmd_scpi, query=True)

    p = sub.add_parser("write", help="raw SCPI write (alias)")
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
        if os.environ.get("PSU_DEBUG"):
            raise
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                         ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
