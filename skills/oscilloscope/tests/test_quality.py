import math

import pytest


def wave(freq=10.0, n=1000, dt=1e-3, amp=1.0, offset=0.0, clip=None):
    ts = [i * dt for i in range(n)]
    if clip is None:
        vs = [offset + amp * math.sin(2 * math.pi * freq * t) for t in ts]
    else:
        vs = [max(-clip, min(clip, offset + amp * math.sin(2 * math.pi * freq * t))) for t in ts]
    return vs, ts


def codes(warnings):
    return {w["code"] for w in warnings}


def test_flat(scope):
    w = scope.check_quality([0.0] * 100, [i * 1e-6 for i in range(100)],
                            {"yincr": 0.01, "xincr": 1e-6})
    assert "FLAT" in codes(w)


def test_empty(scope):
    assert "EMPTY" in codes(scope.check_quality([], []))


def test_clipping(scope):
    vs, ts = wave(freq=10, clip=0.5, amp=1.0)
    w = scope.check_quality(vs, ts, {"yincr": 0.01, "xincr": 1e-3})
    assert "CLIPPING" in codes(w)


def test_square_is_not_clipping(scope):
    vs = [1.0 if i % 20 < 10 else -1.0 for i in range(1000)]
    ts = [i * 1e-3 for i in range(1000)]
    w = scope.check_quality(vs, ts, {"yincr": 0.01, "xincr": 1e-3})
    assert "CLIPPING" not in codes(w)


def test_dc_offset(scope):
    vs, ts = wave(amp=0.1, offset=1.0)
    w = scope.check_quality(vs, ts, {"yincr": 0.001, "xincr": 1e-3})
    assert "DC_OFFSET" in codes(w)


def test_low_resolution(scope):
    vs, ts = wave(amp=0.005, offset=0.0)
    w = scope.check_quality(vs, ts, {"yincr": 0.001, "xincr": 1e-3})
    assert "LOW_RESOLUTION" in codes(w)


def test_aliasing_near_nyquist(scope):
    vs, ts = wave(freq=480, dt=1e-3, n=2000)
    w = scope.check_quality(vs, ts, {"yincr": 0.01, "xincr": 1e-3})
    assert "ALIASING" in codes(w)


def test_edges_ignore_preexisting_drift(scope):
    v = [-0.2] * 100 + [0.0, -0.2] + [4.6] * 100 + [-0.2] * 100
    t = [i * 1e-6 for i in range(len(v))]
    out = scope._edges(v, t, min(v), max(v))
    assert out["rise_time"] < 1e-5
    assert out["fall_time"] < 1e-5


def test_recovery_retries(scope):
    class Inst:
        def __init__(self):
            self.writes = []
            self.queries = []

        def query(self, cmd):
            self.queries.append(cmd)
            return "1"

        def write(self, cmd):
            self.writes.append(cmd)

    class Flaky(scope.Dialect):
        name = "flaky"

        def __init__(self):
            super().__init__("FLAKY")
            self.calls = 0

        def acquire(self, inst, ch, points):
            self.calls += 1
            if self.calls < 2:
                raise RuntimeError("no frame")
            return ({"xincr": 1e-6, "xorig": 0, "xref": 0, "yincr": 1.0,
                     "yorig": 0.0, "yref": 0, "points": 2}, [0, 1])

    inst = Inst()
    data, log = scope.acquire_with_recovery(inst, Flaky(), [1], None, attempts=3)
    assert len(data[1]["volts"]) == 2
    assert log and log[0]["recovery"] == "wait-opc"
    assert "*OPC?" in inst.queries


def test_recovery_exhausted_raises(scope):
    class Inst:
        def query(self, cmd):
            return "1"

        def write(self, cmd):
            pass

    class Dead(scope.Dialect):
        name = "dead"

        def acquire(self, inst, ch, points):
            raise RuntimeError("no frame")

    with pytest.raises(RuntimeError):
        scope.acquire_with_recovery(Inst(), Dead("X"), [1], None, attempts=2)
