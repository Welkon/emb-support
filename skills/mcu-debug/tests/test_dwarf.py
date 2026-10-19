def test_globals_indexed(fake):
    dr = fake.dap.DwarfReader(fake.path)
    names = set(dr.globals_env())
    for name in ("g_counter", "g_pt", "g_name", "g_color", "g_head", "g_arr"):
        assert name in names


def test_global_values(fake):
    dr = fake.dap.DwarfReader(fake.path)
    values = {g["name"]: g["value"] for g in dr.globals_at(fake.mem.read)}
    assert values["g_counter"] == 7
    assert values["g_pt"] == {"x": 3, "y": 4}
    assert values["g_name"] == [ord("h"), ord("i"), 0]
    assert values["g_color"] == "GREEN"
    assert values["g_arr"] == [10, 20, 30, 40]


def test_struct_type_layout(fake):
    from dap_debug import _tref
    dap = fake.dap
    dr = dap.DwarfReader(fake.path)
    die, cu, _ = dr.globals_env()["g_pt"]
    tr = _tref(dr, dap.DwarfReader._type(die, cu), cu)
    assert tr["kind"] == "struct"
    assert tr["members"]["x"][0] == 0
    assert tr["members"]["y"][0] >= 4
    from dap_debug import _tr_size
    assert _tr_size(tr) >= 8


def test_typedef_resolves_to_struct(fake):
    from dap_debug import _type_by_name
    dr = fake.dap.DwarfReader(fake.path)
    tr = _type_by_name(dr, "pt_t")
    assert tr is not None and tr["kind"] == "struct"


def test_locals_roundtrip(fake):
    dr = fake.dap.DwarfReader(fake.path)
    ei = fake.ei
    pc = ei.symbols["add"]
    regs = {"sp": 0x28000000, "pc": pc}
    env = dr.locals_env(pc, regs)
    assert {"a", "b", "local"} <= set(env)
    # write known values at the addresses the location expressions produced
    for name, value in (("a", 7), ("b", 3), ("local", 10)):
        _, _, addr = env[name]
        fake.mem.write(addr, value.to_bytes(4, "little"))
    got = {x["name"]: x["value"] for x in dr.locals_at(pc, regs, fake.mem.read)}
    assert got["a"] == 7 and got["b"] == 3 and got["local"] == 10


def test_sizeof_base_and_array(fake):
    dap, dr = fake.dap, fake.dap.DwarfReader(fake.path)
    from dap_debug import _tr_size, _tref
    die, cu, _ = dr.globals_env()["g_counter"]
    assert _tr_size(_tref(dr, dap.DwarfReader._type(die, cu), cu)) == 4
    die, cu, _ = dr.globals_env()["g_arr"]
    tr = _tref(dr, dap.DwarfReader._type(die, cu), cu)
    assert tr["kind"] == "array" and tr["count"] == 4
