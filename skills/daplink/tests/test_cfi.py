def test_fde_lookup(fake):
    cf = fake.dap.CfiUnwinder(fake.path)
    assert cf.fdes, "expected at least one FDE"
    assert cf.find(fake.ei.symbols["main"]) is not None
    assert cf.find(0xDEADBEEF) is None


def test_unwind_first_frame_is_exact(fake):
    cf = fake.dap.CfiUnwinder(fake.path)
    sp = 0x28000000
    frames = cf.unwind(fake.ei.symbols["main"], {"r7": sp, "sp": sp, "lr": 0}, lambda a: 0, 4)
    assert frames[0]["exact"] is True
    assert frames[0]["pc"] == fake.ei.symbols["main"] & ~1
    # x86-64 fixture: CFA = rsp + 8
    assert frames[0]["cfa"] == sp + 8


def test_unwind_stops_on_null_return_address(fake):
    cf = fake.dap.CfiUnwinder(fake.path)
    sp = 0x28000000
    frames = cf.unwind(fake.ei.symbols["main"], {"r7": sp, "sp": sp, "lr": 0}, lambda a: 0, 8)
    assert len(frames) <= 2
