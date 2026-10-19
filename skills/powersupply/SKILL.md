---
name: powersupply
description: Control programmable bench power supplies over LAN (SCPI socket), USB (USBTMC/VISA) or serial — Rigol DP800, Keysight E36xx, Siglent SPD, Rohde & Schwarz HMC, GW Instek, BK Precision, Owon, Aim-TTi and Korad. Use this skill whenever the user mentions a power supply, PSU, bench supply, programmable source, SCPI voltage/current setpoints, OVP/OCP, output enable, voltage ramp, or asks to set/measure/log supply rails — including 可编程电源 / 直流电源 / 设电压 / 设电流 / 开输出 / 限流保护 / 电源老化记录 — even if they do not name the model. Also use it for safe output control and power-rail logging.
---

# Programmable Power Supply

通用可编程电源 CLI。结构：**传输层**（LAN socket / pyvisa / usbtmc / 串口）、**方言层**（按品牌生成 SCPI 或 Korad 串口命令）、**安全层**（电压/电流上限、输出联锁、回读校验）。

```bash
scripts/psu.py idn --host 192.168.1.60
scripts/psu.py set --host 192.168.1.60 --ch 1 --voltage 5 --current 1 --verify
scripts/psu.py output --host 192.168.1.60 --ch 1 on --yes
scripts/psu.py measure --host 192.168.1.60 --ch 1
```

## 0. 安全第一

电源比示波器危险，所有会让输出变化的操作都有保护：

- **默认上限**：`max_voltage=30 V`、`max_current=5 A`，超出直接拒绝。
  改上限：`--max-voltage 60` 或 `config set max_voltage 60`。
- **开输出必须 `--yes`**，否则拒绝执行。
- **`all-off`** 无需确认，用于紧急关闭所有通道。
- `ramp` / `sequence` 也必须 `--yes`；异常时会按 `safe_off`（默认开）关闭输出。
- `set` 只改设定值，不会自动开输出。
- 保护值（OVP/OCP）不替代硬件限流，先确认电源的物理量程。

## 1. 环境

```bash
scripts/psu.py doctor --host 192.168.1.60     # pyvisa / usbtmc / 串口 / 连通性
scripts/psu.py discover                       # VISA 资源
scripts/psu.py discover --scan 192.168.1.0/24 # 扫 5025 端口
scripts/psu.py setup                          # 安装 pyvisa/pyvisa-py/pyusb/pyserial
```

- LAN 用原生 socket，零依赖。
- USB 走 pyvisa（或 Linux `/dev/usbtmc*`）。
- Korad 等串口电源：`--serial /dev/ttyUSB0 --baud 9600`。
- DP100（USB HID）：`--hid dp100`（自动枚举设备）。
- DPS-150（USB CDC）：`--serial /dev/ttyACM0 --family dps150`。
- B&K 168x / Manson：`--serial /dev/ttyUSB0 --family bk168x`（1685B 加 `--current-decimals 2`）。
- Linux/WSL 权限：`scripts/install_udev.sh`。
- WSL 会自动检测：启动时识别 WSL；连接时若本地没有设备，会对 Windows 侧
  **已 Shared** 的电源自动执行 `usbipd attach`；`doctor --attach-usb` 可手动触发。

## 2. 品牌与方言

| family | 典型型号 | 命令风格 |
|---|---|---|
| `rigol` | DP832 / DP800 | `:CHANnel<n>:VOLTage`、`:OUTPut CHANnel<n>,ON` |
| `keysight` | E36312A / E3631A / E364xA | `:INSTrument:NSELect` + `:VOLTage` / `:OUTPut` |
| `siglent` | SPD3303X / SPD3303X-E | `:CH<n>:VOLT`、`:OUTP CH<n>,ON` |
| `rns` | HMC8041/2/3 | `:INSTrument:NSELect` + `:OUTPut:CHANnel<n>:STATe` |
| `korad` | KA3005P / Tenma | 串口 `VSET1:` / `ISET1:` / `OUT1` |
| `gwinstek` | GPP/GPD | 通道选择 + `:VOLT` / `:OUTP` |
| `bkprecision` | 9130B / 9200 | 通道选择 + `:VOLT` / `:OUTP` |
| `owon` | SPE/SPD 系列 | `:CH<n>:VOLT`、`:OUTP CH<n>,ON` |
| `aimtti` | PL/CPX 系列 | 通用 `:VOLT` / `:CURR` / `:OUTP` |
| `itech` | IT6300/IT6900 | `:INSTrument:NSELect` + `:VOLTage` / `:OUTPut` |
| `generic` | 其它 SCPI | `:VOLTage` / `:CURRent` / `:OUTPut` |
| `dp100` | 正点原子 DP100（0–30 V / 0–5 A / 100 W） | **USB HID**（hidapi） |
| `dps150` | FNIRSI DPS-150 | **USB CDC 串口**，F1/F0 帧 + float32 寄存器 |
| `bk168x` | B&K 1685B/1687B/1688B、Manson HCS-3xxx | 串口 ASCII（`VOLT123` / `GETD` / `SOUT0`） |

细节与来源见 `references/dialects.md`；排错见 `references/troubleshooting.md`。

## 3. 标准工作流

```bash
# 识别
scripts/psu.py idn --host <ip> --json
scripts/psu.py channels --host <ip>            # 通道数与能力

# 设限值（只改设定，不开输出）
scripts/psu.py set --host <ip> --ch 1 --voltage 5 --current 1 --verify

# 开输出（必须 --yes），再测量
scripts/psu.py output --host <ip> --ch 1 on --yes
scripts/psu.py measure --host <ip> --ch 1

# 记录 V/I/P
scripts/psu.py log --host <ip> --ch 1 --duration 30 --interval 0.5 --out rail.csv

# 关闭
scripts/psu.py output --host <ip> --ch 1 off
# 或紧急全关
scripts/psu.py all-off --host <ip>
```

## 4. 电压斜坡与序列

```bash
# 软件斜坡：0 V -> 12 V，每步 0.5 V，间隔 0.2 s
scripts/psu.py ramp --host <ip> --ch 1 --start 0 --to 12 --step 0.5 --delay 0.2 --yes

# JSON 序列
cat > seq.json <<'EOF'
{"steps": [
  {"voltage": 3.3, "current": 0.5, "delay": 1},
  {"voltage": 5.0, "current": 0.5, "delay": 2},
  {"voltage": 0.0, "current": 0.5, "delay": 0}
]}
EOF
scripts/psu.py sequence seq.json --host <ip> --ch 1 --yes
```

序列里每一步都会检查 `max_voltage/max_current`；异常时按 `safe_off` 关闭输出。

## 5. 命令速查

| 命令 | 作用 | 关键参数 |
|---|---|---|
| `idn` / `channels` | 识别与通道能力 | `--family` |
| `set` | 设电压/电流设定值 | `--ch`、`--voltage`、`--current`、`--verify` |
| `get` | 读设定值 | `--ch` |
| `measure` | 测 V/I/P | `--items voltage,current,power` |
| `output` | 开/关输出 | `on` 需 `--yes` |
| `all-off` | 关闭所有通道 | 无 |
| `protect` | OVP/OCP | `--ovp`、`--ocp` |
| `ramp` | 软件斜坡 | `--to`、`--start`、`--step`、`--delay`、`--yes` |
| `sequence` | JSON 序列 | 文件、`--yes` |
| `log` | V/I/P 记录 | `--duration`、`--interval`、`--out` |
| `web` | 本地网页 UI + 实时曲线 | `--bind`、`--web-port`、`--open` |
| `scpi` / `query` / `write` | 原始 SCPI（非 SCPI 设备会拒绝） | `--query` |
| `config` | 默认值与上限 | `host/resource/serial/max_voltage/max_current/safe_off` |

通用连接参数：`--host`、`--port 5025`、`--resource`、`--serial`、`--baud`、`--backend`、`--family`、`--timeout`、`--max-voltage`、`--max-current`。

## 5.5 网页 UI（独立使用）

```bash
scripts/psu.py web --hid dp100 --open
scripts/psu.py web --host 192.168.1.60 --bind 127.0.0.1 --web-port 8765
```

- 默认只绑定 `127.0.0.1`，不对外网开放；`--bind 0.0.0.0` 会暴露到局域网（无鉴权，谨慎）。
- WSL 下 `--open` 会用 **Windows 浏览器** 打开（通过 `cmd.exe start`/PowerShell）；
  地址用 `localhost`，WSL2 会自动转发。
- 页面是 **React + Tailwind + shadcn 风格**组件（已预构建在 `webapp/dist`），按设备
  `capabilities` 自动显示/隐藏 OVP、OCP、功率、输入电压和通道 tabs。
- 支持 **中/英** 与 **亮/暗** 主题切换（记忆到 localStorage）；实时曲线用
  **ECharts**（Canvas、双 Y 轴），**一张图同时显示电压和电流**，可用 V/A 按钮
  独立显隐；时间窗 10/30/60 秒可选，采样率 5/10/20/30 Hz 可选
  （DP100 默认 30 Hz，其他设备默认 10 Hz）。
- 实时数据走 **SSE**（`/api/stream`），DP100 每个采样只读一次 HID；服务端后台
  采样线程维护最近 4 分钟环形缓冲，`/api/history` 在页面打开时预填曲线，避免“刚打开没线”。
- 曲线默认**不缓存**：只保留当前时间窗（内部为支持 60 秒切换保留最近 62 秒）；
  可手动开缓存（最多 1 小时）用于 CSV 导出。刷新页面会清空，长期记录用 `log`。
- 顶部标题栏固定，Basic/Advanced 在标题栏内切换；用 **Framer Motion** 做 Tab 滑块、
  页面淡入、告警滑入等轻量动画，并遵循系统“减少动态效果”设置；Advanced 使用无卡片的分区布局，
  顶部指标条也做成扁平分隔条；时间窗、采样率、V/A 显隐会记住；
  控制区顶部是预设下拉框，选择电压+电流组合（3.3/5/9/12/24 V 默认组），可“保存当前”
  自定义；VSET/ISET 按 Enter 或移出输入框自动应用，聚焦后滚轮微调（Shift ×10、Alt ×0.1）；
  曲线可暂停，悬停显示该时刻 V/A 数值。
- 设备异常（断连、OVP/OCP/OPP/OTP/反接/欠压、温度 ≥60 °C）会弹出原生 `alert()`，
  并在右下角显示不改变页面布局的浮层告警（至少 10 秒），同时把浏览器标题改成 `⚠ ...`；
  恢复后再次异常会重新提醒。
- 提供：设压设流、输出 ON/OFF（ON 需要浏览器确认 + API `confirm`）、ALL OFF、
  OVP/OCP、实时 V/I/P/温度读数、设备信息、序列输出、电压/电流扫描、CSV 下载。
- DP100 的 `/api/state` 用一次 `snapshot()` 合并 HID 读取，不再为每个测量值各读一遍。
- 服务端同样执行电压/电流上限检查；网页不是绕过安全层的通道。

## 6. 安全边界

- 开输出、斜坡、序列必须 `--yes`；`set` 不会自动开输出。
- 任何设定先过电压/电流上限；`sequence` 逐步检查。
- `ramp`/`sequence` 异常时默认关输出（`safe_off`）。
- OVP/OCP 只是软件保护，不能替代硬件限流和保险丝。
- 带电池/电容负载时，关闭输出后端子仍可能有电压。

## 7. 自测

```bash
~/.local/share/psu/venv/bin/python -m pytest tests -q
scripts/psu.py setup --dev
```

测试使用本地 mock SCPI 电源（Rigol DP832 风格），不接触真实硬件。
