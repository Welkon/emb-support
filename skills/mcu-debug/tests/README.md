# Tests

Offline test suite. No probe or target hardware is required.

## Run

```bash
~/.local/share/mcu-debug/venv/bin/python -m pytest tests -q
```

If pytest is missing:

```bash
scripts/dap.py setup --dev
```

## What is covered

| File | Scope |
|---|---|
| `test_elf.py` | symbol/line lookup, exec ranges, address resolution |
| `test_dwarf.py` | globals, struct/array/enum types, locals round-trip, sizes |
| `test_expr.py` | C expression evaluator: member/arrow/index, casts, arithmetic, errors |
| `test_cfi.py` | FDE lookup and CFA computation of the DWARF unwinder |
| `test_fault.py` | root-cause rules (NULL, peripheral, PC-in-RAM, stack overflow, imprecise), ranking, bit decode |
| `test_report.py` | text/HTML report sections, template completeness, HTML escaping |
| `test_cli.py` | subprocess smoke tests: help, symbols, offline diagnose, fail-fast, config |
| `test_repl.py` | persistent session commands, `source`, error recovery, `quit` semantics |
| `test_engines.py` | pyOCD/probe-rs selection and CLI argument mapping (fake binary) |
| `test_semihost.py` | SYS_WRITE0 servicing over a simulated BKPT #0xAB halt |
| `test_onhit.py` | on-hit scripts (print/bt/continue), breakpoint registry |
| `test_selfcheck.py` | hardware self-check schema and offline results |

## Fixtures

`conftest.py` builds a small DWARF-enabled ELF with `gcc -g -O0 -no-pie` once per
session (tests that need DWARF are skipped when gcc is absent), then exposes a
byte-addressed memory image plus a fake pyOCD target/session. All persistent
state (config, breakpoint registry, flash backups) is redirected to `tmp_path`.

## Not covered

- Real probe behavior (SWD timing, flash algorithms, SWO, multicore silicon)
- ARM-specific CFI rules (the fixture is x86-64, so only the unwinder mechanics
  and CFA math are validated)
- pyOCD version drift
