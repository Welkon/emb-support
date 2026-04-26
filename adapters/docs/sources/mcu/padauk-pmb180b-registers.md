# Padauk PMB180(B) Tool Registers

ID: `mcu/padauk-pmb180b-registers`

## Purpose

This summary covers only the `PMB180(B)` registers/macros actually used by currently implemented `emb-agent-adapters` tools.

It is NOT a complete register manual, nor a replacement for the original datasheet.

## Coverage

- `timer-calc`
- `pwm-calc`
- `lpwmg-calc`
- `lvdc-threshold`
- `charger-config`
- `comparator-threshold`

## Timer16

### `T16M`

- Purpose: `Timer16` mode / clock source / prescaler / interrupt bit configuration macro
- Current tool usage:
  - Clock sources: `SYSCLK` / `IHRC` / `ILRC` / `PA0` / `PA4`
  - Prescalers: `/1` / `/4` / `/16` / `/64`
  - Interrupt bits: `BIT8 ~ BIT15`
- Current tool output:
  - `$ T16M <clock>,/<prescaler>,bit<interrupt-bit>;`

## TM2 PWM

### `TM2C`

- Purpose: TM2 mode, clock source, output pin, polarity
- Current tool usage:
  - Clock sources: `SYSCLK` / `IHRC` / `ILRC` / `NILRC` / `COMPARATOR` / `PA0_R/F` / `PA4_R/F`
  - Output pins: `PA3` / `PA4`
- Current tool output:
  - `$ TM2C <clock>,<pin>,PWM[,Inverse];`

### `TM2S`

- Purpose: TM2 resolution, prescaler, post-divider
- Current tool usage:
  - Resolution: `8BIT` / `7BIT` / `6BIT`
  - Prescaler: `/1` / `/4` / `/16` / `/64`
  - Post-divider: `/1 ~ /32`
- Current tool output:
  - `$ TM2S <resolution>,/<prescaler>,/<divider>;`

### `TM2CT`

- Purpose: Count register
- Current tool usage:
  - Current route outputs `TM2CT = 0;` fixed

### `TM2B`

- Purpose: Period/duty-related upper-bound register
- Current tool usage:
  - Route outputs candidate period register values
- Note:
  - Current tool works with the existing `padauk-tm2-pwm` model; if the manual later distinguishes PWM mode and fixed-period mode more finely, mode differences need to be supplemented

## LPWMG

### `LPWMGCLK`

- Purpose: LPWMG master enable, shared clock source, shared prescaler
- Current tool usage:
  - Clock sources: `SYSCLK` / `IHRC`
  - Prescalers: `/1` / `/2` / `/4` / `/8` / `/16` / `/32` / `/64` / `/128`
- Current tool output:
  - `$ LPWMGCLK Enable,/<prescaler>,<clock>;`
- Note:
  - `IHRC*2` is currently handled by passing the actual `clock-hz` in the tool; not split separately at the macro name layer

### `LPWMGCUBH` / `LPWMGCUBL`

- Purpose: Shared period upper-bound registers for the three `LPWMG0/1/2` channels
- Current tool usage:
  - `LPWMGCUBH` corresponds to `CB10_1[10:3]`
  - `LPWMGCUBL[7:6]` corresponds to `CB10_1[2:1]`
- Current tool output:
  - `LPWMGCUBL = 0x..;`
  - `LPWMGCUBH = 0x..;`
- Pitfall:
  - The three channels share a period register; each channel cannot be treated as an independent PWM block

### `LPWMG0C` / `LPWMG1C` / `LPWMG2C`

- Purpose: Per-channel output selection, output pin, polarity
- Current tool usage:
  - `LPWMG0`: `PA0` / `PA1` / `PA5`
  - `LPWMG1`: `PA4` / `PA6`
  - `LPWMG2`: `PA3` / `PA5`
- Current tool output:
  - `$ LPWMGxC LPWMGx,<pin>;`
- Note:
  - Inverted output is currently only flagged as a hint; no fixed parameter ordering is enforced

### `LPWMG0DTL/H` / `LPWMG1DTL/H` / `LPWMG2DTL/H`

- Purpose: Per-channel duty cycle registers
- Current tool usage:
  - `DTH` corresponds to `DB10_1[10:3]`
  - `DTL[7:6]` corresponds to `DB10_1[2:1]`
  - `DTL.5` corresponds to `DB0`
- Current tool model:
  - Duty numerator = `DB10_1 + DB0*0.5 + 0.5`
- Pitfall:
  - This is half-step duty, not a regular integer duty register

## LVDC

### `LVDC`

- Purpose: Low-voltage detect threshold configuration and detection result read
- Current tool usage:
  - `LVDC[7:2]`: threshold encoding
  - `LVDC.0`: detection result
- Current tool model:
  - Range: `1.85V ~ 5.0V`
  - Step: `0.05V`
  - Encoding: `code << 2`
- Current tool output:
  - `LVDC = 0x..;`
- Status interpretation:
  - `LVDC.0 = 1`: below set threshold
  - `LVDC.0 = 0`: above set threshold
- Pitfalls:
  - `LVDC` does not support interrupt, nor wakeup
  - When using internal `1.20V bandgap` reference during charging, internal detection is typically ~`0.15V` higher than actual battery voltage
  - Therefore the tool automatically applies `+0.15V` compensation search in `--charging` mode

## Charger

### `CHG_CTRL`

- Purpose: Charge current level configuration; `bit0` can also serve as operating status candidate
- Current tool usage:
  - Current levels: `50 / 100 / 200 / 250 / 300 / 350 / 400 / 500mA`
  - `CHG_CTRL.0`
- Current tool output:
  - `$ CHG_CTRL <current>mA;`
- Pitfalls:
  - `CHG_CTRL.0` cannot be used alone to determine charge-full
  - Older `PMB180` requires at minimum `V400_FG` and duration

### `CHG_TEMP`

- Purpose: Charge-status-related read-only bits
- Current tool usage:
  - `CHG_TEMP.4`: `VCC > VBAT`
  - `CHG_TEMP.3`: `VCC` voltage normal
  - `CHG_TEMP.1`: `PMB180B` charge-complete indicator
- Current tool determination:
  - `5V` input present: must satisfy `CHG_TEMP.4 && CHG_TEMP.3`
  - `PMB180B` charge-full: `CHG_TEMP.1 = 0`
- Pitfalls:
  - Padauk documentation has reversed high/low semantics for `CHG_TEMP.1` in some places
  - Current repo follows your empirical measurement: high `= charging`, low `= charge complete`

### `V400_FG`

- Purpose: Above-4V flag bit
- Current tool usage:
  - Older `PMB180` charge-full auxiliary condition
- Current tool determination:
  - Fast rule: `CHG_CTRL.0 && V400_FG && duration > 1s`
  - Time rule: continue charging above `4V` for some duration; currently uses `500mAh -> 1h` minimum rule conversion

## Comparator

### `GPCC`

- Purpose: Comparator enable, positive/negative inputs, sync/polarity
- Current tool usage:
  - Positive inputs: `P_R` / `P_PA4`
  - Negative inputs: `N_PA3` / `N_PA4` / `N_PA6` / `N_PA7` / `BANDGAP` / `N_R`
- Current tool output:
  - `$ GPCC Enable[,Sync_TM2][,Inverse],<negative>,<positive>;`

### `GPCS`

- Purpose: Internal reference level selection, optional output
- Current tool usage:
  - 4 internal reference formulas
- Current tool output:
  - `$ GPCS [Output,]VDD*<numerator>/<denominator>;`
- Pitfall:
  - Internal reference detection during charging should also consider ~`0.15V`-magnitude offset risk

## Maintenance Boundaries

- Only keep "register summaries that current tools encounter"
- Specific algorithm parameters still follow `extensions/tools/devices/pmb180b.json` and `chip-support/algorithms/*.cjs`
- If adding uncovered peripherals later, supplement summaries incrementally in the same manner; do not copy the entire register manual directly
