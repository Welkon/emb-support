# Tektronix notes

The Tektronix SCPI dialect is different from the Rigol and Keysight dialects. This document records the verified paths and the known problems.

## Connection

A TBS 1102B has only a USB device port. It has no LAN port. Use USBTMC first.

```
USB0::0x0699::0x0368::<serial>::INSTR
```

```bash
scripts/scope.py list                      # Needs pyvisa
scripts/scope.py idn --resource "USB0::0x0699::0x0368::C012345::INSTR"
```

WSL:

```powershell
usbipd list
usbipd attach --wsl --busid 2-3
```

Linux permissions:

```bash
scripts/install_udev.sh        # 0699 is the Tektronix vendor ID
```

## Windows and the TekVISA bitness problem

On Windows, a vendor TekVISA runtime needs the same bitness for Python and `visa32.dll`.

- Use a **32-bit Python**, for example a separate venv.
- Do **not** use `--backend @py`. Omit `--backend` and let PyVISA load the vendor DLL automatically.
- If you must give an explicit path, use the 32-bit path:
  `C:\Program Files (x86)\IVI Foundation\VISA\WinNT\TekVISA\Bin\Visa32.dll`
  Do not use the 64-bit path without `(x86)`. That path fails.
- A typical bitness error is `VI_ERROR_INV_OBJECT` or "Could not find module ... Visa32.dll".

The skill uses these defaults:

- Windows: `backend=None` (automatic).
- Linux and macOS: `@py`.

Use `--backend auto` or `config set backend auto` to change the default.

To check the backend and the bitness:

```bash
python -m pyvisa.info     # Shows the backends and the bitness
```

## Waveform capture: verified path

The skill uses the ASCII `CURVe?` path that was verified on a TBS 1102B.

```
DATa:SOUrce CH1
DATa:ENCdg ASCII
DATa:WIDth 1
DATa:STARt 1
DATa:STOP <n>
CURVe?
```

Try the scaling fields in this order. The spelling is different on some firmware versions.

| Field | Candidates |
|---|---|
| XINcr | `WFMPre:XINcr?`, then `WFMOutpre:XINcr?`, then `WFMPRE:XINCR?` |
| XZEro | `WFMPre:XZEro?`, then `WFMOutpre:XZEro?`, then `WFMPRE:XZERO?` |
| PT_Off | `WFMPre:PT_Off?`, then `WFMOutpre:PT_Off?`, then `WFMPRE:PT_OFF?` |
| YMUlt | `WFMPre:YMUlt?`, then `WFMOutpre:YMUlt?`, then `WFMPRE:YMULT?` |
| YZEro | `WFMPre:YZEro?`, then `WFMOutpre:YZEro?`, then `WFMPRE:YZERO?` |
| YOFf | `WFMPre:YOFf?`, then `WFMOutpre:YOFf?`, then `WFMPRE:YOFF?` |
| NR_Pt | `WFMOutpre:NR_Pt?`, then `WFMPre:NR_Pt?` |

Use these formulas:

```
time    = XZEro + (i - PT_Off) * XINcr
voltage = (raw - YOFf) * YMUlt + YZEro
```

Notes:

- If `CURVe?` returns no data, make sure that the source channel is visible on the screen.
- Do not set `DATA:STOP` above the record length. For deep memory, read `:ACQuire:POINts?` or `WFMOutpre:NR_Pt?` first.
- ASCII mode is slower than binary mode, but it has the best compatibility. For a large record, you can use RIBinary. The skill uses ASCII at this time.

## Trigger and intermittent faults

A TBS 1102B supports single and sequence trigger:

```
ACQuire:STOPAfter SEQuence
ACQuire:STATE RUN
TRIGger:STATe?
```

The `monitor` command uses this path with the Tektronix dialect:

1. Apply the setup.
2. Send `STOPAfter SEQuence` and `RUN`.
3. Poll `ACQuire:STATE?`. The value 0 means stopped.
4. Capture the waveform after a hit.
5. Re-arm when requested.

Pulse-width trigger:

```
TRIGger:A:TYPe PULSe
TRIGger:A:PULse:WIDth:WHEn LESSthan|GREATERthan
TRIGger:A:PULse:WIDth:WIDth <seconds>
TRIGger:A:PULse:POLarity POSitive|NEGative
```

## Screenshot

A TBS 1102B sends hardcopy to the front panel or a USB PictBridge device. It has no stable general download command. The command `:SAVE:IMAGe:FILEFormat PNG` and the query `:DISPlay:DATA?` do not work on this model. An unsupported screenshot query can also desynchronise the USBTMC queue.

The Tektronix dialect disables the screen dump. The `shot` command captures CH1 and writes an SVG waveform plot. Use a CSV capture as the primary evidence for this model.

## Verified controls

The removed `tektronix-scope` skill contained a control catalog that was verified on a TBS 1102B. The catalog has 127 usable keys with query, set, and action templates. The skill keeps this catalog in `references/tektronix-tbs1000b.md`. Send a key with `scope.py scpi`.

Common commands:

| Function | Command |
|---|---|
| Vertical scale | `CH1:SCAle 0.5` |
| Vertical position | `CH1:POSition 0` |
| Coupling | `CH1:COUPling DC` |
| Probe | `CH1:PRObe 10` |
| Timebase | `HORizontal:SCAle 1e-3` |
| Trigger level | `TRIGger:A:EDGE:LEVel 0.8` |
| Trigger slope | `TRIGger:A:EDGE:SLOpe RISe` |
| Acquisition state | `ACQuire:STATE RUN` or `ACQuire:STATE STOP` |
| Single sequence | `ACQuire:STOPAfter SEQuence` |
| Waveform source | `DATa:SOUrce CH1` |
| Curve | `CURVe?` |

## Hardware validation (TBS 1102B, WSL)

- The WSL kernel has no `usbtmc` module. The device does not appear as `/dev/usbtmc*`. The skill uses **pyvisa-py with pyusb and libusb-package**. The `scope.py setup` command installs `libusb-package`. The `scope.py` program runs again in the skill venv at startup.
- Read the text preamble first. Read `CURVe?` after the preamble. If you read text after the curve, a timeout can occur.
- `WFMOutpre:NR_Pt?` is not reliable on a TBS. The skill does not use this query. It uses the sample count from the actual data.
- For continuous acquisition, send `:ACQuire:STOPAfter RUNSTOP` and then `:ACQuire:STATE RUN`. The command `:RUN` alone leaves the instrument stopped.
- A screenshot query can break the USBTMC queue. The Tektronix dialect disables the screen dump. The `shot` command captures CH1 and writes an SVG plot.
- The record length limit of this model is **2500 points**. `DATa:STOP` above this value is truncated.
- If an external timeout desynchronises the link, the most reliable recovery is `usbipd detach` and then `usbipd attach`.
