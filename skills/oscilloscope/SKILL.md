---
name: oscilloscope
description: Control bench oscilloscopes over a LAN (SCPI socket) or USB (USBTMC or VISA). Supports Rigol, Keysight, Agilent, Tektronix, Siglent, LeCroy, Rohde & Schwarz, GW Instek, Yokogawa, OWON, Hantek, Micsig, BK Precision, UNI-T, Fluke, PeakTech and generic SCPI instruments. Use this skill when the user mentions an oscilloscope, scope, DSO, MSO, SCPI, VISA, USBTMC, VXI-11, waveform capture, trigger setup, probe or channel configuration, screen capture, frequency measurement, or asks to inspect a signal on real hardware. Use it also for intermittent-fault monitoring (arm, wait, capture evidence) and for offline analysis of exported waveform files, even when the user does not name the brand.
---

# Oscilloscope

This skill controls bench oscilloscopes from a command line. It has three layers:

1. **Transport layer.** It uses a raw TCP socket, pyvisa, or a Linux usbtmc device.
2. **Dialect layer.** It builds SCPI commands for each instrument family.
3. **Acquisition layer.** It converts raw samples to volts, measures the waveform, and writes evidence files.

```bash
scripts/scope.py idn --host 192.168.1.50
scripts/scope.py capture --host 192.168.1.50 --channels 1,2 --out run.csv
scripts/scope.py measure --host 192.168.1.50 --channel 1 --items vpp,rms,freq
scripts/scope.py shot --host 192.168.1.50 --out screen.png
```

## 1. Before you start

Make these three decisions first:

1. **Interface.** Use `--host` for a LAN instrument. Use `--resource USB0::...::INSTR` for USB.
2. **Family.** The `idn` command reads `*IDN?` and selects the family. If the result is wrong, add `--family`.
3. **State change.** Start with read-only commands: `idn`, `measure`, `capture`. Tell the user before you change a channel, the timebase, or the trigger.

## 2. Environment

```bash
scripts/scope.py doctor --host 192.168.1.50
scripts/scope.py list
scripts/scope.py discover --scan 192.168.1.0/24
scripts/scope.py setup
```

- The LAN path has no dependencies. It uses a raw TCP socket.
- The USB path needs pyvisa and pyvisa-py. On Linux, a usbtmc kernel device also works.
- On Linux and WSL, install the udev rules with `scripts/install_udev.sh`.
- The program detects WSL at startup. If you do not give `--host` or `--resource`, it tries these steps in order:
  1. A local `/dev/usbtmc*` device.
  2. A single VISA resource.
  3. On WSL, `usbipd attach` for a Windows-side oscilloscope.
- To disable automatic attach, use `--no-auto-attach` or set `SCOPE_NO_AUTO_ATTACH=1`.
- The CLI execs `SCOPE_HOME/venv` only when the active interpreter cannot import `pyvisa`; set `SCOPE_NO_REEXEC=1` to keep the current interpreter. `SCOPE_HOME` defaults to `.emb-agent/bench/scope` inside a project that has a `.emb-agent` marker, and keeps using an existing `~/.local/share/scope`. On a sandboxed host, run `setup` once so the venv and caches stay inside the workspace: every command that must exec or write outside it costs the user an approval prompt.
- `doctor` shows the Windows-side usbipd devices, the vendor IDs, and the bind and attach commands:

```bash
scripts/scope.py doctor --attach-usb
```

A device in state `Not shared` needs `usbipd bind --busid X` (Administrator). A device in state `Shared` can be attached directly.

## 3. Families

The `family` field from `idn` selects the command syntax.

| Family | Typical instruments | Notes |
|---|---|---|
| `rigol` | DHO800/900, MSO5000, DS1000Z | Uses `:TIMebase:MAIN:SCALe` and `:WAVeform:PREamble?`. |
| `keysight` | InfiniiVision DSO and MSO | Uses `:TIMebase:SCALe`. Supports PNG screenshots. |
| `tektronix` | TBS, TDS, DPO, MSO | Uses ASCII `CURVe?` with WFMPre and WFMOutpre fallback. |
| `siglent` | SDS series | Uses `:TDIV` and `C1` channel names. |
| `lecroy` | WaveRunner, WaveSurfer | Measures the waveform in software. |
| `rns` | Rohde & Schwarz | Reuses the Keysight dialect. |
| `gwinstek` | GDS series | Uses `:MEASure:*? CHANnelN`. |
| `owon` | OWON XDS, Hanmatek DOS and SDS | Uses a 4-byte length frame with a JSON header. |
| `peaktech` | PeakTech 13xx | Uses the Owon protocol. |
| `hantek` | Hantek DSO2000 (DSO2C50) | Control and measurement are verified. Waveform export uses a vendor command. |
| `micsig` | Micsig MHO series | Uses `:MENU:RUN`, `:MENU:STOP`, `:MEASure:*? CHn` and `:SYS:SCR?`. |
| `bkprecision` | BK Precision 2540 and 2560 | Uses the LeCroy MAUI command set. |
| `unit` | UNI-T UPO 2000E and 3000E | Uses `:CHANn:SCAL` and `:WAVeform:*`. |
| `fluke` | Fluke PM3370, PM3380 and PM3390 | Uses `SENSe:SWEep:TIME` and `TRACe?`. |
| `atten`, `zlg` | ATTEN, ZLG ZDS | No public SCPI manual was found. The skill identifies the device and uses generic commands. |
| `yokogawa`, `generic` | Other SCPI instruments | Uses generic commands and the `scpi` command. |

Read `references/dialects.md` for command sources and confidence levels. Read `references/tektronix.md` for Tektronix details, including the Windows TekVISA bitness problem.

## 4. Basic workflow

```bash
# 1. Identify the instrument.
scripts/scope.py idn --host <ip> --json

# 2. Read the state. Do not change it.
scripts/scope.py scpi --host <ip> ":TRIGger:STATe?" --query
scripts/scope.py measure --host <ip> --channel 1 --items vpp,rms,freq,period

# 3. Change the settings only when necessary.
scripts/scope.py channel  --host <ip> --ch 1 --scale 0.5 --offset 0 --coupling DC --probe 10
scripts/scope.py timebase --host <ip> --scale 1e-3
scripts/scope.py trigger  --host <ip> --source 1 --level 0.8 --slope rising --mode normal

# 4. Capture the waveform and the evidence.
scripts/scope.py run single --host <ip>
scripts/scope.py capture --host <ip> --channels 1,2 --points 10000 --out captures/run.csv --json
scripts/scope.py shot --host <ip> --out captures/run.png
```

Use numeric waveform files (CSV or JSON) as the primary evidence. A screenshot is a secondary aid for a human reader. A CSV file supports diff, statistics, and machine analysis.

## 5. Intermittent faults: `monitor`

```bash
# Trigger one event and capture the evidence.
scripts/scope.py monitor --host <ip> --channels 1 --max-events 1 \
  --trigger-type edge --trigger-source 1 --trigger-level 1.0 \
  --timebase 5e-6 --outdir captures --prefix glitch

# Use a preset: glitch-short, power-on-spike, intermittent-noise, missing-pulse, burst-pulse.
scripts/scope.py monitor --host <ip> --preset glitch-short --channels 1 --auto-rearm --max-events 5

# Show the commands. Do not touch the instrument.
scripts/scope.py monitor --host <ip> --preset glitch-short --dry-run
```

The `monitor` command does these steps:

1. It applies the setup.
2. It arms a single or sequence trigger.
3. It polls `:TRIGger:STATe?` or `:ACQuire:STATE?`.
4. It writes `captures/<prefix>-NN.csv` and `.json` after a hit.
5. It re-arms when you use `--auto-rearm`.

If a dialect has no pulse trigger, the command uses an edge trigger and writes a warning to stderr.

## 6. Commands

| Command | Function | Key options |
|---|---|---|
| `idn` | Read `*IDN?` and select the dialect. | `--family` |
| `list`, `discover` | List VISA resources or scan a subnet. | `--scan`, `--backend` |
| `doctor` | Check the environment and the connection. | `--host`, `--attach-usb` |
| `test` | Run the skill test suite. | `--install`, `-k` |
| `channel` | Set the vertical scale, offset, coupling, and probe. | `--ch`, `--scale`, `--offset`, `--coupling`, `--probe` |
| `timebase` | Set the timebase. | `--scale`, `--offset` |
| `trigger` | Set an edge trigger. | `--source`, `--level`, `--slope`, `--mode` |
| `run` | Run, stop, single, or autoscale. | action |
| `capture` | Capture a waveform. | `--channels`, `--points`, `--out`, `--format`, `--single`, `--plot`, `--cache` |
| `measure` | Measure the signal. The skill calculates the value when the instrument cannot. | `--channel`, `--items` |
| `shot` | Save a screenshot, or a waveform plot when no screen dump is available. | `--out` |
| `scpi`, `query`, `write` | Send a raw SCPI command. | `--query` |
| `monitor` | Watch for an event and write evidence. | See section 5. |
| `analyze` | Analyze a CSV or NPZ file offline. | `--csv`, `--npz`, `--fft`, `--plot` |
| `config` | Store default values. | `set`, `get`, `list`, `unset` |

Connection options: `--host`, `--port 5025`, `--resource`, `--backend`, `--family`, `--timeout`, `--json`.

## 7. Recovery and signal quality

The `capture` command has two protection layers.

**Layer 1: retry.**

If the waveform is empty or a timeout occurs, the command tries these steps in order:

1. Send `*OPC?` and wait.
2. Send `:RUN` and force a trigger.
3. Run autoset. This step is optional and needs `--autoset-on-empty`.

The `recovery` field in the JSON output records each attempt and each action. Use `--no-recovery` to disable retries.

**Layer 2: signal-quality checks.**

Each channel gets a `quality` list. A warning has a `code`, a `message`, and a `suggestion`.

| Code | Meaning |
|---|---|
| `FLAT` | The signal has almost no amplitude. |
| `CLIPPING` | Many samples sit on the extreme values. The signal can be clipped. |
| `DC_OFFSET` | The DC offset is too large. |
| `LOW_RESOLUTION` | The signal uses very few ADC codes. |
| `ALIASING` | The measured frequency is near the Nyquist limit. |
| `EMPTY` | The waveform has no samples. |

Use `--no-quality` to disable the checks. The `analyze` command applies the same checks to an offline file. The `monitor` command also applies them.

## 8. One-shot capture and analysis

By default, `capture` does all of these steps in one command:

1. Capture the waveform.
2. Calculate the statistics.
3. Run the signal-quality checks.
4. Calculate the FFT, the harmonics, and the THD.
5. Classify the waveform: sine, square, triangle, sawtooth, pulse, or DC.
6. Write an SVG plot when you use `--plot`.

```bash
# Single-shot capture: arm, wait for the trigger, read, analyze.
scripts/scope.py capture --single 3 --points 2000 --json

# Capture only. This is faster.
scripts/scope.py capture --single 3 --no-analyze --json
```

- `--single [seconds]`: The scope arms a single sequence and waits for the trigger. Tektronix uses `STOPAfter SEQUENCE`. Other dialects use `:SINGle`.
- Each channel has an `analysis` object. The object contains `waveform`, `fundamental_hz`, `thd_pct`, `harmonics`, `overshoot_pct`, `noise_rms`, and `crest_factor`.
- On a TBS 1102B, one command takes about 3 to 5 seconds. The pyvisa start takes about 1.4 seconds. The waveform transfer takes about 2 seconds. The analysis takes less than 20 milliseconds.
- The skill caches the resource string in `~/.local/share/scope/last_resource`. This step removes the resource enumeration delay.

## 9. Advanced analysis, plots, and cache

The instrument supplies raw samples and a small number of measurements. The skill calculates the advanced values.

```bash
# Capture, plot, and write an NPZ cache.
scripts/scope.py capture --points 2000 --out run.csv --plot run.svg --cache run.npz

# Offline analysis: FFT, harmonics, THD, overshoot, noise, and crest factor.
scripts/scope.py analyze --npz run.npz --fft --plot run-an.svg
```

- `advanced` calculates the overshoot, the undershoot, the top and base levels, the noise RMS, the crest factor, the fundamental frequency, harmonics 2 to 5, and the THD.
- `--plot` writes an SVG file. It has no external dependency. It decimates the data to `--plot-points` samples, so a large record does not stall the plot.
- `--cache [path]` writes the time and voltage arrays to an NPZ file. `analyze --npz` reads this file and skips a second transfer.
- The default cache path is `~/.local/share/scope/cache/`. An NPZ file is much smaller than a CSV file.

**Screenshot.** The TBS 1102B has no host-side screen dump command. When the instrument has no screen dump, `shot` captures CH1 and writes an SVG waveform plot. The JSON output has `fallback: waveform-plot`. The skill does not report a plot as a screenshot.

## 10. Safety

- `channel`, `timebase`, `trigger`, `run`, and `autoscale` change the live state of the instrument. Use read-only commands first unless the user asks for a change.
- Read the old value before you write a new value (`scpi "...?" --query`). You can then restore the old value.
- For high-impedance or high-voltage signals, check the probe attenuation and the coupling first. Do not assume a 10x probe.
- `monitor` re-arms the trigger and can stop the acquisition. Make sure that this action does not disturb the waveform that the user is watching.
- A screenshot or a long capture can occupy the front panel. Restore the original settings before you finish.

## 11. Troubleshooting

Read `references/troubleshooting.md` for connection failures, USBTMC permissions, WSL, binary block truncation, missing screenshots, and the Windows TekVISA bitness problem. Read `references/tektronix.md` for Tektronix-specific problems.

## 12. Code structure

```text
scripts/scope.py                  stable entry point (arguments and compatibility exports)
scripts/scopescpi/common.py       configuration, output, block and frame parsers
scripts/scopescpi/transport.py    socket, pyvisa, usbtmc
scripts/scopescpi/dialects/       one module per family, registry, auto-detection
scripts/scopescpi/acquisition.py  scaling, statistics, measurement fallback
scripts/scopescpi/cli.py          subcommands
```

Old scripts can call `scripts/scope.py` as before. To reuse the internal API, import it directly:

```python
from scopescpi.dialects import RigolDialect
```

## 13. Tests

```bash
scripts/scope.py test --install   # uses the skill venv, installs pytest if needed
scripts/scope.py test -k capture  # a subset
```

`scope.py test` uses `~/.local/share/scope/venv/bin/python` when it exists and the
active interpreter otherwise. `scope.py setup --dev` installs pytest into the venv.

The tests use a local mock SCPI server with the Rigol and Tektronix dialects. The tests do not touch hardware.

## 14. Hardware validation

The skill was tested on a **Tektronix TBS 1102B** (USB `0699:0368`, WSL with usbipd).

- `doctor` found the resource `USB0::1689::872::C039642::0::INSTR`.
- `idn` returned `TEKTRONIX,TBS 1102B,...` and selected the `tektronix` dialect.
- `capture --points 1000` returned 5.4 Vpp at about 995 Hz. The quality check did not report a false warning.
- `measure`, `analyze`, and `monitor --max-events 1` passed.
- `shot` wrote an SVG waveform plot. The TBS 1102B has no screen dump command.
- The TBS 1102B record length limit is 2500 points. A larger request is truncated by the instrument.

WSL note: the kernel has no `usbtmc` module. The skill uses pyvisa-py with libusb. The `setup` command installs `libusb-package`. At startup, `scope.py` runs again in the skill venv. Set `SCOPE_NO_REEXEC=1` to disable this behavior.

## 15. Writing style

The documentation uses ASD-STE100 Simplified Technical English as a guide. Use short sentences, the active voice, and the simple present tense. Use "must" for a requirement and "can" for a capability.
