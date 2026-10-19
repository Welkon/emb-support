# 方言与命令差异

本 skill 用方言类生成 SCPI；`idn` 自动选择，`--family` 可覆盖。所有命令都可以用
`scope.py scpi "<任意 SCPI>" --query` 绕过方言层。

## 通道

| 操作 | rigol / keysight / siglent | tektronix | 通用 |
|---|---|---|---|
| 垂直档位 | `:CHANnel1:SCALe 0.5` | `:CH1:SCALe 0.5` | 同左 |
| 偏移 | `:CHANnel1:OFFSet 0` | `:CH1:OFFSet 0` | 同左 |
| 耦合 | `:CHANnel1:COUPling DC` | `:CH1:COUPling DC` | 同左 |
| 探头 | `:CHANnel1:PROBe 10` | `:CH1:PROBe 10` | 同左 |
| 显示 | `:CHANnel1:DISPlay ON` | `:CH1:DISPlay ON` | 同左 |

## 时基与触发

| 操作 | rigol | keysight | siglent | tektronix |
|---|---|---|---|---|
| 时基 | `:TIMebase:MAIN:SCALe` | `:TIMebase:SCALe` | `:TDIV` | `:HORizontal:SCAle` |
| 触发电平 | `:TRIGger:EDGE:LEVel` | 同左 | 同左 | `:TRIGger:A:EDGE:LEVel` |
| 触发源 | `CHANnel1` | `CHANnel1` | `C1` | `CH1` |
| 斜率 | `POSitive/NEGative` | 同左 | 同左 | `SLOpe RISe/FALL` |
| 扫描模式 | `:TRIGger:SWEep NORMal` | 同左 | 同左 | `:TRIGger:A:MODe NORMal` |

脉冲宽度触发目前只在 Tektronix 方言里映射：
`:TRIGger:A:TYPe PULSe` + `:PULse:WIDth:WHEn` + `:PULse:WIDth:WIDth` + `:PULse:POLarity`。
其它品牌会降级到边沿触发并给出警告；需要时用 `scpi` 发送品牌专用命令。

## 波形传输

### Rigol / Keysight / Siglent（`:WAVeform` 家族）

```
:WAVeform:SOURce CHANnel1
:WAVeform:FORMat BYTE
:WAVeform:POINts <n>        # 部分型号需要 :WAVeform:MODE RAW
:WAVeform:PREamble?         # format,type,points,count,xincr,xorig,xref,yincr,yorig,yref
:WAVeform:DATA?             # IEEE-488.2 block
```

电压：`(raw - yref) * yincr + yorig`；时间：`(i - xref) * xincr + xorig`。

Siglent 部分型号的 preamble 只有 5 个字段（points, xincr, xorig, yincr, yorig），
方言里已兼容。

### Tektronix（`CURVe?` + `WFMOutpre`）

本 skill 采用在 TBS1102B 上验证过的 ASCII 路径：

```
DATa:SOUrce CH1
DATa:ENCdg ASCII
DATa:WIDth 1
DATa:STARt 1
DATa:STOP <n>
CURVe?
```

缩放字段按 `WFMPre:*` → `WFMOutpre:*` → `WFMPRE:*` 顺序回退尝试：
`XINcr, XZEro, PT_Off, YMUlt, YZEro, YOFf, NR_Pt`。
电压：`(raw - YOFf) * YMUlt + YZEro`；时间：`(i - PT_Off) * XINcr + XZEro`。

## 截图

| 品牌 | 命令 | 说明 |
|---|---|---|
| Rigol | `:DISPlay:DATA?` | 返回 PNG/BMP，取决于型号 |
| Keysight | `:DISPlay:DATA? PNG,SCReen,COLor` | 标准 PNG |
| Siglent | `:SCReen:DATA?` / `:DISPlay:DATA?` | 固件差异大 |
| Tektronix | `:SAVE:IMAGe:FILEFormat PNG` | TBS1102B 的 hardcopy 主要走前面板/USB，不保证可下载 |
| LeCroy | `:HARDcopy:SETUP? PNG` | 取决于选件 |

`shot` 会依次尝试方言里的候选命令，只接受真正的 PNG/JPEG 数据。

## 测量

| 品牌 | 自动测量 | 说明 |
|---|---|---|
| Rigol | `:MEASure:VPP? CHANnel1` | 支持 VPP/VRMS/FREQ/PER 等 |
| Keysight | `:MEASure:VPP? CHANnel1` | 同上 |
| Siglent | `:MEASure:VPP? C1` | 同上 |
| Tektronix | 不映射 | 用 `capture` 后的波形计算 |
| LeCroy / 通用 | 不映射 | 同上 |

不支持的项会回退到波形计算（Vpp/Vmin/Vmax/mean/RMS/freq/period/duty/rise/fall）。

## 新增品牌

在 `scripts/scope.py` 里继承 `Dialect`，只覆盖不同的方法，然后注册到 `FAMILIES` 和
`detect_family()`。最少只需要覆盖：

- `ch()` / `timebase_scale()` / `trigger_*()`
- `acquire()`（如果波形传输不是 `:WAVeform` 家族）
- `measure_query()` / `screenshot_queries()`

加完用 mock server 写一条方言测试，避免回归。


## 新增方言（来自公开仓库）

以下命令集来自 GitHub 上经过实机验证的项目，按置信度标注。

| family | 来源 | 已验证内容 | 置信度 |
|---|---|---|---|
| `owon` | `bushjavier/hanmatek-dos1104-py`（Owon SDS1104 命令集，实机 V1.2.0） | 通道/时基/触发/测量/波形/截图 | 高 |
| `hantek` | `p96xl/hantek-dso2000-esu-tester`（DSO2C50，101 条查询实测 94 条应答） | 通道/时基/触发/测量/状态 | 中；波形只能走 `PRIVate:WAVeform:DATA:ALL?` |
| `micsig` | `tralamazza/micsig-rs`（MHO14-200N） | run/stop/single、测量、截图 | 中；波形导出未实现 |
| `bkprecision` | `robertozeitoun/bkprecision`（LeCroy MAUI 命令集） | 通道/时基/触发/测量/波形（WAVEDESC） | 中高；波形解析已实现 |
| `unit` / `fluke` / `zlg` | 仅 IDN 识别 | 无 | 低；按通用 SCPI 处理 |

### OWON / Hanmatek 的自定义帧

与 IEEE-488.2 块不同：

- 波形和截图：`[4 字节小端长度][payload]`
- `:DATA:WAVE:SCREEN:HEAD?` 返回 JSON header（时基、采样率、每通道 V/div、探头）
- 采样点是 16 位小端 ADC 码；`volts = code * V/div / 6400`
- 查询回复以 `->` 结尾，需要去掉；测量回复形如 `Vpp : 2.040V->`，带单位

### Hantek DSO2000

- 测量：`:MEASure:CHANnel<n>:ITEM? VPP`（不是 `:MEAS:CH1:PKPK?`）
- 时基位置是 `:TIMebase:POSition`，不是 `:TIMebase:OFFSet`
- `:MEASure:...:ITEM? VRMS` 返回的是频率，不要用；RMS 用波形计算
- 波形导出：`PRIVate:WAVeform:DATA:ALL?`（私有格式，本 skill 不做解码）

### Micsig

- 查询判定按 header 里的 `?`，参数化查询如 `:MEASure:PKPK? CH1` 不以 `?` 结尾
- 波形块的长度字段是采样点数而不是字节数，raw TCP 会读断；只用 USB 或 `micsig-rs`
- 截图 `:SYS:SCR?` 返回 JPEG（固件 JFIF 头可能损坏，需修复）

### BK Precision / LeCroy MAUI

- 通道 `C1:VDIV`、`C1:OFST`、`C1:CPL`
- 时基 `TDIV`
- 触发 `TRMD`、`TRLV`、`TRSL`、`TRSE EDGE,SR,C1,...`
- 测量 `C1:PAVA? VPP`
- 波形 `C1:WF? DAT2` 返回 WAVEDESC + 采样点；已实现解析：
  `comm_type`（8/16 位）、`wave_array_1`、`wave_array_count`、
  `vertical_gain/offset`、`horiz_interval/offset`，以及 `C1:WF? DAT2` 前的命令回显前缀。
  `volt = gain * raw - offset`；`time = i * interval + horiz_offset`。
- BK Precision 2540/2560 直接复用该方言（`BkPrecisionDialect(LeCroyDialect)`）


## 搜索引擎找到的厂商手册（国产为主）

用 Brave 搜索（Bing RSS 对中文/型号会串结果，DuckDuckGo 被拦）拿到以下官方或半官方文档。

| 品牌 | 文档 | 关键结论 |
|---|---|---|
| UNI-T 优利德 | [UPO 3000E/2000E Programming Manual](https://unitrend.oss-cn-hongkong.aliyuncs.com/uploads/attach/20250624/171046f30ffda67ff849c78002191.pdf) | `:CHANn:SCAL`、`:TIMebase:SCALe`、`:WAVeform:PREamble?`（10 字段）、`:DISPlay:DATA?` |
| Micsig 麦科信 | [Micsig SCPI Command Manual](https://www.micsig.com/uploads/Micsig-Oscilloscope-SCPI-Command-Manual-EN-2024.5.21_1716272598.pdf) | `:TIMebase:EXTent`、`:MENU:RUN/STOP/SINGLE`、`:WAVeform:PREamble?`（**9 字段**） |
| PeakTech | [SCPI 13 Series Oscilloscope v1.5](https://www.peaktech.de/media/e7/ac/4c/1638517336/SCPI%2013%20Series%20Oscilloscope%20v1.5.pdf) | 与 Owon 同协议（`:DATA:WAVE:SCREen:HEAD?`、4 字节长度帧） |
| Fluke | [PM3370/3380/3390 SCPI User's Manual](https://xdevs.com/doc/Fluke/Fluke%20PM%203370,%203380,%203390%20Series%20SCPI%20User's%20Manual.pdf) | `SENSe:SWEep:TIME`、`TRACe? CHn`、`TRIGger:SOURce INTernaln` |
| Hantek 汉泰 | [DSO2000 SCPI Programmer's Manual](https://www.hantek.com/uploadpic/hantek/files/20211231/DSO2000%20Series%C2%A0SCPI%C2%A0Programmers%C2%A0Manual.pdf) | `:MEASure:CHANnel<n>:ITEM?`、私有波形导出 |
| Siglent 鼎阳 | [SDS Programming Guide](https://siglentna.com/wp-content/uploads/dlm_uploads/2023/04/SDS-Series_ProgrammingGuide_EN11D.pdf) | 已在 `siglent` 方言覆盖 |
| Rigol 普源 | [MSO/DS1000Z Programming Guide](https://www.batronix.com/files/Rigol/Oszilloskope/_DS&MSO1000Z/MSO_DS1000Z_ProgrammingGuide_EN.pdf) | 已在 `rigol` 方言覆盖 |
| R&S / Hameg | [HMO1002 Programming Manual](https://www.batronix.com/files/Rohde-&-Schwarz/Oscilloscope/HMO1xx2/HMO1002_1202_ProgrammingManual_en.pdf) | 与 Keysight 风格一致，`rns` 方言可用 |

### UNI-T UPO（`unit`）

- 通道：`:CHAN<n>:SCAL`、`:OFFS`、`:COUP`、`:PROB`、`:DISP`
- 时基：`:TIMebase:SCALe`、`:TIMebase:OFFSet`
- 触发：`:TRIGger:MODE EDGE`、`:TRIGger:SOURce CHAN<n>`、`:TRIGger:LEVel`、`:TRIGger:EDGE:SLOPe POSitive|NEGative`、`:TRIGger:SWEep AUTO|NORMal|SINGle`
- 采集：`:RUN` / `:STOP`；单次 = `:TRIGger:SWEep SINGle` + `:RUN`
- 波形：`:WAVeform:FORMat BYTE`、`:WAVeform:SOURce CHAN<n>`、`:WAVeform:POINts`、`:WAVeform:PREamble?`、`:WAVeform:DATA?`
- 测量：`:MEASure:VPP? CHAN<n>`、`VMAX`、`VMIN`、`VAVerage`、`VRMS`、`FREQuency`、`PERiod`
- 截图：`:DISPlay:DATA?`

### Micsig（`micsig`）

- 通道：`:CHANnel<n>:SCALe`、`:POSition`、`:COUPle`、`:PROBe`、`:DISPlay`
- 时基：`:TIMebase:EXTent`（s/div）、`:TIMebase:POSition`
- 运行：`:MENU:RUN` / `:MENU:STOP` / `:MENU:SINGLE`；状态 `:TRIGger:STATus?`
- 触发：`:TRIGger:EDGE:SOURce CH<n>`、`:SLOPe RISE|FALL`、`:LEVel`；扫描 `:TRIGger:MODE AUTO|NORMal`
- 波形：`:WAVeform:SOURce CH<n>`、`:MODE NORMal`、`:FORMat BYTE`、`:STARt/:STOP`、`:PREamble?`
- **preamble 只有 9 个字段**（无 points，用 count），方言里单独解析
- 截图：`:SYS:SCR?`（JPEG；固件 JFIF 头可能损坏）
- 波形块长度字段在部分固件里是采样点数而不是字节数，raw TCP 可能读断；USB 更稳

### PeakTech（`peaktech`）

与 Owon 完全同协议：`:CH<n>:SCAL`、`:HORIzontal:Scale`、`:DATA:WAVE:SCREen:HEAD?`、
采样点 16 位小端、volts = code × V/div ÷ 6400。继承 `OwonDialect`。

### Fluke CombiScope（`fluke`）

- 通道开关：`SENSe:FUNCtion:ON "XTIMe:VOLTage<n>"`
- 垂直：`SENSe:VOLTage:RANGe:PTPeak`、`SENSe:VOLTage:RANGe:OFFSet`
- 时基：`SENSe:SWEep:TIME`、`SENSe:SWEep:OFFSet:TIME`
- 触发：`TRIGger:SOURce INTernal<n>`、`TRIGger:LEVel`
- 波形：`TRACe:POINts CH<n>,<n>` + `TRACe? CH<n>`（带仪器相关缩放，本 skill 未实现）

### 搜索过但没找到公开 SCPI 的

- **ZLG 致远 ZDS 系列**：官网/搜索引擎/GitHub 均未找到可用的 SCPI 编程手册，保留 `zlg` 识别 + 通用命令。
- **ATTEN 安泰信**：同样未找到公开命令集，保留 `atten` 识别 + 通用命令。
- **Iwatsu、Chroma、Kenwood**：没有可用的现代 SCPI 手册（Iwatsu 多为老模拟机，Chroma 以校准仪为主）。
- **PicoScope / Digilent / Saleae / DSLogic**：走厂商 SDK 或 sigrok，不是 SCPI 方言；要支持需单独后端。
