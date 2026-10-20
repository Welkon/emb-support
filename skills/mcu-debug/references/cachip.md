# CACHIP toolchain

This document is the reference for the CACHIP USB HID programmer. Scripts are in
`scripts/cachip/`.

## Hardware

The programmer is a TFT emulator downloader. It uses USB HID with VID `0xFFCA`
and PID `0x0125`. The device is an STM32F103 high-density MCU with SPI flash and
an OLED/TFT display. The usual target is a CA51M550S1B touch MCU with TK3 touch
and channel 3.

The protocol is a vendor HID protocol. Each report is 64 bytes. Each command
starts with one command byte.

## Script environment

- Windows: install the Python binding for `hidapi`: `pip install hidapi`.
- Linux: add a udev rule for USB access. See `LINUX_DEPLOY.md` in the original
  CACHIP bundle if it is available.
- All scripts import each other from the same directory. Use `sys.path` with
  `scripts/cachip/`.

## Tools

| Script | Function |
|---|---|
| `cachip_burner.py` | Burns a target HEX file. Runs Connect (model echo and voltage check), erase, write and verify. It checks the status byte of each command. |
| `cachip_touch_debug.py` | Touch debug library and CLI. Commands: TD_Connect, GetState, GetChannelCount, GetBaselineData, GetRawData, GetThresholdData and SetThresholdData. |
| `fw_manager.py` | Writer and slot management. Commands: FW_List (0x60), Info (0x61), Create (0x62), Delete (0x63), SyncCache (0x66), SetKey (0x67) and GetLimit (0x69). |
| `fw_update.py` | Updates or restores the downloader firmware. See the update sequence below. |
| `ai_tune.py` | Automatic calibration. It records the baseline with no touch, records three touches, suggests thresholds, writes them and verifies the result. |
| `optimize.py` | Bayesian threshold search. It returns a trade-off curve and an offline simulation. |
| `waveform.py` | Waveform analysis. Fast sampling, ASCII waveform, and classification of tap, long press, multi-tap and false touch. |
| `mcu_table.py` | Table of more than 160 target chips (HEX model ID to name). `0x028F` is CA51M550S1B. |
| `PROTOCOL.md` | Full protocol documentation: command table, frame format and timing. |

## Quick use

```bash
# Burn a target. Run Connect first. HEX or BIN is accepted.
python scripts/cachip/cachip_burner.py target.hex --name CA51M550S1B

# Touch debug with a live data stream.
python scripts/cachip/cachip_touch_debug.py --count 10 --interval 0.1

# Automatic calibration. The user removes the hand, then presses TK3 three times for 1 s.
python scripts/cachip/ai_tune.py

# Writer slot list, delete or create.
python scripts/cachip/fw_manager.py list

# Downloader firmware update or restore.
python scripts/cachip/fw_update.py update CACHIP_TOOL_v1.1.0.8_20260507.bin
```

## Protocol facts (measured)

- **Firmware update frame**: `[cmd] + [00] + [address 4B LE] + [length 1B] + [00] + [data]`. The total length must be 64 bytes or less. Command E2 uses exactly 64 bytes. A 1-byte prefix works. A 2-byte prefix truncates data.
- **Firmware update sequence**: E0 (start) → heartbeat → E4 (send only, do not read) → wait 2 s and reconnect. USB re-enumerates and the old handle becomes invalid. Then E3 (erase 2 KB sector), E2 (write 56 B blocks), E1 (verify 60 B at 0x0802ACB0), E4 00 (clear the update flag). Then unplug and replug. Software cannot reset the MCU.
- **Status check**: Do not check the status byte for a heartbeat (0x00). For power (0x11), check that the voltage is above 2 V. For all other commands, byte `[1]` must be `0x00`. The Connect response is the model echo in bytes `[2:4]`. Connect is slow (more than 3 s). Its timeout is 10 s.
- **Touch response**: `cmd + 00 + channel + value 2B LE`. On TK3, the measured raw value is about 8100 to 8300. The baseline tracks automatically. The default threshold is 500.
- **Writer slot address**: start at 0x0833E0 with a step of 0xA780 in SPI flash.

## Lessons learned

Each item below caused a failure in the past.

1. **Firmware string replacement must keep the length.** Pad to the original length and assert the total firmware length. A length change shifts the firmware and bricks the device. Recovery needs a full chip erase with ST-Link and a new flash.
2. **Long strings**: Move the string to empty data space (the 0xFF gap at firmware offset 0x5804) and change the pointer. The version pointer is in the pool at 0xFAFC.
3. **Deep reset (51x3) breaks the connection on new firmware.** Remove it from the default flow. Use `connect(deep=False)`.
4. **Half recovery after CM_Reenumerate**: The response to `10 00` has a non-zero state such as 9D, F1, E3 or B8. Unplug and replug the device.
5. **The official tool and the scripts cannot connect at the same time.** The device is exclusive. Stop leftover Frida or Python processes.
6. **A failed update bricks the device.** The OLED shows update mode or stays black. Recovery: use the ST-Link on a NUCLEO-C031C6 board (SWDIO, SWCLK, GND, VDD) with STM32CubeProgrammer. Erase the whole chip, then download the bin at 0x08000000.
7. **Always check the voltage and the status byte before a burn.** A successful Connect alone is not enough.

## Firmware customization (tested)

- Version string at 0x0293BA. An equal-length replacement works, for example `VER1.1.0` to `VER1.2.0`.
- Boot logo: top line CACHIP (red), middle line company name (white), bottom line version. The logo image data is not located. It is probably in a factory area of the external SPI flash. Check the W25Q part on the board.
- Edit the bin, run `fw_update.py update`, then unplug and replug. Any located data can be changed.
- Firmware backup: `scripts/cachip/CACHIP_TOOL_v1.1.0.8_20260507.bin` (official version, 175,544 B).

## Target touch calibration (standard flow)

1. Run `python scripts/cachip/ai_tune.py`. The script tunes all channels. A baseline sigma below 5 is good. The suggested threshold is `touch delta / 2 + noise margin`.
2. The threshold write is a run-time setting. A reboot restores the firmware default of 500. To make it permanent, change the default threshold table in the firmware or find the SPI flash storage mechanism.
3. Verify: read the threshold (0x58 00 channel), press TK3, then check that the key flag is 1 and the delta is above the threshold.
