# Padauk PMS150G

ID: `mcu/padauk-pms150g`

## Purpose

This summary supports `PMS150G`-related family / device / chip profiles, and future `PMS15B/PMS150G` low-end family adaptation.

## Shared Conclusions

- Core: Ultra-low-cost `8-bit OTP MCU`
- Resource bounds: ROM/RAM is very tight; adaptation must insist on ROM-first
- Timer resources: `Timer16`
- PWM resources: `TM2 PWM`
- Analog: `comparator`
- Capability gaps: No ADC

## Key Information Currently Landed in the Repo

- `timer-calc` covers `Timer16`
- `pwm-calc` covers `TM2 PWM`
- `comparator-threshold` covers internal reference level search
- `adc-scale` explicitly returns `unsupported`
- `chip profile` includes `sop8`, `dip8`, `sot23-6`, `sot23-8`
- Additionally supplemented `mcu/padauk-pms150g-registers` for centralized register summaries relevant to current tools

## Maintenance Boundaries

- Only keep extracted facts reusable across profiles here
- Specific calculation parameters still follow `extensions/tools/devices/pms150g.json`
- If later adding similar devices like `PMS152`, `PMS154`, confirm differences individually; do not copy directly
