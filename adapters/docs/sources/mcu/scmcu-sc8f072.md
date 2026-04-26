# SCMCU SC8F072

ID: `mcu/scmcu-sc8f072`

## Purpose

This summary supports `SC8F072`-related family / device / chip profiles, and future same-series derivative adaptation.

## Shared Conclusions

- Core: 8-bit Flash MCU, suitable for small bare-metal control and low-cost home appliance / lighting / general control scenarios
- Timer resources: At minimum includes `TMR0` and `TMR2`
- PWM resources: Independent `10-bit PWM`
- Analog: `comparator` and `12-bit ADC`
- Low-power: Supports `sleep-wakeup`

## Key Information Currently Landed in the Repo

- `timer-calc` covers `TMR0` and `TMR2`
- `pwm-calc` covers independent `10-bit PWM`
- `comparator-threshold` covers internal reference threshold search
- `adc-scale` covers `12-bit ADC` basic conversion
- `chip profile` includes multiple packages: `sot23-6`, `sop8`, `msop10`, `sop14`, `sop16`, `qfn16`
- Additionally supplemented `mcu/scmcu-sc8f072-registers` for centralized register summaries relevant to current tools

## Maintenance Boundaries

- Only keep extracted shared facts here
- Specific register bits, route selection, and algorithm parameters still follow `extensions/**/*.json` and `chip-support/**/*.cjs`
- If later adding same-series devices, reuse this summary first, then supplement new source documents per chip differences
