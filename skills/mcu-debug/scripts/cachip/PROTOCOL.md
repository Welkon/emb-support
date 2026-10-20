# CACHIP Tool protocol (reverse engineering, v1)

Source: static analysis of `CACHIP_TOOL_4.1.3.exe`. Items marked with a warning
sign need a capture or a measurement to confirm.

## Architecture

```
PC (this driver or the official GUI) <-- serial or USB HID --> CACHIP downloader <-- ISP --> target MCU
```

- USB HID: `VID_FFCA PID_0125`. The report length is fixed. Short data is padded with zeros. The exact report length needs confirmation; 64 B is likely.
- Serial: raw byte stream. Baud rates: 9600, 19200, 38400, 57600, 115200, 256000, 460800, 921600.
- Serial frame boundaries need confirmation. They may be fixed length or a raw stream.

## Frame format

### Request (PC to downloader)

```
[0]   command ID (1 B)
[1..] payload (command-specific, no length field, no checksum)
```

### Response (downloader to PC)

```
[0]   command ID echo (1 B)
[1]   error code (1 B). 0x00 = success, non-zero = error.
[2..] data (command-specific)
```

On error, the PC reports "expected ID_xxx" when the ID echo does not match.

## Command ID table

| ID | Command | Description | Payload (needs confirmation) |
|---|---|---|---|
| 0x06 | Info | Read tool information | Empty? Response byte [2] is the state. |
| 0x08 | Connect | Open the connection | 4 B parameter plus data |
| 0x09 | Disconnect | Close the connection | Empty |
| 0x0B | EraseTgtFlash | Erase the target flash | Needs confirmation |
| 0x0C | WriteTgtFlash | Write the target flash | Needs confirmation |
| 0x0D | VerifyTgtFlash | Verify the target flash | Needs confirmation |
| 0x0F | WriteCache | Write the downloader cache | `offset(4 B LE) + data(<=58 B)` |
| 0x10 | ScreenStatus | Screen state | Needs confirmation |
| 0x11 | TargetPower | Target power control | Needs confirmation |
| 0x13 | WriteEvent | Write an event | Needs confirmation |
| 0x50 | TD_Connect | Touch: connect | Needs confirmation |
| 0x51 | TD_Disconnect | Touch: disconnect | Empty |
| 0x52 | TD_GetState | Touch: state | Needs confirmation |
| 0x53 | TD_GetChannelCount | Touch: channel count | Needs confirmation |
| 0x54 | TD_GetRefChData | Touch: reference channel data | Needs confirmation |
| 0x55 | TD_GetKeysFlagSN | Touch: key flags and serial number | Needs confirmation |
| 0x56 | TD_GetBaselineData | Touch: baseline | Needs confirmation |
| 0x57 | TD_GetRawData | Touch: raw value | Needs confirmation |
| 0x58 | TD_GetThresholdData | Touch: threshold | Needs confirmation |
| 0x59 | TD_SetThresholdData | Touch: set threshold | Needs confirmation |
| 0x5A | TD_GetChannelNumber | Touch: channel number | Needs confirmation |
| 0x60 | FW_List | Firmware list | Needs confirmation |
| 0x61 | FW_Info | Firmware information | Needs confirmation |
| 0x62 | FW_Create | Create a firmware slot | Needs confirmation |
| 0x65 | FW_Delete | Delete a firmware slot | Needs confirmation |
| 0x66 | FW_SyncCacheToFw | Cache to firmware | Needs confirmation |
| 0x67 | FW_SetActive | Activate a firmware slot | Needs confirmation |
| 0x68 | FW_SetKey | Set a key | Needs confirmation |
| 0x69 | FW_SetMeta | Set metadata | Needs confirmation |
| 0x6C | FW_SetLimit | Set a count limit | Needs confirmation |
| 0x6D | FW_GetLimit | Read the count limit | Needs confirmation |
| 0x6E | FW_LimitInc | Increase the count | Needs confirmation |
| 0xE0 | Update helper | Update helper | Needs confirmation |
| 0xE1 | UPGRADE_RD_MEM | Update: read memory | Needs confirmation |
| 0xE2 | UPGRADE_WR_MEM | Update: write memory | Needs confirmation |
| 0xE3 | UPGRADE_ERASE | Update: erase | Needs confirmation |
| 0xE4 | Update helper | Update helper | Needs confirmation |

## Known behavior

- **WriteCache block size**: Split data into blocks of 58 B (0x3A) or less. Send one frame per block: `0x0F + offset(4 B LE) + chunk`. The offset is absolute and increases. Read one response after each block. The timeout is 100 ms. Compare response byte [2] with the expected value.
- **Timeouts**: Connect 5000 ms, Disconnect 1000 ms, all other commands 100 ms.
- **HID write**: If the data is shorter than the report, pad with 0x00, then call WriteFile.
- **HID read**: Clear the buffer, call FlushFileBuffers, then ReadFile with the report length. Retry on `ERROR_OPERATION_ABORTED` (0x3E5).
- The transport layer is a vtable abstraction with Serial and HidApiUSB implementations. The protocol layer does not see the difference.

## Dynamic verification (2025, full burn succeeded)

The OLED showed "burn success 100%".

### Full protocol (final)

**Transport**: WriteFile to the interrupt endpoint. 65 bytes = `[0x00 report id] + [64 B TEA ciphertext]`.

**Encryption**: TEA. Key: `13 5A 64 30 5A 5A 17 66 B0 50 0F 66 4D 0A 07 5F`.
Pad the plaintext to 64 bytes. Encrypt as 8 ECB blocks.

**Burn sequence**:

1. Heartbeat `00 04`.
2. `10 00`, `10 01` plus checksum (4 B), `10 02 01`, `10 04 01`.
3. Connect: `08` + model ID (2 B) + `"5M"` + model name + 5x00 + model name + 5x00.
4. TargetPower `11 03`, WriteEvent `13 01`, `10 02 04`, progress 0 (`10 03 00`).
5. Erase: `0B 02 000000`.
6. Write loop, 109 times: `0F` (write cache: `0F` + 4 B offset + 0x20 + 32 B data) → `0C` (write flash: `0C` + address + 0 + 0x20 0x00) → progress (`10 03 N`).
7. At progress 100: `10 02 07` (verifying) → progress 0.
8. Verify loop, 109 times: `0D` (verify: `0D` + address + 0x20 + expected data) → progress.
9. At progress 100: Disconnect `09` → `10 02 05` → TargetPower off `11 00` → OLED shows "burn success 100%".

**Firmware handling**: Parse the Intel HEX file. Fill gaps with 0x00. Pad the tail (the last block if shorter than 32 B) with 0xFF. Add one block of 0xFF. The write and verify loops cover 109 blocks up to 0xD80.

### Status codes (command-specific success values, not 0x00)

| Command | Success status | Measured |
|---|---|---|
| Info (0x06) | 0xC0 | Yes |
| Connect (0x08) | 0x41 | Yes, with a target connected |
| EraseTgtFlash (0x0B) | 0x01 | Yes |
| WriteCache (0x0F) | 0x00 | Yes |
| WriteTgtFlash (0x0C) | 0x40 | Yes |
| VerifyTgtFlash (0x0D) | 0x81 | Yes |
| Disconnect (0x09) | 0x80 | Yes |
| TargetPower (0x11) | 0x80 | Yes |
| TD_GetChannelCount (0x53) | 0x00 | Yes |

A 3434-byte firmware was burned through the driver. The official tool verified it ("The verification was successful."). Flow: Connect → Erase → WriteCache (blocks of 58 B or less) → WriteTgtFlash → Verify.

## Items that still need a dynamic check

1. HID report length (64 B is likely).
2. Serial frame boundaries (fixed length or a length field).
3. Connect payload meaning (4 B parameter plus data).
4. Payload layout of each command (erase, write flash, verify, touch).
5. Error code meanings (non-zero values).
6. TD_* channel data length (0x1E = 30? channel buffer).
7. Encrypted firmware format (related to FW_SetKey).

## Static analysis addresses (for reference)

- Protocol core: `0x464590` (Connect), `0x4649f0` (Disconnect), `0x465200` (WriteCache).
- Command functions: `0x464000` to `0x471000`.
- HID transport: `0x472200` (write), `0x4722c0` (read).
- Serial library: `0x433000` to `0x434500` (built from win.cc).
- CACHIPTool vtable: `0x5e55a0`.

## Touch debug protocol (measured 2025)

**Channel**: interrupt endpoint WriteFile/ReadFile through hidapi. One request gets one response. TEA encryption is the same as for burning.

**Connect sequence**:

```
51           TD_Disconnect      (clear leftover state)
11 02        TargetPower 2      (off)
50           TD_Connect
11 03        TargetPower 3      -> [11][voltage 2B LE]  (0x0149 = 3.29 V)
10 04 03     debug mode         (use 10 04 01 for burning)
52           TD_GetState        -> [52][00][01] connected
53           TD_GetChannelCount -> [53][00][count]  (1 = one touch key)
5A 01        TD_GetChannelNumber -> [5A][00][01][channel]  (03 = TK3)
58 00 CH     TD_GetThresholdData -> [58][00][CH][threshold 2B LE]  (500)
```

**Poll loop** (6 frames per round):

```
11 03        keep power on -> voltage
55           TD_GetKeysFlagSN   -> [55][00][key flags]  (0 = released, 1 = pressed)
58 00 CH     TD_GetThresholdData
56 00 CH     TD_GetBaselineData -> [56][00][CH][baseline 2B LE]
57 00 CH     TD_GetRawData      -> [57][00][CH][current value 2B LE]
54           TD_GetRefChData    (reference channel)
```

**Touch detection (measured)**: delta = baseline - current. On touch, the raw value drops (about 8100 to 177). The delta (7881) is much larger than the threshold (500), so the key flag becomes 1. On release, the value recovers within about +/-50 and the key flag becomes 0.

**Response format**: 64 B plaintext = 16 B data + 8 B x 6 repeated padding. Data = `[cmd][00][channel][value 2B LE][random or sequence ...]`.

**TD_* command table**:

| Command | ID | Description |
|---|---|---|
| TD_Connect | 0x50 | Connect the debug board |
| TD_Disconnect | 0x51 | Disconnect |
| TD_GetState | 0x52 | State (01 = connected) |
| TD_GetChannelCount | 0x53 | Channel count |
| TD_GetRefChData | 0x54 | Reference channel data |
| TD_GetKeysFlagSN | 0x55 | Key flags |
| TD_GetBaselineData | 0x56 | Baseline |
| TD_GetRawData | 0x57 | Current value |
| TD_GetThresholdData | 0x58 | Threshold |
| TD_SetThresholdData | 0x59 | Set threshold (not captured, inferred) |
| TD_GetChannelNumber | 0x5A | Channel number |

**Linux**: `python3 scripts/cachip/cachip_touch_debug.py --count 100 --interval 0.1`

## Automatic tuning (ai_tune.py, measured 2025)

**Flow** (about 10 seconds):

1. Connect and record 5 s of no-touch data. Sigma measures the noise level.
2. Prompt the user to touch the TK key three times. Edge detection records the delta on each press.
3. Compute the best threshold: `(max no-touch delta + median touch delta) / 2`, minimum 100.
4. Write it online with 0x59, read it back and verify. The old value can be restored.

**Measured data (TK3)**:

- No touch: mean 8231, sigma 9.1, max delta 17 (clean environment).
- Touch: delta 1685 to 1940 (clear trigger).
- Suggested threshold: 100 (the old value was 500). The write and verify succeeded.

**Key points**:

- A stuck device recovers only after a USB replug. A software deep clear does not work.
- Poll interval must be 0.1 s or more per frame. A shorter interval causes misaligned responses.
- The official tool and a custom script cannot connect at the same time.

## Bayesian threshold search (optimize.py, measured)

- One capture (8 s no touch, 6 touches), then simulate all thresholds offline and produce a trade-off curve.
- Output: a table of threshold vs false-touch rate and trigger rate, then choose the best value and write it with 0x59.
- Measured: clean environment (sigma 7.6). Thresholds from 23 to 1500 gave 0% false touch and more than 93% trigger.
- Environment modes: dry, normal, wet. The noise margin is x2, x3 and x5.

## Touch waveform analysis (waveform.py, measured)

- Fast sampling (about 30 ms per frame). Send only `11 03`, `55` and `57`.
- Record 10 frames before the press, the press interval with timestamps, and the release.
- Features: depth, time to 50%, duration and oscillation rate.
- Classes: tap (<0.5 s), long press (>1 s), standard press, possible false touch (oscillation >0.3 or slow press).
- Measured: captured a 0.03 s tap. Feature rows go to `wave_features.csv` for ML training.
- Key points: poll interval 20 ms or more. The ring buffer scrolls continuously and supports fast multi-tap.

## Gesture recognition (waveform.py, measured)

- Multi-tap: release interval <0.6 s = multi-tap. <0.35 s = fast multi-tap.
- Measured: single taps (interval 0.79 s and 1.33 s) and multi-tap (interval 0.14 s) separate cleanly.
- One physical key provides tap, multi-tap, long press, standard press, and false-touch rejection (slow press or oscillation).
- The feature CSV can train an ML classifier (`wave_features.csv`).

## Writer and slot management (measured)

**Commands** (TEA encryption, one request gets one response):

```
FW_List:       60 [index] -> 60 00 [name1] 00 [name2]... (response lists from the index)
FW_Info:       61 [name length][name] -> 61 00 [size 4B][model 2B][slot address 4B]
FW_Create:     62 [name length][name][00x4][model 2B]["5M"][slot address 4B]
                 Slot address starts at 0x0833E0. Each slot adds 0xA780.
                 Official values: 0x0833E0 and 0x08DB60.
FW_Delete:     63 [name length][name]  (must SetActive first; status 18 = success)
FW_SetActive:  65 [name length][name][00x16]
FW_SyncCache:  66 [name length][name][00x5][segment offset/256 2B][last segment length 2B (0 = full)][length/256 2B][00x7]
FW_SetKey:     67 [name length][name]
FW_GetLimit:   69 [type 3/4/7][name length][name]
Write cache:   0F [address 4B][length 1B][data]  (58 B per frame, 512 B per segment = 9 frames)
```

**Add firmware flow** (measured with a 3434 B firmware):

```
Create -> [0F x 9 cache + Sync(offset 0,2,4...12)] x 7 -> done
```

Pad the last segment to 512 B with 0xFF. A precise length above 255 makes the device silent. `Info` size = segment count x 512 (3584 with padding; burning still works).

**Delete firmware flow**: SetActive (65) → Delete (0x63). Status 18 = success.

**Key points**:

- The slot address is assigned automatically (0x0833E0 + N x 0xA780). Each firmware gets a unique slot.
- If the slot table is full, Create returns status 1. Delete a slot first.
- The model is not hard-coded. The protocol is generic; the Create frame carries the model.

## Burn status checks (measured 2025, fixes a false-success bug)

- Read the response after each command. Status byte [1] == 0x00 means success.
- Heartbeat (00): response [1] = 07 and version "1.1.x". Do not check the status.
- Power (11): response [1:3] = voltage 2 B LE (3.28 V). Below 2 V means a target problem.
- Connect (08): response [2:4] = model echo. It must match.
- Erase (0B): status 00 means success.
- 0F, 0C, 0D: status 00 means success for each block.
- Deep reset (51x3) breaks the connection on firmware v1.1.0.8. It is removed from the default flow.

## Firmware update flow (fw_update.py, measured 2025)

- Frame: `[cmd] + [00] + [address 4 B LE] + [length 1 B] + [00] + [data]`. Total length 64 B or less.
- E0 (start update) → heartbeat (00 07) → E4 (send only, do not read) → **wait 2 s and reconnect the device (critical)** → E3 erase → E2 write → E1 verify.
- After E4, the device re-enumerates on USB. The old handle is invalid. Reconnect.
- After a successful update, unplug and replug USB to restart the device.
- Measured: 74 sector erases, 2733 write blocks, 2551 verify blocks. All passed.
- **Final command: E4 00 exits update mode and restarts the device.** Send it after the verify step.
- Check the restart: send `10 00` (a normal-mode command) after reconnect.
- The E1 verify range is 0x08005800 to 0x0802ACB0 (end of code). The tail configuration area is not verified.
- Restart tests: disable, enable and CM_Reenumerate do not trigger an internal reset. HID has no USB interface, so IOCTL_USB_RESET is not reachable.
- Final step: unplug and replug the device. The official tool does a driver-level USB reset.
