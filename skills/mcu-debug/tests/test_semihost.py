from types import SimpleNamespace


def semi_args(**over):
    base = dict(duration=0.5, elf=None, target=None, probe=None, frequency=None,
                pack=None, core=None, engine="pyocd", chip=None, connect=None,
                timeout=5, sdk=None)
    base.update(over)
    return SimpleNamespace(**base)


def test_semihost_write0(fake, capsys, monkeypatch):
    dap, t, mem = fake.dap, fake.target, fake.mem
    pc = t.regs["pc"]
    mem.write(pc, b"\xab\xbe")                      # BKPT #0xAB
    mem.write(0xE000ED30, (0b10).to_bytes(4, "little"))   # DFSR.BKPT
    text = 0x28001000
    mem.write(text, b"hello semihost\x00")
    t.regs["r0"] = 0x04                            # SYS_WRITE0
    t.regs["r1"] = text
    # resume() returns to the halt immediately so the agent processes one request
    monkeypatch.setattr(t, "resume", lambda: setattr(t, "state", "HALTED"))

    dap.cmd_semi(semi_args())
    out = capsys.readouterr().out
    assert "hello semihost" in out
    assert t.regs["pc"] == pc + 2
