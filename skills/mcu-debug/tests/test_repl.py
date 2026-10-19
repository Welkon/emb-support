from types import SimpleNamespace


def repl(dap, fake, commands):
    ns = SimpleNamespace(elf=str(fake.elf), target=None, probe=None, frequency=None,
                         pack=None, core=None, timeout=5, json=False, cmd=commands)
    dap.cmd_repl(ns)


def test_repl_core_commands(fake, capsys):
    dap, ei = fake.dap, fake.ei
    dr = dap.DwarfReader(fake.path)
    g_counter_addr = dr.globals_env()["g_counter"][2]
    repl(dap, fake, [
        "status",
        "p g_counter",
        "p g_pt.x + 1",
        "bt",
        "bp main",
        "bp list",
        f"x {g_counter_addr:#x} 8",
        "regs r0=1",
        "help",
        "quit",
        "p 1",
    ])
    out = capsys.readouterr().out
    assert "pc=0x" in out and "main" in out
    assert "\n7\n" in out
    assert "\n4\n" in out
    assert "via cfi" in out
    assert "breakpoint at" in out
    assert f"{ei.symbols['main']:#010x}" in out
    assert "07 00 00 00" in out
    assert "r0 <- 0x1" in out
    assert "commands:" in out
    # commands after quit must not execute
    assert "\n1\n" not in out.split("commands:")[-1].split("quit")[-1]


def test_repl_unknown_command(fake, capsys):
    repl(fake.dap, fake, ["nope"])
    assert "unknown command" in capsys.readouterr().out


def test_repl_source_file(fake, capsys, tmp_path):
    script = tmp_path / "cmds.txt"
    script.write_text("p g_pt.y\n")
    repl(fake.dap, fake, [f"source {script}"])
    assert capsys.readouterr().out.strip().endswith("4")


def test_repl_error_does_not_kill_session(fake, capsys):
    repl(fake.dap, fake, ["bp definitely_not_a_symbol", "p g_counter"])
    out = capsys.readouterr().out
    assert "error" in out
    assert "\n7\n" in out
