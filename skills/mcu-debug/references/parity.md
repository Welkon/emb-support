# 能力对照：本 skill vs cmsis-dap-mcp

cmsis-dap-mcp（`guohj2021/CMSIS-DAP-MCP`，44 个 MCP 工具，npm `npx -y cmsis-dap-mcp`）是 DAPLink 协议下工具面最全的现成实现。本 skill 以 pyOCD 为后端复刻它的能力面，差异如下。

## 已齐平（40/44）

| cmsis-dap-mcp | 本 skill | 说明 |
|---|---|---|
| `list_probes` / `get_probe_info` | `probes` / `doctor` | 输出含序列号、板名、target override |
| `connect` / `disconnect` | `connect` / `status` | 无长驻会话，每条命令独立连接；`blocking=False` |
| `get_target_info` | `info` / `connect` | part number、状态、PC |
| `read_memory` / `write_memory` | `mem read` / `mem write` | `--width 8/16/32`、`--count`，输出 hex |
| `verify_memory` | `verify FILE` | 直接比 ELF/HEX/BIN 与目标内存，报首个不一致地址 |
| `read_core_register` / `write_core_register` / `list_core_registers` | `regs` + `mem`/`svd` | 读全部核心寄存器；写用 `dapreg`/`mem` |
| `get_core_status` | `status` | state + halt reason + PC |
| `halt` / `resume` / `step` / `reset` | `halt` / `resume` / `step` / `reset` | `step --count N` |
| `set_breakpoint` / `clear_breakpoints` / `list_breakpoints` | `bp set/clear/list` | hw/sw/auto；`--wait` 一次完成"下断点→运行→等命中" |
| `set_watchpoint` / `clear_watchpoints` / `list_watchpoints` | `wp set/clear/list` | `--size`、`--type r/w/rw` |
| `erase_flash` / `program_flash` | `erase` / `flash` | flash 由 pyOCD CLI 执行，默认带校验 |
| `load_svd` / `list_peripherals` / `read_peripheral` / `write_peripheral` | `svd attach/list/read/write` | 用 pyOCD 自带 SVD 解析器；另有 `svd field` 位域读写 |
| `read_dap` / `write_dap` | `dapreg read/write` | 底层 `target.dp.read_reg/write_reg` |
| `read_option_bytes` / `write_option_bytes` | `option read/write --addr` | 必须显式给地址；写入需 `--yes` |
| `get_config` / `update_config` / `reload_config` | `config get/set/unset/list` | 持久化到 `~/.local/share/mcu-debug/config.json` |
| `define_chip` | `pack install` / `--pack` | 走 CMSIS-Pack；不支持无中生有定义芯片 |
| （无对应工具，CLI 有）RTT | `rtt` | pyOCD 原生 SEGGER RTT Viewer |
| （无对应工具）GDB server | `gdb` | `--detach` 后台运行 |

额外多出来的：

- `diagnose`：规则推理出按置信度排序的根因（空指针/外设时钟/栈溢出/执行数据/非精确总线错误…）+ 自包含 HTML 可视化报告（内存映射、反汇编高亮、栈 hex、回溯）。cmsis-dap-mcp 无等价能力。
- `fault`：一次给出 CFSR/HFSR/DFSR 解码、异常栈帧（faulting PC/LR）、回溯和栈用量 —— cmsis-dap-mcp 的 `dump_cpu_state` 只到寄存器。
- `bt`：DWARF CFI 精确回溯（寄存器逐帧重建）；缺 CFI 时才退回帧指针/栈扫描。
- `vars print`：完整 C 表达式求值（`.` `->` `[]` `*` `&`、算术位运算比较、类型强转、枚举）。
- `watch`：表达式时间序列监视（Live Watch）。
- `disasm` / `sym`：反汇编、符号与地址/行号互查。
- `vars globals/locals/print`：DWARF 类型化变量查看（结构体/数组/枚举/指针）。
- `bp set file.c:42`：按源码行下断点。
- `--cond` / `--log` / `--max-hits` / `--continue`：条件断点与命中日志。
- `step --over/--out/--line`：跨函数、跳到下一行。
- `rtos`：FreeRTOS/RTX5/ThreadX/Zephyr 任务列表。
- `snapshot save/load/diff`：RAM 快照对比。
- `gdb-batch`：有 GDB 时直接跑 `bt full` / `info locals` / 任意表达式。
- `wait`：resume 后轮询到命中，返回 halt reason。
- `verify`：不写只比，适合 CI/回归。
- `pack search/install`：器件包管理。

## 未齐平（4 项，均有明确原因）

| 缺失 | 原因 | 替代 |
|---|---|---|
| `set_flash_breakpoint` | 已实现，但会擦写整个扇区（含备份/恢复），需 `--yes` | `bp set <addr> --type flash --yes` |
| `run_script`（J-Link/OpenOCD 脚本） | 已由 `repl` + `source FILE` 覆盖 | `dap.py repl -c ...` / `source cmds.txt` |
| `define_chip`（运行时定义芯片） | pyOCD 只认 CMSIS-Pack | `pack install`，或换 OpenOCD cfg |

## 已闭环的差距

- SWO/ITM：用 pyOCD 的 `SWVReader` 实时解码（探针需支持 SWO），不是 OpenOCD。
- 长驻会话：`repl` 一次连接执行全部命令，断点/状态/core 在会话内保持。
- 多核：`cores` + 全局 `--core`。
- 性能：`cycles`（DWT CYCCNT）、`profile`（PC 采样）。

## 用不用 MCP 的判断

- 需要 agent 在一次会话里做几十次细粒度读写（live watch、位域轮询）→ MCP 常驻会话更省开销。
- 需要可审计、可重放、可写进脚本的命令 → 本 skill。
- 两者可以共存：MCP 做交互式探查，本 skill 做烧录/回归/CI。

安全差异：cmsis-dap-mcp 的 `program_flash`/`erase`/`write_option_bytes` 无二次确认；本 skill 对 `option write` 要求 `--yes`，对 `erase --chip-erase` 在文档中要求用户确认。
