import pytest

FAMILIES = {
    "RIGOL TECHNOLOGIES,DP832,SN,1.0": "rigol",
    "Keysight Technologies,E36312A,SN,1.0": "keysight",
    "Siglent Technologies,SPD3303X,SN,1.0": "siglent",
    "Rohde&Schwarz,HMC8043,SN,1.0": "rns",
    "KORAD,KA3005P,SN,1.0": "korad",
    "GW INSTEK,GPP-3323,SN,1.0": "gwinstek",
    "B&K PRECISION,9130B,SN,1.0": "bkprecision",
    "ITECH,IT6302,SN,1.0": "itech",
    "OWON,SPE3103,SN,1.0": "owon",
    "AIM-TTI,PL303QMD,SN,1.0": "aimtti",
    "ACME,PSU-1,SN,1.0": "generic",
}


@pytest.mark.parametrize("idn,family", FAMILIES.items())
def test_detect(module, idn, family):
    assert module.detect_family(idn) == family


def test_korad_commands(module):
    d = module.Korad()
    assert d.set_voltage(1, 5) == "VSET1:5.00"
    assert d.set_current(1, 1) == "ISET1:1.000"
    assert d.measure_voltage(1) == "VOUT1?"
    assert d.output(1, True) == "OUT1"
    assert d.output(1, False) == "OUT0"


def test_siglent_commands(module):
    d = module.SiglentSpd()
    assert d.set_voltage(2, 12) == ":CH2:VOLT 12"
    assert d.output(2, True) == ":OUTP CH2,ON"
    assert d.measure_voltage(2) == ":MEAS:VOLT? CH2"


def test_keysight_selection(module):
    d = module.KeysightE36xx()
    assert d.select(2) == ":INSTrument:NSELect 2"
    assert d.measure_current(1) == ":MEASure:CURRent?"


def test_rns_output(module):
    d = module.RnsHmc()
    assert d.output(3, True) == ":OUTPut:CHANnel3:STATe ON"
    assert d.output_state(3) == ":OUTPut:CHANnel3:STATe?"


def test_itech_commands(module):
    d = module.Itech()
    assert d.select(2) == ":INSTrument:NSELect 2"
    assert d.set_voltage(2, 5) == ":VOLTage 5"
    assert d.output(2, True) == ":OUTPut ON"
    assert d.measure_power(2) == ":MEASure:POWer?"
    assert d.ovp(2, 6) == ":VOLTage:PROTection 6;:VOLTage:PROTection:STATe ON"
    assert d.ocp(2, 1.5) is None


def test_limits_are_model_independent(module):
    for cls in (module.RigolDp800, module.KeysightE36xx, module.SiglentSpd,
                module.Korad, module.Generic):
        d = cls()
        assert d.channels
        assert d.set_voltage(d.channels[0], 1)
