"""Command implementations and argument parser."""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import socket
import statistics
import subprocess
import sys
import time
from pathlib import Path

from .common import (
    CONFIG, HOME, IS_WIN, VENV, die, emit, load_config, save_config,
    venv_reexec_argv,
)
from .transport import SocketInstrument, UsbtmcInstrument, VisaInstrument
from .session import Session
from .capabilities import advertised
from .dialects import FAMILIES, detect_family, make_dialect
from .acquisition import MEASURE_ITEMS, measure_channel, stats
from .quality import check as check_quality
from .analysis import advanced, classify, load_npz, spectrum
from .evidence import Evidence
from .plan import ChannelSetup, Executor, Plan, TriggerSetup, query_run_state
from .result import Result
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


def cmd_test(a) -> None:
    """Run the skill test suite with the skill venv (or the active interpreter)."""
    skill = Path(__file__).resolve().parents[2]
    py = VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")
    if not py.exists():
        py = Path(sys.executable)
    has_pytest = subprocess.run([str(py), "-c", "import pytest"],
                                capture_output=True).returncode == 0
    if not has_pytest:
        if not getattr(a, "install", False):
            die(f"pytest is not installed for {py}. Run: scope.py test --install")
        p = subprocess.run([str(py), "-m", "pip", "install", "-U", "pytest"],
                           capture_output=True, text=True, timeout=600)
        if p.returncode != 0:
            die(f"pytest install failed: {(p.stderr or p.stdout)[-1200:]}")
    cmd = [str(py), "-m", "pytest", "tests", "-q"]
    if getattr(a, "k", None):
        cmd += ["-k", a.k]
    sys.exit(subprocess.call(cmd, cwd=str(skill)))


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
        info["hints"].append(
            "if the instrument is visible to Windows only, run the same command with "
            "`--bridge windows` (add `--win-python <path>` for a Windows venv that has pyvisa)")
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
    inst = Session(a)
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
    inst = Session(a)
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
        applied = {"scale": a.scale, "offset": a.offset, "coupling": a.coupling,
                   "probe": a.probe, "on": a.on}
        result = Result(idn=idn, family=d.name)
        result.set("channel", a.ch)
        result.set("applied", {k: v for k, v in applied.items() if v is not None})
        emit(result.to_dict(), as_json=True)
    finally:
        inst.close()


def cmd_timebase(a) -> None:
    inst = Session(a)
    try:
        d, idn = _dialect_for(a, inst)
        cmds = []
        if a.scale is not None:
            cmds.append(d.timebase_scale(a.scale))
        if a.offset is not None:
            cmds.append(d.timebase_offset(a.offset))
        for c in cmds:
            inst.write(c)
        applied = {"scale": a.scale, "offset": a.offset}
        result = Result(idn=idn, family=d.name)
        result.set("applied", {k: v for k, v in applied.items() if v is not None})
        emit(result.to_dict(), as_json=True)
    finally:
        inst.close()


def cmd_trigger(a) -> None:
    inst = Session(a)
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
        applied = {"source": a.source, "level": a.level, "slope": a.slope,
                   "mode": a.mode}
        result = Result(idn=idn, family=d.name)
        result.set("applied", {k: v for k, v in applied.items() if v is not None})
        emit(result.to_dict(), as_json=True)
    finally:
        inst.close()


def cmd_run(a) -> None:
    inst = Session(a)
    try:
        d, _ = _dialect_for(a, inst)
        if a.action == "run":
            commands = d.run_commands()
        else:
            commands = [{"stop": d.stop, "single": d.single, "autoscale": d.autoscale}[a.action]()]
        for cmd in commands:
            inst.write(cmd)
        emit(Result(values={"action": a.action}).to_dict(), as_json=True)
    finally:
        inst.close()


def cmd_capture(a) -> None:
    channels = [int(x) for x in a.channels.split(",") if x.strip()]
    inst = Session(a)
    try:
        d, idn = _dialect_for(a, inst)
        executor = Executor(inst, d)
        if a.single is not None:
            executor.arm_wait(Plan(mode="single", wait=a.single, poll=0.02))
        plan = Plan(read=channels, points=a.points,
                    no_recovery=a.no_recovery, autoset=a.autoset_on_empty)
        try:
            data, recovery = executor.acquire(plan)
        except Exception as e:  # noqa: BLE001
            die(f"capture failed after retries: {e}")
        result = Result(idn=idn, family=d.name)
        result.set("channels", _channel_summaries(data, a.no_quality, a.no_analyze))
        result.set("recovery", recovery)
        evidence = Evidence()
        if a.out:
            path = Path(a.out).expanduser()
            fmt = a.format or path.suffix.lstrip(".").lower() or "csv"
            if fmt == "csv":
                evidence.csv("csv", path, data)
            elif fmt == "json":
                evidence.json("json", path, {
                    str(k): {"times": v["times"], "volts": v["volts"]}
                    for k, v in data.items()})
            elif fmt == "npz":
                evidence.npz("npz", path, data)
            else:
                die(f"unsupported output format: {fmt}")
        if a.cache:
            if a.cache is True:
                cache_path = (Path(a.out).with_suffix(".npz") if a.out
                              else HOME / "cache" / f"capture-{int(time.time())}.npz")
            else:
                cache_path = Path(a.cache).expanduser()
            evidence.npz("cache", cache_path, data)
        if a.plot:
            first = next(iter(data.values()))
            extra = advanced(first["volts"], first["times"], first["meta"])
            evidence.svg("plot", a.plot, first["times"], first["volts"],
                         title=f"{idn} CH{list(data)[0]}", extra=extra,
                         max_points=a.plot_points)
        for kind, path in evidence.manifest().items():
            result.add_evidence(kind, path)
        payload = result.to_dict()
        if a.json:
            emit(payload, as_json=True)
        else:
            lines = [f"{idn}  [{d.name}]"]
            for ch, st in payload["channels"].items():
                lines.append(f"CH{ch}: {st.get('points')} pts  Vpp={st.get('vpp'):.4g}V "
                             f"mean={st.get('mean'):.4g}V" +
                             (f"  f={st['freq']:.4g}Hz" if "freq" in st else "") +
                             (f"  [{st['analysis']['waveform']['type']}]"
                              if st.get("analysis", {}).get("waveform") else ""))
                for warning in st.get("quality", []):
                    lines.append(f"  [{warning['severity']}] {warning['code']}: "
                                 f"{warning['message']} -> {warning['suggestion']}")
            for step in recovery:
                lines.append(f"  recovery: attempt {step['attempt']} -> {step['recovery']}")
            for kind, path in evidence.manifest().items():
                lines.append(f"saved {kind}: {path}")
            emit(payload, "\n".join(lines))
    finally:
        inst.close()

def _write_csv(path: Path, data: dict) -> None:
    Evidence().csv("csv", path, data)

def _query_or_none(inst, cmd):
    """Ask once; an instrument that does not implement a query must not sink the rest."""
    try:
        value = inst.query(cmd)
    except Exception as exc:
        return None, str(exc)
    value = (value or "").strip()
    return (value or None), None


def cmd_status(a) -> None:
    """Describe the whole instrument in one connection (read-only).

    Channels first: every dialect supports those queries, so a vendor quirk in
    an acquisition query cannot hide the wiring. The caller sees values, `null`,
    and an `unsupported` list, never a SCPI error to work around.
    """
    inst = Session(a)
    try:
        d, idn = _dialect_for(a, inst)
        channels = [int(x) for x in (a.channels or "1").split(",") if x.strip()]
        problems = []

        per_channel = {}
        for n in channels:
            item = {}
            for key, cmd in d.channel_status_queries(n).items():
                item[key], err = _query_or_none(inst, cmd)
                if err:
                    problems.append(f"CH{n} {key}: {err}")
            per_channel[str(n)] = item

        settings = {}
        for key, cmd in d.status_queries().items():
            settings[key], err = _query_or_none(inst, cmd)
            if err:
                problems.append(f"{key}: {err}")

        result = Result(idn=idn, family=d.name)
        result.set("settings", settings).set("channels", per_channel)
        result.set("capabilities", advertised(d))
        connection = {"source": getattr(inst, "connection_source", None),
                      "endpoint": getattr(inst, "resource", None)}
        result.set("connection", {k: v for k, v in connection.items() if v})
        result.unsupported = [k for k, v in settings.items() if v is None]
        if inst.reconnects:
            result.set("reconnects", inst.reconnects)
        if problems:
            result.set("errors", problems)
        emit(result.to_dict(), as_json=True)
    finally:
        inst.close()


def _check_items(text: str) -> list[str]:
    items = [x.strip().lower() for x in (text or "").split(",") if x.strip()]
    bad = [x for x in items if x not in MEASURE_ITEMS]
    if bad:
        die(f"unknown measurement(s): {', '.join(bad)}; choose from {', '.join(MEASURE_ITEMS)}")
    return items


def _fmt_value(value) -> str:
    return f"{value:.6g}" if isinstance(value, (int, float)) else str(value)


def cmd_measure(a) -> None:
    inst = Session(a)
    try:
        d, idn = _dialect_for(a, inst)
        items = _check_items(a.items or "vpp,rms,freq,period")
        values = measure_channel(inst, d, a.channel, items)
        result = Result(idn=idn, family=d.name)
        result.set("channel", a.channel).set("measurements", values)
        emit(result.to_dict(), as_json=True)
    finally:
        inst.close()


def _parse_channel_spec(text: str) -> dict:
    """Parse `N[:scale[:offset[:probe[:coupling]]]]`, e.g. `1:0.5:-2.3:10:DC`."""
    parts = text.split(":")
    spec = {"n": int(parts[0])}
    for key, raw in zip(("scale", "offset", "probe", "coupling"), parts[1:]):
        if raw:
            spec[key] = raw.upper() if key == "coupling" else float(raw)
    return spec


def _arm_human(out: dict) -> str:
    lines = [f"{out['idn']}  [{out['family']}]  {out['mode']}"]
    if out.get("armed"):
        lines.append(f"armed; trigger state {out.get('trigger_state')} (no capture)")
    elif out.get("timed_out"):
        lines.append(f"no trigger within {out['waited_s']} s; nothing captured")
    else:
        lines.append(f"captured after {out['waited_s']} s")
    for ch, st in out.get("channels", {}).items():
        lines.append(f"CH{ch}: {st.get('points')} pts  Vpp={st.get('vpp'):.4g}V "
                     f"mean={st.get('mean'):.4g}V" +
                     (f"  f={st['freq']:.4g}Hz" if "freq" in st else "") +
                     (f"  [{st['analysis']['waveform']['type']}]"
                      if st.get("analysis", {}).get("waveform") else ""))
        for w in st.get("quality", []):
            lines.append(f"  [{w['severity']}] {w['code']}: {w['message']} -> {w['suggestion']}")
    for ch, values in out.get("measurements", {}).items():
        lines.append(f"measure CH{ch}: " +
                     "  ".join(f"{k}={_fmt_value(v)}" for k, v in values.items()))
    for key in ("out", "plot", "shot"):
        if out.get(key):
            lines.append(f"saved {key}: {out[key]}")
    if out.get("shot_error"):
        lines.append(f"shot: {out['shot_error']}")
    return "\n".join(lines)


def _channel_summaries(data, no_quality=False, no_analyze=False):
    out = {}
    for ch, item in data.items():
        st = stats(item["volts"], item["times"])
        if not no_quality:
            st["quality"] = check_quality(item["volts"], item["times"], item["meta"])
        if not no_analyze:
            adv = advanced(item["volts"], item["times"], item["meta"])
            adv["waveform"] = classify(item["volts"], item["times"], st, adv)
            st["analysis"] = adv
        out[str(ch)] = st
    return out


def _arm_plan(a):
    specs = [_parse_channel_spec(x) for x in (a.ch or [])]
    channels = [int(x) for x in (a.channels or "").split(",") if x.strip()]
    if not channels:
        channels = [s["n"] for s in specs] or [1]
    return Plan(
        channels=[ChannelSetup(s["n"], s.get("scale"), s.get("offset"),
                               s.get("probe"), s.get("coupling")) for s in specs],
        timebase=a.timebase, timebase_offset=a.timebase_offset,
        trigger=TriggerSetup(source=a.source, level=a.level, slope=a.slope),
        mode=a.mode, wait=a.wait, no_wait=a.no_wait,
        read=channels, points=a.points)


def _monitor_plan(a, channels):
    ch = channels[0] if channels else 1
    return Plan(
        channels=[ChannelSetup(ch, scale=a.channel_scale, offset=a.channel_offset)],
        timebase=a.timebase,
        trigger=TriggerSetup(
            type=a.trigger_type or "edge", source=a.trigger_source,
            level=a.trigger_level, slope=a.trigger_slope, sweep=a.trigger_mode,
            pulse_width=a.pulse_width, pulse_polarity=a.pulse_polarity,
            pulse_when=a.pulse_when),
        mode="single", wait=max(0.1, a.duration), read=channels,
        points=a.points, attempts=2, unknown_is_done=True,
        settle=a.settle, poll=max(0.02, a.interval))


def _plan_settings(plan):
    trigger = plan.trigger
    settings = {
        "channels": ",".join(str(c.n) for c in plan.channels),
        "timebase": plan.timebase,
        "trigger_type": trigger.type if trigger else None,
        "trigger_source": trigger.source if trigger else None,
        "trigger_level": trigger.level if trigger else None,
        "trigger_slope": trigger.slope if trigger else None,
        "trigger_mode": trigger.sweep if trigger else None,
        "pulse_width": trigger.pulse_width if trigger else None,
        "pulse_when": trigger.pulse_when if trigger else None,
        "pulse_polarity": trigger.pulse_polarity if trigger else None,
        "channel_scale": plan.channels[0].scale if plan.channels else None,
        "channel_offset": plan.channels[0].offset if plan.channels else None,
    }
    return {k: v for k, v in settings.items() if v is not None}


def cmd_arm(a) -> None:
    """Apply a setup, arm, wait for the trigger, then capture in one connection."""
    items = _check_items(a.measure) if a.measure else []
    inst = Session(a)
    try:
        d, idn = _dialect_for(a, inst)
        plan = _arm_plan(a)
        executor = Executor(inst, d)
        arm = executor.arm_wait(plan)
        result = Result(idn=idn, family=d.name)
        result.set("mode", a.mode).set("armed", arm.armed)
        result.set("waited_s", arm.waited_s).set("trigger_state", arm.trigger_state)
        result.set("captured", arm.captured)
        if arm.timed_out:
            result.set("timed_out", True)
        if arm.warnings:
            result.set("warnings", arm.warnings)
        evidence = Evidence()
        if arm.captured:
            data, recovery = executor.acquire(plan)
            if recovery:
                result.set("recovery", recovery)
            result.set("channels", _channel_summaries(data, a.no_quality, a.no_analyze))
            if a.measure:
                result.set("measurements", {
                    str(ch): measure_channel(inst, d, ch, items) for ch in plan.read})
            if a.out:
                path = Path(a.out).expanduser()
                fmt = a.format or path.suffix.lstrip(".").lower() or "csv"
                if fmt == "csv":
                    evidence.csv("csv", path, data)
                elif fmt == "json":
                    evidence.json("json", path, {
                        str(k): {"times": v["times"], "volts": v["volts"]}
                        for k, v in data.items()})
                else:
                    die(f"unsupported output format: {fmt}")
            if a.plot:
                first = next(iter(data.values()))
                extra = advanced(first["volts"], first["times"], first["meta"])
                evidence.svg("plot", a.plot, first["times"], first["volts"],
                             title=f"{idn} CH{list(data)[0]}", extra=extra,
                             max_points=a.plot_points)
        if a.shot:
            _, blob = d.screenshot(inst)
            if blob:
                evidence.bytes("shot", a.shot, blob)
            else:
                result.warn("this model has no screen dump")
        for kind, path in evidence.manifest().items():
            result.add_evidence(kind, path)
        payload = result.to_dict()
        emit(payload, None if a.json else _arm_human(payload), as_json=a.json)
    finally:
        inst.close()


def cmd_monitor(a) -> None:
    apply_preset(a)
    if a.dry_run:
        channels = [int(x) for x in a.channels.split(",") if x.strip()]
        plan = _monitor_plan(a, channels)
        result = Result()
        result.set("dry_run", True)
        result.set("plan", ["apply the setup", "arm one trigger sequence",
                            f"wait up to {a.duration:g} s",
                            f"capture channels {a.channels}",
                            f"write {a.outdir}/<prefix>-NN.csv and .json"])
        result.set("settings", _plan_settings(plan))
        emit(result.to_dict(), as_json=True)
        return
    inst = Session(a)
    try:
        d, idn = _dialect_for(a, inst)
        channels = [int(x) for x in a.channels.split(",") if x.strip()]
        plan = _monitor_plan(a, channels)
        executor = Executor(inst, d)
        evidence = Evidence()
        deadline = time.time() + a.duration
        events = []
        for i in range(max(1, a.max_events)):
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            plan.wait = remaining
            arm = executor.arm_wait(plan)
            if not arm.captured:
                break
            data, recovery = executor.acquire(plan)
            stem = Path(a.outdir).expanduser() / f"{a.prefix}-{i + 1:02d}"
            evidence.csv(f"event-{i + 1:02d}-csv", stem.with_suffix(".csv"), data)
            summary = {"idn": idn, "family": d.name, "event": i + 1,
                       "recovery": recovery,
                       "channels": _channel_summaries(data, a.no_quality, True)}
            evidence.json(f"event-{i + 1:02d}-json", stem.with_suffix(".json"), summary)
            events.append({"event": i + 1,
                           "csv": str(stem.with_suffix(".csv")),
                           "json": str(stem.with_suffix(".json")),
                           "stats": summary["channels"]})
            if not a.auto_rearm:
                break
        result = Result(idn=idn, family=d.name)
        result.set("events", events)
        for kind, path in evidence.manifest().items():
            result.add_evidence(kind, path)
        emit(result.to_dict(), as_json=True)
    finally:
        inst.close()

def cmd_watch(a) -> None:
    """Measure the same signals repeatedly and report the trend.

    Covers the poll loop that otherwise turns into one heredoc per sample.
    """
    channels = [int(x) for x in a.channel.split(",") if x.strip()]
    items = _check_items(a.items)
    inst = Session(a)
    try:
        d, idn = _dialect_for(a, inst)
        rows = []
        for i in range(a.samples):
            row = {"sample": i + 1, "channels": {}}
            for ch in channels:
                row["channels"][str(ch)] = measure_channel(inst, d, ch, items)
            if a.state:
                row["trigger_state"] = query_run_state(inst, d)
            rows.append(row)
            if not a.json:
                cells = [f"CH{ch} " + " ".join(f"{k}={_fmt_value(row['channels'][str(ch)].get(k))}"
                                                for k in items)
                         for ch in channels]
                trig = ""
                if a.state:
                    trig = f"  trig={'STOP' if row.get('trigger_state') else 'RUN'}"
                print(f"[{i + 1}/{a.samples}] " + "  ".join(cells) + trig, flush=True)
            if i + 1 < a.samples and a.interval:
                time.sleep(a.interval)
        summary = {}
        for ch in channels:
            summary[str(ch)] = {}
            for item in items:
                values = [r["channels"][str(ch)].get(item) for r in rows]
                values = [v for v in values if isinstance(v, (int, float))]
                if values:
                    summary[str(ch)][item] = {
                        "min": min(values), "median": statistics.median(values),
                        "max": max(values), "mean": sum(values) / len(values)}
        result = Result(idn=idn, family=d.name)
        result.set("samples", len(rows)).set("items", items)
        result.set("rows", rows).set("summary", summary)
        evidence = Evidence()
        if a.out:
            evidence.json("out", a.out, result.to_dict())
        for kind, path in evidence.manifest().items():
            result.add_evidence(kind, path)
        payload = result.to_dict()
        if a.json:
            emit(payload, as_json=True)
        else:
            lines = []
            for ch, per_item in summary.items():
                for item, s in per_item.items():
                    lines.append(f"CH{ch} {item}: min={s['min']:.6g} "
                                 f"median={s['median']:.6g} max={s['max']:.6g}")
            if payload.get("out"):
                lines.append(f"saved: {payload['out']}")
            print("\n".join(lines))
    finally:
        inst.close()


def cmd_shot(a) -> None:
    inst = Session(a)
    try:
        d, idn = _dialect_for(a, inst)
        evidence = Evidence()
        result = Result(idn=idn, family=d.name)
        if not d.screenshot_queries():
            data, _ = Executor(inst, d).acquire(Plan(read=[1], attempts=2))
            item = data[1]
            extra = advanced(item["volts"], item["times"], item["meta"])
            path = Path(a.out).expanduser().with_suffix(".svg")
            evidence.svg("plot", path, item["times"], item["volts"],
                         title=f"{idn} CH1 (scope has no screen dump)", extra=extra)
            result.set("fallback", "waveform-plot")
            result.warn("the instrument cannot export a screenshot; "
                        "rendered a waveform plot instead")
        else:
            _, blob = d.screenshot(inst)
            if not blob:
                die("screenshot failed: the instrument did not return PNG/JPEG data. "
                    "Try the raw command in references/dialects.md")
            evidence.bytes("shot", a.out, blob)
            result.set("bytes", len(blob))
        for kind, path in evidence.manifest().items():
            result.add_evidence(kind, path)
        emit(result.to_dict(), as_json=True)
    finally:
        inst.close()

def cmd_scpi(a) -> None:
    """Batch raw SCPI on one connection (maintainer escape hatch).

    Deliberately hidden from help and docs: if a workflow needs a command
    sequence, add an intent verb here or a query to the driver, do not teach
    the caller SCPI.
    """
    commands = a.command if isinstance(a.command, list) else [a.command]
    inst = Session(a)
    try:
        results = []
        for cmd in commands:
            try:
                value = inst.query(cmd) if a.query else inst.write(cmd)
                results.append({"ok": True, "command": cmd,
                                "response": value if a.query else None})
            except Exception as exc:  # noqa: BLE001
                results.append({"ok": False, "command": cmd, "error": str(exc)})
        emit(results[0] if len(results) == 1 else results, as_json=True)
        if any(not r["ok"] for r in results):
            sys.exit(1)
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


def _channel_key(name: str) -> str:
    key = str(name).strip().lower()
    return key[2:] if key.startswith("ch") else key


def read_csv_capture(path: Path):
    """Return (header, {channel: (times, volts)}) for every data column."""
    with path.open(newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        raise ValueError("empty CSV")
    header = rows[0]
    if len(header) > 1:
        columns = {name: i for i, name in enumerate(header) if i > 0}
        time_col = 0
    else:
        columns = {header[0]: 0}
        time_col = 0
    series = {_channel_key(name): ([], []) for name in columns}
    for row in rows[1:]:
        if len(row) <= time_col or any(len(row) <= i for i in columns.values()):
            continue
        stamp = float(row[time_col])
        for name, index in columns.items():
            times, volts = series[_channel_key(name)]
            times.append(stamp)
            volts.append(float(row[index]))
    return header, series


def cmd_analyze(a) -> None:
    """Analyze every channel of a saved record; fixed verbs, free-form data math."""
    if not a.csv and not a.npz:
        die("analyze requires --csv or --npz")
    if a.npz:
        path = Path(a.npz).expanduser()
        if not path.exists():
            die(f"file not found: {path}")
        data = load_npz(path)
        if not data:
            die("no channels found in npz")
        series = {str(ch): (item["times"], item["volts"]) for ch, item in data.items()}
        header = ["time"] + [f"ch{ch}" for ch in series]
    else:
        path = Path(a.csv).expanduser()
        if not path.exists():
            die(f"file not found: {path}")
        header, series = read_csv_capture(path)
    if not series:
        die(f"no data columns in {path}")

    channels = {}
    for ch, (times, volts) in series.items():
        st = stats(volts, times)
        st["warnings"] = check_quality(volts, times)
        st["logic_levels"] = _logic_levels(volts)
        channels[ch] = st

    target = str(a.channel) if a.channel is not None else next(iter(series))
    if target not in channels:
        die(f"channel {target} is not in {path}; columns: {', '.join(series)}")
    if a.fft:
        for ch, (times, volts) in series.items():
            try:
                channels[ch].update(spectrum(volts, (times[1] - times[0]) if len(times) > 1 else 0))
            except RuntimeError as exc:
                channels[ch]["fft_error"] = str(exc)

    out = dict(channels[target])
    out.update({"file": str(path), "columns": header, "channel": target,
                "channels": channels})
    evidence = Evidence()
    if a.plot:
        if Path(a.plot).suffix.lower() != ".svg":
            die("--plot currently supports .svg output")
        times, volts = series[target]
        evidence.svg("plot", a.plot, times, volts,
                     title=f"{path.name} ch{target}", extra=out,
                     max_points=a.plot_points)
        out.update(evidence.manifest())
    emit(Result(values=out).to_dict(), as_json=True)


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


RAW_COMMANDS = {"scpi": None, "query": True, "write": False}


def _raw_main(name: str, argv: list[str]) -> None:
    """Maintainer escape hatch, kept out of the documented interface on purpose."""
    ap = argparse.ArgumentParser(prog=f"scope.py {name}",
                                 description="internal escape hatch; prefer an intent verb")
    add_conn(ap)
    ap.add_argument("command", nargs="+")
    if name == "scpi":
        ap.add_argument("--query", action="store_true")
    a = ap.parse_args(argv)
    if name != "scpi":
        a.query = RAW_COMMANDS[name]
    cmd_scpi(a)


def main() -> None:
    target = venv_reexec_argv(sys.argv)
    if target is not None:
        os.execv(target[0], target)
    if len(sys.argv) > 1 and sys.argv[1] in RAW_COMMANDS:
        return _raw_main(sys.argv[1], sys.argv[2:])
    ap = argparse.ArgumentParser(prog="scope.py", description="Generic oscilloscope control (LAN/USB)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("setup", help="create venv and install pyvisa/usb support")
    p.add_argument("--dev", action="store_true")
    p.set_defaults(fn=cmd_setup)

    p = sub.add_parser("test", help="run the skill test suite")
    p.add_argument("--install", action="store_true", help="install pytest if it is missing")
    p.add_argument("-k", dest="k", help="pytest -k expression")
    p.set_defaults(fn=cmd_test)

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

    p = sub.add_parser("status", help="one read-only read of the whole instrument")
    add_conn(p)
    p.add_argument("--channels", default="1", help="comma-separated channel list")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("idn", help="identify the instrument and dialect")
    add_conn(p)
    p.set_defaults(fn=cmd_idn)

    p = sub.add_parser("config", help="persistent defaults")
    p.add_argument("config_cmd", choices=["get", "set", "unset", "list"])
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.set_defaults(fn=cmd_config)

    p = sub.add_parser("channel", help="advanced: set a channel (arm --ch is the usual path)")
    add_conn(p)
    p.add_argument("--ch", type=int, default=1)
    p.add_argument("--scale", type=float, help="volts/div")
    p.add_argument("--offset", type=float, help="volts")
    p.add_argument("--coupling", choices=["DC", "AC", "GND", "dc", "ac", "gnd"])
    p.add_argument("--probe", type=float)
    p.add_argument("--on", type=lambda x: x.lower() in ("1", "on", "true"), default=None)
    p.set_defaults(fn=cmd_channel)

    p = sub.add_parser("timebase", help="advanced: set the timebase (arm --timebase ...)")
    add_conn(p)
    p.add_argument("--scale", type=float, help="seconds/div")
    p.add_argument("--offset", type=float, help="seconds")
    p.set_defaults(fn=cmd_timebase)

    p = sub.add_parser("trigger", help="advanced: set an edge trigger (arm --source/--level ...)")
    add_conn(p)
    p.add_argument("--source", type=int)
    p.add_argument("--level", type=float)
    p.add_argument("--slope", choices=["rising", "falling", "either", "RISING", "FALLING", "EITHER"])
    p.add_argument("--mode", choices=["auto", "normal", "single", "AUTO", "NORMAL", "SINGLE"])
    p.set_defaults(fn=cmd_trigger)

    p = sub.add_parser("run", help="advanced: run / stop / single / autoscale")
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

    p = sub.add_parser("arm", help="apply a setup, arm, wait, then capture and measure")
    add_conn(p)
    p.add_argument("--ch", action="append", metavar="N[:SCALE[:OFFSET[:PROBE[:COUPLING]]]]",
                   help="channel to set up; repeat for more channels")
    p.add_argument("--channels", help="channels to capture (default: the --ch channels, else 1)")
    p.add_argument("--timebase", type=float, help="seconds per division")
    p.add_argument("--timebase-offset", type=float)
    p.add_argument("--source", type=int, help="trigger source channel")
    p.add_argument("--level", type=float, help="trigger level in volts")
    p.add_argument("--slope", choices=["rising", "falling", "either"])
    p.add_argument("--mode", choices=["single", "normal"], default="single")
    p.add_argument("--wait", type=float, default=10.0, help="seconds to wait for the trigger")
    p.add_argument("--no-wait", action="store_true",
                   help="arm and report the state; do not wait for a trigger")
    p.add_argument("--points", type=int)
    p.add_argument("--measure", help="measurements to take on each captured channel")
    p.add_argument("--out")
    p.add_argument("--format", choices=["csv", "json"])
    p.add_argument("--plot")
    p.add_argument("--plot-points", type=int, default=4000)
    p.add_argument("--shot")
    p.add_argument("--no-quality", action="store_true")
    p.add_argument("--no-analyze", action="store_true")
    p.set_defaults(fn=cmd_arm)

    p = sub.add_parser("watch", help="measure the same signals repeatedly and summarize")
    add_conn(p)
    p.add_argument("--channel", default="1", help="channel or comma-separated channels")
    p.add_argument("--items", default="vavg,vmin,vmax")
    p.add_argument("--samples", type=int, default=5)
    p.add_argument("--interval", type=float, default=0.5, help="seconds between samples")
    p.add_argument("--state", action="store_true", help="also record the trigger state")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_watch)

    p = sub.add_parser("shot", help="save a screenshot")
    add_conn(p)
    p.add_argument("--out", default="scope.png")
    p.set_defaults(fn=cmd_shot)

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
    p.add_argument("--channel", type=int, help="channel for --plot (default: first)")
    p.add_argument("--plot", help="write an SVG waveform plot")
    p.add_argument("--plot-points", type=int, default=4000)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_analyze)

    p = sub.add_parser("list", help="list VISA resources")
    p.add_argument("--backend")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_discover, scan=None, port=None)

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
