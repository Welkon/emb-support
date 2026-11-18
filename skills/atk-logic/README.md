# atk-logic

Drive an ALIENTEK ATK-Logic (DL16/DL32) analyzer and decode with the GUI's own
sigrok decoders. Entry point: `scripts/atkla.py` — full command reference in
`SKILL.md`.

## Measurement record (only CH2 wired, scope calibration source)

Recorded on the bench with a single wire on panel CH2 (1 kHz / 50 % calibration
output). Protocol channel numbers are zero-based, so that capture shows activity
on channel 2 only; every other channel is a constant level (verified by removing
the second wire and re-capturing).

| command | samples | duty | frequency |
|---|---|---|---|
| `usb capture --ch 2:none --freq 2m --time 100ms` | 200 064 | 49.97 % | — |
| `usb capture --ch 2:none --freq 10m --time 100ms` | 1 000 064 | 50.07 % | 994.8 Hz |
| vendor CLI on the same signal | 1 000 000 | 50.07 % | 990.0 Hz |

Frequency comes from the median edge interval, not edge counting: this capture
contains 23 two-sample glitches, so `edges / 2 / duration` would report 1234.9 Hz
instead of 994.7 Hz. Details: `references/native-usb.md`.

## Tests

`python3 -m unittest discover -s tests -p 'test_*.py'` (no pytest dependency);
repository registers are covered by `node tests/run-tests.cjs`.
