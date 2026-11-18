---
name: atk-logic
description: Capture digital timing with an ATK-Logic analyzer (ALIENTEK DL16 / DL32, ATK-PTDL16/32) through the vendor's atk-logic-cli JSONL CLI, then decode it — timing facts (duty, edges, pulse widths, CSV, VCD) and protocol semantics (IR NEC/RC5/RC6/SIRC, UART/Modbus, I2C, SPI, CAN, SWD, 1-Wire, DHT11, WS2812) using the 209 sigrok decoders the ATK GUI ships. Use this skill whenever the user mentions a logic analyzer, ATK-Logic, DL16, DL32, atk-logic-cli, ATKDL, digital timing capture, channel/trigger/sample-rate setup, OR asks to decode a bus or a remote: UART/I2C/SPI/IR/CAN/SWD frames, 逻辑分析仪, 时序采集, 抓数字波形, 采样率, 触发, 协议解码, 红外解码, 遥控器, 串口解码, even when no brand is named. Also use it for GUI-saved .atkdl projects, GUI decode CSVs, and turning a capture into evidence another tool can open.
---

# ATK Logic Analyzer

This skill answers bench questions about digital lines on an ATK-Logic analyzer.
The interface is **intents** — "what is plugged in", "capture this line",
"what did I capture" — never the vendor's command line.

1. **Intent layer.** `doctor`, `list`, `info`, `caps`, `capture`, `read`,
   `series`, `decode`, `decoders`. One invocation answers one question and
   returns one JSON object with `--json`.
2. **Protocol layer.** `atklogic/protocol.py` speaks either one-shot commands or
   the vendor's `session --stdio --mode ai` JSONL stream and keeps its event
   flood out of the result.
3. **Decode layer.** `atklogic/decode.py` reads the vendor's LSB-first bit
   packing and computes timing facts; `atklogic/pdhost.py` hosts the GUI's own
   sigrok protocol decoders, so IR remotes, UART, I2C, SPI and 200 other
   protocols decode with the vendor's mature implementations.

```bash
# What is on the bench?
scripts/atkla.py doctor
scripts/atkla.py info

# What can this device do with two channels enabled?
scripts/atkla.py caps --ch 0,1

# One capture that returns evidence, not a file name.
scripts/atkla.py capture --ch 0:none --ch 2:rising --freq 1m --time 100ms \
  --threshold 1.8 --out evidence/uart

# Decode a protocol with the GUI's own decoders (IR, UART, I2C, SPI, CAN, ...).
scripts/atkla.py decoders --search ir
scripts/atkla.py decode evidence/ir --protocol ir_nec --ch ir=0

# Later, or for a GUI project: statistics, edges, VCD for PulseView.
scripts/atkla.py read evidence/uart --json
scripts/atkla.py read evidence/uart --vcd evidence/uart/trace.vcd --csv evidence/uart/edges.csv --csv-transitions
```

## Measured on hardware (native USB, ch2 only)

Current bench: only panel **CH2** is wired (scope calibration source, 1 kHz / 50 %).
Channel numbering in the protocol is zero-based, so a capture with only CH2 wired
shows activity on channel 2 and a constant level everywhere else.

| run | samples | duty | frequency |
|---|---|---|---|
| `usb capture --ch 2:none --freq 2m --time 100ms` | 200 064 | 49.97 % | — |
| `usb capture --ch 2:none --freq 10m --time 100ms` | 1 000 064 | **50.07 %** | **994.8 Hz** |
| vendor CLI, same signal | 1 000 000 | 50.07 % | 990.0 Hz |

Sample count equals rate x duration exactly on both runs, so the time base is right;
`references/native-usb.md` explains why the frequency must come from the median edge
interval (edge counting reports 1234.9 Hz because of 23 two-sample glitches).

## 0. Rules that keep a capture honest

1. **Never guess a frequency or a duration.** The device accepts a profile-
   dependent set of pairs. `capture` asks `device.capabilities` first and picks
   the legal pair closest to the request, then reports every substitution under
   `adjustments`. `--strict` refuses instead of adjusting.
2. **Know what waits for a trigger.** `none` captures immediately; `rising`,
   `falling`, `high`, `low` and `both` wait until the line reaches that
   condition. With no probe attached that never happens, so `capture` stops
   after `--trigger-timeout` seconds of silence (default 20) with
   `trigger_not_found` and keeps whatever the buffer already held. Use
   `--ch N:none` when you only want "what is on the line right now".
3. **One capture at a time.** Wait for `idle` before the next one; `capture`
   does this, and a second run against a busy device returns `device_busy`.
4. **Do not overwrite capture directories.** The vendor CLI refuses an existing
   output path; this skill does too (`output_conflict`). Failed runs keep
   `.bin.partial` files — `read` uses them when the named BIN is absent, and
   nothing renames or deletes them.
5. **Do not force-kill during a capture.** `capture` stops with
   `capture.stop`, then waits for the device to unwind. Killing the process can
   leave the analyzer needing a replug.

## 1. First contact

```bash
scripts/atkla.py doctor --json     # CLI found? staging writable? device enumerated?
scripts/atkla.py info --json       # model, real channel count, USB speed, firmware
scripts/atkla.py list --json       # just the enumeration
```

`info` connects briefly and prints the *actual* channel range
(`usableChannels`, e.g. `0-31`), which is the only authority on channel ids —
`profileComplete:false` in `doctor` is normal right after enumeration.

Device ids are `dl16:<port>` or `dl32:<port>` (this bench: `dl32:1`). `capture`
lists devices first, takes the only one automatically, and raises
`multiple_devices` (with the ids) when several are attached. Channel ids are
checked against the device profile before anything is sent; `--device-id`
overrides the choice.

## 2. Capture

```bash
scripts/atkla.py capture --ch 0:rising --ch 1:none --freq 2m --time 50ms
scripts/atkla.py capture --ch 0,1,2,3 --freq 20m --time 200ms --mode stream
scripts/atkla.py capture --ch 0:none --format both --out evidence/i2c   # BIN + GUI project
```

| flag | meaning |
|---|---|
| `--ch ID[:TRIGGER]` | repeatable; `0,1,2` is shorthand for three `none` channels |
| `--freq` | sample rate: `1m`, `2.5MHz`, `20000000` |
| `--time` | capture time: `10ms`, `1s`, `500us`, or plain ms |
| `--threshold` | one threshold for all channels, volts in `[-5, 5]` (default 1.8) |
| `--position` | trigger position in percent (default 50) |
| `--mode` | `buffer` (device memory, may enable RLE) or `stream` (as fast as USB sustains) |
| `--format` | `bin` (default), `atkdl` (GUI project), `both` |
| `--out` | evidence directory; default `captures/atk_<stamp>` |
| `--strict` | refuse an unsupported rate/time instead of adjusting |
| `--trigger-timeout` | seconds of silence before a waiting capture is stopped (0 = forever) |
| `--one-shot` | one CLI process per step instead of a JSONL session (escape hatch) |

The result carries the execution facts, not just a path:

```json
{
  "ok": true,
  "capture": {
    "status": "complete", "mode": "buffer",
    "frequencyHz": 1000000, "durationMs": 10, "rle": false,
    "channels": [{"id": 0, "trigger": "none"}],
    "analysis": [{"channel": 0, "bits": 10000, "duty": 0.053,
                  "edges": 9428, "cycleRateHz": 47140.0, "stuck": false}]
  },
  "adjustments": [],
  "timing": {"seconds": 3.0, "deviceSeconds": 4.4}
}
```

`capture` analyses the BIN immediately, so "is the line toggling at all" is
answered without a second command. `--no-analyze` skips it for huge traces.

Sizing: samples = `frequencyHz × durationMs / 1000` per channel, one bit each.
A 20 MHz × 10 s capture is 200 Mbit per channel — legal on this device (as a GUI
project it ships 24 MiB of chunks) but not something to read bit by bit.

## 3. Read a capture

```bash
scripts/atkla.py read evidence/uart                       # per-channel statistics
scripts/atkla.py read evidence/uart --json                # the same as data
scripts/atkla.py read evidence/uart --csv edges.csv --csv-transitions
scripts/atkla.py read evidence/uart --vcd trace.vcd       # PulseView / GtkWave
scripts/atkla.py read "D:/proj/my.atkdl" --ch 0 --extract /tmp/proj
```

`read` accepts a capture directory, its `capture.json`, or an `.atkdl` project
(saved by the GUI or produced with `--format atkdl`). A project's
`project.decoders` lists the GUI decoder configuration; the decoded rows are not
in the project, only in an exported CSV, which `--gui-csv FILE` summarises
(annotation counts, min/max/mean per row, units from percent/ns/hz). For a project it unpacks
the per-channel chunks into a temporary directory, honours the project's real
sample count (chunk padding is not data) and removes the copy afterwards unless
`--extract DIR` is given.

Reported per channel: `bits`, `ones`, `duty`, `edges`, `rises`, `falls`,
`firstLevel`, `lastLevel`, `runCount`, `minRunBits`/`maxRunBits` (pulse widths),
`glitches` (with `--glitch-ns`), `cycleRateHz`, `edgeRateHz`, `minPulseUs`,
`maxPulseUs`, and `stuck: true` for a line that never moved.

Limits are explicit, not silent: counts and duty are computed for any size with
big-integer bit tricks, but pulse widths need a per-bit walk and are skipped
above 8 M samples unless `--run-lengths` is passed. CSV and VCD refuse above
50 M samples; slice with `--start`/`--count` or `--ch`.

Bit order, if you read the BIN yourself: sample 0 is bit 0 of byte 0, sample 7
is bit 7, then the next byte continues. `validBits` in `capture.json` is the
only truth about length; the unused high bits of the last byte are zero.

## Simulated signals (no hardware)

When no driver circuit is available, any VCD-producing simulator stands in for the
analyzer. Icarus Verilog (3.7k stars) is enough; `sim/` ships a minimal I2C master
testbench.

```bash
iverilog -B "$IVL" -o i2c.vvp sim/i2c_tb.v && vvp -M "$IVL" i2c.vvp
scripts/atkla.py sim --vcd /tmp/iv/i2c.vcd --scl scl --sda sda_line --rate 10m --out /tmp/sim_i2c
scripts/atkla.py decode /tmp/sim_i2c --protocol i2c --ch scl=0 --ch sda=1 --row packets
# 0.1000 ms  packets  0x50 WR: 00 53
```

`sim` writes the same layout a capture has (`capture.json` plus `channel_N.bin`),
so `read`, `decode` and `--csv` work unchanged. Details and the install recipe
(no root needed) are in `references/simulation.md`. Simulation proves decoder
wiring and options; it cannot prove real levels, glitches or trigger behaviour.

## Find a staged condition (software trigger)

The device has one simple trigger, so multi-stage conditions are resolved after
acquisition instead of on hardware:

```bash
scripts/atkla.py find evidence/i2c --stage 2:rising --stage 4:high --within 10ms --limit 5
```

`--stage CH:STATE` repeats (`rising`, `falling`, `high`, `low`, `both`); the search
starts at every match of the first stage and walks forward through the rest,
bounded by `--within`. Each hit reports the sample and time of every stage.

The same search runs straight off a live acquisition with `usb find`, which
captures on the native USB path and searches the fresh samples without writing
files:

```bash
scripts/atkla.py usb find --ch 2:none --freq 10m --time 100ms \
    --stage 2:rising --stage 2:low --within 4us --limit 3
# → hits at 306.2 us, 1311.5 us, 2316.9 us (one per 1 kHz cycle)
```

## Measure bursts (blinks, PWM bursts, mode changes)

```bash
scripts/atkla.py bursts evidence/blink --ch 2 --min-gap 1ms
```

Splits a channel into bursts separated by `--min-gap` of silence and reports, per
burst: start/end time, duration, average duty, **duty at the start and end plus the
min/max over 20 slices** (`dutyTrend`: `ramp-up` / `ramp-down` / `steady`), edge
count, median-period frequency and the gap before it. A breathing light is a ramp,
so the average alone hides it: one measured burst went 0.82 % → 99.26 % while
averaging 50.05 %. `rampMs` is the time between the lowest and the highest slice,
which answers "how long does dimming take": 495.6 ms on a 498.1 ms breathing
segment. On a real product capture this printed three 498 ms bursts at
50.06 % duty with 32 258 Hz PWM, separated by 8 ms gaps.

## Watch a folder

```bash
scripts/atkla.py watch --dir ~/proj --once        # scan once
scripts/atkla.py watch --dir ~/proj --interval 5  # keep polling
```

Each new `.atkdl` prints samples, channel count and frequency; unreadable files
report an error code instead of stopping the loop.

## 4. Decode a protocol (the GUI's decoders)

The GUI ships the sigrok decoder collection (209 modules, including every IR
protocol). `decode` runs those modules directly on the capture — same
decoders, same options, no GUI and no extra install.

```bash
scripts/atkla.py decoders --search ir          # ir_nec, ir_rc5, ir_rc6, ir_sirc, ...
scripts/atkla.py decode evidence/ir --protocol ir_nec --ch ir=0
scripts/atkla.py decode evidence/uart --protocol uart --ch rx=0 \
  --option baudrate=115200 --option format=ascii --row rx-data-vals
scripts/atkla.py decode evidence/i2c --protocol i2c --ch scl=7 --ch sda=6 \
  --window 49.9ms:52ms --row packets
scripts/atkla.py decode evidence/spi --protocol spi \
  --ch sck=0 --ch mosi=1 --ch miso=2 --ch cs=3

# A decoder on another decoder's stream, and the GUI's CSV shape.
scripts/atkla.py decode evidence/rs485 --protocol uart+modbus \
  --ch rx=0 --option baudrate=115200 --option modbus.scchannel=TX --csv modbus.csv
```

- `--ch NAME=ID` maps a decoder channel to a capture channel (`--ch 0` for
  single-channel decoders). Required channels are checked.
- `--option KEY=VALUE` is type-checked against the decoder's defaults and its
  allowed values.
- `--row` keeps the readable rows (`packets`, `rx-data-vals`, `fields`,
  `addr-data`); without it the bit rows drown the answer.
- `--window`/`--max-samples`/`--max-edges` bound the work on large captures;
  a truncated window is reported, never silent.
- Chains: `--protocol uart+modbus` runs the logic decoder first and feeds its
  packets to the next one (`spi+spiflash`, `i2c+atsha204a`). `--option
  level.key=value` targets a level; unprefixed options go to the logic level.
  Levels are checked against the decoders' `inputs`/`outputs`.
- `--all-levels` includes upstream rows; `--csv FILE` writes the annotations in
  the GUI's CSV shape (round-trips through `read --gui-csv`).
- 99 decoders take logic directly; the rest need an upstream decoder, which the
  chain syntax provides for the pairs that fit together.

Verified on the vendor's own samples: `uart_tx_115200` → `ALIENTEK`, EEPROM I²C
→ `0x50 WR: 00 53 … 0x50 RD: 33`, SPI flash → MOSI `54 4d 33 32 20 53 50 49`
(`TM32 SPI TEST`), PWM → 100 ns / 30 %, synthetic NEC → `Address: 0x00`,
`Command: 0x45`.

For IR, probe the receiver's **demodulated output** (idle high, bursts low),
not the LED; a 38 kHz carrier capture decodes as nothing. If a decode returns
no annotations the skill says so as a warning instead of an empty success.
`references/decoders.md` carries the reuse analysis (why the GUI cannot be
driven headlessly, why the shipped decoders can, GPL loaded in place) plus the
vendor-fork API notes and the verified protocol list.

## 5. Repeated capture

```bash
scripts/atkla.py series --ch 0:none --time 10ms --count 5 --interval 0.5 --out evidence/boot
```

One command, N captures, one table of duty/edges per run, stopping at the first
failure. Each sample reconnects the device, which keeps every run independent
at the cost of about a second per sample.

## 6. Environment

- The vendor binary is a **Windows** program (`atk-logic-cli.exe`) using the
  CYUSB driver. On WSL it runs on the Windows side through interop: **keep the
  analyzer attached to Windows and do not `usbipd attach` it to the distro**,
  or the CLI can no longer reach it.
- The CLI is found through `ATK_LOGIC_CLI`, then the saved config, then `PATH`,
  then `C:\Program Files\ATK-Logic\atk-logic-cli.exe` (visible as
  `/mnt/c/Program Files/...`).
- **Staging.** When `--out` is on the Linux filesystem, the capture is written
  to the Windows temp directory and copied back once, because a large trace
  written across the 9p share can trip `output_too_slow`. `--out /mnt/c/...`
  writes natively and keeps the CLI's timestamped subdirectory; `--keep-stage`
  keeps the Windows copy for inspection.
- `ATK_LOGIC_HOME` moves the config/state directory, `ATK_LOGIC_STAGING` forces
  the staging root, `ATK_LOGIC_CLI` overrides the binary.
- Device state lives in the CLI process, so every command starts a connection
  and ends it cleanly. An aborted capture needs roughly 15 s to unwind; that
  delay is the device stopping and uploading, not a hang.

## 7. Errors

Every failure is one JSON object with `ok:false`, `error.code`, `message`,
`retryable` and `suggestions`. Branch on `code`, never on `message`.

| code | what it means here | what to do |
|---|---|---|
| `trigger_not_found` | the line never reached the trigger condition; the run was stopped and partial data kept | check probe/ground/threshold, or use `--ch N:none`, or raise `--trigger-timeout` |
| `invalid_capture_combination` | the rate/time/channel count is not legal (only with `--strict`, or from the device) | run `caps` and choose from the list |
| `device_busy` | another program or capture holds the device | wait for `idle`, close the GUI, retry |
| `multiple_devices` | more than one analyzer is attached | pass `--device-id` from the error's list |
| `invalid_arguments` (channels) | a channel id is outside the device's real range | use the range from `info` |
| `device_not_found` / `device_disconnected` | no analyzer, or it was unplugged | replug, then `doctor` |
| `device_in_bootloader` | the analyzer is in upgrade mode | leave bootloader mode before capturing |
| `output_conflict` | the output directory exists | choose a new `--out` |
| `output_too_slow` / `output_write_failed` | disk too slow, full, or unwritable | capture to `/mnt/c/...` or free space; the partial is kept |
| `atkdl_save_failed` | the BIN is fine, only the GUI project failed | keep the BIN, re-run with `--format atkdl` |
| `capture_incomplete` | the stream ended before `idle` | keep `capture.json` and `.bin.partial`, then retry |
| `cli_not_found` / `cli_not_runnable` | the vendor CLI is missing or cannot start on this host | install ATK-Logic or set `ATK_LOGIC_CLI` |

`references/troubleshooting.md` has the symptom-first version, including the
harmless `CYUSB ... LastError=997` log line and what to do after a forced kill.

## 8. Boundaries

The vendor CLI has no decoding, no roll mode, no multi-level or serial
triggers, and one capture at a time. Decoding happens locally on the capture,
not in the CLI:

- Protocol semantics come from `decode` (the GUI's decoders) or, as a fallback,
  from `--vcd` handed to sigrok/PulseView. Capture generously either way
  (`--freq` at least 5×, preferably 10× the fastest bit rate).
- Stacked decoders (a PD on another PD's stream) are not hosted yet; decode the
  upstream protocol and read its rows.
- The GUI's own decoded rows are not stored in a project — only decoder
  configuration is. `project.decoders` and `--gui-csv` cover the cases where
  the user already has GUI results.
- For a trigger on a pattern across several lines, capture with `none` and
  filter in the decode step; the hardware supports one simple condition per
  channel.
- RLE is chosen by the device for large buffered captures and is reported
  (`rle: true`); the BIN layout is unchanged.

## 9. Files

- `scripts/atkla.py` — the intent CLI.
- `scripts/atklogic/` — host/path bridge, protocol, capabilities, capture,
  decode, ATKDL reader, protocol-decoder host.
- `references/cli-protocol.md` — the vendor contract as observed, with quirks.
- `watch --dir DIR [--once]` — report GUI projects as they appear in a directory
  (new `.atkdl` files print samples/channels/frequency).
- `usb capture ... --remove-glitches N` — absorb pulses shorter than N samples
  before computing duty/edges/frequency (measured: 23 glitches removed, frequency
  unchanged at 994.8 Hz).
- `sim --vcd TRACE --scl scl --sda sda --rate 10m --out DIR` — turn an HDL
  simulation into a capture directory (no hardware needed); see
  `references/simulation.md`, which ships a minimal I2C testbench in `sim/`.
- `references/native-usb.md` — the native USB route: session sequence, 0x12 layout,
  stream packet layout, and the calibration numbers (ch2 only, 10 MHz).
- `references/official-comparison.md` — capability matrix against the vendor CLI and GUI,
  the decoder-reuse conclusion, and what the native USB route still lacks (throughput).
- `references/atkdl-format.md` — project layout and how `validBits` is derived.
- `references/decoders.md` — using the GUI's 209 decoders, their API quirks and limits.
- `references/gui-parity.md` — which GUI capabilities the skill has, which it does not, and why.
- `references/troubleshooting.md` — symptom, cause, action.
- `tests/` — offline tests with a fake CLI; `python -m unittest discover -s tests`.
