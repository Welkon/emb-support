---
name: oscilloscope
description: Control bench oscilloscopes over a LAN (SCPI socket) or USB (USBTMC or VISA). Supports Rigol, Keysight, Agilent, Tektronix, Siglent, LeCroy, Rohde & Schwarz, GW Instek, Yokogawa, OWON, Hantek, Micsig, BK Precision, UNI-T, Fluke, PeakTech and generic SCPI instruments. Use this skill when the user mentions an oscilloscope, scope, DSO, MSO, SCPI, VISA, USBTMC, VXI-11, waveform capture, trigger setup, probe or channel configuration, screen capture, frequency measurement, or asks to inspect a signal on real hardware. Use it also for intermittent-fault monitoring (arm, wait, capture evidence) and for offline analysis of exported waveform files, even when the user does not name the brand. Bench questions are answered one intent per command (status, arm, watch, capture, monitor); the caller never composes SCPI.
---

# Oscilloscope

This skill answers bench questions about a live instrument. The interface is
**intents** — "what is it doing", "show me this event", "watch this rail" —
never vendor commands. It has four layers:

1. **Intent layer.** `status`, `arm`, `watch`, `capture`, `monitor`, `shot`,
   `analyze`. One invocation answers one question on one connection.
2. **Driver layer.** One module per family turns an intent into that vendor's
   command set. SCPI does not leave this layer.
3. **Transport layer.** Raw socket, pyvisa, or Linux usbtmc.
4. **Acquisition layer.** Samples to volts, measurements, quality checks, evidence.

Rule: if a bench question has no verb, add a verb (or a driver method). Do not
work around it with a raw command or a heredoc. Raw commands are what make the
skill expensive to use: one more connection, one more approval, one more typo.

```bash
# Give the connection once. Later commands remember it.
scripts/scope.py status --resource 'USB0::...::INSTR' --json

# One event: set up, arm, wait, capture, measure, screenshot.
scripts/scope.py arm --ch 1:0.5:0:10:DC --timebase 1e-3 \
  --source 1 --level 1.5 --measure vpp,vavg \
  --out evidence/power-on.csv --shot evidence/power-on.png

# A trend: 10 samples on one connection, with summary statistics.
scripts/scope.py watch --channel 1 --items vavg,vmin,vmax \
  --samples 10 --interval 0.5 --out evidence/vdd-decay.json
```

## 1. Ask for the answer

| Question | Command |
|---|---|
| What is the instrument set to? | `status --json` |
| Show me this event once | `arm --ch ... --timebase ... --measure ...` |
| Prepare the trigger, then act outside the scope | `arm ... --no-wait` |
| Let the skill choose scale/trigger/timebase | `arm --auto-fit` |
| What is on the screen right now? | `capture --out ... --json` |
| Measure the same signal over time | `watch --samples ... --items ...` |
| Catch an intermittent event and keep evidence | `monitor --preset ...` |
| Save a screenshot | `shot --out ...` |
| Analyze a saved capture offline | `analyze --csv ... --fft` |

Three rules keep the command count low:

1. **One connection per question.** `status`, `arm`, `watch`, `capture` and
   `monitor` each set up, act, read back and save in a single invocation.
2. **Give the connection once.** The first `--host` or `--resource` is stored in
   the skill config; later commands need no connection flags.
3. **Read before you write.** `status` is read-only. Say what you will change
   before you change the timebase, a channel, or the trigger.

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

`idn` selects the family from the identification string. Override with
`--family` only when detection is wrong.

| Family | Typical instruments |
|---|---|
| `rigol` | DHO800/900, MSO5000, DS1000Z |
| `keysight` | InfiniiVision DSO and MSO |
| `tektronix` | TBS, TDS, DPO, MSO |
| `siglent` | SDS series |
| `lecroy` | WaveRunner, WaveSurfer |
| `rns` | Rohde & Schwarz |
| `gwinstek` | GDS series |
| `owon` | OWON XDS, Hanmatek DOS and SDS |
| `peaktech` | PeakTech 13xx |
| `hantek` | Hantek DSO2000 (DSO2C50) |
| `micsig` | Micsig MHO series |
| `bkprecision` | BK Precision 2540 and 2560 |
| `unit` | UNI-T UPO 2000E and 3000E |
| `fluke` | Fluke PM3370, PM3380 and PM3390 |
| `atten`, `zlg` | ATTEN, ZLG ZDS |
| `yokogawa`, `generic` | Other instruments |

The per-family command mapping is driver material in `references/dialects.md`.
Workflows never depend on it. Read `references/tektronix.md` only for the
Tektronix details, including the Windows TekVISA bitness problem.

## 4. Workflow

### 4.1 First contact

```bash
scripts/scope.py status --resource 'USB0::6833::1303::DS1ZE255216073::0::INSTR' --json
```

`status` returns the identification, the family, the timebase, the trigger and
the per-channel settings. A field the instrument does not implement is `null`
and listed under `unsupported`. That is not an error and needs no follow-up
command. After this call the connection is remembered.

### 4.2 Capture one event

```bash
scripts/scope.py arm --ch 1:0.5:0:10:DC --ch 2:1:0:10:DC \
  --timebase 1e-3 --source 1 --level 1.5 --slope rising \
  --channels 1,2 --measure vpp,vavg,freq \
  --out evidence/run.csv --plot evidence/run.svg --shot evidence/run.png --json
```

`--ch` is `N[:scale[:offset[:probe[:coupling]]]]`, in volts and seconds. Omit a
field and the instrument keeps its current value. `arm` applies the setup, arms
one sequence, waits for the trigger (`--wait`), then captures, measures, checks
signal quality and writes the files. When it times out it says so and does not
save a meaningless record. Use `--mode normal` for a free-running read instead
of a single sequence.

`--auto-fit` closes the loop: if the capture is clipped, off-centre, low
resolution or aliased, `arm` adjusts scale, offset, timebase or trigger level
and captures again (at most three adjustments). Every change is listed under
`adjustments`, so the result stays auditable.

`--timing 1,2` adds an edge-to-edge result between two captured channels:
`delay` (signed mean), `skew` (standard deviation over pairs), `pair` counts and
the matching `window_s`. `--timing-edge-a` and `--timing-edge-b` select rising or
falling. Both channels must be in the same capture.

`--preset` fills the setup for a recurring scenario: `vdd-droop`, `power-on`,
`pulse-train`, `button-bounce`. A preset only supplies values you did not give,
and it sets the measurements that scenario usually needs (`pulse_width`,
`vmin`/`vmax`, ...). Combine it with `--auto-fit` when the signal level is
unknown:

```bash
scripts/scope.py arm --preset vdd-droop --auto-fit --ch 2:1:0:10:DC \
  --out evidence/droop.csv --json
```

### 4.3 Arm first, act outside the scope

Some tests need the scope waiting before you power the board:

```bash
scripts/scope.py arm --ch 2:1:0:10:DC --timebase 1e-3 \
  --source 2 --level 1.5 --no-wait --json
```

It returns `armed: true` and the trigger state (`WAIT` or `RUN`) without
capturing. Enable the supply, then use `capture` or `watch` to collect the
result. Do not guess whether the arm took effect.

### 4.4 Watch a signal over time

```bash
scripts/scope.py watch --channel 1 --items vavg,vmin,vmax \
  --samples 20 --interval 0.5 --state --out evidence/vdd-decay.json
```

One connection, 20 samples. The JSON has every row plus min, median, max and
mean per channel and item. This replaces a hand-written poll loop.

### 4.5 Evidence

Use numeric waveform files (CSV or JSON) as the primary evidence. A screenshot
is a secondary aid for a human reader. A CSV file supports diff, statistics and
machine analysis.

## 5. Intermittent faults: `monitor`

```bash
# Trigger one event and capture the evidence.
scripts/scope.py monitor --host <ip> --channels 1 --max-events 1 \
  --trigger-type edge --trigger-source 1 --trigger-level 1.0 \
  --timebase 5e-6 --outdir captures --prefix glitch

# Use a preset: glitch-short, power-on-spike, intermittent-noise, missing-pulse, burst-pulse.
scripts/scope.py monitor --host <ip> --preset glitch-short --channels 1 --auto-rearm --max-events 5

# Show the plan. Do not touch the instrument.
scripts/scope.py monitor --host <ip> --preset glitch-short --dry-run
```

The `monitor` command does these steps:

1. It applies the setup.
2. It arms a single or sequence trigger.
3. It waits for the trigger state the driver reports.
4. It writes `captures/<prefix>-NN.csv` and `.json` after a hit.
5. It re-arms when you use `--auto-rearm`.

If a dialect has no pulse trigger, the command uses an edge trigger and writes a warning to stderr.

## 6. Commands

| Command | Function | Key options |
|---|---|---|
| `status` | Read the whole instrument in one connection: timebase, trigger, acquisition and per-channel settings. | `--channels`, `--json` |
| `idn` | Read `*IDN?` and select the dialect. | `--family` |
| `list`, `discover` | List VISA resources or scan a subnet. | `--scan`, `--backend` |
| `doctor` | Check the environment and the connection. | `--host`, `--attach-usb` |
| `test` | Run the skill test suite. | `--install`, `-k` |
| `channel` | Set the vertical scale, offset, coupling, and probe. | `--ch`, `--scale`, `--offset`, `--coupling`, `--probe` |
| `timebase` | Set the timebase. | `--scale`, `--offset` |
| `trigger` | Set an edge trigger. | `--source`, `--level`, `--slope`, `--mode` |
| `run` | Run, stop, single, or autoscale. | action |
| `capture` | Read the current screen settings and waveform. | `--channels`, `--points`, `--out`, `--format`, `--single`, `--plot`, `--cache`, `--timing` |
| `arm` | Set up, arm, wait, then capture, measure and save in one connection. | `--ch`, `--timebase`, `--source`, `--level`, `--measure`, `--out`, `--shot`, `--no-wait`, `--auto-fit`, `--preset`, `--timing` |
| `watch` | Measure the same signals repeatedly and summarize the trend. | `--channel`, `--items`, `--samples`, `--interval`, `--state` |
| `measure` | Measure the signal. The skill calculates the value when the instrument cannot. | `--channel`, `--items` |
| `shot` | Save a screenshot, or a waveform plot when no screen dump is available. | `--out` |
| `monitor` | Watch for an event and write evidence. | See section 5. |
| `analyze` | Analyze a CSV or NPZ file offline. | `--csv`, `--npz`, `--fft`, `--plot`, `--timing` |
| `config` | Store default values. | `set`, `get`, `list`, `unset` |

Advanced knobs for a one-off change: `channel`, `timebase`, `trigger`, `run`.
They are not part of the normal flow; `arm` applies the same settings and also
captures the result.

Measurement items: `vpp`, `vmin`, `vmax`, `mean`, `vavg`, `rms`, `freq`,
`period`, `duty`, `rise`, `fall`, `pulse_width`, `negative_width`. The last two
are the widest high and low pulse inside the record. The instrument answers when
the driver has a query; otherwise the skill computes them from the captured
samples, so no CSV post-processing is needed.

`measurement_details` says where each number came from: `source` is
`instrument` or `waveform`, `unit` is explicit, and waveform values also carry
`resolution` (one ADC code or one sample interval) and a resolution-based
`uncertainty`. Instrument values have no invented accuracy figure.

Connection options: `--host`, `--port 5025`, `--resource`, `--backend`. Give them
once: the working endpoint is stored in the skill config and reused. `--family`,
`--timeout` and `--json` apply to the current command only.

Start with `status`: it is read-only and replaces a chain of individual reads.
Queries the instrument does not implement come back as `null` and are listed
under `unsupported`. Its `capabilities` object lists the measurement items the
driver can answer and the ones the skill computes from the waveform.
`connection.source` reports how the instrument was found (`explicit-resource`,
`config-resource`, `discovered`, `wsl-attach`, ...).

WSL with an instrument only Windows can see: `scripts/scope.py --bridge windows status --json`. The command runs on the Windows interpreter with the same dialect code; add `--win-python C:\path\to\python.exe` (or set `SCOPE_WIN_PYTHON`) to pick a Windows venv that has pyvisa.

## 7. Recovery and signal quality

The `capture` command has two protection layers.

**Layer 1: retry.**

If the waveform is empty or a timeout occurs, the command tries these steps in order:

1. Wait for the instrument to finish the pending operation.
2. Re-run the acquisition and force a trigger.
3. Autoscale. This step is optional and needs `--autoset-on-empty`.

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

`analyze` reports every channel in the record. `--channel` selects the channel
used by `--fft` and `--plot`; the per-channel results are always under
`channels`.

## 8. One-shot capture and analysis

By default, `capture` does all of these steps in one command:

1. Read the waveform.
2. Calculate the statistics.
3. Run the signal-quality checks.
4. Calculate the FFT, the harmonics, and the THD.
5. Classify the waveform: sine, square, triangle, sawtooth, pulse, or DC.
6. Write an SVG plot when you use `--plot`.

Use `arm` when the setup is part of the question, and `capture` when the
instrument is already set up and you only want the data.

```bash
# Single-shot read: arm, wait for the trigger, read, analyze.
scripts/scope.py capture --single 3 --points 2000 --json

# Read only. This is faster.
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
- Read `status --json` before you write. Keep that output so you can restore the old values.
- For high-impedance or high-voltage signals, check the probe attenuation and the coupling first. Do not assume a 10x probe.
- `monitor` re-arms the trigger and can stop the acquisition. Make sure that this action does not disturb the waveform that the user is watching.
- A screenshot or a long capture can occupy the front panel. Restore the original settings before you finish.

## 11. Troubleshooting

Read `references/troubleshooting.md` for connection failures, USBTMC permissions, WSL, binary block truncation, missing screenshots, and the Windows TekVISA bitness problem. Read `references/tektronix.md` for Tektronix-specific problems.

## 12. Code structure

```text
scripts/scope.py                    stable entry point (arguments and compatibility exports)
scripts/scopescpi/cli.py            argparse plus the intent verbs (status, arm, watch, ...)
scripts/scopescpi/plan.py           Plan + Executor shared by arm, capture --single, monitor
scripts/scopescpi/session.py        one session per intent; reconnect and retry once
scripts/scopescpi/connection.py     ordered chain: flags, config, usbtmc, cache, discovery, WSL
scripts/scopescpi/capabilities.py   closed vocabulary: driver query or waveform fallback
scripts/scopescpi/autofit.py        deterministic scale/offset/timebase/level fitting
scripts/scopescpi/uncertainty.py    unit, source, resolution and uncertainty per measurement
scripts/scopescpi/timing.py         cross-channel edge-to-edge delay and skew
scripts/scopescpi/result.py         Result envelope; refuses command strings
scripts/scopescpi/evidence.py       atomic artifact writes, one manifest per intent
scripts/scopescpi/dialects/         adapters: one module per family, the only place with SCPI
scripts/scopescpi/acquisition.py    scaling, statistics, measurement fallback
scripts/scopescpi/transport.py      socket, pyvisa, usbtmc (no resolution)
scripts/scopescpi/common.py         configuration, output, block and frame parsers
scripts/scopescpi/quality.py        signal-quality checks
scripts/scopescpi/analysis.py       FFT, harmonics, classification, plots
```

Six invariants hold this shape together. `tests/test_architecture.py` and
`tests/test_workflow.py` enforce them:

1. **Closed vocabulary.** The agent can ask only the questions in this file.
   `status.capabilities` says which of them are measured and which are computed.
2. **Total capabilities.** A capability has a driver query or a host fallback.
   An adapter returns `None`, never an exception, when it cannot answer.
3. **One session per intent.** Verbs use `Session`; `connect()` appears only in
   `connection.py`. A dead handle is reopened and the operation retried once.
4. **One executor.** `arm`, `capture --single` and `monitor` apply setup, arm
   and wait through the same `Plan`/`Executor`.
5. **Atomic evidence.** Files go through `Evidence`; a failed intent leaves no
   partial artifact.
6. **No commands in results.** `Result` refuses command strings, and
   `status.connection.source` reports how the instrument was found.
7. **Corrections are auditable.** `--auto-fit` reports every change under
   `adjustments`; no adjustment happens silently.
8. **Measurements carry provenance.** `measurement_details` gives unit, source
   and uncertainty; cross-channel numbers come from one record.

**Adding a capability.** Keep the interface at the intent level:

1. Add the item to `capabilities.MEASUREMENTS` with a fallback key produced by
   `stats()`. The capability test fails if it has neither a query nor a fallback.
2. Add the driver query where the instrument has one. Return `None` elsewhere so
   the fallback is used; never raise for an unsupported feature.
3. Add a test with the mock instrument. Assert the shape of the answer, not the
   vendor string.
4. Document the item in the table above. Do not document its command.

A raw-command escape hatch exists for maintainers, but it is not part of the
documented interface and no workflow may depend on it.

Old scripts can call `scripts/scope.py` as before. To reuse the internal API,
import it directly:

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
