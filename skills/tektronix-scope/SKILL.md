---
name: "tektronix-scope"
description: "Remote-control Tektronix oscilloscopes over VISA/SCPI and capture live waveform data to local files for debugging. Use when Codex needs to discover a Tek scope, connect by USB or TCPIP resource string, run direct SCPI queries or writes, inspect instrument state non-invasively, or export waveform samples to CSV and JSON for AI-assisted analysis."
---

# Tektronix Scope

## Overview

Use the bundled Python helper to talk to Tektronix oscilloscopes through PyVISA.
Prefer numeric waveform capture over screenshots when the goal is AI analysis, because CSV plus metadata is easier to inspect, diff, and post-process.
For `TBS1102B`, prefer USBTMC over the rear USB Device port; this model does not offer the Ethernet-style workflow used by newer scopes.

## Prerequisites

- Install `pyvisa`. For a pure-Python backend, install `pyvisa-py` too.
- Prefer full VISA resource strings such as `USB0::0x0699::...::INSTR`.
- Read `references/tektronix-workflow.md` if transport, backend, or preamble fields are unclear.
- Read `references/tbs1102b.md` when working specifically with `TBS1102B`.

## Default Workflow

1. Discover resources first:

```bash
python3 scripts/tek_scope.py list --backend @py
python3 scripts/tek_scope.py scan --backend @py
```

2. For `TBS1102B`, prefer the one-shot capture path when you want AI to inspect both analog channels:

```bash
python3 scripts/tek_scope.py capture --backend @py --outdir captures --prefix tbs1102b
```

3. Identify the target instrument before changing anything when you need a specific resource:

```bash
python3 scripts/tek_scope.py idn --resource USB0::0x0699::...::INSTR --backend @py
```

4. Query state before issuing write commands:

```bash
python3 scripts/tek_scope.py query --resource USB0::0x0699::...::INSTR --backend @py "TRIGger:STATE?"
python3 scripts/tek_scope.py query --resource USB0::0x0699::...::INSTR --backend @py "HORizontal:SCAle?"
```

4.1. If you want structured control instead of writing raw SCPI by hand, inspect the built-in TBS1102B catalog first:

```bash
python3 scripts/tek_scope.py control list
python3 scripts/tek_scope.py control list --group trigger
python3 scripts/tek_scope.py control show channel.scale
```

The default `control list/show` view now exposes only the TBS1102B subset that passed live validation.
If you need to inspect the broader TBS1000B-family catalog, add `--all`:

```bash
python3 scripts/tek_scope.py control list --all
python3 scripts/tek_scope.py control show --all save.setup
```

4.2. Query a catalogued control key when you want machine-readable output with the exact SCPI header:

```bash
python3 scripts/tek_scope.py control get \
  --resource USB0::0x0699::...::INSTR \
  --backend @py \
  --channel CH1 \
  channel.scale
```

4.3. Set a catalogued control key when you want a safer wrapper around a known command family:

```bash
python3 scripts/tek_scope.py control set \
  --resource USB0::0x0699::...::INSTR \
  --backend @py \
  --channel CH1 \
  channel.scale \
  --value 0.5
```

4.4. Execute action-style commands such as autoset, trigger force, reset, or hardcopy:

```bash
python3 scripts/tek_scope.py control action \
  --resource USB0::0x0699::...::INSTR \
  --backend @py \
  system.autoset
```

Guarded operations such as autoset, reset, recall/save, hardcopy, calibration, or file-destructive commands are hidden from the default profile and require `--allow-risky`:

```bash
python3 scripts/tek_scope.py control action \
  --resource USB0::0x0699::...::INSTR \
  --backend @py \
  --allow-risky \
  system.autoset
```

5. Capture waveform data when the user wants to inspect a single signal:

```bash
python3 scripts/tek_scope.py waveform \
  --resource USB0::0x0699::...::INSTR \
  --backend @py \
  --source CH1 \
  --csv captures/ch1.csv \
  --metadata captures/ch1.json
```

5.1. Use `monitor` when the user wants the scope to watch for an intermittent event and auto-capture evidence after it appears:

```bash
python3 scripts/tek_scope.py monitor \
  --resource USB0::0x0699::...::INSTR \
  --backend @py \
  --mode trigger \
  --channels CH1 \
  --max-events 1 \
  --outdir captures \
  --prefix glitch-watch
```

5.2. For bursty or one-shot faults, prefer arming the scope in single-sequence mode before monitoring and re-arm it after each captured event:

```bash
python3 scripts/tek_scope.py monitor \
  --resource USB0::0x0699::...::INSTR \
  --backend @py \
  --mode trigger \
  --match SAVE \
  --setup-channel CH1 \
  --channel-scale 1.0 \
  --channel-position 0 \
  --horizontal-scale 1.0E-4 \
  --trigger-type pulse \
  --trigger-source CH1 \
  --trigger-level 1.0 \
  --trigger-mode NORMal \
  --pulse-when LESSthan \
  --pulse-width 5.0E-6 \
  --pulse-polarity POSitive \
  --arm-stopafter SEQuence \
  --auto-rearm \
  --channels CH1 \
  --max-events 5 \
  --outdir captures \
  --prefix burst-watch
```

5.3. If the scope is already configured for limit test or another built-in detector, monitor the resulting counters instead of blindly polling waveform data:

```bash
python3 scripts/tek_scope.py monitor \
  --resource USB0::0x0699::...::INSTR \
  --backend @py \
  --mode limit \
  --channels CH1 \
  --duration-s 60 \
  --outdir captures \
  --prefix limit-watch
```

5.4. Inspect the built-in intermittent-fault presets when you want a shorter command line for common scenarios:

```bash
python3 scripts/tek_scope.py monitor --list-presets
python3 scripts/tek_scope.py monitor --show-preset burst-pulse
```

5.5. Use a preset first, then override only the thresholds and scales that depend on the product under test:

```bash
python3 scripts/tek_scope.py monitor \
  --resource USB0::0x0699::...::INSTR \
  --backend @py \
  --preset burst-pulse \
  --setup-channel CH1 \
  --trigger-source CH1 \
  --trigger-level 1.0 \
  --channel-scale 1.0 \
  --channel-position 0 \
  --channels CH1 \
  --outdir captures \
  --prefix burst-watch
```

5.6. Save a tuned monitor configuration into a reusable JSON profile when the same fault needs repeated bench validation:

```bash
python3 scripts/tek_scope.py monitor \
  --preset glitch-short \
  --trigger-source CH1 \
  --trigger-level 0.8 \
  --channel-scale 0.5 \
  --horizontal-scale 2.0E-5 \
  --save-profile captures/glitch-short-profile.json \
  --dry-run
```

Then reload the profile later:

```bash
python3 scripts/tek_scope.py monitor \
  --profile captures/glitch-short-profile.json \
  --resource USB0::0x0699::...::INSTR \
  --backend @py
```

6. Analyze an existing capture when the user wants a quick electrical summary instead of scanning all samples manually:

```bash
python3 scripts/tek_scope.py analyze \
  --csv captures/ch1.csv \
  --metadata captures/ch1.json \
  --update-metadata
```

7. Render a short human-readable report when the user wants a result they can scan quickly or paste elsewhere:

```bash
python3 scripts/tek_scope.py report --metadata captures/ch1.json
```

8. Only send write commands that alter acquisition, trigger, vertical scale, or measurements when the user asked for that explicitly:

```bash
python3 scripts/tek_scope.py write \
  --resource USB0::0x0699::...::INSTR \
  --backend @py \
  --wait-opc \
  "ACQuire:STATE RUN"
```

## Operating Rules

- Start with `list`, `idn`, or `query` unless the user clearly asked to reconfigure the scope.
- Treat timebase, trigger, acquisition mode, and channel scale as live instrument state. Do not change them speculatively.
- Keep both the waveform CSV and metadata JSON when collecting evidence for debugging.
- The metadata JSON now includes a lightweight `analysis` block with min/max/pp/avg/rms, estimated high/low levels, threshold, edge counts, estimated frequency, estimated duty cycle, and average high/low pulse widths.
- Use `report` when the user wants a compact textual summary instead of raw JSON.
- For `TBS1102B`, assume USBTMC first, not LAN.
- Use `--backend @py` when NI-VISA is unavailable and the scope is reachable over LAN or a supported USB transport.
- Use `--dry-run` to show the exact SCPI sequence without touching hardware.
- On `TBS1102B`, if `CURVE?` returns nothing, confirm the selected source channel is displayed on screen.
- Use `capture` when the user wants a low-friction `CH1/CH2` dump. It auto-detects a single Tek USB scope and writes per-channel `CSV + JSON`.
- `capture` skips hidden channels by default to avoid changing live display state. Add `--show-hidden` only when the user explicitly wants the script to force channels on.
- `monitor` is the right path for intermittent faults. It polls a scope-side condition and captures waveform evidence only after the scope reports an event.
- `monitor` supports `trigger`, `limit`, and generic `query` modes. Use `trigger` for single-sequence or pulse-trigger workflows, `limit` for template/violation counters, and `query` when the user already knows a reliable SCPI status bit.
- `monitor` can now configure common setup items directly before waiting: `--channel-scale`, `--channel-position`, `--horizontal-scale`, `--trigger-type`, `--trigger-source`, `--trigger-level`, pulse-trigger width options, and `--arm-stopafter`.
- `monitor` also supports built-in `--preset` templates for common intermittent-fault patterns: `glitch-short`, `power-on-spike`, `intermittent-noise`, `missing-pulse`, and `burst-pulse`.
- `monitor --profile <file.json>` lets the agent save and reload a full monitor setup so the bench workflow can be repeated without retyping a long CLI.
- When `monitor` uses `--arm-stopafter`, it now reads back `ACQuire:STOPAfter?`, `TRIGger:STATE?`, and `ACQuire:STATE?` after the initial arm and after every auto-rearm, and it fails fast if `STOPAfter` did not stay on the requested mode.
- For the "agent configures parameters, human reproduces the fault" workflow, `monitor` is now enough by itself: one command can write the setup values, arm the scope, wait for the event, and export evidence.
- `monitor` is not a sample-by-sample live stream into AI. It is a practical event watcher: poll scope state, wait for the hardware to catch the event, then export waveform evidence for analysis.
- `control` now exposes a structured catalog for the TBS1102B command families in the official programmer manual, including acquisition, trigger, vertical, horizontal, measurement, cursor, FFT, save/recall, filesystem, status, and waveform-transfer groups.
- `control get/set/action` is the preferred path for common reconfiguration because it records the exact canonical SCPI header being used.
- The default TBS1102B profile now hides family commands that were proven unsupported on this model or that are destructive enough to require an explicit `--allow-risky` opt-in.
- `control list --all` and `control show --all` let you inspect the wider family catalog without re-enabling those operations for normal use.
- Keep `query` and `write` as the escape hatch for any valid SCPI string that is not yet convenient to express as a catalog key or that needs an exact vendor-specific argument payload.

## TBS1102B Notes

- Use `scan` to enumerate USB resources and identify the exact `USB0::...::INSTR` string.
- Use `capture` for the common `CH1/CH2` workflow instead of manually repeating `waveform` twice.
- The official programmer manual covers `TBS1102B` under the `TBS1000B` family.
- Remote control and waveform transfer are practical on this model.
- Direct host-side screenshot extraction is not the default path in this skill, because `TBS1102B` hardcopy behavior is centered on USB/PictBridge and front-panel save workflows rather than a clean generic screenshot-download command.

## Bundled Resources

- `scripts/tek_scope.py`
  Common entrypoint for resource discovery, device scanning, one-shot `CH1/CH2` capture, lightweight waveform analysis, direct SCPI query/write, structured `control` catalog operations, and ASCII waveform capture with Tek preamble scaling.
- `references/tektronix-workflow.md`
  Connection patterns, install notes, Tek preamble fallback details, and troubleshooting guidance.
- `references/tbs1102b.md`
  Model-specific notes for the `TBS1102B`, including USBTMC connection expectations and image-capture limitations.

## Troubleshooting

- If resource discovery fails, confirm the VISA backend first, then verify the exact resource string.
- If waveform capture fails on preamble fields, read `references/tektronix-workflow.md` and switch to explicit probing with `query`.
- If a write command changes live capture behavior unexpectedly, query the relevant state, restore only the user-approved settings, and document the delta.
