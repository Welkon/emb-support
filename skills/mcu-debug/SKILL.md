---
name: mcu-debug
metadata:
  short-description: "Debug and flash Cortex-M, build XC8 firmware, and burn CACHIP touch MCUs"
description: "Debug and flash ARM Cortex-M targets through DAPLink, CMSIS-DAP, ST-Link, J-Link or probe-rs; build SCMCU/PIC firmware with XC8; and drive the CACHIP USB HID programmer for CA51 touch MCUs. Use this skill when the user mentions a debug probe (DAPLink, CMSIS-DAP, SWD, SWDIO, SWCLK, pyOCD, probe-rs, ST-Link, J-Link), asks to flash firmware, erase a chip, read registers or memory, set breakpoints, capture RTT or SWO output, or diagnose a HardFault. Also use it for XC8 builds (SCMCU, PIC, .scw, map file, ROM/RAM size) and CACHIP tasks (CA51M550S1B, TK3 touch, touch calibration, writer slots, downloader firmware update). Do not use it for J-Link-native flows that need JLinkExe-only features (RTT Viewer, J-Link scripts); use the jlink skill. Do not use it for ESP32 or ESP8266 UART flashing."
---

# MCU workbench: debug, flash, build

This skill covers three separate toolchains. Read only the part that matches the task.

All hardware actions for ARM targets go through `scripts/dap.py`. The script is a thin layer over pyOCD. pyOCD does probe discovery, flash algorithms, CMSIS-Packs, RTT and the GDB server. The script only normalizes the command line and the output.

Why the script exists:

- The pyOCD `cmd` and `gdbserver` commands wait for a probe when none is attached. The script opens a session with `blocking=False`. If no probe is present, it fails in about one second.
- `pyocd json -p/-t` returns nested data. The script flattens it.
- Error messages include a hint for the next check.

## 0. Task routing

Do this step first. The three toolchains are independent.

| Task or keyword | Use |
|---|---|
| CA51, CA51M550S1B, TK3 touch, TFT emulator downloader, CACHIP, writer slot, downloader firmware update | `references/cachip.md` and `scripts/cachip/`. Windows and `hidapi` are required. |
| PIC, SCMCU, XC8, `.scw`, SCMCU IDE, build, ROM/RAM, map file | `references/xc8-build.md` and `scripts/xc8/build_xc8.py`. Windows and the XC8 toolchain are required. |
| ARM Cortex-M, DAPLink, CMSIS-DAP, ST-Link, J-Link, SWD, RTT, HardFault, probe-rs | The rest of this document and `scripts/dap.py`. |

Do not apply the CACHIP or XC8 flow to an ARM target. Do not connect pyOCD to a CA51 or PIC target.

## 0.1 Probe task routing

| Condition | Use |
|---|---|
| Probe is DAPLink, CMSIS-DAP or ST-Link compatible | This skill. |
| Probe is J-Link and the user needs RTT Viewer, J-Link scripts or J-Flash | The `jlink` skill. Do not mix tools. |
| J-Link is configured as CMSIS-DAP (`-f CMSIS-DAP`) | This skill. |
| The user only needs a serial log and has no debug probe | A serial skill. |
| The user needs bit-field peripheral access by name | Read `references/engines.md`. The SVD commands provide this. |

## 1. Environment check

Run this command at the start of each session:

```bash
python3 scripts/dap.py doctor
```

The script directory is the skill directory. From another directory, use the absolute path:

`~/.pi/agent/skills/mcu-debug/scripts/dap.py`

`doctor` prints JSON. Check these fields first:

- `probes`: An empty array means the probe is not visible. Read `references/troubleshooting.md`.
- `wsl: true`: In WSL, the probe must be attached to Linux first. Any command that needs a probe reads the Windows-side `usbipd list` after a failed connect. If a known probe is already shared, the script runs `usbipd attach --wsl`, then retries the connect. Disable this behavior with `--no-wsl-auto-attach` or `DAP_WSL_AUTO_ATTACH=0`. `doctor` lists the Windows state in `windows.probes`.
  - `dap.py wsl status`: Show Windows-side devices only.
  - `dap.py wsl attach --busid 2-1`: Attach one device. If the device is not shared, the script tells the user to run `usbipd bind --busid 2-1` as administrator.
  - `dap.py doctor --attach`: Attach the first known probe that is not attached.
- `targets_cached`: The number of built-in targets. Zero is not an error. Install a pack.
- `problems`: If this array is not empty, read `hints`.

If pyOCD is missing, run:

```bash
python3 scripts/dap.py setup
```

`setup` creates a virtual environment and installs pyOCD. It needs network access and takes about 30 seconds. It prefers Python 3.10 to 3.13. Python 3.14 can fail because `cmsis-pack-manager` may have no wheel.

To install the optional tools:

```bash
python3 scripts/dap.py setup --dev        # adds pytest for the test suite
python3 scripts/dap.py setup --probe-rs   # downloads the pinned probe-rs release
```

`dap.py env` prints the resolved data directory, venv path, and engine paths. Use it when a documented path does not exist. The data directory can fall back to the legacy `~/.local/share/daplink`.

## 2. Standard workflow

A failed hardware action can brick the board or erase option bytes. Follow the steps in order.

1. **Confirm the probe and the target**
   ```bash
   scripts/dap.py probes
   scripts/dap.py targets --search stm32f103
   ```
   The target name must match the `targets` output. If the name is missing, install a pack:
   ```bash
   scripts/dap.py pack search GD32F303
   scripts/dap.py pack install GD32F303CC
   ```
2. **Flash the firmware**
   ```bash
   scripts/dap.py flash build/fw.elf -t stm32f103rc
   ```
   - A `.bin` file needs a base address: `flash fw.bin@0x08000000 -t ...` or `--base 0x08000000`.
   - If the target sleeps, shares SWD pins, or has read protection, add `--frequency 1000000`. If needed, run `erase --chip-erase` first.
   - The flash command verifies by default. Do not disable verification unless the user asks.
3. **Reset and verify**
   ```bash
   scripts/dap.py reset -t stm32f103rc
   scripts/dap.py mem read 0x08000000 --count 4 --json
   ```
4. **Observe the target**
   - RTT: `scripts/dap.py rtt -t <target> --duration 20 --log /tmp/rtt.log`
   - Breakpoint: `bp set main --elf build/fw.elf --wait 10`
   - Conditional breakpoint: `bp set main --cond "r0==3" --wait 30`. The target stops only when `r0==3`.
   - Step by line or over calls: `step --line --elf fw.elf` or `step --over --elf fw.elf`
   - Crash report: `scripts/dap.py diagnose --elf fw.elf --html /tmp/fault.html`
   - Raw crash state: `scripts/dap.py fault --elf fw.elf`
   - Peripheral register: `svd attach <chip.svd>`, then `svd read GPIOA.CRL` or `svd field GPIOA.CRL.MODE0 1`

## 3. Advanced debug

These commands need `--elf`. You can also run `dap.py config set elf build/fw.elf` once. The commands use pyelftools and capstone from pyOCD. No extra install is needed.

**Backtrace**
```bash
scripts/dap.py bt
scripts/dap.py disasm --symbol HardFault_Handler --count 20
scripts/dap.py sym find config
scripts/dap.py sym addr 0x08001a3c
```

A frame with `via: cfi` comes from `.debug_frame` or `.eh_frame`. It is exact. The unwinder rebuilds the registers for each frame. If CFI data is missing, the output falls back to `via: fp` or `via: stack+0x..`. These two are heuristic and can be wrong. The `exact_frames` field gives the number of exact frames.

**Variables and expressions**
```bash
scripts/dap.py vars globals --filter gpio
scripts/dap.py vars print "g_state.mode"
scripts/dap.py vars print "head->next->val + 1"
scripts/dap.py vars print "arr[2] * 2"
scripts/dap.py vars print "*(uint32_t*)0x40010808"
scripts/dap.py vars print "r0 & 0xF"
scripts/dap.py vars locals
scripts/dap.py vars locals --frame 1
```

The evaluator supports `.`, `->`, `[]`, `*`, `&`, arithmetic, bit operations, comparisons, logical operations, `(type*)` casts, enum names, and the base types `uint8_t` to `uint64_t`, `int` and `char`. Local variables use the CFA as the frame base. Outer frames depend on CFI. Without CFI, the values are estimates.

**Live watch**
```bash
scripts/dap.py watch "g_state.count" --interval 0.2 --count 50
scripts/dap.py watch "adc_buf[0]" -n 100 --interval 0.05
```

The command returns a time series, min, max, and a change flag. The target can keep running. Global variables are readable while the target runs. Local variables need a halted target.

**RTOS**
```bash
scripts/dap.py rtos
scripts/dap.py rtos --rtos freertos
```

**Conditional breakpoints and logging**
```bash
scripts/dap.py bp set 0x08000abc --cond "[0x20000000]==1" --log "r0" --wait 30 --max-hits 3
```

The condition uses a register, a constant, or `[address]` with `==`, `!=`, `>`, `<`, `>=` or `<=`. Use `[0x20000000:1]` to set the width. If the condition is false, the target continues. `--max-hits` limits the number of recorded hits.

**Interactive session**
```bash
scripts/dap.py repl --elf fw.elf
scripts/dap.py repl --elf fw.elf -c "bp main" -c "run 5" -c "bt" -c "p g_state.mode" -c quit
```

The session uses one connection. Breakpoints, run state and core selection persist. This avoids a reconnect for each command. Commands: `run`, `step`, `next`, `finish`, `line`, `bp` (with `if EXPR`), `wp`, `bt`, `print`, `locals`, `globals`, `regs`, `mem`, `disasm`, `fault`, `watch`, `core`, `source`. Enter `help` for the full list.

**Trace and performance**
```bash
scripts/dap.py swo --cpu-freq 72000000 --swo-freq 2000000 --duration 5
scripts/dap.py swo --raw /tmp/swo.bin --duration 10
scripts/dap.py profile --elf fw.elf --duration 5 --interval 0.01
scripts/dap.py cycles --enable --reset
scripts/dap.py cycles --hz 72000000
```

`swo` decodes ITM and printf data to the terminal. The probe must support SWO. DAPLink v2 and ST-Link support it. CMSIS-DAP v1 HID usually does not, and the command reports an error. `profile` samples the PC with periodic halts. It finds hot spots but disturbs the target. For lossless profiling, use periodic PC over SWO or ETM.

**Multicore**
```bash
scripts/dap.py cores
scripts/dap.py regs --core 1
scripts/dap.py bp set main --core 1 --elf fw.elf
```

**Flash breakpoints**
```bash
scripts/dap.py bp set 0x08001234 --type flash --yes
scripts/dap.py bp clear 0x08001234
```

The command erases and rewrites the whole sector. It backs up the sector to `flash_bp.json` in the data directory. `dap.py env` shows that directory. If power fails during the write, flash the board again. Prefer hardware breakpoints.

**Semihosting**
```bash
scripts/dap.py semi --duration 10 --elf fw.elf
```

The host serves `SYS_WRITE0` and other requests when the target runs `bkpt #0xAB`. Output goes to the terminal. The command stops on a real breakpoint or fault.

**On-board self-check**
```bash
scripts/dap.py selfcheck --elf fw.elf --json
```

The check is non-destructive. It tests the probe, target, registers, memory, vector table, SP, a hardware breakpoint, CFI unwinding, line info and probe capabilities. The exit code is 0 only if all checks pass. See `references/validation.md` for the full acceptance matrix.

**Breakpoint on-hit script**
```bash
scripts/dap.py bp set 0x08001234 --on-hit "print r0; bt; continue" --max-hits 5 --wait 30
```

The script supports `print EXPR`, `bt`, `continue`, `stop` and `silent`. Separate the commands with a semicolon. The commands run on each hit.

**Fault analysis and report**
```bash
scripts/dap.py diagnose --elf fw.elf --html /tmp/fault.html --rtt-log /tmp/rtt.log --open
```

The command captures one snapshot, applies the rule engine, and writes ranked root-cause hypotheses. Each hypothesis includes evidence and next steps. It also writes a self-contained HTML report with these items:

- The memory map, with the PC, SP and fault address.
- The decoded fault flags.
- The backtrace table.
- Disassembly at the fault address, with the faulting instruction highlighted.
- A stack hex dump, with plausible return addresses in green.

The rules cover NULL pointers (BFAR near 0), disabled peripheral clocks (fault address in the DEVICE region), stack overflow (SP outside RAM, MSTKERR, STKERR), execution from data (PC outside an executable segment), invalid instruction or Thumb state, imprecise bus errors (write buffer delay), divide by zero, unaligned access, disabled FPU, and stack protector failures (`__stack_chk_fail` in the backtrace).

For offline analysis, save the snapshot and replay it:

```bash
scripts/dap.py diagnose --save /tmp/crash.json
scripts/dap.py diagnose --snapshot /tmp/crash.json --html report.html
```

**Memory snapshot and compare**
```bash
scripts/dap.py snapshot save /tmp/ram.bin --addr 0x20000000 --len 0x4000
scripts/dap.py snapshot diff /tmp/ram.bin --addr 0x20000000
```

Use this command to compare RAM after a normal run and after a fault.

**Full GDB fallback**
```bash
scripts/dap.py gdb-batch --elf fw.elf -ex "bt full" -ex "info locals" -ex "p/x *0x40010808"
```

The command starts `pyocd gdbserver`, runs the GDB commands, and stops the server. It needs `arm-none-eabi-gdb` or `gdb-multiarch`, or `DAP_GDB` set to a GDB path. The native commands cover most cases when GDB is not available.

## 4. Command reference

| Command | Purpose | Key options |
|---|---|---|
| `doctor` | Check the environment, probe and target cache. Includes Windows-side probes in WSL. | `--attach` |
| `wsl status/attach/detach` | Find or attach Windows-side USB probes in WSL. | `--busid`, `--dry-run` |
| `engines` | Show pyOCD and probe-rs availability. | None |
| `setup` | Create the venv and install pyOCD. | `DAPLINK_PYTHON` |
| `probes`, `connect`, `status` | List probes, connect and report the target, or show run state. | `--json` |
| `targets` | List or search targets. | `--search/-s`, `--limit/-n` |
| `pack search/install/list` | Manage CMSIS-Packs. | Query string |
| `flash FILE` | Flash the firmware. Verification is on by default. | `-t`, `-u`, `-f`, `-e`, `--base`, `--no-reset` |
| `verify FILE` | Compare ELF, HEX or BIN with target memory. Do not write. | `--base`, `--max-report` |
| `erase` | Erase flash. | `--chip-erase` (dangerous), `--range` |
| `reset` | Reset the target. | `--halt` |
| `halt`, `resume`, `step` | Control execution. | `--count`, `--over`, `--out`, `--line` |
| `wait` | Resume and wait for a hit. | `--cond`, `--log`, `--max-hits`, `--continue` |
| `bp set/list/clear` | Manage breakpoints (hardware, software, auto, flash). | `SYMBOL`, `file.c:LINE`, `--cond`, `--on-hit`, `--wait`, `--all` |
| `wp set/list/clear` | Manage data watchpoints. | `--size`, `--type r/w/rw` |
| `mem read/write ADDR` | Read or write memory. | `--width 8/16/32`, `--count N` |
| `regs`, `regset NAME V` | Read or write core registers. | `--json` |
| `state` | Show registers, fault decode and the exception frame. | None |
| `fault` | Show the fault, exception frame, backtrace and stack use. | `--limit`, `--max-stack` |
| `diagnose` | Rank root causes and write an optional HTML report. | `--html`, `--save`, `--rtt-log`, `--snapshot`, `--open` |
| `bt` | Show the backtrace with symbols and line numbers. | `--limit`, `--max-stack` |
| `disasm` | Disassemble code. | `--at`, `--symbol`, `--count`, `--mode` |
| `sym list/find/addr` | Search symbols or map an address to a line. | `--limit` |
| `vars globals/locals/print` | Read DWARF variables, including structs, arrays and enums. | `--filter`, `a.b.c` |
| `rtos` | List RTOS tasks. | `--rtos freertos/rtx5/threadx/zephyr` |
| `snapshot save/load/diff` | Save, restore or compare a RAM region. | `--addr`, `--len` |
| `gdb-batch` | Run GDB commands in batch. | `-ex ...`, `--elf` |
| `repl` | Start a persistent GDB-style session. | `-c 'cmd'` (repeatable) |
| `cores` | List cores. | Use `--core` with other commands. |
| `cycles` | Read the DWT cycle counter. | `--enable`, `--reset`, `--hz` |
| `profile` | Sample the PC and list hot functions. | `--duration`, `--interval`, `--top` |
| `swo` | Decode SWO/ITM trace. | `--cpu-freq`, `--swo-freq`, `--duration`, `--raw` |
| `semi` | Serve the ARM semihosting console. | `--duration` |
| `selfcheck` | Run the non-destructive hardware self-check. | `--elf`, `--json` |
| `record` | Write board evidence (selfcheck, snapshot, report). | `--out`, `--elf`, `--target`, `--toolchain`, `--opt`, `--rtt-log` |
| `bp --type flash` | Write a BKPT instruction to flash. | `--yes` (erases a sector) |
| `svd attach/list/read/write/field` | Read or write SVD peripherals and bit fields. | `PERIPH.REG[.FIELD]`, `--svd` |
| `dapreg read/write` | Access raw DP registers. | `ADDR [VALUE]` |
| `option read/write` | Read or write option bytes. An explicit address is required. | `--addr`, `--yes` |
| `config get/set/unset/list` | Store default values. | `target/probe/frequency/pack/elf/svd` |
| `rtt` | Read the SEGGER RTT log. | `-a`, `--duration`, `-d` |
| `gdb` | Start a GDB server. | `-p 3333`, `--detach`, `--persist` |
| `info` | Show target information. | Session options |

Session options: `-t/--target`, `-u/--probe`, `-f/--frequency`, `--pack`, `--elf`, `--connect halt/pre-reset/under-reset/attach`, `--engine auto/pyocd/probe-rs`, `--chip` (probe-rs chip name).

**Two engines**: pyOCD is the default. It can install CMSIS-Packs at run time, and it supports SVD, RTOS and fault analysis. probe-rs is faster. It provides RTT/defmt, SWO/ITM/ETF and statistical profiling.

```bash
scripts/dap.py engines
scripts/dap.py flash fw.elf --engine probe-rs --chip STM32F103RC
scripts/dap.py rtt --engine probe-rs --chip STM32F103RC --elf fw.elf
scripts/dap.py profile --engine probe-rs --chip STM32F103RC --elf fw.elf --duration 5
scripts/dap.py swo --engine probe-rs --chip STM32F103RC --duration 5
```

`dap.py engines` shows the state of each engine. If probe-rs is missing, run `dap.py setup --probe-rs`.

`--engine auto` is the default. It selects probe-rs when probe-rs is installed and the chip name resolves. Resolution order: `--chip`, then config, then an exact or unique-prefix match of the pyOCD target name against `probe-rs chip list`. The two engines use different chip names (pyOCD `stm32f103rc` vs probe-rs `STM32F103RC`). Set `--chip` when the names differ. See `references/engines.md`.

Store defaults with `dap.py config set target stm32f103rc`. Then you do not need `-t` on each command.

Hardware breakpoints live in the FPB. They survive between processes. After `bp set 0x08000abc`, a separate `wait` command can hit the breakpoint. A reset clears it.

## 5. Safety

The following actions are not reversible. Get explicit confirmation from the user before you run them.

- `erase --chip-erase`: Erases all flash, including the bootloader and calibration data.
- `mem write` to option bytes or read-protection registers (for example STM32 `0x1FFFF800` or `0x40022020`): A wrong value can lock the chip or block future connects.
- `flash` with the wrong target: pyOCD uses the wrong memory map and can write outside the flash region.
- `bp set --type flash`: Erases and rewrites the whole sector. A power loss during the write needs a new flash.
- `swo` and `profile` change the run state. The halt sampling in `profile` distorts timing-sensitive code.

Do not erase the whole chip, unlock protection, or write option bytes unless the user asks for it. If read protection blocks the probe, tell the user to use `--connect under-reset` or a vendor tool. Do not guess register values.

## 6. Troubleshooting

Read `references/troubleshooting.md` for these symptoms: probe not visible, permission error, `target not found`, flash timeout, unstable SWD, missing RTT, and GDB connect failure. Find the symptom and read only that section.

If the script itself fails, run `doctor`, then `pyocd -v` for the low-level log, then read `references/engines.md`.

## 7. When to use another tool

See `references/parity.md` for the feature comparison with `cmsis-dap-mcp`.

pyOCD has the widest coverage: CMSIS-Packs, built-in flash algorithms, RTT and GDB server. It is not universal.

- No CMSIS-Pack and no built-in target: use OpenOCD. See `references/engines.md`.
- Need better RTT, SWO or live variable sampling: use the probe-rs path in `references/engines.md`.
- Need an AI-facing structured debug tool instead of shell commands: `cmsis-dap-mcp` (zero-install with `npx`) is an option. It uses a different permission model. This skill does not include it by default.

Read `references/engines.md` before you change engines. Do not mix commands from two engines in one task.

## 8. Tests and CI

```bash
scripts/dap.py test --install     # uses the real venv, installs pytest if needed
scripts/dap.py record --out workspace --elf fw.elf   # needs a probe
ruff check scripts tests
```

CI runs `.github/workflows/ci.yml` on Python 3.11 and 3.13 with `ruff` and `pytest`. The runtime pins `pyocd==0.46.0`. Override it with `DAPLINK_PYOCD`.

The tests use a real DWARF ELF from `gcc -g` and a fake target and memory. They cover ELF parsing, DWARF types and locals, C expressions, CFI unwinding, fault rules, text and HTML reports, the CLI and the REPL. All persistent state goes to a temporary directory. Hardware paths (SWD timing, flash algorithms, SWO, multicore) still need an on-board check. See `references/validation.md`.
