# Engine selection: pyOCD vs probe-rs

The skill has two backends. pyOCD is the default because it can install vendor
CMSIS-Packs at runtime; probe-rs is offered for tracing, profiling, RTT/defmt and
raw speed.

```bash
dap.py engines                                          # what is installed
dap.py flash fw.elf --engine probe-rs --chip STM32F103RC
dap.py flash fw.elf --engine pyocd -t stm32f103rc       # default
```

`--engine auto` picks probe-rs when it is installed and `--chip` (or
`config set chip`) is available, otherwise pyOCD.

## Unified behavior

Where the two backends overlap, the skill exposes one interface:

| Aspect | Unified behavior |
|---|---|
| Engine choice | `--engine auto` (default): probe-rs when installed and the chip resolves, otherwise pyOCD |
| Chip naming | `--chip STM32F103RC` wins; otherwise the pyOCD target (`stm32f103rc`) is matched against `probe-rs chip list` (exact, then unique prefix) |
| Flash flags | `--frequency` is converted to probe-rs `--speed` (kHz); `--connect under-reset` maps to `--connect-under-reset` |
| Verify | pyOCD compares segments itself; probe-rs runs `verify`; both return `{ok, op, engine, ...}` |
| Erase | `--chip-erase` in both; probe-rs always erases the whole chip |
| RTT | `rtt --duration N`: pyOCD `rtt`, probe-rs `attach [ELF]` |
| GDB | same `--port`, `--detach`, `--log`; probe-rs uses `--gdb-connection-string` |
| Output | every JSON result carries `engine` plus `ok`/`op`; streaming commands write text to stdout and diagnostics to stderr |

Commands that *always* use pyOCD (no probe-rs equivalent): `bp/wp`, `step/wait`,
`bt`, `vars`, `watch`, `svd`, `rtos`, `diagnose`, `fault`, `state`, `mem/regs`,
`option`, `dapreg`, `snapshot`, `cores`, `cycles`, `pack`, `repl`.
probe-rs-only paths: `itm`/ETF trace via `swo --engine probe-rs`, `profile --engine probe-rs`.

`targets --engine auto` lists pyOCD targets; use `--engine probe-rs` to list
probe-rs chips. `probes --engine probe-rs` shows the probe-rs probe list.

## Decision table

| Need | Use |
|---|---|
| Vendor part only covered by a CMSIS-Pack (many GD32/HC32/APM32/MM32 parts) | pyOCD (`pack install`) |
| SVD peripheral view, RTOS thread view, fault root-cause engine | pyOCD (skill commands) |
| RTT with `defmt` decoding, panic capture | probe-rs |
| SWO/ITM trace, ETF (on-chip trace buffer) | probe-rs (`itm swo` / `itm memory`) |
| Statistical profiling (`flat` / `callstack`) | probe-rs (`profile`) |
| Fast flash throughput, single static binary | probe-rs |
| RISC-V / Xtensa targets | probe-rs |
| Multi-core (`--core`), DWT cycle counter | either (skill wrappers) |

## pyOCD backend

Strengths:

- Runtime CMSIS-Pack manager: `dap.py pack search/install <part>` makes vendor
  parts work without regenerating a target database.
- Built-in SVD parser, RTOS plugins (FreeRTOS/RTX5/ThreadX/Zephyr), SWV reader.
- Python API used by the skill for registers, memory, breakpoints, CFI/expressions,
  and the fault analyser.
- Stable CLI target names (`stm32f103rc`), shared with `targets`.

Limits:

- No live ETM/ETF trace, no built-in statistical profiler.
- Slower connect/flash than probe-rs.
- Requires Python + pyOCD installed (the skill creates its own venv).

## probe-rs backend (v0.32, Apache-2.0)

Verified CLI surface used by this skill:

| Skill command | probe-rs command |
|---|---|
| `flash FILE` | `download FILE --binary-format elf\|hex\|bin --verify --reset` |
| `verify FILE` | `verify FILE --binary-format ...` |
| `erase --chip-erase` | `erase` |
| `reset` | `reset [--core N]` |
| `rtt` | `attach [ELF]` (RTT + defmt, no flashing) |
| `gdb` | `gdb --gdb-connection-string 127.0.0.1:PORT [ELF]` |
| `profile --duration N` | `profile --duration N ELF flat` |
| `swo --duration N` | `itm swo <ms> <cpu_hz> <baud_hz>` |
| `targets --engine probe-rs` | `chip list` |
| `info` | `info` |

probe-rs also ships features not wrapped here:

- `run ELF`: flash + reset + stream RTT/defmt/panics (cargo runner style).
- `itm memory`: capture ITM into the on-chip ETF/ETB instead of SWO pin.
- `debug`: built-in command-line debugger.
- `dap-server`: Microsoft DAP server for editors.
- `benchmark`: probe throughput measurement.
- `trace LOC`: sample a memory location over time (scope-like).
- `--chip-description-path <file>`: custom chip description for parts outside the
  registry.

Limits versus pyOCD:

- No runtime `.pack` installation: the chip database is compiled in (regenerate
  with `target-gen`, or pass a chip description file).
- No SVD/RTOS/`dump_cpu_state` equivalents; the skill's DWARF/CFA/fault analysis
  stays on the pyOCD side.
- Chip names differ from pyOCD target names (`STM32F103RC` vs `stm32f103rc`);
  pass them with `--chip`.
- Probe `--probe` accepts a probe selector (index/serial), which is close to but
  not identical to pyOCD's `--probe` unique ID.

## Installing

```bash
# probe-rs (pinned release, installed into the data dir)
dap.py setup --probe-rs

# or install it yourself
curl --proto '=https' --tlsv1.2 -LsSf https://github.com/probe-rs/probe-rs/releases/latest/download/probe-rs-tools-installer.sh | sh

# pyOCD
dap.py setup
```

Set `DAP_PROBE_RS=/path/to/probe-rs` to use a non-PATH binary.
Persist defaults with:

```bash
dap.py config set engine probe-rs
dap.py config set chip STM32F103RC
```

## Known pitfalls

- `--speed` is derived from `--frequency` (Hz) as kHz; probe-rs rejects very high
  SWD clocks on long wires just like pyOCD.
- `probe-rs attach` needs the ELF to locate the RTT control block and decode
  `defmt`; without it, only raw RTT scanning is possible.
- probe-rs progress bars are written to stderr; JSON consumers should read
  stdout only.
- `erase` in probe-rs always erases the whole non-volatile memory; there is no
  sector-range option.
