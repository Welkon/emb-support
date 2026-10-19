import pytest


@pytest.fixture
def ev(fake):
    dap = fake.dap
    dr = dap.DwarfReader(fake.path)
    env = dap._env(dr, {})
    return dap, dr, env, fake.mem.read


def value(ev, expr):
    dap, dr, env, read = ev
    return dap.eval_expr(dr, expr, env, read).load(read)


@pytest.mark.parametrize("expr,expected", [
    ("g_counter", 7),
    ("g_pt.x", 3),
    ("g_pt.x + g_pt.y", 7),
    ("g_arr[2]", 30),
    ("g_arr[1] * 2 + 1", 41),
    ("g_head->val", 1),
    ("g_head->next->val", 2),
    ("*g_ptr", 7),
    ("g_ptr[0]", 7),
    ("1 + 2 * 3", 7),
    ("(1 + 2) * 3", 9),
    ("!0 + (3 > 2)", 2),
    ("(uint8_t)0x1234", 0x34),
    ("1 << 4 | 3", 19),
    ("7 % 4", 3),
])
def test_expressions(ev, expr, expected):
    assert value(ev, expr) == expected


def test_enum_renders_name(ev):
    dap, dr, env, read = ev
    assert dap._fmt_val(dap.eval_expr(dr, "g_color", env, read), dr, read) == "GREEN"


def test_address_of_array_element(ev, fake):
    assert value(ev, "&g_arr[1]") == 0x404044


def test_struct_renders_fields(ev):
    dap, dr, env, read = ev
    assert dap._fmt_val(dap.eval_expr(dr, "g_pt", env, read), dr, read) == {"x": 3, "y": 4}


def test_pointer_arithmetic_steps_by_element(ev):
    base = value(ev, "g_ptr")
    assert value(ev, "g_ptr + 1") == base + 4


def test_cast_to_pointer_then_deref(ev):
    assert value(ev, "*(int*)&g_counter") == 7


def test_register_expression(ev):
    dap, dr, env, read = ev
    env["r0"] = dap.Val(v=0x1F)
    assert dap.eval_expr(dr, "r0 & 0xF", env, read).load(read) == 0xF


@pytest.mark.parametrize("expr", [
    "does_not_exist",
    "g_pt->x",
    "g_arr.x",
    "g_pt.missing",
    "g_arr[1].x",
    "(notatype)1",
    "1 +",
])
def test_expression_errors(ev, expr):
    dap, dr, env, read = ev
    with pytest.raises(ValueError):
        dap.eval_expr(dr, expr, env, read)
