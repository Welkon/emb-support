# 方言与命令差异

`idn` 自动识别品牌；`--family` 可覆盖。所有命令都能用 `psu.py scpi "<命令>" --query` 绕过方言层。

## Rigol DP800（`rigol`）

```
:CHANnel<n>:VOLTage <v>        :CHANnel<n>:VOLTage?
:CHANnel<n>:CURRent <a>        :CHANnel<n>:CURRent?
:OUTPut CHANnel<n>,ON|OFF     :OUTPut? CHANnel<n>
:MEASure:VOLTage? CHANnel<n>
:MEASure:CURRent? CHANnel<n>
:MEASure:POWEr? CHANnel<n>
:CHANnel<n>:OVP <v>            :CHANnel<n>:OCP <a>
```

通道 1–3。DP832 的 CH3 通常是小电流通道。

## Keysight E36xx（`keysight`）

```
:INSTrument:NSELect <n>        # 选择输出
:VOLTage <v>                   :VOLTage?
:CURRent <a>                   :CURRent?
:OUTPut ON|OFF                 :OUTPut?
:MEASure:VOLTage?              :MEASure:CURRent?
:OUTPut:OVP:VOLTage <v>
```

E36312A 有三个输出；E3631A/E364xA 类似。OCP 因型号而异，本 skill 对 Keysight 只映射 OVP。

## Siglent SPD3303X（`siglent`）

```
:CH<n>:VOLT <v>                :CH<n>:VOLT?
:CH<n>:CURR <a>                :CH<n>:CURR?
:OUTP CH<n>,ON|OFF             :OUTP? CH<n>
:MEAS:VOLT? CH<n>              :MEAS:CURR? CH<n>
:MEAS:POW? CH<n>
```

通道 1–2；第三路（tracking）通常随 CH1/CH2。

## R&S HMC804x（`rns`）

```
:INSTrument:NSELect <n>
:VOLTage / :CURRent
:OUTPut:CHANnel<n>:STATe ON|OFF   :OUTPut:CHANnel<n>:STATe?
:MEASure:VOLTage? / :MEASure:CURRent?
```

HMC8041/2/3 的通道数分别为 1/2/3（本 skill 默认给出 1–4，超出会报错）。

## Korad / Tenma（`korad`，串口）

```
VSET<n>:<v>     ISET<n>:<a>
VSET<n>?        ISET<n>?
VOUT<n>?        IOUT<n>?
OUT<n>          # 1 = on, 0 = off
```

9600 8N1；不支持 OVP/OCP/Power 查询，功率由 V×I 计算。
`psu.py ... --serial /dev/ttyUSB0 --baud 9600`。

## GW Instek / BK Precision / Aim-TTi / Owon

这些型号的通道选择命令因系列而异，当前实现：

- `gwinstek` / `bkprecision`：`:INSTrument:NSELect` + 通用 `:VOLT`/`:CURR`/`:OUTP`
- `owon`：`:CH<n>:VOLT` / `:OUTP CH<n>,ON`
- `aimtti`：通用 `:VOLT` / `:CURR` / `:OUTP`

首次使用建议先 `idn` + `channels`，再用 `scpi` 核对关键命令。

## 新增品牌

在 `scripts/psuscpi/dialects.py` 继承 `Dialect`，覆盖：

- `channels`
- `set_voltage` / `set_current` / `get_voltage` / `get_current`
- `measure_voltage` / `measure_current` / `measure_power`（没有就返回 `None`）
- `output` / `output_state`（没有就返回 `None`）
- `ovp` / `ocp`（不支持返回 `None`）
- 多输出且需要选择的型号：`selected = True` + `select(n)`

注册到 `FAMILIES` 和 `detect_family()`，并补一条命令生成测试。

## 来源

- Rigol DP800 Programming Guide
- Keysight E36312A / E3631A / E364xA programming guides
- Siglent SPD3303X programming guide
- R&S HMC804x SCPI reference
- Korad KA3005P serial protocol
- `pymeasure` 的 Keysight E36xx 驱动（交叉验证）


## 非 SCPI 驱动

### 正点原子 DP100（`dp100`，USB HID）

协议参考 `lymzzyh/dp100-mcp`（MIT）与 `weigu1/dp100_manipulator`。

- VID:PID `2e3c:af01`，HID report 64 字节
- 帧：`FB op 00 len <data> crc_lo crc_hi`；CRC16-Modbus（poly 0xA001，init 0xFFFF）
- 响应：`FA op 00 len <data> crc`
- 操作码：`0x10` 设备信息、`0x30` 实时遥测、`0x35` 设定/输出、`0x40` 系统信息
- 遥测（`0x30`）：`vin, vout, iout, vo_max`（mV/mA），`out_mode`、`work_state`
- 设定（`0x35`，子命令 `0x20` + 输出位 + `v_mv, i_ma, ovp_mv, ocp_ma`）
- 最大电压由设备上报的 `vo_max` 决定（本 skill 会先读再限制）
- 依赖 `hidapi`；Linux 需要 hidraw 权限（udev/plugdev）

### FNIRSI DPS-150（`dps150`，USB CDC）

协议参考 `nasheed-x/dps150_api` 的 `PROTOCOL.md`。

- USB CDC，115200 8N1，RTS 置位
- 帧：`F1/F0 | cmd | reg | len | data | checksum`，`checksum = (reg+len+sum(data)) & 0xFF`
- 命令：`0xC1` 会话、`0xB1` 写寄存器、`0xA1` 读寄存器
- 关键寄存器：
  - `0xC1` 设定电压（float32 LE）
  - `0xC2` 设定电流（float32 LE）
  - `0xC3` 实测 V/I/P（3×float32）
  - `0xD1/0xD2` OVP/OCP
  - `0xDB` 输出开关（uint8）
  - `0xDE/0xE0` 型号/固件字符串
  - `0xE2/0xE3` 最大电压/电流
- 打开后先发会话包 `F1 C1 00 01 01 02`

### B&K 168x / Manson HCS-3xxx（`bk168x`，串口）

协议参考 `JacobBeningo/devpsu`（MIT）。

- 9600 8N1，命令以 CR 结尾，响应以 `OK` 行结束
- `VOLT123` = 12.3 V（3 位 + 1 位小数）
- `CURR050` = 5.0 A（1685B 用两位小数，需 `--current-decimals 2`）
- `GETS` → 设定值；`GETD` → 实测值 + CV/CC 标志
- `SOUT0` 开输出、`SOUT1` 关输出（注意是反的）
- `SOVP`/`SOCP` 设置保护；`GMAX` 读型号量程

### ITECH（`itech`，SCPI）

来自 ITECH IT6300 Programming Guide：

```
:INSTrument:NSELect <n>
:VOLTage / :CURRent
:OUTPut ON|OFF
:MEASure:VOLTage? / :CURRent? / :POWer?
:VOLTage:PROTection <v>
:CURRent:PROTection <a>
```

通道 1–3；IT6900 系列命令族相同。
