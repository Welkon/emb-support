"""Talking to the vendor CLI: one-shot commands and the JSONL session.

Two transports, same protocol:

* ``run_json`` - a single CLI process for one control command (``device
  list``, ``device connect``, ``capture validate``).
* ``Session`` - ``session --stdio --mode ai``, a JSONL request/response stream
  that keeps one device connection across several captures. This is what makes
  a repeated capture cheap and, more importantly, what lets the skill ask for
  ``capture.stop`` instead of killing a process mid-acquisition.

Both keep the vendor's stdout for data and its log lines in a file, so a
capture never mixes human text into a JSON result. Silence is treated as a
finding, not as patience: a capture whose trigger never fires produces no
further events, so after ``trigger_timeout`` seconds of silence the skill stops
the run, keeps the partial data and says the trigger did not fire.
"""

from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import tempfile
import threading
import time
from typing import Callable, Iterable

from .common import SkillError, vendor_error

PROGRESS_EVENTS = ("capture.progress", "output.progress")


def _stderr_sink():
    return tempfile.NamedTemporaryFile(
        mode="w+", prefix="atk-logic-", suffix=".log", delete=False, encoding="utf-8"
    )


def _read_tail(handle, limit: int = 4000) -> str:
    try:
        handle.flush()
        handle.seek(0)
        data = handle.read()
    except (OSError, ValueError):
        return ""
    return data[-limit:].strip()


def _timeout(context: str, seconds: float) -> SkillError:
    return SkillError(
        "timeout",
        f"{context or 'the CLI'} did not answer within {seconds:.0f} s",
        ["check the device is still plugged in", "raise --timeout for a long capture"],
        retryable=True,
    )


class EventTape:
    """Keep the shape of a capture's event stream, not every line of it.

    The vendor repeats ``output.progress`` thousands of times for a single
    ATKDL export (200k lines were observed for a 10 ms trace). The tape counts
    events, keeps the interesting ones, and reports a progress step only when
    the percentage actually moved.
    """

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.interesting: list[dict] = []
        self.started: dict | None = None
        self.finished: dict | None = None
        self.idle = False
        self.error: dict | None = None
        self.rle = False
        self.last_percent: dict[str, float] = {}
        self.dropped = 0
        self.last_event_at = time.monotonic()

    def feed(self, event: dict) -> str | None:
        name = str(event.get("event") or "")
        self.last_event_at = time.monotonic()
        if name:
            self.counts[name] = self.counts.get(name, 0) + 1

        if name in PROGRESS_EVENTS:
            self.dropped += 1
            key = name if name == "capture.progress" else f"{name}:{event.get('format')}"
            percent = float(event.get("percent") or 0)
            previous = self.last_percent.get(key)
            if previous is not None and percent - previous < 2 and percent < 100:
                return None
            self.last_percent[key] = percent
            if name == "output.progress":
                return f"saving {event.get('format')} {percent:.0f}%"
            return f"capturing {percent:.0f}%"

        if len(self.interesting) < 40:
            self.interesting.append(event)

        if name == "capture.started":
            self.started = event
            self.rle = bool(event.get("rle"))
            return "capture started" + (" (RLE)" if self.rle else "")
        if name == "rle_enabled":
            self.rle = True
            return "RLE enabled by the device"
        if name == "capture.finished":
            self.finished = event
            return "capture finished"
        if name == "idle":
            self.idle = True
            return "idle"
        if name == "error":
            self.error = event
            return "the device reported an error"
        return None

    def directory(self) -> str | None:
        for source in (self.finished, self.started):
            if source and source.get("directory"):
                return str(source["directory"])
        return None

    def summary(self) -> dict:
        return {
            "events": self.counts,
            "progress_events": self.dropped,
            "rle": self.rle,
            "idle": self.idle,
        }


def _parse_json_line(line: str) -> dict | None:
    line = line.strip()
    if not line:
        return None
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


class StreamReader:
    """Line reader with a timeout, so silence can be reported as silence."""

    def __init__(self, stream) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._stream = stream
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        try:
            for line in self._stream:
                self._queue.put(line)
        finally:
            self._queue.put(None)

    def next(self, timeout: float) -> dict | None:
        try:
            line = self._queue.get(timeout=timeout)
        except queue.Empty:
            raise _timeout("the device", timeout)
        if line is None:
            raise SkillError(
                "process_exited",
                "the CLI exited before the capture finished",
                ["run doctor; replug the analyzer if the link dropped"],
            )
        return _parse_json_line(line)


def run_json(
    invocation,
    args: Iterable[str],
    timeout: float = 90.0,
    context: str = "",
) -> dict:
    """Run one control command and return its JSON object."""
    argv = invocation.argv + list(args) + ["--json"]
    sink = _stderr_sink()
    try:
        try:
            completed = subprocess.run(
                argv,
                cwd=invocation.cwd,
                stdout=subprocess.PIPE,
                stderr=sink,
                timeout=timeout,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            raise _timeout(context, timeout)
        objects = [
            obj for obj in (_parse_json_line(line) for line in completed.stdout.splitlines())
            if obj is not None
        ]
    finally:
        tail = _read_tail(sink)
        sink.close()
        try:
            os.unlink(sink.name)
        except OSError:
            pass

    if not objects:
        raise SkillError(
            "invalid_output",
            f"{context or 'the CLI'} returned no JSON (exit {completed.returncode})",
            ["run the same command by hand; stdout must be JSONL"],
            details={"stderr_tail": tail, "exit_code": completed.returncode},
        )
    result = objects[-1]
    result.setdefault("_exit_code", completed.returncode)
    if result.get("ok") is False:
        error = vendor_error(result, context)
        error.details.setdefault("stderr_tail", tail)
        raise error
    result.setdefault("_stderr_tail", tail)
    return result


def _trigger_error(tape: EventTape, trigger_timeout: float) -> SkillError:
    percent = tape.last_percent.get("capture.progress")
    details = {
        "secondsOfSilence": round(trigger_timeout, 1),
        "progressAtStop": percent,
        "events": tape.summary(),
    }
    return SkillError(
        "trigger_not_found",
        "the capture stopped because the trigger never fired "
        f"({trigger_timeout:.0f} s without an event while the device waited)"
        + (f" at {percent:.0f}%" if percent is not None else ""),
        [
            "check the probe, ground and threshold: the line may never reach the trigger condition",
            "use --ch N:none to capture unconditionally, or --ch N:high/--ch N:low for a level trigger",
            "raise --trigger-timeout (or set 0) to wait longer for a real event",
        ],
        retryable=True,
        details=details,
    )


def run_events(
    invocation,
    args: Iterable[str],
    timeout: float = 600.0,
    trigger_timeout: float = 20.0,
    on_event: Callable[[dict], None] | None = None,
    on_prompt: Callable[[str], None] | None = None,
) -> tuple[EventTape, str]:
    """Run ``capture run`` in one process and stream its events into a tape."""
    argv = invocation.argv + list(args) + ["--json"]
    sink = _stderr_sink()
    tape = EventTape()
    deadline = time.monotonic() + timeout
    process = None
    interrupted = False
    stopping = False
    try:
        process = subprocess.Popen(
            argv,
            cwd=invocation.cwd,
            stdout=subprocess.PIPE,
            stderr=sink,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert process.stdout is not None
        reader = StreamReader(process.stdout)
        while True:
            now = time.monotonic()
            if now > deadline:
                if not stopping:
                    # The manual's Ctrl+C behaviour: ask for the default stop
                    # and give the device time to finish and disconnect.
                    stopping = True
                    process.send_signal(getattr(signal, "SIGINT", signal.SIGTERM))
                    deadline = time.monotonic() + 30.0
                    continue
                raise _timeout("capture", timeout)
            wait = deadline - now
            if trigger_timeout:
                wait = min(wait, max(0.5, trigger_timeout - (now - tape.last_event_at)))
            try:
                event = reader.next(wait)
            except SkillError as error:
                if interrupted:
                    break
                if error.code != "timeout" or not trigger_timeout or tape.finished:
                    raise
                # No event for a whole trigger timeout: ask the CLI to stop the
                # way Ctrl+C would, then read whatever it salvaged.
                interrupted = True
                process.send_signal(getattr(signal, "SIGINT", signal.SIGTERM))
                continue
            if event is None:
                continue
            prompt = tape.feed(event)
            if event.get("ok") is False and event.get("error"):
                tape.error = event
            if on_event:
                on_event(event)
            if prompt and on_prompt:
                on_prompt(prompt)
            if tape.idle:
                break
        try:
            process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            process.terminate()
    finally:
        tail = _read_tail(sink)
        sink.close()
        try:
            os.unlink(sink.name)
        except OSError:
            pass
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
            try:
                process.stdout.close()
            except (OSError, ValueError):
                pass
    if tape.error:
        error = vendor_error(tape.error, "capture")
        error.details.setdefault("stderr_tail", tail)
        raise error
    if interrupted:
        raise _trigger_error(tape, trigger_timeout)
    if not tape.finished or not tape.idle:
        raise SkillError(
            "capture_incomplete",
            "the capture stream ended before the device reported idle",
            ["keep the .bin.partial files and read capture.json before retrying"],
            retryable=True,
            details={"tape": tape.summary(), "stderr_tail": tail},
        )
    return tape, tail


class Session:
    """A ``session --stdio --mode ai`` process with request/response matching."""

    def __init__(self, invocation, response_timeout: float = 120.0) -> None:
        self.invocation = invocation
        self.response_timeout = response_timeout
        self._counter = 0
        self._sink = _stderr_sink()
        self.process = subprocess.Popen(
            invocation.argv + ["session", "--stdio", "--mode", "ai"],
            cwd=invocation.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._sink,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert self.process.stdout is not None
        self._reader = StreamReader(self.process.stdout)

    # ------------------------------------------------------------------ io
    def next_id(self) -> str:
        self._counter += 1
        return f"req-{self._counter}"

    def send(self, request_id: str, method: str, params: dict | None = None) -> None:
        line = json.dumps({"id": request_id, "method": method, "params": params or {}})
        assert self.process.stdin is not None
        try:
            self.process.stdin.write(line + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, ValueError):
            raise SkillError(
                "process_exited",
                "the CLI session is no longer accepting requests",
                details={"stderr_tail": self.stderr_tail()},
            )

    def request(self, method: str, params: dict | None = None, timeout: float | None = None):
        request_id = self.next_id()
        self.send(request_id, method, params)
        deadline = time.monotonic() + (timeout or self.response_timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _timeout(method, timeout or self.response_timeout)
            event = self._reader.next(remaining)
            if event is None:
                continue
            if event.get("id") == request_id:
                if event.get("ok") is False:
                    raise vendor_error(event, method)
                return event

    def capture(self, params: dict, trigger_timeout: float = 20.0,
                on_prompt: Callable[[str], None] | None = None,
                on_event: Callable[[dict], None] | None = None,
                timeout: float = 600.0) -> tuple[EventTape, dict]:
        """Submit ``capture.run`` and consume events until ``idle``."""
        request_id = self.next_id()
        self.send(request_id, "capture.run", params)
        tape = EventTape()
        accepted: dict = {}
        deadline = time.monotonic() + timeout
        while True:
            now = time.monotonic()
            if now > deadline:
                self.stop()
                raise _timeout("capture", timeout)
            wait = deadline - now
            if trigger_timeout:
                wait = min(wait, max(0.5, trigger_timeout - (now - tape.last_event_at)))
            try:
                event = self._reader.next(wait)
            except SkillError as error:
                if error.code != "timeout" or not trigger_timeout:
                    raise
                if tape.finished:
                    raise
                # Silence while the buffer waits for the trigger: stop politely
                # and report the partial capture instead of waiting forever.
                self.stop()
                self._drain_after_stop()
                raise _trigger_error(tape, trigger_timeout)
            if event is None:
                continue
            if event.get("id") == request_id:
                if event.get("ok") is False:
                    raise vendor_error(event, "capture.run")
                accepted = event
                continue
            prompt = tape.feed(event)
            if on_event:
                on_event(event)
            if prompt and on_prompt:
                on_prompt(prompt)
            if event.get("event") == "error":
                tape.error = event
                break
            if tape.idle:
                break
        if tape.error:
            raise vendor_error(tape.error, "capture")
        return tape, accepted

    def _drain_after_stop(self, timeout: float = 15.0) -> None:
        """Wait for idle with ``capture.status``; events after a stop are optional."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                status = self.request("capture.status", timeout=5)
            except SkillError:
                return
            if status.get("state") == "idle":
                return
            time.sleep(0.2)

    def status(self) -> dict:
        return self.request("capture.status")

    def stop(self, immediate: bool = False) -> dict:
        try:
            return self.request("capture.stop", {"immediate": immediate}, timeout=30)
        except SkillError:
            return {}

    def stderr_tail(self) -> str:
        return _read_tail(self._sink)

    def close(self, wait: float = 60.0) -> None:
        """``session.close``, then let the process exit on its own."""
        try:
            if self.process.poll() is None:
                self.request("session.close", timeout=30)
        except SkillError:
            pass
        try:
            self.process.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
        finally:
            for stream in (self.process.stdin, self.process.stdout):
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass
            self._sink.close()
            try:
                os.unlink(self._sink.name)
            except OSError:
                pass

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            try:
                self.stop()
            except Exception:  # noqa: BLE001 - never mask the original failure
                pass
        self.close()
