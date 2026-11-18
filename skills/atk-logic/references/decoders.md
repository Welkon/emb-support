# Protocol decoders

The ATK-Logic GUI ships the **sigrok decoder collection**: 209 decoders as plain
Python modules under `<install>/decoders/<id>/pd.py`, `api_version = 3`,
including every IR protocol (`ir_nec`, `ir_rc5`, `ir_rc6`, `ir_sirc`, `ir_irmp`,
`ir_ltto`, `ir_recoil`), UART/modbus, I²C, SPI, CAN, SWD, USB PD, DSI, 1-Wire,
DHT11/AM230x, WS2812 and the usual sensor/EEPROM decoders.

There is no headless entry point in the vendor software and no reusable
`libsigrokdecode` DLL (it is statically linked into `ATK-Logic.exe`). The
decoders themselves, however, are self-contained Python, so this skill hosts
them directly:

* `scripts/atklogic/pdhost.py` provides the `sigrokdecode` module the decoders
  import (`Decoder`, `OUTPUT_ANN/PYTHON/BINARY`, `SRD_CONF_SAMPLERATE`).
* Samples come from the capture's BIN files; the host answers each `wait()`
  from a precomputed change list, so no per-sample Python loop is involved for
  quiet lines.
* `self.options` starts from the decoder's own defaults and is overridden by
  `--option`.

The decoders are loaded **in place** from the installation. Nothing is copied
into this repository: they keep their own licence (GPLv2+/GPLv3+), and the
Apache-2.0 bundle only calls them, the same way it calls the vendor CLI.

## 复用分析：GUI 解码器能不能直接用（方案与结论）

问题：GUI 里已经有成熟的协议解析（IR 的 NEC/RC5/RC6/SIRC 等），技能能否直接复用，
而不是重写一套？

调查（命令跑在 ATK-Logic 安装目录与真实工程上，不是推测）：

| 事实 | 证据 |
|---|---|
| 解码器是 sigrok 的 Python 模块，不是厂商私有实现 | 209 个目录，208 个含 `pd.py`（`common/` 是共享库），208 个声明 `api_version = 3`；`ir_nec/pd.py` 头部就是 libsigrokdecode 的 GPL 版权行 |
| IR 一族齐全 | `ir_nec`, `ir_rc5`, `ir_rc6`, `ir_sirc`, `ir_irmp`, `ir_ltto`, `ir_recoil` |
| 没有可复用的库入口 | `ATK-Logic.exe` 的导入表里与解码相关的只有 `glib-2.0-0.dll`、`python37.dll`；全目录无 `libsigrokdecode*.dll`、无 `_sigrokdecode*.pyd`、`python37.zip` 里无 `sigrokdecode` 模块；`strings` 里有 “libsigrokdecode is already initialized” / “SIGROKDECODE_DIR” → libsigrokdecode 是**静态链进 exe** 的 |
| 没有无头入口 | 厂商文档只描述 CLI 的采集命令；GUI 无命令行/IPC；工程里 `Qt5RemoteObjects.dll` 是内部实现细节，未文档化 |
| 工程只存解码器“配置”，不存结果 | `BH-TS0013-09.atkdl` 的 `decodeJson` 只有 PWM/通道 0/active-high/注释行定义，180 KB 工程对应 120 027 行结果在导出的 CSV 里；`vernier.ini` 只有游标 |

三条候选路线：

1. **驱动 GUI**（pywinauto 点界面，或逆向 QtRemoteObjects）：不可行做底座——未文档化、仅
   Windows、GUI 和 CLI 会争同一台 USB 设备、厂商升级即坏，且需要人盯着窗口。
2. **复用 libsigrokdecode / 厂商内嵌解释器**：不可行——库是静态链接，没有导出入口；厂商的
   Python 3.7 运行时不对外暴露 `sigrokdecode` 模块。
3. **自己当宿主，原地加载厂商的 Python 解码器**：采用。需要实现的接口很小
   （`Decoder`、`put/register/wait/has_channel/metadata`、`OUTPUT_ANN/PYTHON/BINARY`、
   `SRD_CONF_SAMPLERATE`），样本来自我们本来就能读的 BIN；GPL 代码留在安装目录，仓库只调用、
   不复制，和调用厂商 CLI 同一性质。

**结论**：GUI 的协议解析能力可以脱离 GUI 复用，最成熟的一批（尤其 IR 全家族、UART/I2C/SPI/
CAN/SWD 等）已在本技能中可用；代价是实现并维护一个几十行的 `sigrokdecode` 兼容宿主，并锁定
厂商 fork 的 `api_version = 3` 语义（见下一节）。209 个里 99 个直接吃 logic，其余 109 个需要
上游码流——这是当前唯一的能力缺口，遇到时明确返回 `decoder_needs_stacking`，不会给出错误结果。
实现位于 `scripts/atklogic/pdhost.py`，行为由 `tests/test_pdhost.py` 覆盖（含厂商解码器集成
测试，未安装 ATK 时自动跳过）。

## Vendor fork differences

The shipped decoders expect two behaviours that differ from upstream
sigrokdecode. Both were verified against real decoding runs:

| behaviour | vendor fork | this host |
|---|---|---|
| `self.wait(cond)` | returns the levels at the matched sample, e.g. `(can_rx,) = self.wait({0: 'f'})` | returns `tuple(level[pin])` |
| `self.matched` | one entry per **condition** of the wait list | `(bool, ...)` in condition order |
| `self.samplerate` | set by the decoder's own `metadata(SRD_CONF_SAMPLERATE, ...)` | host calls `metadata(6, rate)` before `start()` |

Condition forms seen in the collection: `{pin: 'e'|'r'|'f'|'h'|'l'}`,
`{pin: level, pin2: level}` (AND), `{'skip': n}`, and lists of these (OR).

## Commands

```bash
# What can this installation decode?
scripts/atkla.py decoders --search ir
scripts/atkla.py decoders --search uart

# IR: the decoder needs one channel and a polarity option.
scripts/atkla.py decode evidence/ir --protocol ir_nec --ch ir=0 \
  --option polarity=active-low

# UART: 115200 8N1, one line, print ASCII.
scripts/atkla.py decode "D:/proj/uart.atkdl" --protocol uart --ch rx=0 \
  --option baudrate=115200 --option format=ascii --row rx-data-vals

# I²C: name the two lines and pick a window with traffic.
scripts/atkla.py decode evidence/i2c --protocol i2c --ch scl=7 --ch sda=6 \
  --window 49.9ms:52ms --row addr-data --row packets

# SPI: four lines, mode 0.
scripts/atkla.py decode evidence/spi --protocol spi \
  --ch sck=0 --ch mosi=1 --ch miso=2 --ch cs=3 --option cpol=0 --option cpha=0
```

`--ch NAME=ID` maps a **decoder** channel name (from `decoders`) to a capture
channel id. For a single-channel decoder, `--ch 0` is enough. Required channels
must all be present; unknown names or ids are errors, not guesses.

`--option KEY=VALUE` is type-checked against the decoder's declared default
(int/float/bool/string) and, when the decoder lists `values`, against that
list.

`--row ROW` keeps only the annotation rows asked for (`packets`,
`rx-data-vals`, `fields`, ...). Rows are what make a decoder readable: the
`bits` rows are noisy, the `data`/`packets` rows are the answer.

`--window START:END` (seconds, or `us`/`ms`/`s` suffixes) bounds the work;
`--max-samples` (default 50 M) and `--max-edges` (default 4 M) stop a window
that would be too large, with a suggestion to narrow it. A capture larger than
`--max-samples` is decoded from the start and reported with
`window.truncated: true`.

### IR specifics

Probe the **receiver's output pin**, not the LED: a TSOP/VS1838 output is
already demodulated (idle high, bursts low), which is exactly what `ir_nec`
and friends expect with their default `polarity=active-low`. Pointing the probe
at the LED itself shows the 38 kHz carrier and decodes as nothing. If a capture
produces no annotations, check in this order: channel mapping, `--option
polarity=active-high`, sample rate (≥ 1 MHz; 2–4 MHz is comfortable), and that
the window contains a frame.

## Output

```json
{
  "ok": true,
  "protocol": {"id": "ir_nec", "name": "IR NEC", "license": "gplv2+"},
  "channels": {"ir": 0},
  "options": {"polarity": "active-low", "cd_freq": 0, "extended": "no"},
  "window": {"startSample": 0, "samples": 88980, "seconds": 0.08898, "truncated": false},
  "counts": {"annotations": 41, "byRow": {"bits": 30, "fields": 7, "remote-vals": 1},
             "pythonEvents": 0, "droppedAnnotations": 0},
  "annotations": [
    {"start": 1000, "end": 10000, "class": "agc-pulse", "row": "bits", "texts": ["AGC pulse", "AGC", "A"]}
  ]
}
```

Annotations are sorted by time and capped (`--max-annotations`, default 5000);
`counts.droppedAnnotations` says how many were dropped. A decoder that stops
with an exception still returns its annotations plus `failure`; if it produced
none, the command fails with `decoder_failed`.

## What has been verified

| protocol | capture | result |
|---|---|---|
| UART | vendor `test/uart_tx_115200.atkdl`, ch0, 115200 | `ALIENTEK` repeated, 168 data annotations |
| I²C | vendor `test/eeprom_24c02_i2c.atkdl`, SCL=ch7 SDA=ch6 | `0x50 WR: 00 53`, `0x50 WR: 01 54` |
| IR NEC | synthetic demodulated frame, addr 0x00 cmd 0x45 | `Address: 0x00`, `Command: 0x45`, remote name from the decoder's own table |
| SPI | vendor `test/spi_flash_w25q128.atkdl`, clk=0 mosi=1 miso=2 cs=3 | MOSI bytes `54 4d 33 32 20 53 50 49 …` = `TM32 SPI TEST` |
| PWM | vendor `test/pwm_10M_30_25.atkdl`, ch0 | period 100 ns (10 MHz), duty 30 % — matches the file name |
| PWM (timing) | `read` on `BH-TS0013-09.atkdl` | duty 60.47 % vs the GUI export's 60.45 % |

## Limits

* **No stacking yet.** 99 of the 209 decoders take logic directly; the other
  109 (for example `modbus` on `uart`, `atsha204a` on `i2c`) need an upstream
  decoder's stream. Asking for one returns `decoder_needs_stacking` naming the
  upstream module. Decode the upstream protocol and read its `packets` row for
  now.
* Decoders decode the **logic level** of the captured line. Differential and
  line-coded buses (CAN transceiver output, USB PD BMC, MIPI DSI) decode only
  as far as the captured logic waveform allows; the annotation text is the
  decoder's own claim, not a bus-analyzer verdict.
* Sample rate still rules: at least 5× the fastest bit/symbol rate, 10× to be
  comfortable (115200 baud needs ≥ 1 MHz, 20 MHz is generous; IR NEC needs
  ≥ 1 MHz, 2-4 MHz is safer).
* `--decoders DIR` or `SIGROKDECODE_DIR` selects another collection; the config
  key `decoders` does the same.
