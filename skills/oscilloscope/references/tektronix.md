# Tektronix 专项

Tektronix 的 SCPI 方言与 Rigol/Keysight 差异较大，这里记录已经验证过的路径和坑。

## 连接

TBS1102B 只有 USB Device 口，**没有 LAN**。优先用 USBTMC：

```
USB0::0x0699::0x0368::<serial>::INSTR
```

```bash
scripts/scope.py list                      # 需要 pyvisa
scripts/scope.py idn --resource "USB0::0x0699::0x0368::C012345::INSTR"
```

WSL：

```powershell
usbipd list
usbipd attach --wsl --busid 2-3
```

Linux 权限：

```bash
scripts/install_udev.sh        # 0699 = Tektronix
```

## Windows + TekVISA 位数（最常见的坑）

在 Windows 上用厂商 TekVISA runtime 时，Python 和 `visa32.dll` 的位数必须一致：

- 用 **32 位 Python**（例如单独的 venv）。
- **不要**传 `--backend @py`；省略 `--backend`，让 PyVISA 自动加载厂商 DLL。
- 需要显式路径时用 32 位的：
  `C:\Program Files (x86)\IVI Foundation\VISA\WinNT\TekVISA\Bin\Visa32.dll`
  而不是缺少 `(x86)` 的 64 位路径。
- 位数不匹配的典型报错：`VI_ERROR_INV_OBJECT` / “Could not find module ... Visa32.dll”。

本 skill 的默认行为：Windows 上 `backend=None`（自动），Linux/macOS 上 `@py`。可用
`--backend auto` 或 `config set backend auto` 覆盖。

确认方式：

```bash
python -m pyvisa.info     # 看 Backends 与 bitness
```

## 波形采集（已验证路径）

TBS1102B 上验证的是 ASCII `CURVe?`：

```
DATa:SOUrce CH1
DATa:ENCdg ASCII
DATa:WIDth 1
DATa:STARt 1
DATa:STOP <n>
CURVe?
```

缩放字段按以下顺序回退（不同固件拼写不同）：

| 字段 | 候选 |
|---|---|
| XINcr | `WFMPre:XINcr?` → `WFMOutpre:XINcr?` → `WFMPRE:XINCR?` |
| XZEro | `WFMPre:XZEro?` → `WFMOutpre:XZEro?` → `WFMPRE:XZERO?` |
| PT_Off | `WFMPre:PT_Off?` → `WFMOutpre:PT_Off?` → `WFMPRE:PT_OFF?` |
| YMUlt | `WFMPre:YMUlt?` → `WFMOutpre:YMUlt?` → `WFMPRE:YMULT?` |
| YZEro | `WFMPre:YZEro?` → `WFMOutpre:YZEro?` → `WFMPRE:YZERO?` |
| YOFf | `WFMPre:YOFf?` → `WFMOutpre:YOFf?` → `WFMPRE:YOFF?` |
| NR_Pt | `WFMOutpre:NR_Pt?` → `WFMPre:NR_Pt?` |

换算：

```
time    = XZEro + (i - PT_Off) * XINcr
voltage = (raw - YOFf) * YMUlt + YZEro
```

注意：

- `CURVe?` 返回空时，先确认源通道在屏幕上处于显示状态。
- `DATA:STOP` 不要超过记录长度；深存储时先读 `:ACQuire:POINts?` 或 `WFMOutpre:NR_Pt?`。
- ASCII 模式比二进制慢，但兼容性最好；大点数采集可以改用 RIBinary（本 skill 暂用 ASCII）。

## 触发与间歇故障

TBS1102B 支持单次/序列触发：

```
ACQuire:STOPAfter SEQuence
ACQuire:STATE RUN
TRIGger:STATe?
```

`monitor` 在 Tektronix 方言下就是走这条路径：配置 → `STOPAfter SEQuence` + `RUN` → 轮询
`ACQuire:STATE?`（0 = 已停）→ 命中后采集 → 可选重新武装。

脉冲宽度触发：

```
TRIGger:A:TYPe PULSe
TRIGger:A:PULse:WIDth:WHEn LESSthan|GREATERthan
TRIGger:A:PULse:WIDth:WIDth <seconds>
TRIGger:A:PULse:POLarity POSitive|NEGative
```

## 截图

TBS1102B 的 hardcopy 主要走前面板/USB PictBridge，没有一个稳定的通用下载命令。
`shot` 会尝试 `:SAVE:IMAGe:FILEFormat PNG` 和 `:DISPlay:DATA?`，失败时会明确报错。
这种型号优先用 `capture` 的 CSV 作为证据，不要依赖截图。

## 已验证的控制项

删掉的旧 `tektronix-scope` 技能里有一份在 TBS1102B 上逐条验证过的控制目录（127 个可用
键，含 query/set/action 模板）。已提取到 `references/tektronix-tbs1000b.md`，用
`scope.py scpi` 发送即可。

常用命令：

| 用途 | 命令 |
|---|---|
| 垂直档位 | `CH1:SCAle 0.5` |
| 垂直位置 | `CH1:POSition 0` |
| 耦合 | `CH1:COUPling DC` |
| 探头 | `CH1:PRObe 10` |
| 时基 | `HORizontal:SCAle 1e-3` |
| 触发电平 | `TRIGger:A:EDGE:LEVel 0.8` |
| 触发斜率 | `TRIGger:A:EDGE:SLOpe RISe` |
| 采集状态 | `ACQuire:STATE RUN` / `STOP` |
| 单次序列 | `ACQuire:STOPAfter SEQuence` |
| 波形源 | `DATa:SOUrce CH1` |
| 曲线 | `CURVe?` |


## 实机验证（TBS 1102B，WSL）

- WSL 内核没有 `usbtmc` 模块，`/dev/usbtmc*` 不会出现；走 **pyvisa-py + pyusb + libusb-package**。
  `scope.py setup` 会安装 `libusb-package`，`scope.py` 启动时自动 re-exec 到该 venv。
- 采集顺序必须是**先读文本 preamble、再读 `CURVe?`**；反过来会出现 `WFMOutpre:NR_Pt?` 超时。
- `WFMOutpre:NR_Pt?` 在 TBS 上不可靠，已不再查询，点数用实际样本数。
- 连续采集用 `:ACQuire:STOPAfter RUNSTOP` + `:ACQuire:STATE RUN`；只发 `:RUN` 会保持停止。
- 截图查询会破坏 USBTMC 队列，TBS 方言已禁用 `shot`（返回明确错误）。
- 若链路因外部超时进入 desync，最可靠的是 `usbipd detach` + `attach` 重新枚举。
