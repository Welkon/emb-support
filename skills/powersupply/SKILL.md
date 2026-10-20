---
name: powersupply
description: Control programmable bench power supplies over LAN (SCPI socket), USB (USBTMC or VISA), or serial. Supports Rigol DP800, Keysight E36xx, Siglent SPD, Rohde & Schwarz HMC, GW Instek, BK Precision, Owon, Aim-TTi, Korad, ALIENTEK DP100, FNIRSI DPS-150, and B&K 168x. Use this skill when the user mentions a power supply, PSU, bench supply, programmable source, SCPI voltage or current setpoints, OVP, OCP, output enable, voltage ramp, or supply-rail logging. Use it also for safe output control and long power-rail records.
---

# Programmable Power Supply

This skill controls programmable power supplies. The code has three layers:

- Transport: LAN socket, VISA, USBTMC, serial port, or USB HID.
- Dialect: brand-specific SCPI or serial commands.
- Safety: voltage and current limits, output interlocks, and readback checks.

```bash
scripts/psu.py idn --host 192.168.1.60
scripts/psu.py set --host 192.168.1.60 --ch 1 --voltage 5 --current 1 --verify
scripts/psu.py output --host 192.168.1.60 --ch 1 on --yes
scripts/psu.py measure --host 192.168.1.60 --ch 1
```

## 0. Safety first

A power supply is more dangerous than an oscilloscope. The tool protects output changes.

- The default limits are 30 V and 5 A. The tool rejects larger values. Change a limit with --max-voltage 60 or config set max_voltage 60.
- Output ON requires --yes. The tool rejects the command without it.
- all-off needs no confirmation. Use it for an emergency stop on all channels.
- ramp and sequence require --yes. On an error, they turn the output off when safe_off is enabled.
- set changes setpoints only. It does not enable the output.
- OVP and OCP do not replace a hardware current limit. Check the physical rating first.

## 1. Environment

```bash
scripts/psu.py doctor --host 192.168.1.60
scripts/psu.py discover
scripts/psu.py discover --scan 192.168.1.0/24
scripts/psu.py setup
```

- LAN uses a native socket. It has no extra dependency.
- USB uses VISA or Linux /dev/usbtmc*.
- Serial supplies such as Korad use --serial /dev/ttyUSB0 --baud 9600.
- ALIENTEK DP100 uses USB HID: --hid dp100.
- FNIRSI DPS-150 uses USB CDC: --serial /dev/ttyACM0 --family dps150.
- B&K 168x and Manson use --serial /dev/ttyUSB0 --family bk168x. Add --current-decimals 2 for the 1685B.
- Linux and WSL permissions: run sudo bash scripts/install_udev.sh. Replug the device or run usbipd attach again after the install.
- WSL detection: the tool detects WSL at start. If no local device exists, it attaches a Shared Windows supply with usbipd attach. Use doctor --attach-usb to attach manually.

## 2. Families and dialects

| family | Typical model | Command style |
|---|---|---|
| rigol | DP832, DP800 | :CHANnel<n>:VOLTage, :OUTPut CHANnel<n>,ON |
| keysight | E36312A, E3631A, E364xA | :INSTrument:NSELect and :VOLTage / :OUTPut |
| siglent | SPD3303X, SPD3303X-E | :CH<n>:VOLT, :OUTP CH<n>,ON |
| rns | HMC8041/2/3 | :INSTrument:NSELect and :OUTPut:CHANnel<n>:STATe |
| korad | KA3005P, Tenma | serial VSET1:, ISET1:, OUT1 |
| gwinstek | GPP, GPD | channel select and :VOLT / :OUTP |
| bkprecision | 9130B, 9200 | channel select and :VOLT / :OUTP |
| owon | SPE, SPD | :CH<n>:VOLT, :OUTP CH<n>,ON |
| aimtti | PL, CPX | :VOLT, :CURR, :OUTP |
| itech | IT6300, IT6900 | :INSTrument:NSELect and :VOLTage / :OUTPut |
| generic | other SCPI | :VOLTage, :CURRent, :OUTPut |
| dp100 | ALIENTEK DP100 (0-30 V, 0-5 A, 100 W) | USB HID with hidapi |
| dps150 | FNIRSI DPS-150 | USB CDC, F1/F0 frames and float32 registers |
| bk168x | B&K 1685B/1687B/1688B, Manson HCS-3xxx | serial ASCII: VOLT123, GETD, SOUT0 |

See references/dialects.md for details and sources. See references/troubleshooting.md for faults.

## 3. Standard workflow

```bash
# Identify the supply.
scripts/psu.py idn --host <ip> --json
scripts/psu.py channels --host <ip>

# Set limits. This does not enable the output.
scripts/psu.py set --host <ip> --ch 1 --voltage 5 --current 1 --verify

# Enable the output. Use --yes. Then measure.
scripts/psu.py output --host <ip> --ch 1 on --yes
scripts/psu.py measure --host <ip> --ch 1

# Record V, I, and P.
scripts/psu.py log --host <ip> --ch 1 --duration 30 --interval 0.5 --out rail.csv

# Disable one channel.
scripts/psu.py output --host <ip> --ch 1 off

# Emergency stop on all channels.
scripts/psu.py all-off --host <ip>
```

## 4. Voltage ramp and sequence

```bash
# Software ramp: 0 V to 12 V, step 0.5 V, delay 0.2 s.
scripts/psu.py ramp --host <ip> --ch 1 --start 0 --to 12 --step 0.5 --delay 0.2 --yes

# JSON sequence.
cat > seq.json <<'JSON'
{"steps": [
  {"voltage": 3.3, "current": 0.5, "delay": 1},
  {"voltage": 5.0, "current": 0.5, "delay": 2},
  {"voltage": 0.0, "current": 0.5, "delay": 0}
]}
JSON
scripts/psu.py sequence seq.json --host <ip> --ch 1 --yes
```

The tool checks max_voltage and max_current at each step. On an error, it turns the output off when safe_off is enabled.

## 5. Command reference

| Command | Function | Key options |
|---|---|---|
| idn, channels | Identify the supply and its channels | --family |
| set | Set voltage and current | --ch, --voltage, --current, --verify |
| get | Read setpoints | --ch |
| measure | Measure V, I, and P | --items voltage,current,power |
| output | Enable or disable the output | on requires --yes |
| all-off | Disable all channels | none |
| protect | Set OVP and OCP | --ovp, --ocp |
| ramp | Software voltage ramp | --to, --start, --step, --delay, --yes |
| sequence | Run a JSON sequence | file, --yes |
| log | Record V, I, and P | --duration, --interval, --out |
| web | Local Web UI and live chart | --bind, --web-port, --open |
| scpi, query, write | Raw SCPI | --query |
| config | Defaults and limits | host, resource, serial, max_voltage, max_current, safe_off |

Common connection options: --host, --port 5025, --resource, --serial, --baud, --backend, --family, --timeout, --max-voltage, and --max-current.

## 5.5 Web UI

```bash
scripts/psu.py web --hid dp100 --open
scripts/psu.py web --host 192.168.1.60 --bind 127.0.0.1 --web-port 8765
```

- The default bind address is 127.0.0.1. The UI is not open to the network.
- --bind 0.0.0.0 opens the UI to the LAN. The UI has no authentication. Use it with care.
- On WSL, --open starts a Windows browser through cmd.exe start or PowerShell. Use localhost. WSL2 forwards the port.
- The UI uses React, Tailwind, and shadcn-style components. The prebuilt files are in webapp/dist.
- The UI reads device capabilities. It hides OVP, OCP, power, input voltage, or channel controls when the device does not support them.
- The UI supports Chinese and English, and light and dark themes. Settings persist in localStorage.
- The live chart uses ECharts on a canvas with two Y axes. One chart shows voltage and current. The V and A buttons show or hide each series.
- The time window is 10, 30, or 60 seconds. The default is 30 seconds.
- The sample rate adapts to the device: DP100 uses 20 Hz. Other devices use 10 Hz. DP100 HID needs a 20-50 ms frame interval. A shorter interval can cause a disconnect.
- The UI shows skeleton cards until the first state arrives. The chart draws no curve while the output is off.
- Live data uses SSE at /api/stream. The DP100 reads one HID report per sample. A background sampler keeps a 4-minute ring buffer. /api/history pre-fills the chart.
- Chart cache is off by default. The chart keeps the current window. You can enable cache for CSV export. The cache limit is 1 hour.
- The right side of the chart has scope knobs for V/div, V position, A/div, and A position. AUTO calculates the range one time. It saves the result as MAN.
- The title bar is fixed. Basic and Advanced share the same title bar.
- Framer Motion animates the tab indicator, page changes, and alerts. It obeys reduced-motion settings.
- The Advanced view has no cards. It contains sequence output, voltage scanning, and current scanning.
- The control panel starts with a preset list. You can save the current voltage and current as a preset. Presets that exceed the device limits are hidden.
- Press Enter or leave a setpoint field to apply it. The field also applies after a short delay. Use the mouse wheel on a focused field to change the last displayed digit.
- Pause freezes the chart. The Cache button controls the chart buffer. Hover shows V and A values.
- The output ON state uses a solid green badge. A green dot pulses in the CONTROL title.
- Web Audio plays two tones for output ON/OFF and a low tone for a device fault. The speaker button mutes the sound and saves the setting.
- Device faults include disconnect, OVP, OCP, OPP, OTP, reverse polarity, input under-voltage, and temperature of 60 degrees C or more. The UI shows a native alert() and a floating warning. The warning does not move the page layout. It stays for at least 10 seconds. The browser title also changes to a warning symbol.
- The UI provides setpoint control, output ON/OFF, OVP/OCP, live V/I/P and temperature, device information, sequence output, voltage and current scans, and CSV export.
- Visual style: warm orange, ivory, and ink colors. Industrial grid and square panels. Geist and Geist Mono fonts. Voltage is orange. Current is steel blue.
- The DP100 /api/state call uses one snapshot() read. It does not read each value separately.
- The server also enforces voltage and current limits. The UI is not a path around the safety layer.

## 6. Safety limits

- Output ON, ramp, and sequence require --yes. set does not enable the output.
- The tool checks voltage and current limits before each setpoint. sequence checks each step.
- On an error, ramp and sequence turn the output off when safe_off is enabled.
- OVP and OCP are software functions. They do not replace a hardware current limit or a fuse.
- A battery or a large capacitor can keep voltage on the terminals after output OFF.

## 7. Self-test

```bash
~/.local/share/psu/venv/bin/python -m pytest tests -q
scripts/psu.py setup --dev
```

The tests use a local mock SCPI supply with a Rigol DP832 command style. The tests do not touch real hardware.
