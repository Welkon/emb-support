import pytest


def snapshot(dap, **over):
    snap = {
        "target": "FAKE", "state": "HALTED", "halt_reason": "VECTOR_CATCH",
        "registers": {"pc": 0x08000100, "lr": 0x08000101, "sp": 0x20008000},
        "fault": {"CFSR": 0, "HFSR": 0, "BFAR": 0, "MMFAR": 0},
        "stack": {"initial_sp": 0x20008000, "sp": 0x20008000, "used": 0},
        "exception_frame": None, "backtrace": [],
        "regions": [
            {"name": "FLASH", "start": 0x08000000, "end": 0x08040000, "type": "FLASH"},
            {"name": "RAM", "start": 0x20000000, "end": 0x20005000, "type": "RAM"},
            {"name": "PERIPH", "start": 0x40000000, "end": 0x40030000, "type": "DEVICE"},
        ],
        "disasm": [], "stack_words": [],
    }
    snap.update(over)
    return snap


def causes(hyps):
    return " | ".join(h["cause"] for h in hyps)


def test_null_pointer_and_precise_bus_fault(dap):
    snap = snapshot(dap, fault={"CFSR": (1 << 9) | (1 << 15), "HFSR": 1 << 30,
                                "BFAR": 4, "MMFAR": 0})
    hyps = dap.analyze_fault(snap)
    text = causes(hyps)
    assert "near NULL" in text
    assert any("BFAR=0x00000004" in e for h in hyps for e in h["evidence"])
    assert any(h["score"] >= 0.9 for h in hyps)
    assert hyps == sorted(hyps, key=lambda h: -h["score"])


def test_peripheral_address_classified(dap):
    snap = snapshot(dap, fault={"CFSR": (1 << 15), "HFSR": 0, "BFAR": 0x40021000, "MMFAR": 0})
    text = causes(dap.analyze_fault(snap))
    assert "peripheral" in text.lower()


def test_pc_outside_code(dap, fake):
    snap = snapshot(dap, registers={"pc": 0x20000100, "lr": 0, "sp": 0x20008000})
    text = causes(dap.analyze_fault(snap, fake.ei))
    assert "outside every executable segment" in text


def test_stack_overflow(dap):
    snap = snapshot(dap, stack={"initial_sp": 0x20008000, "sp": 0x1FFFFFF0,
                                "used": 0x8010, "overflow": True})
    text = causes(dap.analyze_fault(snap))
    assert "stack overflow" in text.lower()


def test_imprecise_bus_fault_has_own_hypothesis(dap):
    snap = snapshot(dap, fault={"CFSR": 1 << 10, "HFSR": 0, "BFAR": 0, "MMFAR": 0})
    text = causes(dap.analyze_fault(snap))
    assert "imprecise" in text.lower()
    # must not be duplicated by the generic bit loop
    assert text.lower().count("imprecise bus error") == 1


def test_no_flags_reports_unknown(dap):
    text = causes(dap.analyze_fault(snapshot(dap)))
    assert "no definitive fault flag" in text


def test_exception_frame_symbol(dap, fake):
    snap = snapshot(dap, exception_frame={"sp_used": "MSP", "faulting_pc": hex(fake.ei.symbols["main"]),
                                          "faulting_lr": "0x0"})
    text = causes(dap.analyze_fault(snap, fake.ei))
    assert "fault site: main" in text


def test_fault_bit_decode(dap):
    assert any("DIVBYZERO" in x for x in dap.decode_faults({"CFSR": 1 << 25, "HFSR": 0}))
    assert any("FORCED" in x for x in dap.decode_faults({"CFSR": 0, "HFSR": 1 << 30}))


def test_classify_address(dap):
    regions = snapshot(dap)["regions"]
    assert "near NULL" in dap._classify_addr(0x8, regions)
    assert "RAM" in dap._classify_addr(0x20001000, regions)
    assert "peripheral" in dap._classify_addr(0x40021000, regions).lower()
    assert "Flash" in dap._classify_addr(0x08001000, regions)


@pytest.mark.parametrize("bit,expect", [("VECTTBL", True), ("DEBUGEVT", False)])
def test_bit_active(dap, bit, expect):
    fault = {"CFSR": 0, "HFSR": 1 << 1}
    assert dap._bit_active(bit, fault) is expect
