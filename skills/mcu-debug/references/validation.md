# Hardware validation (on-board acceptance)

Everything here needs a real probe and target. Run it before trusting the
debug features on a new chip family. `selfcheck` covers the non-destructive
half; the rest is a manual matrix.

## 0. WSL preflight

Any command that needs a probe auto-detects Windows-side probes and attaches
already-shared ones. To inspect or drive it manually:

```bash
dap.py wsl status          # Windows-side USB devices + known probes
dap.py doctor --attach     # attach the first known probe automatically
dap.py wsl attach --busid 2-1
```

`usbipd bind` (elevated, once per port) is still required before `attach`.

## 1. Automated smoke check

```bash
dap.py selfcheck --elf build/fw.elf --json
```

Checks (all non-destructive):

| Check | Pass condition |
|---|---|
| `probe` / `target` | probe serial and part number detected |
| `core_state` | reports RUNNING/HALTED/SLEEPING/LOCKUP |
| `registers` | PC and SP readable |
| `memory` / `vector_table` | 8 bytes readable at 0x0, initial SP non-zero |
| `stack_pointer` | SP is neither 0 nor 0xFFFFFFFF |
| `hw_breakpoint` | set + remove one HW breakpoint at PC |
| `cfi_unwind` | at least one exact (CFI) frame for the current PC |
| `line_info` | PC maps to `file:line` |
| `probe_caps` | capability list (look for `SWO` for tracing) |

Exit code is 0 only when every check passes.

## 2. Manual matrix

Run on each combination you care about:

- cores: Cortex-M0/M0+, M3, M4/M4F, M7 (and M33 if TrustZone matters)
- toolchains: GCC (`-g3`) and ArmClang AC6 (`-g`)
- optimization: `-O0` and `-O2` (or `-Os`)

| Test | Command | Pass condition |
|---|---|---|
| Flash + verify | `dap.py flash fw.elf -t <target>` | no error; `verify` clean |
| Backtrace | `dap.py bt --elf fw.elf` | frame count matches GDB/Keil; `exact_frames` > 0 |
| Frame locals | `dap.py vars locals --frame 1` | outer-frame args match the debugger |
| Expressions | `dap.py vars print "g_state.count + 1"` | matches the watch window |
| Line breakpoint | `dap.py bp set main.c:42 --elf fw.elf --wait 10` | stops on that line |
| Conditional | `bp set <addr> --cond "r0==3" --wait 20` | stops only when true |
| On-hit script | `bp set <addr> --on-hit "print r0; bt; continue"` | prints, continues |
| Watchpoint | `wp set <lvalue> --size 4` then `wait` | stops on write |
| RTOS | `dap.py rtos --elf fw.elf` | thread names/priorities sane |
| SWO | `dap.py swo --duration 5` | ITM text appears |
| RTT | `dap.py rtt --duration 5 --log /tmp/rtt.log` | target printf appears |
| Semihosting | `dap.py semi --duration 10` | `printf` via semihosting appears |
| Fault analysis | force a HardFault, run `dap.py fault --elf fw.elf` | fault type and faulting PC correct |
| HTML report | `dap.py diagnose --elf fw.elf --html /tmp/f.html` | report renders, addresses match |
| Multicore | `dap.py cores`, `regs --core 1` | second core registers change independently |
| Flash breakpoint | `bp set <addr> --type flash --yes` (lab board only) | halts; `bp clear` restores the sector |

## 3. Pass criteria

- `bt` frame count equals the reference debugger (GDB or Keil) at `-O0`.
  At `-O2`, exact frames must be a superset of the non-inlined frames; inline
  frames are a known gap.
- `vars locals` values equal the watch window at `-O0`; at `-O2` only
  CFI-located variables are expected to match.
- No command hangs when the probe is absent or the target is wedged
  (`selfcheck`, `flash`, `bt` must fail within a few seconds).

## 4. Recording results

```bash
dap.py selfcheck --elf fw.elf --json > selfcheck.json
dap.py diagnose --elf fw.elf --save crash.json --html report.html
```

Keep `selfcheck.json` + the chip/toolchain/optimization tuple with any bug
report.
