

def snapshot(dap):
    return {
        "captured_at": "2026-01-01T00:00:00", "elf": None, "target": "FAKE",
        "state": "HALTED", "halt_reason": "VECTOR_CATCH",
        "registers": {"pc": 0x08000100, "lr": 0x08000101, "sp": 0x20008000},
        "fault": {"CFSR": 1 << 9, "HFSR": 1 << 30, "BFAR": 4, "MMFAR": 0},
        "stack": {"initial_sp": 0x20008000, "sp": 0x20008000, "used": 0},
        "exception_frame": {"sp_used": "MSP", "faulting_pc": "0x08000100", "faulting_lr": "0x0"},
        "backtrace": [{"pc": 0x08000100, "symbol": "main", "via": "cfi", "exact": True}],
        "regions": [{"name": "FLASH", "start": 0x08000000, "end": 0x08040000, "type": "FLASH"}],
        "disasm": [{"addr": 0x08000100, "bytes": "00bf", "mnemonic": "nop", "op_str": ""}],
        "stack_words": [{"addr": 0x20008000, "value": 0}],
        "fault_pc": 0x08000100,
    }


def hypothesis(dap, cause="boom"):
    return [{"score": 0.9, "category": "pc", "cause": cause,
             "evidence": ["evidence-line"], "next": ["next-step"]}]


def test_text_report(dap):
    text = dap.render_fault_text(snapshot(dap), hypothesis(dap), None)
    assert "Fault diagnosis" in text
    assert "boom" in text
    assert "Backtrace" in text
    assert "main" in text


def test_html_report_sections(dap, tmp_path):
    out = tmp_path / "report.html"
    dap.render_fault_html(snapshot(dap), hypothesis(dap), out)
    html = out.read_text()
    for section in ("Fault report", "Root causes", "Backtrace", "Core registers",
                    "Fault flags", "Address space", "Disassembly at fault"):
        assert section in html
    assert "{bt_rows" not in html and "{cards}" not in html


def test_html_escapes_injection(dap, tmp_path):
    out = tmp_path / "report.html"
    dap.render_fault_html(snapshot(dap), hypothesis(dap, "<script>alert(1)</script>"), out)
    html = out.read_text()
    assert "&lt;script&gt;" in html
    assert "<script>alert(1)" not in html


def test_text_report_without_backtrace(dap):
    snap = snapshot(dap)
    snap["backtrace"] = []
    text = dap.render_fault_text(snap, hypothesis(dap), None)
    assert "Fault diagnosis" in text
