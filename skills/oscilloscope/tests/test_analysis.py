import math

import pytest


def test_spectrum_peak(scope):
    pytest.importorskip("numpy")
    dt = 1e-4
    volts = [math.sin(2 * math.pi * 1000 * i * dt) for i in range(1000)]
    out = scope.spectrum(volts, dt)
    assert out["fundamental_hz"] == pytest.approx(1000, rel=0.02)
    assert out["thd_pct"] < 1.0


def test_advanced_overshoot(scope):
    # 0 V low, a 2.2 V overshoot, then a 2.0 V settled high level
    volts = [0.0] * 100 + [2.2, 2.2] + [2.0] * 100 + [0.0] * 100
    times = [i * 1e-6 for i in range(len(volts))]
    out = scope.advanced(volts, times)
    assert out["overshoot_pct"] > 5
    assert out["noise_rms"] > 0


def test_write_svg(scope, tmp_path):
    volts = [math.sin(2 * math.pi * i / 100) for i in range(500)]
    times = [i * 1e-6 for i in range(500)]
    out = tmp_path / "wave.svg"
    scope.write_svg(out, times, volts, title="test", extra={"fundamental_hz": 1000})
    text = out.read_text()
    assert "<svg" in text and "<polyline" in text and "Vpp" in text


def test_npz_roundtrip(scope, tmp_path):
    pytest.importorskip("numpy")
    data = {1: {"times": [0.0, 1e-6], "volts": [0.0, 1.0], "meta": {}}}
    path = tmp_path / "cap.npz"
    scope.save_npz(path, data)
    loaded = scope.load_npz(path)
    assert loaded["1"]["volts"] == [0.0, 1.0]


def test_classify_square_sine_triangle(scope):
    import math
    n = 2000
    dt = 1e-5
    ts = [i * dt for i in range(n)]
    square = [1.0 if (i // 50) % 2 == 0 else -1.0 for i in range(n)]
    sine = [math.sin(2 * math.pi * 100 * t) for t in ts]
    triangle = [4 * abs(((100 * t) % 1) - 0.5) - 1 for t in ts]
    for waves, want in ((square, "square"), (sine, "sine"), (triangle, "triangle")):
        st = scope.stats(waves, ts)
        an = scope.advanced(waves, ts, {"xincr": dt})
        got = scope.classify(waves, ts, st, an)["type"]
        assert got == want, (want, got, an.get("thd_pct"))


def test_classify_dc(scope):
    assert scope.classify([1.0] * 100, [i * 1e-6 for i in range(100)], {}, {})["type"] == "dc"
