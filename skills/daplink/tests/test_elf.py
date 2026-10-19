from types import SimpleNamespace

import pytest


def test_symbols_and_lines(fake):
    ei = fake.ei
    assert "main" in ei.symbols and "add" in ei.symbols
    assert ei.frame_name(ei.symbols["main"]) == "main"
    line = ei.line_for(ei.symbols["main"])
    assert line is not None
    assert line[0].endswith("fixture.c")
    assert line[1] > 0


def test_frame_offset(fake):
    ei = fake.ei
    addr = ei.symbols["main"] + 4
    assert ei.frame_name(addr).startswith("main+0x4")


def test_exec_ranges(fake):
    ei = fake.ei
    assert ei.in_code(ei.symbols["main"])
    assert not ei.in_code(0x28000000)


def test_resolve_addr(fake):
    dap, ei = fake.dap, fake.ei
    ns = SimpleNamespace(elf=str(fake.elf))
    assert dap.resolve_addr(ns, "main") == ei.symbols["main"]
    assert dap.resolve_addr(ns, "0x1000") == 0x1000


def test_resolve_unknown_symbol_exits(fake):
    dap = fake.dap
    ns = SimpleNamespace(elf=str(fake.elf))
    with pytest.raises(SystemExit):
        dap.resolve_addr(ns, "definitely_not_a_symbol")
