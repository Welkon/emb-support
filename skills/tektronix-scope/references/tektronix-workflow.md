# Tektronix workflow

## Purpose

Use this note when a Codex instance needs a quick reminder on how to connect to a Tektronix scope, which transport to prefer, and how the bundled waveform capture script derives scaled voltage and time values.

## Install and transport

- Prefer `python3 -m pip install pyvisa pyvisa-py` unless the machine already has NI-VISA.
- Use `--backend @py` when relying on the pure-Python VISA backend.
- Common VISA resource strings:
  - `USB0::0x0699::<product-id>::<serial>::INSTR`
- `TBS1102B` should normally be treated as a USBTMC instrument through the rear USB Device port, not as a LAN scope.

## Safe operating order

1. Discover resources with `list`.
2. Identify the instrument with `idn`.
3. Query live state with `query`.
4. Capture waveform data.
5. Write settings only if the user asked to reconfigure the scope.

This matters because trigger, acquisition mode, horizontal scale, and vertical scale are live instrument state. A premature write can change the evidence before the waveform is captured.

## Recommended commands

List resources:

```bash
python3 scripts/tek_scope.py list --backend @py
python3 scripts/tek_scope.py scan --backend @py
python3 scripts/tek_scope.py capture --backend @py --outdir captures --prefix tbs
```

Identify scope:

```bash
python3 scripts/tek_scope.py idn --resource USB0::0x0699::...::INSTR --backend @py
```

Inspect trigger state:

```bash
python3 scripts/tek_scope.py query --resource USB0::0x0699::...::INSTR --backend @py "TRIGger:STATE?"
```

Capture waveform:

```bash
python3 scripts/tek_scope.py capture --backend @py --outdir captures --prefix tbs

python3 scripts/tek_scope.py waveform \
  --resource USB0::0x0699::...::INSTR \
  --backend @py \
  --source CH1 \
  --csv captures/ch1.csv \
  --metadata captures/ch1.json
```

Analyze waveform:

```bash
python3 scripts/tek_scope.py analyze \
  --csv captures/ch1.csv \
  --metadata captures/ch1.json \
  --update-metadata
```

Render report:

```bash
python3 scripts/tek_scope.py report --metadata captures/ch1.json
```

Start acquisition only when requested:

```bash
python3 scripts/tek_scope.py write \
  --resource USB0::0x0699::...::INSTR \
  --backend @py \
  --wait-opc \
  "ACQuire:STATE RUN"
```

## Waveform scaling

The helper captures ASCII `CURVE?` data and scales each sample with Tek preamble fields.

- Time:
  - `x = x_zero + (index - point_offset) * x_increment`
- Voltage:
  - `y = (raw_sample - y_offset) * y_multiplier + y_zero`

The script queries these fields with fallbacks:

- `WFMOutpre:XINcr?` or `WFMPRE:XINCR?`
- `WFMOutpre:XZEro?` or `WFMPRE:XZERO?`
- `WFMOutpre:PT_Off?` or `WFMPRE:PT_OFF?`
- `WFMOutpre:YMUlt?` or `WFMPRE:YMULT?`
- `WFMOutpre:YZEro?` or `WFMPRE:YZERO?`
- `WFMOutpre:YOFf?` or `WFMPRE:YOFF?`

If one of those queries fails, probe the scope manually with `query` to determine whether the model uses a different command family.

## Model differences

- Older and newer Tek families vary in preamble naming and supported transports.
- `TBS1102B` sits in the `TBS1000B` family and is covered by the `Digital Oscilloscope Series Programmer Manual`.
- ASCII waveform transfer is slower than binary but easier to keep portable and debuggable.
- For `TBS1102B`, a thin auto-detect wrapper around `CURVE?` is more realistic than a high-speed transport layer.
- On `TBS1102B`, hardcopy and image-save flows are oriented around USB/PictBridge and front-panel save actions, so screenshot export is intentionally not the default path in this skill.
- The built-in analysis is intentionally lightweight; it summarizes captured data with level, edge, frequency, duty, and pulse-width estimates, but does not attempt protocol decode or FFT-style heavy processing.

## Troubleshooting

- `No module named pyvisa`
  - Install `pyvisa`, and add `pyvisa-py` if no vendor VISA runtime is present.
- `VI_ERROR_RSRC_NFOUND`
  - Recheck the resource string and confirm the scope is reachable on USB or LAN.
- `CURVE? returned no samples`
  - Confirm the source channel exists, is displayed, and that the scope is producing an acquisition.
- Preamble query failure
  - Manually query likely field names and extend the fallback list in `scripts/tek_scope.py` for the specific scope family.
