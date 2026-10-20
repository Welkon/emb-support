# Dialects and command differences

The skill uses a dialect class for each instrument family. The `idn` command selects the dialect automatically. Use `--family` to select a dialect manually.

To send a command that the dialect layer does not support, use the `scpi` command:

```bash
scripts/scope.py scpi --host <ip> "<SCPI command>" --query
```

## Channel commands

| Function | Rigol, Keysight, Siglent | Tektronix | Generic |
|---|---|---|---|
| Vertical scale | `:CHANnel1:SCALe 0.5` | `:CH1:SCALe 0.5` | Same as left |
| Offset | `:CHANnel1:OFFSet 0` | `:CH1:OFFSet 0` | Same as left |
| Coupling | `:CHANnel1:COUPling DC` | `:CH1:COUPling DC` | Same as left |
| Probe ratio | `:CHANnel1:PROBe 10` | `:CH1:PROBe 10` | Same as left |
| Display | `:CHANnel1:DISPlay ON` | `:CH1:DISPlay ON` | Same as left |

## Timebase and trigger commands

| Function | Rigol | Keysight | Siglent | Tektronix |
|---|---|---|---|---|
| Timebase | `:TIMebase:MAIN:SCALe` | `:TIMebase:SCALe` | `:TDIV` | `:HORizontal:SCAle` |
| Trigger level | `:TRIGger:EDGE:LEVel` | Same | Same | `:TRIGger:A:EDGE:LEVel` |
| Trigger source | `CHANnel1` | `CHANnel1` | `C1` | `CH1` |
| Slope | `POSitive` or `NEGative` | Same | Same | `SLOpe RISe` or `FALL` |
| Sweep mode | `:TRIGger:SWEep NORMal` | Same | Same | `:TRIGger:A:MODe NORMal` |

The Tektronix dialect maps pulse-width trigger commands:

```
:TRIGger:A:TYPe PULSe
:TRIGger:A:PULse:WIDth:WHEn LESSthan|GREATERthan
:TRIGger:A:PULse:WIDth:WIDth <seconds>
:TRIGger:A:PULse:POLarity POSitive|NEGative
```

Other families use an edge trigger and write a warning. Use `scpi` to send a vendor-specific pulse trigger command.

## Waveform transfer

### Rigol, Keysight, and Siglent

```
:WAVeform:SOURce CHANnel1
:WAVeform:FORMat BYTE
:WAVeform:POINts <n>        # Some models also need :WAVeform:MODE RAW
:WAVeform:PREamble?         # format,type,points,count,xincr,xorig,xref,yincr,yorig,yref
:WAVeform:DATA?             # IEEE-488.2 block
```

Use these formulas:

```
voltage = (raw - yref) * yincr + yorig
time    = (i - xref) * xincr + xorig
```

Some Siglent models return a preamble with 5 fields: points, xincr, xorig, yincr, and yorig. The dialect supports this format.

### Tektronix

The skill uses the ASCII path that was verified on a TBS 1102B:

```
DATa:SOUrce CH1
DATa:ENCdg ASCII
DATa:WIDth 1
DATa:STARt 1
DATa:STOP <n>
CURVe?
```

The dialect tries these scaling fields in this order: `WFMPre:*`, then `WFMOutpre:*`, then `WFMPRE:*`.

The fields are `XINcr`, `XZEro`, `PT_Off`, `YMUlt`, `YZEro`, and `YOFf`.

```
voltage = (raw - YOFf) * YMUlt + YZEro
time    = (i - PT_Off) * XINcr + XZEro
```

Read the text fields before you read `CURVe?`. If you read text after the curve, the transfer can leave bytes in the queue.

### OWON and Hanmatek

OWON uses a custom frame. It does not use an IEEE-488.2 block.

- Waveform and screenshot frame: `[4-byte little-endian length][payload]`
- `:DATA:WAVE:SCREEN:HEAD?` returns a JSON header. The header contains the timebase, the sample rate, the V/div for each channel, and the probe ratio.
- Each sample is a 16-bit little-endian ADC code.
- `voltage = code * V/div / 6400`
- A query reply ends with `->`. Remove this suffix.
- A measurement reply has a unit, for example `Vpp : 2.040V->`.

### Hantek DSO2000

The private export command is `PRIVate:WAVeform:DATA:ALL?`. The reply has several packets:

```
[0:2]    "#9"
[2:11]   9-digit packet length
[11:20]  9-digit total byte count (total)
[20:29]  9-digit current offset (off)
[29:128] 99-byte header (channel enable bits at [46:50])
[128:]   data (int8, interleaved in 2000-sample blocks per channel)
```

Join the packets in `off` order.

```
voltage = code / 25 * V/div - offset
dt      = :WAVeform:XINCrement?
```

Do not use `:MEASure:...:ITEM? VRMS`. This query returns a frequency on this firmware. Calculate the RMS value from the waveform.

The timebase position command is `:TIMebase:POSition`. The command `:TIMebase:OFFSet` does not exist.

### Micsig

- A query has a `?` in the header. A parameterized query such as `:MEASure:PKPK? CH1` does not end with `?`.
- The length field of a waveform block is the sample count, not the byte count. A raw TCP read can stop early. Use USB, or use the `micsig-rs` tool.
- `:SYS:SCR?` returns a JPEG image. The JFIF header can be corrupt. Repair the header before you use the image.
- The preamble has 9 fields: format, type, count, xincr, xorig, xref, yincr, yorig, yref. The dialect parses this format.

### LeCroy and BK Precision (MAUI)

- Channel: `C1:VDIV`, `C1:OFST`, `C1:CPL`
- Timebase: `TDIV`
- Trigger: `TRMD`, `TRLV`, `TRSL`, `TRSE EDGE,SR,C1,...`
- Measurement: `C1:PAVA? VPP`
- Waveform: `C1:WF? DAT2` returns a WAVEDESC descriptor and the samples.

The WAVEDESC parser reads these fields:

- `comm_type` (8-bit or 16-bit samples)
- `wave_array_1` (data length in bytes)
- `wave_array_count`
- `vertical_gain` and `vertical_offset`
- `horiz_interval` and `horiz_offset`

The parser also accepts a command echo before `#9`, for example `C1:WF DAT2,#9...`.

```
voltage = gain * raw - offset
time    = i * interval + horiz_offset
```

BK Precision 2540 and 2560 use the same dialect: `BkPrecisionDialect(LeCroyDialect)`.

### Rohde & Schwarz and Hameg

- Set `FORMat UINT,8`.
- Read `CHANnel<n>:DATA?`.
- Read `CHANnel<n>:DATA:XINCrement?`, `XORigin?`, `YINCrement?`, and `YORigin?`.

```
voltage = raw * YINCrement + YORigin
time    = i * XINCrement + XORigin
```

This dialect applies to the HMO1002 and HMO1202. The RTB and RTO families use the same commands.

### Fluke CombiScope

- Channel on and off: `SENSe:FUNCtion:ON "XTIMe:VOLTage<n>"`
- Vertical: `SENSe:VOLTage:RANGe:PTPeak`, `SENSe:VOLTage:RANGe:OFFSet`
- Timebase: `SENSe:SWEep:TIME`, `SENSe:SWEep:OFFSet:TIME`
- Trigger: `TRIGger:SOURce INTernal<n>`, `TRIGger:LEVel`
- Waveform: `FORMat INTeger,8|16`, then `TRACe:POINts CH<n>,<n>`, then `TRACe? CH<n>`

The reply has a format byte, the samples, a checksum, and a newline. A 16-bit sample is big-endian.

```
voltage = raw / 200 * PTPeak - offset       (8-bit)
voltage = raw / 51200 * PTPeak - offset     (16-bit)
time    = -sweep/2 + i * sweep / points
```

## Screenshot commands

| Family | Command | Note |
|---|---|---|
| Rigol | `:DISPlay:DATA?` | Returns PNG or BMP. The format depends on the model. |
| Keysight | `:DISPlay:DATA? PNG,SCReen,COLor` | Standard PNG. |
| Siglent | `:SCReen:DATA?` or `:DISPlay:DATA?` | The command depends on the firmware. |
| Tektronix | `:SAVE:IMAGe:FILEFormat PNG` | A TBS 1102B saves hardcopy to the front panel or a USB device. A host download is not available. |
| LeCroy | `:HARDcopy:SETUP? PNG` | The command depends on the option. |
| OWON | `:DATA:WAVE:SCREEN:BMP?` | Custom frame with a BMP payload. |
| Micsig | `:SYS:SCR?` | JPEG. |
| R&S | `:DISPlay:DATA?` | Model-dependent. |

The `shot` command tries each candidate command for the dialect. It accepts only PNG, JPEG, or BMP data. When no command works, the skill captures CH1 and writes an SVG waveform plot. The JSON output has `fallback: waveform-plot`.

## Measurement commands

| Family | Automatic measurement | Note |
|---|---|---|
| Rigol | `:MEASure:VPP? CHANnel1` | Supports VPP, VRMS, FREQ, and PER. |
| Keysight | `:MEASure:VPP? CHANnel1` | Same. |
| Siglent | `:MEASure:VPP? C1` | Same. |
| Tektronix | Not mapped | The skill calculates the value from the waveform. |
| LeCroy and generic | Not mapped | The skill calculates the value from the waveform. |
| OWON | `:MEAS:CH<n>:PKPK?` | The reply has a label and a unit. |
| Hantek | `:MEASure:CHANnel<n>:ITEM? VPP` | Supports 33 item types. Do not use VRMS. |
| Micsig | `:MEASure:PKPK? CH<n>` | Supports a small set of items. |
| UNI-T | `:MEASure:VPP? CHAN<n>` | Supports VPP, VMAX, VMIN, VAVerage, VRMS, FREQuency, and PERiod. |

When the instrument cannot measure an item, the skill calculates the value from the waveform. The fallback covers Vpp, Vmin, Vmax, mean, RMS, frequency, period, duty, rise, and fall.

## Dialect sources and confidence

| Family | Source | Verified content | Confidence |
|---|---|---|---|
| `owon` | `bushjavier/hanmatek-dos1104-py` (Owon SDS1104, firmware V1.2.0) | Channel, timebase, trigger, measurement, waveform, screenshot | High |
| `hantek` | `p96xl/hantek-dso2000-esu-tester` (DSO2C50, 94 of 101 queries answered) | Channel, timebase, trigger, measurement, state, waveform | Medium-high |
| `micsig` | `tralamazza/micsig-rs` (MHO14-200N) | Run, stop, single, measurement, screenshot | Medium. Waveform export is not implemented. |
| `bkprecision` | `robertozeitoun/bkprecision` (LeCroy MAUI) | Channel, timebase, trigger, measurement, waveform | Medium-high. The WAVEDESC parser is implemented. |
| `unit` | UNI-T programming manual | Channel, timebase, trigger, waveform | High |
| `fluke` | Fluke PM3390 manual | Channel, timebase, trigger, TRACe waveform | Medium. The TRACe formula comes from the manual. |
| `zlg` | No public manual | IDN detection only | Low. Uses generic SCPI. |

## Vendor manuals found with a search engine

The skill used the Brave search engine to find these documents. Bing RSS returned incorrect results for some model numbers. DuckDuckGo blocked the requests.

| Brand | Document | Key result |
|---|---|---|
| UNI-T | [UPO 3000E/2000E Programming Manual](https://unitrend.oss-cn-hongkong.aliyuncs.com/uploads/attach/20250624/171046f30ffda67ff849c78002191.pdf) | `:CHANn:SCAL`, `:TIMebase:SCALe`, `:WAVeform:PREamble?` (10 fields), `:DISPlay:DATA?` |
| Micsig | [Micsig SCPI Command Manual](https://www.micsig.com/uploads/Micsig-Oscilloscope-SCPI-Command-Manual-EN-2024.5.21_1716272598.pdf) | `:TIMebase:EXTent`, `:MENU:RUN/STOP/SINGLE`, `:WAVeform:PREamble?` (9 fields) |
| PeakTech | [SCPI 13 Series Oscilloscope v1.5](https://www.peaktech.de/media/e7/ac/4c/1638517336/SCPI%2013%20Series%20Oscilloscope%20v1.5.pdf) | Same protocol as Owon: `:DATA:WAVE:SCREen:HEAD?` and a 4-byte length frame |
| Fluke | [PM3370/3380/3390 SCPI User's Manual](https://xdevs.com/doc/Fluke/Fluke%20PM%203370,%203380,%203390%20Series%20SCPI%20User's%20Manual.pdf) | `SENSe:SWEep:TIME`, `TRACe? CHn`, `TRIGger:SOURce INTernaln` |
| Hantek | [DSO2000 SCPI Programmer's Manual](https://www.hantek.com/uploadpic/hantek/files/20211231/DSO2000%20Series%C2%A0SCPI%C2%A0Programmers%C2%A0Manual.pdf) | `:MEASure:CHANnel<n>:ITEM?`, private waveform export |
| Siglent | [SDS Programming Guide](https://siglentna.com/wp-content/uploads/dlm_uploads/2023/04/SDS-Series_ProgrammingGuide_EN11D.pdf) | The `siglent` dialect covers these commands. |
| Rigol | [MSO/DS1000Z Programming Guide](https://www.batronix.com/files/Rigol/Oszilloskope/_DS&MSO1000Z/MSO_DS1000Z_ProgrammingGuide_EN.pdf) | The `rigol` dialect covers these commands. |
| R&S and Hameg | [HMO1002 Programming Manual](https://www.batronix.com/files/Rohde-&-Schwarz/Oscilloscope/HMO1xx2/HMO1002_1202_ProgrammingManual_en.pdf) | The commands match the Keysight style. The `rns` dialect covers them. |

### UNI-T UPO

- Channel: `:CHAN<n>:SCAL`, `:OFFS`, `:COUP`, `:PROB`, `:DISP`
- Timebase: `:TIMebase:SCALe`, `:TIMebase:OFFSet`
- Trigger: `:TRIGger:MODE EDGE`, `:TRIGger:SOURce CHAN<n>`, `:TRIGger:LEVel`, `:TRIGger:EDGE:SLOPe POSitive|NEGative`, `:TRIGger:SWEep AUTO|NORMal|SINGle`
- Acquisition: `:RUN` and `:STOP`. For a single capture, use `:TRIGger:SWEep SINGle` and then `:RUN`.
- Waveform: `:WAVeform:FORMat BYTE`, `:WAVeform:SOURce CHAN<n>`, `:WAVeform:POINts`, `:WAVeform:PREamble?`, `:WAVeform:DATA?`
- Measurement: `:MEASure:VPP? CHAN<n>`, `VMAX`, `VMIN`, `VAVerage`, `VRMS`, `FREQuency`, `PERiod`
- Screenshot: `:DISPlay:DATA?`

### Micsig

- Channel: `:CHANnel<n>:SCALe`, `:POSition`, `:COUPle`, `:PROBe`, `:DISPlay`
- Timebase: `:TIMebase:EXTent` (s/div), `:TIMebase:POSition`
- Run: `:MENU:RUN`, `:MENU:STOP`, `:MENU:SINGLE`. State: `:TRIGger:STATus?`
- Trigger: `:TRIGger:EDGE:SOURce CH<n>`, `:SLOPe RISE|FALL`, `:LEVel`. Sweep: `:TRIGger:MODE AUTO|NORMal`
- Waveform: `:WAVeform:SOURce CH<n>`, `:MODE NORMal`, `:FORMat BYTE`, `:STARt`, `:STOP`, `:PREamble?`
- The preamble has 9 fields. It has a count field but no points field.
- Screenshot: `:SYS:SCR?` (JPEG)

### PeakTech

PeakTech uses the Owon protocol:

- `:CH<n>:SCAL`
- `:HORIzontal:Scale`
- `:DATA:WAVE:SCREen:HEAD?`
- 16-bit little-endian samples
- `voltage = code * V/div / 6400`

### Hantek private waveform

See the Hantek section above. The skill joins the packets by `off`. The sample scaling is `code / 25 * V/div - offset`.

### Fluke CombiScope

See the Fluke section above. A 16-bit sample is big-endian. The skill calculates the time axis from `SENSe:SWEep:TIME`.

## Brands with no public SCPI reference

- **ZLG ZDS series:** The vendor site, search engines, and GitHub have no usable SCPI manual. The skill keeps `zlg` for device identification and uses generic commands.
- **ATTEN:** The skill found no public command set. It keeps `atten` for device identification and uses generic commands.
- **Iwatsu, Chroma, Kenwood:** The skill found no modern SCPI manual.
- **PicoScope, Digilent, Saleae, DSLogic:** These products use a vendor SDK or sigrok. They are not SCPI instruments. They need a separate backend.

## Add a new dialect

1. Create a class that inherits from `Dialect` in `scripts/scopescpi/dialects/`.
2. Override only the methods that are different.
3. Add the class to `FAMILIES` and to `detect_family()` in `dialects/__init__.py`.
4. Add a test with the mock server.

The minimum set of methods is:

- `ch()`, `timebase_scale()`, and the `trigger_*()` methods
- `acquire()` when the waveform transfer is not a `:WAVeform` command
- `measure_query()` and `screenshot_queries()`
