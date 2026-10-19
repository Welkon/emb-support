from types import SimpleNamespace


def test_selfcheck_offline(fake, capsys):
    dap = fake.dap
    ns = SimpleNamespace(elf=str(fake.elf), target=None, probe=None, frequency=None, pack=None,
                         core=None, engine="pyocd", chip=None, connect=None, timeout=5, json=True)
    dap.cmd_selfcheck(ns)
    import json
    data = json.loads(capsys.readouterr().out)
    assert data["op"] == "selfcheck"
    names = {c["name"]: c["ok"] for c in data["checks"]}
    assert names["probe"] and names["target"] and names["registers"]
    assert names["memory"] and names["hw_breakpoint"]
    assert names["cfi_unwind"] and names["line_info"]
