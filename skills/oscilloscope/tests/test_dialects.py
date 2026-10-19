import pytest

NEW_BRANDS = {
    "OWON,XDS3104,SN,1.0": "owon",
    "HANMATEK,DOS1104,SN,V1.2.0": "owon",
    "HANTEK,DSO2C50,SN,1.0.8": "hantek",
    "MICSIG,MHO14-200N,SN,1.143": "micsig",
    "B&K PRECISION,2560,SN,1.0": "bkprecision",
    "UNI-T,UPO1054,SN,1.0": "unit",
    "FLUKE,190-504,SN,1.0": "fluke",
    "ZLG,ZDS1104,SN,1.0": "zlg",
    "PEAKTECH,1330,SN,1.0": "peaktech",
    "ATTEN,ADS1102,SN,1.0": "atten",
}


@pytest.mark.parametrize("idn,family", NEW_BRANDS.items())
def test_detect_new_brands(scope, idn, family):
    assert scope.detect_family(idn) == family


def test_owon_commands(scope):
    d = scope.OwonDialect("OWON")
    assert d.channel_scale(1, 0.5) == ":CH1:SCAL 0.5"
    assert d.channel_offset(2, -1) == ":CH2:OFFS -1"
    assert d.timebase_scale(1e-3) == ":HORIzontal:Scale 0.001"
    assert d.trigger_source(1) == ":TRIGger:SINGle:SOURce CH1"
    assert d.run() == ":RUNning RUN"
    assert d.measure_query("vpp", 1) == ":MEAS:CH1:PKPK?"
    assert d.clean("Vpp : 2.040V->") == "Vpp : 2.040V"
    assert d.parse_measure("Vpp : 2.040V->") == pytest.approx(2.04)
    assert d.parse_measure("F : 1.000kHz->") == pytest.approx(1000)


def test_micsig_commands(scope):
    d = scope.MicsigDialect("MICSIG")
    assert d.run() == ":MENU:RUN"
    assert d.stop() == ":MENU:STOP"
    assert d.single() == ":MENU:SINGLE"
    assert d.measure_query("vpp", 2) == ":MEASure:PKPK? CH2"
    assert d.screenshot_queries() == [":SYS:SCR?"]


def test_hantek_commands(scope):
    d = scope.HantekDialect("HANTEK")
    assert d.measure_query("vpp", 1) == ":MEASure:CHANnel1:ITEM? VPP"
    assert d.trigger_slope("rising") == ":TRIGger:EDGe:SLOPe RISIng"
    assert d.state_queries() == [":TRIGger:STATus?"]


def test_bk_commands(scope):
    d = scope.BkPrecisionDialect("B&K")
    assert d.channel_scale(1, 0.5) == "C1:VDIV 0.5"
    assert d.timebase_scale(1e-3) == "TDIV 0.001"
    assert d.trigger_sweep("NORMAL") == "TRMD NORM"
    assert d.measure_query("vpp", 2) == "C2:PAVA? VPP"
    assert d.arm_single() == ["TRMD SINGLE"]


def test_unit_commands(scope):
    d = scope.UnitDialect("UNI-T")
    assert d.channel_scale(1, 0.5) == ":CHAN1:SCAL 0.5"
    assert d.timebase_scale(1e-3) == ":TIMebase:SCALe 0.001"
    assert d.trigger_source(2) == ":TRIGger:SOURce CHAN2"
    assert d.measure_query("vpp", 1) == ":MEASure:VPP? CHAN1"
    assert d.arm_single() == [":TRIGger:SWEep SINGle", ":RUN"]


def test_micsig_preamble_and_commands(scope):
    d = scope.MicsigDialect("MICSIG")
    meta = d.parse_preamble("0,0,100,1e-06,-5e-05,0,0.01,0,50")
    assert meta["points"] == 100
    assert meta["xincr"] == pytest.approx(1e-6)
    assert meta["yincr"] == pytest.approx(0.01)
    assert d.timebase_scale(1e-3) == ":TIMebase:EXTent 0.001"
    assert d.trigger_slope("rising") == ":TRIGger:EDGE:SLOPe RISE"


def test_peaktech_is_owon(scope):
    d = scope.PeakTechDialect("PEAKTECH")
    assert d.run() == ":RUNning RUN"
    assert d.measure_query("vpp", 1) == ":MEAS:CH1:PKPK?"


def test_fluke_commands(scope):
    d = scope.FlukeDialect("FLUKE")
    assert d.channel_display(1, True) == 'SENSe:FUNCtion:ON "XTIMe:VOLTage1"'
    assert d.timebase_scale(1e-3) == "SENSe:SWEep:TIME 0.001"
    assert d.trigger_source(2) == "TRIGger:SOURce INTernal2"


@pytest.mark.parametrize("cls", ["HantekDialect", "BkPrecisionDialect", "FlukeDialect",
                                 "LeCroyDialect", "RnsDialect", "GwInstekDialect",
                                 "YokogawaDialect", "ZlgDialect", "AttenDialect"])
def test_unsupported_capture_raises(scope, cls):
    d = getattr(scope, cls)("X")
    with pytest.raises(RuntimeError):
        d.acquire(None, 1, None)


def test_micsig_acquire(scope, micsig):
    inst = scope.SocketInstrument("127.0.0.1", micsig.port, timeout=2)
    try:
        data = scope.acquire_channels(inst, scope.MicsigDialect(micsig.idn), [1], None)
    finally:
        inst.close()
    assert len(data[1]["volts"]) == 100
    assert data[1]["volts"][0] == pytest.approx(0)
    assert data[1]["times"][1] - data[1]["times"][0] == pytest.approx(1e-6)


def test_unit_acquire(scope, rigol):
    inst = scope.SocketInstrument("127.0.0.1", rigol.port, timeout=2)
    try:
        data = scope.acquire_channels(inst, scope.UnitDialect("UNI-T"), [1], None)
    finally:
        inst.close()
    assert data[1]["volts"][0] == pytest.approx(-0.5)
    assert data[1]["volts"][-1] == pytest.approx(0.49)
