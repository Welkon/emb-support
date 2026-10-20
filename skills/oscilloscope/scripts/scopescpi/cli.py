"""Command implementations and argument parser."""

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
    CONFIG, HOME, IS_WIN, VENV, die, emit, load_config, save_config,
)
from .transport import SocketInstrument, UsbtmcInstrument, VisaInstrument, connect
from .dialects import FAMILIES, detect_family, make_dialect
from .acquisition import (
    ITEM_MAP, MEASURE_ITEMS, acquire_channels, acquire_with_recovery,
    measure_channel, stats,
)
from .quality import check as check_quality
from .analysis import advanced, classify, load_npz, save_npz, spectrum, write_svg
from .wsl import (
    attach_hint, attach_scope_devices, is_wsl, list_devices, windows_host_ip,
)

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
    pkgs = ["pyvisa", "pyvisa-py", "pyusb", "libusb-package", "numpy"]
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
    if is_wsl():
        devices, err = list_devices()
        scope_devices = [d for d in devices if d["vendor"]]
        wsl = {"host_ip": windows_host_ip(), "usbipd_error": err,
               "devices": scope_devices,
               "hints": [h for d in scope_devices for h in attach_hint(d)]}
        if not scope_devices:
            wsl["hints"].append("no oscilloscope VID seen by usbipd; plug the scope into Windows and rerun")
        if getattr(a, "attach_usb", False):
            wsl["attach"] = attach_scope_devices()
        info["wsl"] = wsl
        info["hints"].append("WSL detected: USB instruments must be attached with usbipd before they appear here")
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
            hint = "; use --scan 192.168.1.0/24"
            if is_wsl():
                hint += "; on WSL run `doctor --attach-usb` for USB instruments"
            emit({"ok": False, "error": f"pyvisa unavailable: {e}{hint}"}, as_json=True)
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
        if a.action == "run":
            commands = d.run_commands()
        else:
            commands = [{"stop": d.stop, "single": d.single, "autoscale": d.autoscale}[a.action]()]
        for cmd in commands:
            inst.write(cmd)
        emit({"ok": True, "action": a.action, "commands": commands}, as_json=True)
    finally:
        inst.close()


def cmd_capture(a) -> None:
    inst = connect(a)
    try:
        d, idn = _dialect_for(a, inst)
        channels = [int(x) for x in a.channels.split(",") if x.strip()]
        recovery = []
        try:
            if a.single is not None:
                for cmd in d.arm_single():
                    inst.write(cmd)
                deadline = time.time() + a.single
                while time.time() < deadline:
                    if query_run_state(inst, d) is True:
                        break
                    time.sleep(0.02)
            if a.no_recovery:
                data = acquire_channels(inst, d, channels, a.points)
            else:
                data, recovery = acquire_with_recovery(
                    inst, d, channels, a.points,
                    attempts=3, allow_autoset=a.autoset_on_empty)
        except Exception as e:  # noqa: BLE001
            die(f"capture failed after retries: {e}")
        summary = {"ok": True, "idn": idn, "family": d.name, "channels": {},
                   "recovery": recovery}
        for ch, item in data.items():
            st = stats(item["volts"], item["times"])
            if not a.no_quality:
                st["quality"] = check_quality(item["volts"], item["times"], item["meta"])
            if not a.no_analyze:
                adv = advanced(item["volts"], item["times"], item["meta"])
                adv["waveform"] = classify(item["volts"], item["times"], st, adv)
                st["analysis"] = adv
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
        if a.cache:
            if a.cache is True:
                cache_path = (Path(a.out).with_suffix(".npz") if a.out
                              else HOME / "cache" / f"capture-{int(time.time())}.npz")
            else:
                cache_path = Path(a.cache).expanduser()
            save_npz(cache_path, data)
            summary["cache"] = str(cache_path)
        if a.plot:
            plot_path = Path(a.plot).expanduser()
            if plot_path.suffix.lower() != ".svg":
                die("--plot currently supports .svg output")
            first = next(iter(data.values()))
            extra = advanced(first["volts"], first["times"], first["meta"])
            write_svg(plot_path, first["times"], first["volts"],
                      title=f"{idn} CH{list(data)[0]}", extra=extra,
                      max_points=a.plot_points)
            summary["plot"] = str(plot_path)
        if a.json:
            emit(summary, as_json=True)
        else:
            lines = [f"{idn}  [{d.name}]"]
            for ch, st in summary["channels"].items():
                lines.append(f"CH{ch}: {st.get('points')} pts  Vpp={st.get('vpp'):.4g}V "
                             f"mean={st.get('mean'):.4g}V" +
                             (f"  f={st['freq']:.4g}Hz" if "freq" in st else "") +
                             (f"  [{st['analysis']['waveform']['type']}]"
                              if st.get("analysis", {}).get("waveform") else ""))
                for w in st.get("quality", []):
                    lines.append(f"  [{w['severity']}] {w['code']}: {w['message']} -> {w['suggestion']}")
            for step in recovery:
                lines.append(f"  recovery: attempt {step['attempt']} -> {step['recovery']}")
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
        if not d.screenshot_queries():
            data, _ = acquire_with_recovery(inst, d, [1], None, attempts=2)
            item = data[1]
            extra = advanced(item["volts"], item["times"], item["meta"])
            out = Path(a.out).expanduser().with_suffix(".svg")
            write_svg(out, item["times"], item["volts"],
                      title=f"{idn} CH1 (scope has no screen dump)", extra=extra)
            emit({"ok": True, "fallback": "waveform-plot", "out": str(out),
                  "idn": idn, "family": d.name,
                  "note": "the instrument cannot export a screenshot; rendered a waveform plot instead"})
            return
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
                data, rec = acquire_with_recovery(inst, d, channels, a.points, attempts=2)
            except Exception as e:  # noqa: BLE001
                die(f"monitor capture failed: {e}")
            stem = outdir / f"{a.prefix}-{i + 1:02d}"
            _write_csv(stem.with_suffix(".csv"), data)
            summary = {"idn": idn, "family": d.name, "event": i + 1,
                       "recovery": rec, "channels": {}}
            for ch, item in data.items():
                st = stats(item["volts"], item["times"])
                if not a.no_quality:
                    st["quality"] = check_quality(item["volts"], item["times"], item["meta"])
                summary["channels"][str(ch)] = st
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
    if not a.csv and not a.npz:
        die("analyze requires --csv or --npz")
    if a.npz:
        path = Path(a.npz).expanduser()
        if not path.exists():
            die(f"file not found: {path}")
        data = load_npz(path)
        if not data:
            die("no channels found in npz")
        ch = next(iter(data))
        times, volts = data[ch]["times"], data[ch]["volts"]
        header = ["time", f"ch{ch}"]
    else:
        path = Path(a.csv).expanduser()
        if not path.exists():
            die(f"file not found: {path}")
        header, times, volts = read_csv_capture(path)
    out = stats(volts, times)
    out["warnings"] = check_quality(volts, times)
    out["file"] = str(path)
    out["columns"] = header
    out["logic_levels"] = _logic_levels(volts)
    if a.fft:
        out.update(spectrum(volts, (times[1] - times[0]) if len(times) > 1 else 0))
    if a.plot:
        plot_path = Path(a.plot).expanduser()
        if plot_path.suffix.lower() != ".svg":
            die("--plot currently supports .svg output")
        write_svg(plot_path, times, volts, title=path.name,
                  extra=out, max_points=a.plot_points)
        out["plot"] = str(plot_path)
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
    p.add_argument("--no-auto-attach", action="store_true",
                   help="WSL: do not attach scope USB devices automatically")
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
    p.add_argument("--attach-usb", action="store_true",
                   help="WSL only: attach oscilloscope USB devices via usbipd")
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
    p.add_argument("--no-recovery", action="store_true", help="fail immediately instead of retrying")
    p.add_argument("--autoset-on-empty", action="store_true",
                   help="allow autoset as the last recovery step (changes instrument state)")
    p.add_argument("--no-quality", action="store_true", help="skip signal-quality warnings")
    p.add_argument("--plot", help="write an SVG waveform plot")
    p.add_argument("--plot-points", type=int, default=4000)
    p.add_argument("--cache", nargs="?", const=True, help="write/refresh an NPZ cache")
    p.add_argument("--single", nargs="?", const=5.0, type=float,
                   help="arm a single sequence and wait up to N seconds before reading")
    p.add_argument("--no-analyze", action="store_true",
                   help="skip FFT/harmonics/waveform classification")
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
    p.add_argument("--no-quality", action="store_true")
    p.set_defaults(fn=cmd_monitor)

    p = sub.add_parser("analyze", help="analyze a captured CSV/NPZ offline")
    p.add_argument("--csv")
    p.add_argument("--npz")
    p.add_argument("--fft", action="store_true", help="include FFT, harmonics and THD")
    p.add_argument("--plot", help="write an SVG waveform plot")
    p.add_argument("--plot-points", type=int, default=4000)
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
