import pytest

from scopescpi.uncertainty import from_instrument, from_waveform


def test_voltage_from_waveform_is_bounded_by_the_adc_code():
    found = from_waveform("vpp", 1.04, {"yincr": 0.02, "xincr": 5e-7})
    assert (found.unit, found.source) == ("V", "waveform")
    assert found.resolution == pytest.approx(0.02)
    assert found.uncertainty == pytest.approx(0.02)
    assert found.as_dict()["basis"] == "ADC code width"


def test_averaged_voltage_uses_quantisation_noise():
    found = from_waveform("mean", 3.3, {"yincr": 0.02})
    assert found.uncertainty == pytest.approx(0.02 / 12 ** 0.5)


def test_time_from_waveform_is_one_sample_interval():
    found = from_waveform("pulse_width", 350e-6, {"xincr": 5e-7})
    assert found.unit == "s"
    assert found.uncertainty == pytest.approx(5e-7)


def test_frequency_uncertainty_follows_f_squared_dt():
    found = from_waveform("freq", 5000.0, {"xincr": 5e-7})
    assert found.uncertainty == pytest.approx(5000 ** 2 * 5e-7)


def test_instrument_values_do_not_invent_an_accuracy():
    found = from_instrument("vpp", 1.04)
    assert found.source == "instrument"
    assert found.uncertainty is None
    assert found.unit == "V"
