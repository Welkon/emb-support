"""A plan is the value object behind `arm`, `capture --single` and `monitor`.

The three verbs used to repeat the same sequence: apply setup, arm, wait, read,
measure, save. They now build one Plan and hand it to one Executor, so a fix to
the sequence (a new wait rule, a trigger quirk) lands in one place.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .acquisition import acquire_channels, acquire_with_recovery


@dataclass
class ChannelSetup:
    n: int
    scale: float | None = None
    offset: float | None = None
    probe: float | None = None
    coupling: str | None = None
    invert: bool | None = None
    bw_limit: str | None = None
    display: bool | None = None


@dataclass
class TriggerSetup:
    type: str = "edge"                 # edge | pulse
    source: int | None = None
    level: float | None = None
    slope: str | None = None
    sweep: str | None = None           # SINGle | NORMal | AUTO
    pulse_width: float | None = None
    pulse_polarity: str | None = None
    pulse_when: str | None = None
    holdoff: float | None = None
    slope_level_b: float | None = None
    video_standard: str | None = None
    video_polarity: str | None = None
    video_line: int | None = None


@dataclass
class Plan:
    channels: list[ChannelSetup] = field(default_factory=list)
    timebase: float | None = None
    timebase_offset: float | None = None
    trigger: TriggerSetup | None = None
    mode: str = "single"               # single | normal
    wait: float = 10.0
    no_wait: bool = False
    read: list[int] = field(default_factory=list)
    points: int | None = None
    attempts: int = 3
    no_recovery: bool = False
    autoset: bool = False
    unknown_is_done: bool = False      # monitor: an unknown state after settle counts
    settle: float = 1.0
    poll: float = 0.05
    acquire_mode: str | None = None    # normal | average | peak | hires
    averages: int | None = None
    depth: str | None = None


@dataclass
class ArmResult:
    waited_s: float
    trigger_state: str | None
    armed: bool
    captured: bool
    timed_out: bool = False
    warnings: list = field(default_factory=list)


def acquire_mode_name(value: str | None) -> str | None:
    """Map a driver string (NORMal, AVERages, HRESolution, PEAK) to a mode name."""
    if not value:
        return None
    text = str(value).upper()
    if "AVER" in text:
        return "average"
    if "PEAK" in text:
        return "peak"
    if "HRES" in text:
        return "hires"
    return "normal"


def query_run_state(inst, dialect) -> bool | None:
    """True = stopped (event captured), False = running, None = unknown."""
    for query in dialect.state_queries():
        try:
            value = inst.query(query).strip().upper()
        except Exception:  # noqa: BLE001
            continue
        if query.upper().startswith(":TRIG"):
            return value.startswith("STOP")
        return value in ("0", "STOP", "STOPPED", "OFF")
    return None


class Executor:
    """Turns a Plan into instrument operations. No output, no evidence."""

    def __init__(self, session, dialect):
        self.session = session
        self.dialect = dialect

    # -- setup ---------------------------------------------------------
    @staticmethod
    def _mapped(commands, feature: str, warnings: list[str]) -> list[str]:
        if commands:
            return list(commands)
        warnings.append(f"{feature} is not mapped for this family")
        return []

    def configure(self, plan: Plan) -> list[str]:
        d, s = self.dialect, self.session
        commands: list[str] = []
        warnings: list[str] = []

        for channel in plan.channels:
            n = channel.n
            commands.append(d.channel_display(
                n, True if channel.display is None else channel.display))
            if channel.scale is not None:
                commands.append(d.channel_scale(n, channel.scale))
            if channel.offset is not None:
                commands.append(d.channel_offset(n, channel.offset))
            if channel.coupling:
                commands.append(d.channel_coupling(n, channel.coupling.upper()))
            if channel.probe is not None:
                commands.append(d.channel_probe(n, channel.probe))
            if channel.invert is not None:
                command = d.channel_invert(n, channel.invert)
                commands += self._mapped([command] if command else [],
                                         "channel invert", warnings)
            if channel.bw_limit is not None:
                command = d.channel_bw_limit(n, channel.bw_limit)
                commands += self._mapped([command] if command else [],
                                         "bandwidth limit", warnings)

        if plan.timebase is not None:
            commands.append(d.timebase_scale(plan.timebase))
        if plan.timebase_offset is not None:
            commands.append(d.timebase_offset(plan.timebase_offset))

        if plan.acquire_mode:
            commands += self._mapped(d.acquire_mode(plan.acquire_mode),
                                     "acquisition mode", warnings)
        if plan.averages is not None:
            commands += self._mapped(d.acquire_averages(plan.averages),
                                     "acquisition averaging", warnings)
        if plan.depth is not None:
            commands += self._mapped(d.acquire_depth(plan.depth),
                                     "memory depth", warnings)

        trigger = plan.trigger
        if trigger:
            if trigger.holdoff is not None:
                commands += self._mapped(d.trigger_holdoff(trigger.holdoff),
                                         "trigger holdoff", warnings)
            source = trigger.source if trigger.source is not None else (
                plan.read[0] if plan.read else 1)
            if trigger.type == "slope":
                commands += self._mapped(
                    d.trigger_slope_setup(source, trigger.slope, trigger.level,
                                          trigger.slope_level_b),
                    "slope trigger", warnings)
            elif trigger.type == "video":
                commands += self._mapped(
                    d.trigger_video_setup(source, trigger.video_polarity,
                                          trigger.video_standard, trigger.video_line),
                    "video trigger", warnings)
            else:
                commands += [d.trigger_type()]
                if trigger.source is not None:
                    commands.append(d.trigger_source(trigger.source))
                if trigger.level is not None:
                    commands.append(d.trigger_level(trigger.level))
                if trigger.slope:
                    commands.append(d.trigger_slope(trigger.slope.upper()))
                if trigger.sweep:
                    commands.append(d.trigger_sweep(trigger.sweep.upper()))
                if trigger.type == "pulse":
                    when = ("GREATERthan"
                            if "greater" in (trigger.pulse_when or "less").lower()
                            else "LESSthan")
                    commands += self._mapped(
                        d.trigger_pulse(trigger.pulse_width or 1e-6,
                                        (trigger.pulse_polarity or "positive").upper(),
                                        when),
                        "pulse trigger", warnings)

        # One EDGE mode write, not one per trigger field.
        for command in dict.fromkeys(commands):
            s.write(command)
        return warnings

    # -- arm and wait --------------------------------------------------
    def arm(self, plan: Plan) -> None:
        if plan.mode == "single":
            commands = self.dialect.arm_single()
        else:
            commands = [self.dialect.trigger_sweep("NORMal"), self.dialect.run()]
        for command in commands:
            self.session.write(command)

    def arm_wait(self, plan: Plan) -> ArmResult:
        started = time.time()
        warnings = self.configure(plan)
        self.arm(plan)
        state = query_run_state(self.session, self.dialect)
        if plan.mode == "single" and not plan.no_wait:
            deadline = started + plan.wait
            while time.time() < deadline:
                state = query_run_state(self.session, self.dialect)
                if state is True:
                    break
                if state is None and plan.unknown_is_done:
                    time.sleep(plan.settle)
                    state = query_run_state(self.session, self.dialect)
                    break
                time.sleep(plan.poll)
        waited = round(time.time() - started, 3)
        armed = plan.mode == "single" and plan.no_wait
        captured = (plan.mode != "single" or state is True) and not armed
        return ArmResult(
            waited_s=waited,
            trigger_state=None if state is None else ("STOP" if state else "RUN"),
            armed=armed,
            captured=captured,
            timed_out=plan.mode == "single" and not armed and not captured,
            warnings=warnings,
        )

    # -- read ----------------------------------------------------------
    def acquire(self, plan: Plan):
        """Read the requested channels, restoring the ambient acquire mode.

        Rigol DS1000Z transfers in HRES/PEAK mode can exceed the USB timeout
        (seen on a real bench: 5 s default, 200 ms/div, HRES). Export in
        normal mode and put the previous mode back, unless the caller asked
        for a mode explicitly.
        """
        if not plan.read:
            return {}, []
        d, s = self.dialect, self.session
        restore_mode = None
        if plan.acquire_mode is None:
            query = d.status_queries().get("acquire_type")
            current = None
            if query:
                try:
                    current = s.query(query).strip()
                except Exception:  # noqa: BLE001
                    current = None
            if current and not current.upper().startswith("NORM"):
                restore_mode = acquire_mode_name(current)
                for command in d.acquire_mode("normal"):
                    s.write(command)
        try:
            if plan.no_recovery:
                return acquire_channels(s, d, plan.read, plan.points), []
            return acquire_with_recovery(
                s, d, plan.read, plan.points,
                attempts=plan.attempts, allow_autoset=plan.autoset)
        finally:
            if restore_mode:
                for command in d.acquire_mode(restore_mode):
                    s.write(command)
