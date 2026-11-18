"""Legal frequency/duration combinations.

The device accepts a small, profile-dependent set of pairs, and the vendor
manual is explicit that neither frequency nor duration may be guessed: ask the
device, then choose from the answer. ``resolve`` does the choosing while saying
what it changed, so a capture never silently uses a different sample rate than
the caller asked for.
"""

from __future__ import annotations

from .common import SkillError, fmt_hz, fmt_ms


def channel_list(channels: list[dict]) -> str:
    return ",".join(str(channel["id"]) for channel in channels)


def query_one_shot(invocation, mode: str, channels: list[dict], frequency=None,
                   duration=None, timeout: float = 60.0) -> dict:
    from .protocol import run_json

    args = ["device", "capabilities", "--mode", mode, "--channels", channel_list(channels)]
    if frequency is not None:
        args += ["--frequency", str(int(frequency))]
    elif duration is not None:
        args += ["--time", str(int(duration))]
    return run_json(invocation, args, timeout=timeout, context="device capabilities")


def query_session(session, mode: str, channels: list[dict], frequency=None,
                  duration=None) -> dict:
    params: dict = {"mode": mode, "channels": channels}
    if frequency is not None:
        params["frequencyHz"] = int(frequency)
    elif duration is not None:
        params["durationMs"] = int(duration)
    return session.request("device.capabilities", params)


def options_from(payload: dict) -> list[dict]:
    """Normalise the three capability answer shapes into one options list."""
    if isinstance(payload.get("options"), list):
        return [
            {"frequencyHz": int(option["frequencyHz"]), "timings": option.get("timings") or []}
            for option in payload["options"]
        ]
    if payload.get("query") == "durationOptions":
        frequency = int(payload["frequencyHz"])
        return [
            {
                "frequencyHz": frequency,
                "timings": [{"durationMs": int(d), "rle": False} for d in payload["durationOptionsMs"]],
            }
        ]
    if payload.get("query") == "frequencyOptions":
        duration = int(payload["durationMs"])
        return [
            {
                "frequencyHz": int(f),
                "timings": [{"durationMs": duration, "rle": False}],
            }
            for f in payload["frequencyOptionsHz"]
        ]
    raise SkillError(
        "invalid_output",
        "the device capability answer has no option list",
        ["run device capabilities by hand and check the CLI version"],
        details={"payload": payload},
    )


def _timings(option: dict) -> dict[int, bool]:
    return {int(t["durationMs"]): bool(t.get("rle")) for t in option.get("timings") or []}


def resolve(options: list[dict], frequency_hz: int, duration_ms: int,
            strict: bool = False) -> dict:
    """Pick the legal pair closest to the request and report the difference.

    Frequency is chosen first (largest legal value at or below the request),
    then duration at that frequency. That keeps a requested bandwidth honest:
    a 3 MHz request on a 2 MHz-only profile becomes 2 MHz, never 4 MHz.
    """
    if not options:
        raise SkillError(
            "device_capability_empty",
            "the device returned no legal capture combinations for these channels",
            ["check the channel count; the profile depends on it"],
        )
    by_frequency = {int(o["frequencyHz"]): _timings(o) for o in options}
    frequencies = sorted(by_frequency, reverse=True)
    adjustments: list[str] = []

    frequency = int(frequency_hz)
    if frequency not in by_frequency:
        if strict:
            raise SkillError(
                "invalid_capture_combination",
                f"{fmt_hz(frequency)} is not a legal sample rate for this device and channel count",
                [f"legal rates: {', '.join(fmt_hz(f) for f in frequencies)}"],
            )
        lower = [f for f in frequencies if f <= frequency]
        chosen = lower[0] if lower else min(frequencies)
        direction = "at or below" if lower else "closest"
        adjustments.append(
            f"frequency {fmt_hz(frequency)} -> {fmt_hz(chosen)} (largest legal rate {direction} the request)"
        )
        frequency = chosen

    timings = by_frequency[frequency]
    durations = sorted(timings)
    duration = int(duration_ms)
    if duration not in timings:
        if strict:
            raise SkillError(
                "invalid_capture_combination",
                f"{fmt_ms(duration)} is not a legal capture time at {fmt_hz(frequency)}",
                [f"legal durations: {', '.join(fmt_ms(d) for d in durations)}"],
            )
        shorter = [d for d in durations if d <= duration]
        chosen = shorter[-1] if shorter else durations[0]
        direction = "at or below" if shorter else "closest"
        adjustments.append(
            f"duration {fmt_ms(duration)} -> {fmt_ms(chosen)} (longest legal time {direction} the request)"
        )
        duration = chosen

    return {
        "frequencyHz": frequency,
        "durationMs": duration,
        "rle": timings.get(duration, False),
        "adjustments": adjustments,
        "samplingDepth": frequency * duration // 1000,
        "legalFrequenciesHz": frequencies,
        "legalDurationsMs": durations,
    }


def summarise(options: list[dict], limit: int = 8) -> dict:
    """A compact table: rate, legal durations, which of them use RLE."""
    rows = []
    for option in sorted(options, key=lambda o: -int(o["frequencyHz"])):
        timings = option.get("timings") or []
        durations = sorted(int(t["durationMs"]) for t in timings)
        rows.append(
            {
                "frequencyHz": int(option["frequencyHz"]),
                "durationCount": len(durations),
                "durationsMs": durations if len(durations) <= limit else None,
                "minDurationMs": durations[0] if durations else None,
                "maxDurationMs": durations[-1] if durations else None,
                "rleDurationsMs": sorted(
                    int(t["durationMs"]) for t in timings if t.get("rle")
                ),
            }
        )
    return {"frequencyCount": len(rows), "options": rows}
