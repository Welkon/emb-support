# Padauk PMS150G Tool Registers

ID: `mcu/padauk-pms150g-registers`

## Purpose

This summary covers only the `PMS150G` registers and macros actually used by currently implemented `emb-agent-adapters` tools.

It is NOT a complete register manual.

## Coverage

- `timer-calc`
- `pwm-calc`
- `comparator-threshold`

## Timer16

### `T16M`

- Purpose: `Timer16` mode, clock source, prescaler, interrupt bits
- Current tool usage:
  - Clock sources: `SYSCLK` / `IHRC` / `ILRC` / `PA0` / `PA4`
  - Prescalers: `/1` / `/4` / `/16` / `/64`
  - Interrupt bits: `BIT8 ~ BIT15`
- Current tool output:
  - `$ T16M <clock>,/<prescaler>,BIT<interrupt-bit>;`

### `INTEGS`

- Purpose: Edge trigger direction
- Current tool usage:
  - `BIT_R`
  - `BIT_F`
- Current tool output:
  - `$ INTEGS BIT_R;`
  - `$ INTEGS BIT_F;`

### `stt16`

- Purpose: Write reload value to `Timer16`
- Current tool output:
  - `stt16 <reload>;`
- Note:
  - Current tool searches for ISR reload usage model, not one-shot free-running model

## TM2 PWM

### `TM2C`

- Purpose: TM2 clock source, output pin, PWM mode, polarity
- Current tool usage:
  - Clock sources: `SYSCLK` / `IHRC` / `ILRC` / `COMPARATOR` / `PA0_RISE/FALL` / `PA4_RISE/FALL`
  - Output pins: `PA3` / `PA4`
- Current tool output:
  - `$ TM2C <clock>,<pin>,PWM[,Inverse];`

### `TM2S`

- Purpose: TM2 resolution, prescaler, post-divider
- Current tool usage:
  - Resolution: `8BIT` / `6BIT`
  - Prescaler: `/1` / `/4` / `/16` / `/64`
  - Post-divider: `/1 ~ /32`
- Current tool output:
  - `$ TM2S <resolution>,/<prescaler>,/<divider>;`

### `TM2CT`

- Purpose: TM2 count register
- Current tool usage:
  - Current route outputs `TM2CT = 0;` fixed

### `TM2B`

- Purpose: TM2 period/duty-related register
- Current tool usage:
  - Route outputs candidate upper-bound values
- Note:
  - Current tool works with the existing `TM2 PWM` parameter model; not extended to more complex fixed-period semantic differences

## Comparator

### `GPCC`

- Purpose: Comparator enable, positive/negative inputs, sync/polarity
- Current tool usage:
  - Positive inputs: `P_R` / `P_PA4`
  - Negative inputs: `N_PA3` / `N_PA4` / `BANDGAP` / `N_R` / `N_PA6` / `N_PA7`
- Current tool output:
  - `$ GPCC Enable[,Sync_TM2][,Inverse],<negative>,<positive>;`

### `GPCS`

- Purpose: Internal reference levels and optional output
- Current tool usage:
  - 4 internal reference formulas
- Current tool output:
  - `$ GPCS [Output,]VDD*<numerator>/<denominator>;`

### `BANDGAP`

- Current tool model:
  - `1.20V`
- Pitfall:
  - `bandgap` is not suitable for comparator wakeup

## Maintenance Boundaries

- Only keep "register summaries that current tools encounter"
- Specific formulas, macro names, and candidate values still follow `extensions/tools/devices/pms150g.json` and `chip-support/algorithms/*.cjs`
- If adding more `PMS15x` tools later, incrementally supplement summaries in the same manner
