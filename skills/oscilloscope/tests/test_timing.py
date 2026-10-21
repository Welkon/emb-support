import pytest

from scopescpi.timing import channel_timing, edge_times


def square(period=1e-3, duty=0.5, shift=0.0, n=3000, dt=1e-6, high=3.3):
    times = [i * dt for i in range(n)]
    volts = [high if ((t - shift) % period) < duty * period else 0.0 for t in times]
    return {"times": times, "volts": volts}


def test_rising_edge_delay_and_skew():
    result = channel_timing(square(), square(shift=250e-6))
    assert result["pairs"] >= 2
    assert result["delay"] == pytest.approx(250e-6, abs=2e-6)
    assert result["skew"] == pytest.approx(0, abs=2e-6)
    assert result["jitter_peak_to_peak"] == pytest.approx(0, abs=2e-6)


def test_a_leading_channel_gives_a_negative_delay():
    result = channel_timing(square(), square(shift=-250e-6))
    assert result["delay"] == pytest.approx(-250e-6, abs=2e-6)


def test_falling_edges_are_selectable():
    result = channel_timing(square(), square(shift=250e-6), "falling", "falling")
    assert result["delay"] == pytest.approx(250e-6, abs=2e-6)


def test_edge_times_are_interpolated_at_mid_level():
    times = [0.0, 1e-6, 2e-6, 3e-6]
    volts = [0.0, 1.65, 3.3, 3.3]
    assert edge_times(times, volts)[0] == pytest.approx(1e-6, abs=1e-9)
