# Padauk PMB180(B)

ID: `mcu/padauk-pmb180b`

## Purpose

This summary supports chip-support / profile landing for `PMB180B`, and preserves fact boundaries for future differentiated adaptation of the older `PMB180`.

## Shared Conclusions

- Core: `8-bit OTP MCU` with charge management
- Resource bounds: `1.25KW OTP + 64B RAM`
- Clock: Built-in `IHRC 16MHz` and `ILRC 100KHz`
- Package: `ESOP8`, `ESSOP10`
- IO: Logically 7 IO; `ESOP8` only exposes `PA6/PA5/PA3/PA4/PA0`
- Timer resources: `Timer16`
- PWM resources: `Timer2 PWM`, plus `11-bit LPWMG0/1/2`
- Analog: `GPC comparator`, `1.20V bandgap`, `LVDC`
- Capability gaps: No ADC in current manual

## Key Information Currently Landed in the Repo

- `timer-calc` bound to `Timer16`
- `pwm-calc` currently bound only to `Timer2 PWM`
- `lpwmg-calc` bound to `LPWMG0/1/2` shared frequency and per-channel duty search
- `lvdc-threshold` bound to `LVDC` threshold levels and status bit interpretation
- `charger-config` bound to charge current levels and `CHG_CTRL/CHG_TEMP` status decoding
- `comparator-threshold` bound to `GPC` internal reference level search
- `LVDC` and charger capabilities are now in the tool device binding, directly callable by tools
- Additionally supplemented `mcu/padauk-pmb180b-registers` for centralized register summaries relevant to current tools

## Solidified Pitfalls

- `5V` input detection cannot rely solely on `CHG_TEMP.4`; must satisfy both `CHG_TEMP.4 && CHG_TEMP.3`
- For older `PMB180`, charge-full detection cannot rely solely on `CHG_CTRL.0`
- Older version fast charge-full detection requires at least `CHG_CTRL.0 && V400_FG` sustained for `>1s`
- Older version can also use "continued charge time above 4V" for full detection; current tool uses the `500mAh -> 1h` minimum rule conversion
- `PMB180B` additionally supports `CHG_TEMP.1` for full detection, but semantics are corrected per empirical measurement: high `= charging`, low `= charge complete`
- When `LVDC` uses internal `1.20V bandgap` reference during charging, the internal detection value is typically ~`0.15V` higher than actual battery voltage
- `PMB180B` comparator should also consider similar `0.15V`-magnitude offset risk during charging

## PMB180 vs PMB180B Differences

- Both share the same manual; package and pin arrangement are identical
- `PMB180B` adds charge-complete status bit
- `PMB180B` fixes the old `PMB180` `VCC_Pin` floating micro-leakage issue

## Maintenance Boundaries

- Only keep extracted facts reusable across profiles here
- Specific calculation parameters still follow `extensions/tools/devices/pmb180b.json`
- If later adding the non-B `PMB180` version, do not directly reuse `VCC_Pin`-related electrical notes
