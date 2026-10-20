---
name: mcu-debug
metadata:
  short-description: "Debug/flash Cortex-M, build XC8 firmware, and burn/calibrate CACHIP touch MCUs"
description: Control DAPLink / CMSIS-DAP debug probes over SWD or JTAG for ARM Cortex-M — enumerate probes, install CMSIS-Packs, flash ELF/HEX/BIN with verify, chip/sector erase, reset, read/write memory and core registers, capture SEGGER RTT logs, and run a GDB server. Use this skill whenever the user mentions DAPLink, CMSIS-DAP, DAP, SWD, SWDIO/SWCLK, pyOCD, or a CMSIS-DAP-compatible probe (ST-Link, LPC-Link, NXP/Infineon onboard debugger), or asks to 烧录 / 下载固件 / 刷板子 / 擦除 flash / 看寄存器 / 读内存 / 抓 RTT 日志 / 查 HardFault, or reports "no probe found", "target not found", "flash failed", "SWD error", even when they never name the probe. Also builds SCMCU/PIC firmware with the bundled XC8 flow and drives the CACHIP USB HID programmer for CA51 touch MCUs (burning, touch calibration, firmware slots and downloader updates). Do not use it for J-Link-native flows that depend on JLinkExe-only features (RTT Viewer, J-Link scripts) — use the jlink skill instead — and do not use it for ESP32/ESP8266 UART flashing.
---

# MCU 工具台：调试 / 烧录 / 构建

所有硬件操作都通过 `scripts/dap.py` 完成。它是 pyOCD 的薄封装：pyOCD 负责探针枚举、flash 算法、CMSIS-Packs、RTT 和 gdbserver，脚本只负责参数归一化和输出结构化 JSON，避免每次手工拼 pyOCD 命令时踩参数顺序、target 命名和阻塞等待的坑。

**为什么用脚本而不是直接敲 `pyocd`：**
- pyOCD 的 `cmd` / `gdbserver` 在没有探针时会**阻塞重试**，在 agent 里表现为"卡住"。脚本用 `blocking=False` 打开会话，没有探针立刻报错。
- `pyocd json -p/-t` 的输出是嵌套结构，脚本已解析成扁平列表。
- 错误信息会附上对应的排查建议，省掉一轮猜测。

## 0. 任务分流（先做这一步）

本 skill 覆盖三类互不相干的工具链，按任务只读对应资料：

| 任务 / 关键词 | 入口 |
|---|---|
| CA51 / CA51M550S1B / TK3 触摸 / TFT 仿真下载器 / CACHIP / Writer 槽 / 下载器固件升级 | `references/cachip.md` + `scripts/cachip/`（Windows + `hidapi`） |
| PIC / SCMCU / XC8 / `.scw` / SCMCU IDE / 编译、ROM/RAM、map | `references/xc8-build.md` + `scripts/xc8/build_xc8.py`（Windows + XC8 工具链） |
| ARM Cortex-M / DAPLink / CMSIS-DAP / ST-Link / J-Link / SWD / RTT / HardFault / probe-rs | 本文余下部分 + `scripts/dap.py` |

不要把 CACHIP/XC8 的流程套到 ARM 上，也不要拿 pyOCD 去连 CA51/PIC。

## 0.1 探针任务分类：是否该用 ARM 调试流程


| 情况 | 走哪条路 |
|---|---|
| 探针是 DAPLink / CMSIS-DAP / ST-Link 兼容 | 本 skill |
| 探针是 J-Link，且需要 RTT Viewer、J-Link 脚本、J-Flash | `jlink` skill（JLinkExe），不要混用 |
| J-Link 只是被当成 CMSIS-DAP 用（`-f CMSIS-DAP`） | 本 skill |
| 只通过串口看 log、没有调试器 | 串口 skill，不要本 skill |
| 需要字段级外设语义（按 bitfield 名读写） | 本 skill 只能给原始数值；看 `references/engines.md` 里的 SVD 方案 |

## 1. 环境自检（每次会话第一条命令）

```bash
python3 scripts/dap.py doctor
```

脚本目录是 skill 所在目录；若当前工作目录不在 skill 下，用绝对路径
`~/.pi/agent/skills/mcu-debug/scripts/dap.py`。

`doctor` 输出 JSON，重点看四个字段：

- `probes`：空数组 = 探针不可见。先别改代码，按 `references/troubleshooting.md#探针不可见` 排查。
- `wsl: true`：WSL 里 USB 探针必须先挂到 Linux 侧。**任何需要探针的命令在连接失败时都会自动检测 Windows 侧**：
  读取 `usbipd list`，若存在已 shared 的已知探针（DAPLink/ST-Link/J-Link 等）会自动 `usbipd attach --wsl`，
  然后重试连接。可用 `--no-wsl-auto-attach` 或 `DAP_WSL_AUTO_ATTACH=0` 关闭。
  `doctor` 会在 `windows.probes` 列出状态并给出可直接执行的命令。
  - `dap.py wsl status`：只查看 Windows 侧设备
  - `dap.py wsl attach --busid 2-1`：挂载（设备未 shared 时提示先以管理员运行 `usbipd bind --busid 2-1`）
  - `dap.py doctor --attach`：自动挂载第一个未挂载的已知探针
- `targets_cached`：内置 target 数量，0 不代表出错（内置表可能被裁剪），装 pack 即可。
- `problems`：非空就直接读 `hints`。

首次使用如果 `doctor` 报 pyOCD 缺失：

```bash
python3 scripts/dap.py setup     # 建 venv 并安装 pyOCD（需要网络，约 30s）
```

`setup` 会优先挑 Python 3.10–3.13。3.14 上部分依赖（cmsis-pack-manager）可能没有轮子，所以不要强行指定 3.14。

## 2. 标准工作流

硬件任务出错的代价通常是"把板子刷成砖"或"擦掉 option bytes"，所以按顺序做，每一步都有明确的失败出口：

1. **确认探针和目标**
   ```bash
   scripts/dap.py probes
   scripts/dap.py targets --search stm32f103
   ```
   target 名字必须和 `targets` 输出完全一致。查不到就装 pack：
   ```bash
   scripts/dap.py pack search GD32F303
   scripts/dap.py pack install GD32F303CC
   ```
2. **烧录**（默认带校验；除非用户明确要求，不要加 `--no-verify` 类参数）
   ```bash
   scripts/dap.py flash build/fw.elf -t stm32f103rc
   ```
   - `.bin` 必须给基地址：`flash fw.bin@0x08000000 -t ...` 或 `--base 0x08000000`
   - 目标跑在低功耗模式 / SWD 引脚被复用 / 有读保护时，加 `--frequency 1000000`，必要时先 `erase --chip-erase`
3. **复位并验证**
   ```bash
   scripts/dap.py reset -t stm32f103rc
   scripts/dap.py mem read 0x08000000 --count 4 --json
   ```
4. **看行为**
   - 有 RTT：`scripts/dap.py rtt -t <target> --duration 20 --log /tmp/rtt.log`
   - 断点：`bp set main --elf build/fw.elf --wait 10`（下断点、运行、等命中）
   - 条件断点：`bp set main --cond "r0==3" --wait 30`，只有 r0==3 时才停
   - 逐行/跨函数：`step --line --elf fw.elf` / `step --over --elf fw.elf`
   - 崩溃定位：`scripts/dap.py diagnose --elf fw.elf --html /tmp/fault.html` —— 自动推断根因 + 可视化报告
   - 要看原始现场：`scripts/dap.py fault --elf fw.elf`（寄存器/解码/栈帧/回溯/栈用量）
   - 外设寄存器：`svd attach <chip.svd>` 后 `svd read GPIOA.CRL`，或 `svd field GPIOA.CRL.MODE0 1`

## 3.5 进阶调试

这些命令需要 `--elf`（或 `dap.py config set elf build/fw.elf` 持久化），依赖 pyOCD 自带的 pyelftools/capstone，无需额外安装。

**回溯**
```bash
scripts/dap.py bt            # DWARF CFI 精确展开，带 符号+offset 和 file:line
scripts/dap.py disasm --symbol HardFault_Handler --count 20
scripts/dap.py sym find config     # 符号搜索
scripts/dap.py sym addr 0x08001a3c # 地址 -> 符号 + 行号
```
`via: cfi` 的帧来自 `.debug_frame`/`.eh_frame`，是精确展开（寄存器按 CFI 规则逐帧重建）；
只有缺失 CFI 时才会退回 `via: fp` / `via: stack+0x..`，那两种是启发式，可能误报。
输出里的 `exact_frames` 给出精确帧数量。

**变量与表达式（C 语法）**
```bash
scripts/dap.py vars globals --filter gpio
scripts/dap.py vars print "g_state.mode"
scripts/dap.py vars print "head->next->val + 1"
scripts/dap.py vars print "arr[2] * 2"
scripts/dap.py vars print "*(uint32_t*)0x40010808"
scripts/dap.py vars print "r0 & 0xF"
scripts/dap.py vars locals                      # 当前帧参数/局部变量
scripts/dap.py vars locals --frame 1            # 外层帧（依赖 CFI 重建的 CFA/寄存器）
```
支持：`.` `->` `[]` `*` `&`、算术/位运算/比较/逻辑、`(type*)` 强转、枚举名、`uint8_t..uint64_t/int/char` 等基础类型。
局部变量用 CFA 作为 frame base；外层帧依赖 CFI，缺 CFI 时才是估算。

**实时监视（Live Watch）**
```bash
scripts/dap.py watch "g_state.count" --interval 0.2 --count 50
scripts/dap.py watch "adc_buf[0]" -n 100 --interval 0.05
```
返回时间序列、min/max、是否变化。目标可继续运行（全局变量可读；局部变量需要 halt）。

**RTOS**
```bash
scripts/dap.py rtos                # 自动识别 FreeRTOS/RTX5/ThreadX/Zephyr, 列出任务
scripts/dap.py rtos --rtos freertos
```

**条件断点与日志**
```bash
scripts/dap.py bp set 0x08000abc --cond "[0x20000000]==1" --log "r0" --wait 30 --max-hits 3
```
条件语法：`寄存器/立即数/[地址]` + `== != > < >= <=`。`[0x20000000:1]` 可指定宽度。命中后条件为假会自动继续，`--max-hits` 限制记录次数。

**交互式会话（GDB 式）**

```bash
scripts/dap.py repl --elf fw.elf
# 非交互批处理
scripts/dap.py repl --elf fw.elf -c "bp main" -c "run 5" -c "bt" -c "p g_state.mode" -c quit
```

一个连接内完成所有操作，断点/运行状态/core 选择在会话内保持，避免逐条命令重连。
命令集：`run/step/next/finish/line`、`bp`（含 `if EXPR` 条件）、`wp`、`bt`、`print`、`locals`、
`globals`、`regs`、`mem`、`disasm`、`fault`、`watch`、`core`、`source`。输入 `help` 查看。

**Trace / 性能**

```bash
scripts/dap.py swo --cpu-freq 72000000 --swo-freq 2000000 --duration 5
scripts/dap.py swo --raw /tmp/swo.bin --duration 10     # 同时保存原始流
scripts/dap.py profile --elf fw.elf --duration 5 --interval 0.01
scripts/dap.py cycles --enable --reset                  # 开始计数
scripts/dap.py cycles --hz 72000000                     # 读 CYCCNT 并换算秒
```

`swo` 直接把 ITM/printf 解码到终端，依赖探针支持 SWO（DAPLink v2 / ST-Link 可以，CMSIS-DAP v1 HID 通常不行，会明确报错）。
`profile` 通过周期性 halt 采样 PC，能定位热点但会扰动运行；无损剖析请用 `swo` 的 periodic PC 或 ETM。

**多核**

```bash
scripts/dap.py cores
scripts/dap.py regs --core 1
scripts/dap.py bp set main --core 1 --elf fw.elf
```

**flash 断点（谨慎）**

```bash
scripts/dap.py bp set 0x08001234 --type flash --yes   # 会擦写整块扇区
scripts/dap.py bp clear 0x08001234                    # 从备份恢复
```

原扇区会备份到 `~/.local/share/mcu-debug/flash_bp.json`；断电或恢复失败需要重新烧录。优先用 HW 断点。

**Semihosting**

```bash
scripts/dap.py semi --duration 10 --elf fw.elf
```
目标执行 `bkpt #0xAB` 时由主机服务 `SYS_WRITE0` 等请求，输出直接到终端；遇到真正的断点/异常会停下。

**上板自检**

```bash
scripts/dap.py selfcheck --elf fw.elf --json
```
非破坏性检查：探针、target、寄存器、内存/向量表、SP、HW 断点、CFI 回溯、行号、探针能力。
全通过退出码为 0。完整验收矩阵见 `references/validation.md`。

**断点命中脚本**

```bash
scripts/dap.py bp set 0x08001234 --on-hit "print r0; bt; continue" --max-hits 5 --wait 30
```
支持 `print EXPR`、`bt`、`continue`、`stop`、`silent`，分号分隔；命中后自动执行。

**故障定位与可视化**

```bash
scripts/dap.py diagnose --elf fw.elf --html /tmp/fault.html --rtt-log /tmp/rtt.log --open
```

一次采集并做规则推理，输出按置信度排序的根因假设（每条带证据和下一步），同时生成自包含 HTML：
内存映射上的 PC/SP/故障地址、故障标志位解码、回溯表、出错位置反汇编（高亮出错指令）、栈 hex（绿色标出可用作返回地址的字）。

规则覆盖：空指针（BFAR 接近 0）、外设时钟未开（故障地址落在 DEVICE 区）、栈溢出（SP 越出 RAM/MSTKERR/STKERR）、
执行了数据（PC 不在可执行段）、非法指令/Thumb 状态损坏、非精确总线错误（写缓冲延迟）、除零、非对齐、FPU 未使能、
栈保护触发（回溯含 `__stack_chk_fail`）等。

离线复用：`diagnose --save /tmp/crash.json`，之后 `diagnose --snapshot /tmp/crash.json --html report.html`，
不需要探针即可复盘（也适合把现场发给别人）。

**内存快照 / 对比**
```bash
scripts/dap.py snapshot save /tmp/ram.bin --addr 0x20000000 --len 0x4000
scripts/dap.py snapshot diff /tmp/ram.bin --addr 0x20000000
```
适合做“正常/异常两次运行”的 RAM 对比。

**需要完整 GDB 时**
```bash
scripts/dap.py gdb-batch --elf fw.elf -ex "bt full" -ex "info locals" -ex "p/x *0x40010808"
```
自动启动 `pyocd gdbserver`、跑完命令后关闭。前提是系统里有 `arm-none-eabi-gdb` / `gdb-multiarch`（或设 `DAP_GDB`）。没有 GDB 时以上原生命令覆盖大部分场景。

## 3. 命令速查

| 命令 | 作用 | 关键参数 |
|---|---|---|
| `doctor` | 环境 + 探针 + target 缓存诊断（WSL 含 Windows 侧探针） | `--attach` |
| `wsl status/attach/detach` | WSL：探测/挂载 Windows 侧 USB 探针 | `--busid`、`--dry-run` |
| `engines` | 列出 pyOCD / probe-rs 可用性 | 无 |
| `setup` | 建 venv、装 pyOCD | `DAPLINK_PYTHON` |
| `probes` / `connect` / `status` | 探针列表 / 连接并报 target / 运行状态 | `--json` |
| `targets` | 列出/搜索 target | `--search/-s`、`--limit/-n` |
| `pack search/install/list` | 管理 CMSIS-Packs | 查询词 |
| `flash FILE` | 烧录（默认校验） | `-t`、`-u`、`-f`、`-e`、`--base`、`--no-reset` |
| `verify FILE` | 只比对不写：ELF/HEX/BIN vs 目标内存 | `--base`、`--max-report` |
| `erase` | 擦除 | `--chip-erase`（危险）、`--range` |
| `reset` | 复位 | `--halt` |
| `halt` / `resume` / `step` | 运行控制 | `--count`、`--over`、`--out`、`--line` |
| `wait` | resume 后等命中 | `--cond`、`--log`、`--max-hits`、`--continue` |
| `bp set/list/clear` | 断点（hw/sw/auto/flash） | `SYMBOL`、`file.c:LINE`、`--cond`、`--on-hit`、`--wait`、`--all` |
| `wp set/list/clear` | 数据监视点 | `--size`、`--type r/w/rw` |
| `mem read/write ADDR` | 内存读写 | `--width 8/16/32`、`--count N` |
| `regs` / `regset NAME V` | 读 / 写核心寄存器 | `--json` |
| `state` | 寄存器 + Fault 解码 + 异常栈帧 | 无 |
| `fault` | 事后分析：Fault + 栈帧 + 回溯 + 栈用量 | `--limit`、`--max-stack` |
| `diagnose` | 根因推断 + 可选 HTML 报告 | `--html`、`--save`、`--rtt-log`、`--snapshot`、`--open` |
| `bt` | 回溯（符号 + 行号） | `--limit`、`--max-stack` |
| `disasm` | 反汇编 | `--at`、`--symbol`、`--count`、`--mode` |
| `sym list/find/addr` | 符号与地址/行号互查 | `--limit` |
| `vars globals/locals/print` | DWARF 变量（含结构体/数组/枚举） | `--filter`、`a.b.c` |
| `rtos` | RTOS 任务列表 | `--rtos freertos/rtx5/threadx/zephyr` |
| `snapshot save/load/diff` | RAM 快照与对比 | `--addr`、`--len` |
| `gdb-batch` | 外部 GDB 批处理（DWARF/表达式/条件断点） | `-ex ...`、`--elf` |
| `repl` | 长驻会话（GDB 式交互/批处理） | `-c 'cmd'`（可重复） |
| `cores` | 多核列表 | `--core` 用于其它命令 |
| `cycles` | DWT 周期计数器 | `--enable`、`--reset`、`--hz` |
| `profile` | PC 采样性能剖析 | `--duration`、`--interval`、`--top` |
| `swo` | SWO/ITM 实时 trace | `--cpu-freq`、`--swo-freq`、`--duration`、`--raw` |
| `semi` | ARM semihosting 控制台 | `--duration` |
| `selfcheck` | 上板非破坏性自检 | `--elf`、`--json` |
| `bp --type flash` | 写入 flash 的 BKPT 断点 | `--yes`（会擦写扇区） |
| `svd attach/list/read/write/field` | SVD 外设与位域 | `PERIPH.REG[.FIELD]`、`--svd` |
| `dapreg read/write` | 原始 DP 寄存器 | `ADDR [VALUE]` |
| `option read/write` | option bytes（必须显式地址） | `--addr`、`--yes` |
| `config get/set/unset/list` | 持久化默认值 | `target/probe/frequency/pack/elf/svd` |
| `rtt` | SEGGER RTT 日志 | `-a`、`--duration`、`-d` |
| `gdb` | 启 GDB server | `-p 3333`、`--detach`、`--persist` |
| `info` | 目标信息 | 通用会话参数 |

通用会话参数：`-t/--target`、`-u/--probe`、`-f/--frequency`、`--pack`、`--elf`（符号解析）、`--connect halt/pre-reset/under-reset/attach`、`--engine auto/pyocd/probe-rs`、`--chip`（probe-rs 器件名）。

**两个引擎**：默认 pyOCD（可运行时装 CMSIS-Pack，适合国产芯片、SVD、RTOS、故障分析）。
probe-rs 更快，且提供 RTT/defmt、SWO/ITM/ETF、统计剖析：

```bash
scripts/dap.py engines                                   # 看哪个可用
scripts/dap.py flash fw.elf --engine probe-rs --chip STM32F103RC
scripts/dap.py rtt --engine probe-rs --chip STM32F103RC --elf fw.elf
scripts/dap.py profile --engine probe-rs --chip STM32F103RC --elf fw.elf --duration 5
scripts/dap.py swo --engine probe-rs --chip STM32F103RC --duration 5
```

`--engine auto`（默认）在 probe-rs 可用且能解析出芯片名时自动选它；解析顺序是 `--chip` → config → 用 pyOCD target 名去 `probe-rs chip list` 做精确/唯一前缀匹配。器件名两边不同
（pyOCD `stm32f103rc` vs probe-rs `STM32F103RC`），用 `--chip` 明确指定。详见 `references/engines.md`。
默认值可持久化：`dap.py config set target stm32f103rc`，之后不必每条命令都写 `-t`。

硬件断点存放在 FPB 里，跨进程调用仍然有效，所以 `bp set 0x08000abc` 之后单独跑 `wait` 能命中；复位会清掉它们。

## 4. 安全边界

这些操作不可逆，执行前必须让用户明确确认：

- `erase --chip-erase`：擦掉整片 flash，包括 bootloader 和标定数据。
- `mem write` 到 option bytes / 读保护寄存器（如 STM32 的 `0x1FFFF800`、`0x40022020`）：写错会让芯片锁死或无法再次连接。
- `flash` 到错误 target：pyOCD 会按错误的内存映射下算法，可能写坏非 flash 区域。
- `bp set --type flash`：会擦除并重写整个扇区（含备份/恢复）；执行中掉电需要重新烧录。
- `swo`/`profile` 会改变目标运行状态；`profile` 的 halt 采样会让实时性敏感代码行为失真。

判断依据：如果用户没有明确说出"擦全片""解锁""写 option bytes"，就不要主动做。芯片被读保护锁住时，正确做法是提示用户用 `--connect under-reset` 或厂商工具解锁，而不是自己猜寄存器。

## 5. 排错

常见症状（探针不可见、权限、`target not found`、flash 超时、SWD 不稳、RTT 抓不到、GDB 连不上）都在
`references/troubleshooting.md`，按症状查，不要从头读。

脚本本身出问题时的定位顺序：`doctor` → 加 `pyocd -v` 看底层日志 → 看 `references/engines.md` 决定是否换引擎。

## 6. 什么时候换工具

与现成 `cmsis-dap-mcp` 的逐项能力对照见 `references/parity.md`（含 4 项未覆盖能力及替代方案）。

pyOCD 覆盖面最广（CMSIS-Pack、内置 flash 算法、RTT、gdbserver），但不是万能的：

- 芯片没有 CMSIS-Pack、pyOCD 也没有内置 target → 换 OpenOCD（见 `references/engines.md#没有-pack-的芯片`）。
- 需要更强的 RTT/SWO/实时变量采样 → 见 `references/engines.md` 的 probe-rs 方案。
- 需要 AI 直接持有结构化调试工具（而不是 shell 命令）→ 可接 `cmsis-dap-mcp`（npx 零安装），但那是另一套权限模型；本 skill 默认不引入。

先读 `references/engines.md` 再决定，不要在同一任务里混用两套引擎的命令。

## 7. 自测与 CI（无需硬件）

```bash
~/.local/share/mcu-debug/venv/bin/python -m pytest tests -q   # 101 tests, ~7s
scripts/dap.py setup --dev                                  # 安装 pytest
ruff check scripts tests                                    # 静态检查
```

CI 配置在 `.github/workflows/ci.yml`（Python 3.11/3.13，ruff + pytest）；
运行时版本固定为 `pyocd==0.46.0`（可用 `DAPLINK_PYOCD` 覆盖）。

测试用 `gcc -g` 生成的真实 DWARF ELF + 假目标/假内存，覆盖 ELF 解析、DWARF 类型与局部变量、
C 表达式、CFI 展开、故障规则、文本/HTML 报告、CLI 与 REPL。所有持久状态重定向到临时目录。
硬件相关路径（SWD 时序、flash 算法、SWO、多核芯片）仍需上板验证，见 `tests/README.md`。
