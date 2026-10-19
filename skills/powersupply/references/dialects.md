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
