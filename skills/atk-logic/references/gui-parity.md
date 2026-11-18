# GUI capability parity

Question: the GUI can do more than the CLI — how much of "the GUI's whole
capability" can the skill have, and what does it take to get the rest?

Method: compared the GUI project format (13 real `.atkdl` files), the strings in
`ATK-Logic.exe` / `atk-logic-cli.exe`, the CLI help, the manual's "功能边界"
section, and live probes of the JSONL session (`decode.list`, `decode.run`, … →
`Unknown method`). No claim below rests on a guess.

| capability | GUI | skill | how / why |
|---|---|---|---|
| buffer + stream capture, rate/time/channels/threshold/trigger position | yes | yes | vendor CLI |
| six simple per-channel triggers | yes | yes | vendor CLI |
| RLE for large buffered captures | automatic | automatic, reported (`rle`) | vendor CLI |
| single-level protocol decode (209 decoders) | yes | yes | `decode` hosts the shipped decoders |
| stacked decode (decoder on decoder) | yes | yes | `--protocol uart+modbus`, `spi+spiflash`, verified |
| decoded rows to CSV | yes | yes | `decode --csv` writes the GUI's CSV shape |
| waveform export | VCD/CSV/PNG | VCD/CSV | `read --vcd`, `read --csv` (no PNG) |
| read a project, its channels/rate/settings | yes | yes | `read` reports `project.gui` |
| **multi-stage trigger (16 levels)** | yes | no | CLI has no flag and no JSONL method |
| **serial trigger (pattern on a bus)** | yes | no | same |
| **rolling / loop capture** | yes | no | same |
| **PWM generator output** | yes | no | same |
| **glitch-removal filter** | yes | no | same |
| cursors / on-screen measurements | yes | read-only: `project.gui.cursors`; timings via `read` | cursors are a GUI display state |
| write/save a project | yes | no | skill writes BIN/CSV/VCD/JSON, not `.atkdl` |
| channel colours, heights, favourites | yes | not applicable | cosmetic |

The GUI stores the five acquisition features it alone can configure in
`set.ini`: `stageTriggerData` (16 stages), `serialTriggerData`, `pwmData`,
`glitchRemoval`, and `settingData.isRollingMode`. The vendor CLI exposes none of
them: `--help` lists no such option, the JSONL session answers `Unknown method`
for every `decode.*` / `protocol.*` probe, and the CLI binary carries the
libsigrokdecode strings only because it shares the core, not because it has an
entry point.

## What the manuals say

The boundary above is the vendor's own, not an interpretation:

- **CLI manual** (`docs/ATK CLI AI manual.md`, §9 功能边界, line 437):
  “首版不支持滚动 Stream、循环采集、多级/串行触发、协议解码、网络服务或跨进程控制。”
  So roll, loop, multi-stage and serial triggers are documented as *absent from
  the CLI*. Protocol decoding was in the same list; this skill closes that one by
  hosting the GUI's decoders.
- **GUI manual** (`ATK-Logic_zh_CN.pdf`) documents them as GUI features:
  5.3.4 滚动采集 (p.26), 5.12 多级/串行触发 (p.36), 5.13 毛刺过滤 (p.38),
  5.18 PWM 输出 (p.49); the DL16 spec lists 1 Hz–20 MHz, 2 PWM channels
  (4 on the DL32).
- **CLI user manual**: `PWM` appears once, in the disconnect sequence (“关闭
  PWM”), i.e. the device has a PWM generator that the CLI only turns off.

Neither manual promises a CLI switch for these, so no option is missing from
this skill — the capability lives behind the GUI.

## What reaching the rest would take

1. **Let the GUI acquire, let the skill analyse** (works today, recommended).
   Configure the advanced trigger/PWM/roll in the GUI, save the project, then:
   `read <project>` reports what the GUI was set to (`project.gui`), and
   `read`/`decode`/`--gui-csv` turn the data into numbers and protocol rows.
2. **Drive the GUI** (`pywinauto`, or the undocumented Qt Remote Objects
   interface). Rejected as a foundation: Windows-only, breaks on vendor
   updates, and the GUI and CLI contend for the same USB device.
3. **Implement the USB protocol** — now the cheapest of the three, because it is
   no longer reverse engineering from zero:
   - `alientek-openedv/atk-logic` is the **official GUI source** (GPL-3.0), with
     the command layer in `pv/usb/usb_control.cpp`; stage trigger, serial
     trigger, PWM and glitch removal are all in there.
   - `apiwat59/atk-dl32-mcp` (MIT) has `DL32_PROTOCOL.md`: FX3 `VID 04B4 /
     PID 6A6A`, framed commands `00×8, 0x0A, cmd, len+1, data, 0x0B, CRC32 LE,
     00`, and command ids `0x10` device data, `0x11` parameter setting, `0x12`
     simple trigger, `0x13` stage trigger, `0x14` serial trigger, `0x15` stop,
     `0x17` PWM, `0x18` exit.
   - `LHX369963/dl16-cli` documents and implements `0x11`–`0x15`/`0x17`
     (dry-run payloads, capture modes, evidence logs); `hugelzhang/atk-logic-mcp`
     (MIT) adds `PROTOCOL-NOTES.md` and a sigrok host.

   What is left is a transport (pyusb against the WinUSB/libusbK device) plus the
   payload builders for `0x13`/`0x14`/`0x17`, then verification on hardware —
   days, not weeks, and it needs the analyzer handed to the process that drives
   it. GPL-3.0 source must not be copied into this Apache-2.0 bundle; the MIT
   notes may be adapted with attribution, or the payloads reimplemented from
   the protocol description.

**Conclusion**: everything the GUI does *with* a capture — reading it,
measuring it, and decoding it with the vendor's own protocol decoders, including
multi-level stacks — is available from scripts. Configuring the five
GUI-only acquisition features is the deliberate boundary; the skill does not
pretend to set them, and it documents the two ways around it (GUI-acquire, or
reverse engineering).
