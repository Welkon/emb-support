"""One session per intent, with reconnect-and-retry in one place.

Verbs used to call `connect()` themselves, and a few grew their own recovery
code. This proxy owns the session instead: a dead USB handle is reopened once
per operation, so every verb gets the same guarantee without repeating it.
"""

from __future__ import annotations

from .transport import connect

_DEAD_SESSION = (
    "invalid session", "invalid handle", "session handle", "vi_error",
    "timed out", "timeout", "closed", "broken pipe", "connection reset",
)


def dead_session(exc: BaseException) -> bool:
    """True when the instrument handle is gone, not when a command was refused."""
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in text for marker in _DEAD_SESSION)


class Session:
    """Instrument proxy: one connection, reopened at most a few times."""

    def __init__(self, args):
        self.args = args
        self.reconnects = 0
        self.inst = connect(args)

    # -- transport -----------------------------------------------------
    def _reopen(self) -> None:
        try:
            self.inst.close()
        except Exception:  # noqa: BLE001
            pass
        self.inst = connect(self.args)
        self.reconnects += 1

    def _call(self, name: str, *args, **kwargs):
        try:
            return getattr(self.inst, name)(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            if not dead_session(exc) or self.reconnects >= 3:
                raise
            self._reopen()
            return getattr(self.inst, name)(*args, **kwargs)

    def write(self, cmd: str) -> None:
        return self._call("write", cmd)

    def query(self, cmd: str) -> str:
        return self._call("query", cmd)

    def query_block(self, cmd: str) -> bytes:
        return self._call("query_block", cmd)

    def query_prefixed(self, cmd: str) -> bytes:
        return self._call("query_prefixed", cmd)

    def read_message(self, cmd: str) -> bytes:
        return self._call("read_message", cmd)

    def close(self) -> None:
        try:
            self.inst.close()
        except Exception:  # noqa: BLE001
            pass

    # -- identity (resource/host/path used by the transport) ------------
    def __getattr__(self, name: str):
        if name == "inst":
            raise AttributeError(name)
        return getattr(self.inst, name)
