"""Multi-stage condition search over a capture (a software stand-in for triggers).

The analyzer's hardware only offers a single simple trigger, so staged conditions
are resolved after acquisition: find where stage 1 happens, then look ahead for
stage 2 within a window, and so on.
"""

from __future__ import annotations

import bisect
from pathlib import Path

from . import decode
from .common import SkillError

STATES = ("rising", "falling", "high", "low", "both")


class Trace:
    """One channel of a capture, queried by sample index."""

    def __init__(self, path: str | Path, valid_bits: int) -> None:
        self.path = Path(path)
        self.valid_bits = int(valid_bits)
        self._times: list[int] = []
        self._levels: list[int] = []

    def _load(self) -> None:
        if self._times:
            return
        for index, level in decode.transitions(self.path, self.valid_bits):
            self._times.append(index)
            self._levels.append(level)

    def level_at(self, index: int) -> int:
        self._load()
        position = bisect.bisect_right(self._times, index) - 1
        return self._levels[position] if position >= 0 else 0

    def next_match(self, state: str, start: int) -> int | None:
        """First sample >= ``start`` where the channel satisfies ``state``."""
        self._load()
        if state in ("rising", "falling", "both"):
            wanted = {"rising": 1, "falling": 0, "both": None}[state]
            position = bisect.bisect_left(self._times, start)
            while position < len(self._times):
                if wanted is None or self._levels[position] == wanted:
                    return self._times[position]
                position += 1
            return None
        wanted = 1 if state == "high" else 0
        if self.level_at(start) == wanted:
            return start
        position = bisect.bisect_right(self._times, start)
        while position < len(self._times):
            if self._levels[position] == wanted:
                return self._times[position]
            position += 1
        return None


def search(traces: dict[int, Trace], stages: list[dict], within: int | None = None,
           limit: int = 10, start_at: int = 0) -> list[dict]:
    hits: list[dict] = []
    if not stages:
        raise SkillError("invalid_stage", "at least one stage is required")
    first = stages[0]
    trace = traces[first["channel"]]
    position = start_at
    while len(hits) < limit:
        begin = trace.next_match(first["state"], position)
        if begin is None:
            break
        moment = begin
        matched = [{"channel": first["channel"], "state": first["state"], "sample": begin}]
        for stage in stages[1:]:
            found = traces[stage["channel"]].next_match(stage["state"], moment + 1)
            if found is None or (within is not None and found - begin > within):
                matched = []
                break
            matched.append({"channel": stage["channel"], "state": stage["state"], "sample": found})
            moment = found
        if matched:
            hits.append({"start": begin, "end": moment, "stages": matched})
        position = begin + 1
    return hits
