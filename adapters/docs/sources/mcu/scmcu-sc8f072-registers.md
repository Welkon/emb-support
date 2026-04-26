# SCMCU SC8F072 Tool Registers

ID: `mcu/scmcu-sc8f072-registers`

## Purpose

This summary covers only the `SC8F072` registers and configuration fields actually used by currently implemented `emb-agent-adapters` tools.

It is NOT a complete register manual.

## Coverage

- `timer-calc`
- `pwm-calc`
- `comparator-threshold`
- `adc-scale`

## TMR0

### `TMR0`

- Purpose: 8-bit overflow timer count register
- Current tool usage:
  - Software reload value search
- Current tool output:
  - `TMR0 = <reload>;`
- Note:
  - Current tool calculates using the "write-back TMR0 in ISR" model
  - Does not auto-compensate for the 2 extra instruction cycles from writing back `TMR0`

### `OPTION_REG`

- Purpose: `TMR0` clock source, edge, prescaler assignment
- Current tool usage:
  - `T0LSE_EN`
  - `T0CS`
  - `T0SE`
  - `PSA`
  - `PS`
- Current tool output:
  - `OPTION_REG: T0LSE_EN=..., T0CS=..., T0SE=..., PSA=..., PS=...`

### `T0IF` / `T0IE`

- Purpose: `TMR0` interrupt flag and enable
- Current tool output:
  - `T0IF = 0; T0IE = 1;`

## TMR2

### `PR2`

- Purpose: `TMR2` period register
- Current tool usage:
  - Period search results written directly to `PR2`
- Current tool output:
  - `PR2 = <period>;`

### `T2CON`

- Purpose: `TMR2` clock source, prescaler, postscaler, enable
- Current tool usage:
  - `CLK_SEL`
  - `T2CKPS`
  - `TOUTPS`
  - `TMR2ON`
- Current tool output:
  - `T2CON: CLK_SEL=..., TOUTPS=..., TMR2ON=1, T2CKPS=...`
- Note:
  - Current results are calculated for "interrupt output period", not just base count period

### `TMR2IF` / `TMR2IE`

- Purpose: `TMR2` interrupt flag and enable
- Current tool output:
  - `TMR2IF = 0; TMR2IE = 1;`

## PWM 10-bit

### `PWMCON0`

- Purpose: PWM clock divider and per-channel enable
- Current tool usage:
  - `CLKDIV`
  - `PWM0EN..PWM4EN`
- Current tool output:
  - `PWMCON0: CLKDIV=..., PWMxEN=1`

### `PWMCON1`

- Purpose: PWM output pin group selection
- Current tool usage:
  - `PWMIO_SEL`
- Current tool output:
  - `PWMCON1: PWMIO_SEL=<group_bits>`

### `PWMTL` / `PWMTH`

- Purpose: `PWM0~PWM3` shared period register
- Current tool usage:
  - `PWMTL`
  - `PWMTH<1:0>`
- Current tool output:
  - `PWMTL = <low>;`
  - `PWMTH<1:0> = <high>;`

### `PWMT4L` / `PWMTH<3:2>`

- Purpose: `PWM4` independent period register
- Current tool usage:
  - `PWMT4L`
  - `PWMTH<3:2>`

### `PWMD0L..PWMD4L` / `PWMD01H` / `PWMD23H` / `PWMTH`

- Purpose: Per-channel duty cycle registers
- Current tool usage:
  - `PWM0`: `PWMD0L + PWMD01H<1:0>`
  - `PWM1`: `PWMD1L + PWMD01H<5:4>`
  - `PWM2`: `PWMD2L + PWMD23H<1:0>`
  - `PWM3`: `PWMD3L + PWMD23H<5:4>`
  - `PWM4`: `PWMD4L + PWMTH<5:4>` or profile-defined corresponding high bits
- Pitfalls:
  - `PWM0~PWM3` share a period register; `PWM4` is independent
  - When target duty is `0%`, keeping only `PWMEN` may still produce minimum pulse width; if pure low level is needed, disable the corresponding channel

## Comparator

### `CMPCON0`

- Purpose: Comparator positive/negative inputs, polarity, output enable, master enable
- Current tool usage:
  - `CMPPS`
  - `CMPNS`
  - `CMPNV`
  - `CMPOEN`
  - `CMPEN`
- Current tool output:
  - `CMPCON0: CMPPS=..., CMPNS=..., CMPNV=..., CMPOEN=..., CMPEN=1`

### `CMPCON1`

- Purpose: Analog enable, internal VR bias and levels
- Current tool usage:
  - `AN_EN`
  - `RBIAS_H`
  - `RBIAS_L`
  - `LVDS<3:0>`
- Current tool output:
  - `CMPCON1: AN_EN=1, RBIAS_H=..., RBIAS_L=..., LVDS=...`
- Pitfalls:
  - Internal reference is not a single register value; it is jointly determined by `RBIAS_H/RBIAS_L + LVDS`
  - Current route requires at least one of the positive or negative inputs to use internal `VR`

## ADC

### Reference Sources

- Current tool usage:
  - `vdd`
  - `fvr2v`
  - `fvr1v`
- Current tool output:
  - Reference source recommendations and voltage conversion results

### Channels

- Current tool usage:
  - `AN0~AN7` and profile-listed aliases
- Current tool output:
  - Channel name, converted voltage, target code value
- Note:
  - This summary only covers the reference source / channel abstraction used by tools; does not expand the full ADC control register bit table

## Maintenance Boundaries

- Only keep "register summaries that current tools encounter"
- Specific fields, aliases, and candidate values still follow `extensions/tools/devices/sc8f072.json` and `chip-support/algorithms/*.cjs`
- If adding more `SC8F0xx` tools later, supplement summaries incrementally; do not copy the entire manual
