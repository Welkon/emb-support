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


@dataclass
class ArmResult:
    waited_s: float
    trigger_state: str | None
    armed: bool
    captured: bool
    timed_out: bool = False
    warnings: list = field(default_factory=list)


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
    def configure(self, plan: Plan) -> list[str]:
        d, s = self.dialect, self.session
        commands: list[str] = []
        for channel in plan.channels:
            n = channel.n
            commands.append(d.channel_display(n, True))
            if channel.scale is not None:
                commands.append(d.channel_scale(n, channel.scale))
            if channel.offset is not None:
                commands.append(d.channel_offset(n, channel.offset))
            if channel.coupling:
                commands.append(d.channel_coupling(n, channel.coupling.upper()))
            if channel.probe is not None:
                commands.append(d.channel_probe(n, channel.probe))
        if plan.timebase is not None:
            commands.append(d.timebase_scale(plan.timebase))
        if plan.timebase_offset is not None:
            commands.append(d.timebase_offset(plan.timebase_offset))

        warnings: list[str] = []
        trigger = plan.trigger
        if trigger:
            if trigger.source is not None:
                commands += [d.trigger_type(), d.trigger_source(trigger.source)]
            if trigger.level is not None:
                commands += [d.trigger_type(), d.trigger_level(trigger.level)]
            if trigger.slope:
                commands += [d.trigger_type(), d.trigger_slope(trigger.slope.upper())]
            if trigger.sweep:
                commands.append(d.trigger_sweep(trigger.sweep.upper()))
            if trigger.type == "pulse":
                when = ("GREATERthan" if "greater" in (trigger.pulse_when or "less").lower()
                        else "LESSthan")
                pulse = d.trigger_pulse(
                    trigger.pulse_width or 1e-6,
                    (trigger.pulse_polarity or "positive").upper(), when)
                if pulse:
                    commands += pulse
                else:
                    warnings.append(
                        "pulse trigger is not mapped for this family; using edge")

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
        if not plan.read:
            return {}, []
        if plan.no_recovery:
            return acquire_channels(self.session, self.dialect, plan.read, plan.points), []
        return acquire_with_recovery(
            self.session, self.dialect, plan.read, plan.points,
            attempts=plan.attempts, allow_autoset=plan.autoset)
