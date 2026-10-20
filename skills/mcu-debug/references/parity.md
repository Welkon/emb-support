# Feature comparison: this skill and cmsis-dap-mcp

`cmsis-dap-mcp` (`guohj2021/CMSIS-DAP-MCP`) is a ready-made MCP server for
DAPLink probes. It has 44 MCP tools and installs with `npx -y cmsis-dap-mcp`.
This skill uses pyOCD and copies that feature surface. The table below shows the
differences.

## Equal features

| cmsis-dap-mcp | This skill | Notes |
|---|---|---|
| `list_probes`, `get_probe_info` | `probes`, `doctor` | Output includes the serial number, board name and target override. |
| `connect`, `disconnect` | `connect`, `status` | No long-running session. Each command connects on its own with `blocking=False`. |
| `get_target_info` | `info`, `connect` | Part number, state and PC. |
| `read_memory`, `write_memory` | `mem read`, `mem write` | `--width 8/16/32` and `--count`. Output is hex. |
| `verify_memory` | `verify FILE` | Compares ELF, HEX or BIN with target memory. Reports the first mismatch. |
| `read_core_register`, `write_core_register`, `list_core_registers` | `regs` plus `mem` or `svd` | Reads all core registers. Use `regset` to write one register. |
| `get_core_status` | `status` | State, halt reason and PC. |
| `halt`, `resume`, `step`, `reset` | `halt`, `resume`, `step`, `reset` | `step --count N`. |
| `set_breakpoint`, `clear_breakpoints`, `list_breakpoints` | `bp set/clear/list` | Hardware, software or auto. `--wait` runs the target and waits for the hit. |
| `set_watchpoint`, `clear_watchpoints`, `list_watchpoints` | `wp set/clear/list` | `--size` and `--type r/w/rw`. |
| `erase_flash`, `program_flash` | `erase`, `flash` | pyOCD runs the flash operation. Verification is on by default. |
| `load_svd`, `list_peripherals`, `read_peripheral`, `write_peripheral` | `svd attach/list/read/write` | Uses the pyOCD SVD parser. `svd field` reads or writes one bit field. |
| `read_dap`, `write_dap` | `dapreg read/write` | Calls `target.dp.read_reg` and `write_reg`. |
| `read_option_bytes`, `write_option_bytes` | `option read/write --addr` | An explicit address is required. A write needs `--yes`. |
| `get_config`, `update_config`, `reload_config` | `config get/set/unset/list` | Stored in `~/.local/share/mcu-debug/config.json`. |
| `define_chip` | `pack install` or `--pack` | Uses CMSIS-Packs. It does not define a chip from scratch. |
| Not an MCP tool: RTT | `rtt` | Native pyOCD SEGGER RTT viewer. |
| Not an MCP tool: GDB server | `gdb` | `--detach` runs it in the background. |

## Extra features in this skill

- `diagnose`: ranks root causes and writes a self-contained HTML report. The report includes the memory map, decoded fault flags, backtrace, disassembly at the fault address and a stack hex dump. `cmsis-dap-mcp` has no equivalent.
- `fault`: decodes CFSR, HFSR and DFSR, shows the exception frame and backtrace, and reports stack use.
- `bt`: exact DWARF CFI unwinding. It falls back to frame-pointer or stack scan only when CFI is missing.
- `vars print`: evaluates C expressions with `.`, `->`, `[]`, `*`, `&`, arithmetic, bit operations, comparisons, casts and enum names.
- `watch`: samples an expression and returns a time series.
- `bp set file.c:42`: sets a breakpoint on a source line.
- `--cond`, `--log`, `--max-hits`, `--continue`: conditional breakpoints and hit logs.
- `step --over`, `--out`, `--line`: step over calls, run to return, or run to the next line.
- `rtos`: lists FreeRTOS, RTX5, ThreadX or Zephyr tasks.
- `snapshot save/load/diff`: saves, restores or compares a RAM region.
- `gdb-batch`: runs `bt full`, `info locals` or any GDB command when a GDB binary is available.
- `wait`: resumes the target, waits for a hit and reports the halt reason.
- `verify`: compares without writing. Useful for CI and regression runs.
- `pack search/install`: installs device packs.
- `repl`: keeps one session for many commands.
- `semi`: serves the ARM semihosting console.
- `selfcheck`: runs a non-destructive on-board acceptance check.
- `--engine probe-rs`: uses probe-rs for RTT, SWO/ITM, profiling and faster flashing.
- WSL support: detects Windows probes through `usbipd` and attaches them automatically.

## Remaining differences

| Missing feature | Status |
|---|---|
| Flash breakpoints | Implemented. The command rewrites a whole sector and keeps a backup. Use `--yes`. |
| Command scripts | Covered by `repl` and `source FILE`. |
| Runtime chip definition | pyOCD uses CMSIS-Packs only. Use `pack install` or OpenOCD. |
| ETM instruction trace | Not available. This needs ETM hardware and a decoder. Use SWO periodic PC or the probe-rs ITM path. |
| Inline frames at `-O2` | Not unwound. `bt` can show fewer frames but does not fail. |
| On-board validation | The self-check and the acceptance matrix are ready. Real hardware is still required. See `validation.md`. |

## Choosing a tool

- Need many small reads and writes in one agent session, such as live watch or bit-field polling: an MCP server with a persistent session uses fewer resources.
- Need auditable, replayable commands that fit into a script: this skill.
- You can use both. Use the MCP server for interactive inspection and this skill for flash, regression and CI.

Safety difference: `cmsis-dap-mcp` runs `program_flash`, `erase` and `write_option_bytes` without a second confirmation. This skill requires `--yes` for `option write` and asks for user confirmation before `erase --chip-erase`.
