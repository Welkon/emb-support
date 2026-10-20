import pytest

from scopescpi.transport import VisaInstrument


class TimeoutInstrument:
    def __init__(self):
        self.cleared = 0

    def query(self, cmd):
        raise TimeoutError("VI_ERROR_TMO (-1073807339): Timeout expired before operation completed.")

    def clear(self):
        self.cleared += 1

    def close(self):
        pass


def test_query_timeout_reports_unsupported_command():
    """Rigol DS1000Z does not answer :SYSTem:ERRor?; that must not surface as a
    pyvisa traceback."""
    inst = object.__new__(VisaInstrument)
    inst.inst = TimeoutInstrument()

    with pytest.raises(RuntimeError) as exc:
        inst.query(":SYSTem:ERRor?")

    message = str(exc.value)
    assert ":SYSTem:ERRor?" in message
    assert "--timeout" in message
    assert "scpi --write" in message
    assert inst.inst.cleared == 1, "a failed read must clear the queue"


class EmptyDialect:
    """A channel that exists but transfers no samples."""

    def acquire(self, inst, ch, points):
        return {"xincr": 1e-6, "yincr": 1.0, "yorig": 0.0, "yref": 0.0, "points": 0}, b""


def test_empty_capture_is_an_error_not_an_empty_list(scope):
    with pytest.raises(RuntimeError) as exc:
        scope.acquire_channels(object(), EmptyDialect(), [1], 100)
    message = str(exc.value)
    assert "no samples" in message and "--points" in message
