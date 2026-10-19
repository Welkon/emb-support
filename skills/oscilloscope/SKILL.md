---
name: oscilloscope
description: Control bench oscilloscopes over LAN (SCPI socket) or USB (USBTMC/VISA) from any brand — Rigol, Keysight/Agilent, Tektronix, Siglent, LeCroy, Rohde & Schwarz, GW Instek, Yokogawa and generic SCPI instruments. Use this skill whenever the user mentions an oscilloscope, scope, SCPI, VISA, USBTMC, VXI-11, waveform capture, trigger setup, probe/channel configuration, screen capture, 示波器 / 抓波形 / 看波形 / 调触发 / 测频率 / 截图, or asks to inspect a signal on real hardware — even if they do not name the brand. Also use it for intermittent-fault monitoring (arm, wait, capture evidence) and for analyzing exported waveform CSV files.
---

# Oscilloscope

统一的示波器 CLI。核心是三层：**传输层**（LAN 原生 socket / pyvisa / usbtmc 内核设备）、**方言层**（按品牌生成 SCPI）、**采集层**（波形反缩放、测量、证据落盘）。

```bash
scripts/scope.py idn --host 192.168.1.50                 # 自动识别品牌/方言
scripts/scope.py capture --host 192.168.1.50 --channels 1,2 --out run.csv
scripts/scope.py measure --host 192.168.1.50 --channel 1 --items vpp,rms,freq
scripts/scope.py shot --host 192.168.1.50 --out screen.png
```

## 0. 先判断三件事

1. **接口**：LAN（`--host`，端口 5025）还是 USB（`--resource USB0::...::INSTR`）。
2. **品牌**：`idn` 会自动从 `*IDN?` 识别；识别错时用 `--family` 覆盖。
3. **是否需要改动仪器状态**：只读查询（`idn`/`measure`/`capture`）优先；改通道/时基/触发前先说明。

## 1. 环境

```bash
scripts/scope.py doctor --host 192.168.1.50   # pyvisa / usbtmc / 端口连通性
scripts/scope.py list                        # VISA 资源（USB/VXI-11）
scripts/scope.py discover --scan 192.168.1.0/24   # 局域网扫 5025 端口 + *IDN?
scripts/scope.py setup                       # 需要 USB/VXI-11 时安装 pyvisa/pyvisa-py/pyusb
```

- **LAN 路径零依赖**：用原生 TCP socket，不装 pyvisa 也能用。
- **USB 路径**需要 pyvisa + pyvisa-py（或 Linux `usbtmc` 内核设备）。
- Linux/WSL 权限：`scripts/install_udev.sh`（Tek/Rigol/Siglent/Keysight/LeCroy/R&S/Yokogawa/GW Instek）。
- WSL 的 USB 还需要 Windows 侧 `usbipd attach --wsl --busid X-Y`。

## 2. 品牌与方言

`idn` 的 `family` 字段决定命令拼写。已内置：

| family | 典型设备 | 备注 |
|---|---|---|
| `rigol` | DHO800/900, MSO5000, DS1000Z | `:TIMebase:MAIN:SCALe`、`:WAVeform:PREamble?` |
| `keysight` | InfiniiVision DSO/MSO | `:TIMebase:SCALe`、PNG 截图 |
| `tektronix` | TBS/TDS/DPO/MSO | ASCII `CURVe?` + WFMPre/WFMOutpre 回退 |
| `siglent` | SDS 系列 | `:TDIV`、`C1` 通道写法 |
| `lecroy` | WaveRunner/WaveSurfer | 测量走波形计算 |
| `rns` | Rohde & Schwarz | 复用 Keysight 方言 |
| `gwinstek` | GDS 系列 | `:MEASure:*? CHANnelN` |
| `owon` | OWON XDS / Hanmatek DOS/SDS | 自定义 4 字节长度帧 + JSON header |
| `peaktech` | PeakTech 13xx（Owon 协议） | 与 `owon` 相同，官方 SCPI 手册确认 |
| `hantek` | Hantek DSO2000 (DSO2C50) | 控制/测量已验证；波形导出为厂商私有命令 |
| `micsig` | Micsig MHO 系列 | `:MENU:RUN/STOP`、`:MEASure:*? CHn`、`:SYS:SCR?` 截图 |
| `bkprecision` | BK 2540/2560 | LeCroy MAUI 命令集（`C1:VDIV`、`TRMD`、`C1:PAVA?`） |
| `unit` | UNI-T UPO 2000E/3000E | 官方编程手册：`:CHANn:SCAL`、`:WAVeform:*` |
| `fluke` | Fluke PM3370/80/90 CombiScope | SCPI-99 风格：`SENSe:SWEep:TIME`、`TRACe?` |
| `atten` / `zlg` | 安泰信、致远 ZDS | 未找到公开 SCPI 手册，仅识别 + 通用命令 |
| `yokogawa` / `generic` | 其它 SCPI 设备 | 通用命令 + `scpi` 逃生口 |

品牌细节、来源与置信度见 `references/dialects.md`；Tektronix 专项（含 Windows TekVISA）见 `references/tektronix.md`。
OWON/Hantek 的自定义帧和私有波形导出限制也记录在 `references/dialects.md`。

## 3. 标准工作流

```bash
# 1) 识别
scripts/scope.py idn --host <ip> --json

# 2) 只读检查（不改状态）
scripts/scope.py scpi --host <ip> ":TRIGger:STATe?" --query
scripts/scope.py measure --host <ip> --channel 1 --items vpp,rms,freq,period

# 3) 需要时再配置
scripts/scope.py channel  --host <ip> --ch 1 --scale 0.5 --offset 0 --coupling DC --probe 10
scripts/scope.py timebase --host <ip> --scale 1e-3
scripts/scope.py trigger  --host <ip> --source 1 --level 0.8 --slope rising --mode normal

# 4) 采集与证据
scripts/scope.py run single --host <ip>
scripts/scope.py capture --host <ip> --channels 1,2 --points 10000 --out captures/run.csv --json
scripts/scope.py shot --host <ip> --out captures/run.png
```

采集优先用**数值波形**（CSV/JSON），截图只作为人看的补充：CSV 可 diff、可做统计、可喂给 AI。

## 4. 间歇故障：`monitor`

```bash
# 触发一次，抓证据
scripts/scope.py monitor --host <ip> --channels 1 --max-events 1 \
  --trigger-type edge --trigger-source 1 --trigger-level 1.0 \
  --timebase 5e-6 --outdir captures --prefix glitch

# 预设（glitch-short / power-on-spike / intermittent-noise / missing-pulse / burst-pulse）
scripts/scope.py monitor --host <ip> --preset glitch-short --channels 1 --auto-rearm --max-events 5

# 只看会写哪些命令，不碰硬件
scripts/scope.py monitor --host <ip> --preset glitch-short --dry-run
```

`monitor` 会：配置 → 单次触发/序列触发 → 轮询 `:TRIGger:STATe?` / `:ACQuire:STATE?` → 命中后导出
`captures/<prefix>-NN.csv` + `.json`（含统计）→ 可选自动重新武装。
不支持脉冲触发的方言会降级为边沿触发并在 stderr 警告。

## 5. 命令速查

| 命令 | 作用 | 关键参数 |
|---|---|---|
| `idn` | `*IDN?` + 方言检测 | `--family` |
| `list` / `discover` | VISA 资源 / 子网扫描 | `--scan`、`--backend` |
| `doctor` | 环境与连通性诊断 | `--host` |
| `channel` | 垂直档位/偏移/耦合/探头 | `--ch`、`--scale`、`--offset`、`--coupling`、`--probe` |
| `timebase` | 时基 | `--scale`、`--offset` |
| `trigger` | 边沿触发 | `--source`、`--level`、`--slope`、`--mode` |
| `run` | run/stop/single/autoscale | 子命令 |
| `capture` | 波形采集 | `--channels`、`--points`、`--out`、`--format csv/json/npz` |
| `measure` | 自动测量（不支持时用波形计算） | `--channel`、`--items` |
| `shot` | 截图（PNG/JPEG） | `--out` |
| `scpi` / `query` / `write` | 原始 SCPI 逃生口 | `--query` |
| `monitor` | 事件监视 + 证据导出 | 见第 4 节 |
| `analyze` | 离线分析 CSV | `--csv` |
| `config` | 持久化默认 host/resource/family/timeout/backend | `set/get/list/unset` |

通用连接参数：`--host`、`--port 5025`、`--resource`、`--backend`、`--family`、`--timeout`、`--json`。

## 6. 安全边界

- `channel/timebase/trigger/run/autoscale` 会改变仪器实时状态。用户没有明确要求时，先只读。
- 写命令前先记录原值（`scpi ...? --query`），必要时能恢复。
- 高阻/高压场景先确认探头衰减与耦合；不要假设 10×。
- `monitor` 会重新武装/停止采集；确认不会影响用户正在看的波形。
- 截图/长采集可能占用前面板；结束前把仪器恢复到用户原来的状态。

## 7. 排错

连接失败、USBTMC 权限、WSL、二进制块截断、截图不支持、Windows TekVISA 位数问题，见
`references/troubleshooting.md` 和 `references/tektronix.md`。

## 8. 自测

```bash
~/.local/share/scope/venv/bin/python -m pytest tests -q
scripts/scope.py setup --dev
```

测试使用本地 mock SCPI server（Rigol 与 Tek 两种方言），不接触真实硬件。
