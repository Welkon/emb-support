from types import SimpleNamespace


def test_exec_on_hit_print_and_continue(fake, capsys):
    dap = fake.dap
    dr = dap.DwarfReader(fake.path)
    fake.target.regs["r0"] = 0x2A
    cont, lines = dap._exec_on_hit(fake.target, "print r0; continue", fake.ei, dr, fake.mem.read)
    assert cont is True
    assert lines == ["42"]


def test_exec_on_hit_bt(fake):
    dap = fake.dap
    dr = dap.DwarfReader(fake.path)
    cont, lines = dap._exec_on_hit(fake.target, "bt; stop", fake.ei, dr, fake.mem.read)
    assert cont is False
    assert lines and lines[0].startswith("#0")


def test_exec_on_hit_unknown_command(fake):
    dap = fake.dap
    cont, lines = dap._exec_on_hit(fake.target, "explode", fake.ei, None, fake.mem.read)
    assert cont is False
    assert "unknown on-hit" in lines[0]


def test_bp_set_stores_on_hit(fake, iso):
    dap = fake.dap
    ns = SimpleNamespace(elf=str(fake.elf), target=None, probe=None, frequency=None, pack=None,
                         core=None, engine="pyocd", chip=None, connect=None, timeout=5,
                         bp_cmd="set", addr="main", type="hw", yes=False, all=False,
                         wait=None, cond=None, log=None, max_hits=None, on_hit="print r0")
    dap.cmd_bp(ns)
    reg = dap._bp_load()
    assert reg and reg[0]["on_hit"] == "print r0"
