# Peripheral calculators (retired algorithms)

The `.cjs` calculators that used to live in `adapters/chip-support/algorithms/` are
gone (2026-10, dead code with no caller). Their arithmetic is the part that was
worth keeping, so it lives here as formulas. Every row was checked by hand and
carried a `@test_vector` before removal; the vectors are reproduced below.

Use these to compute a register value, then set it with `dap.py mem write` or put
it in the firmware source. Do not guess: confirm each formula against the
register summary in this directory before you rely on it.

## ESP32-C3

| Peripheral | Formula | Checked example |
| --- | --- | --- |
| LEDC PWM | `divider = f_clk / (f_pwm * 2**resolution)`; `duty_code = round(duty% / 100 * 2**resolution)`; divider splits into 10 integer + 8 fractional bits | 80 MHz, 1 kHz, 10-bit, 50%: divider 78.125 -> integer 78, fraction 32; duty 512 |
| GPTimer | `alarm_count = t_us * 1e-6 * f_clk / prescaler` | 80 MHz, /80, 1 ms -> 1000 |
| ADC1 (12-bit) | `code = voltage / full_scale * 4095`, full scale by attenuation: 0 dB 0.75 V, 2.5 dB 1.05 V, 6 dB 1.3 V, 12 dB 2.5 V | 1.25 V at 12 dB -> 2048 |

## Padauk PMB180B / PMS150G

| Peripheral | Formula | Checked example |
| --- | --- | --- |
| Timer16 | prescalers 1/4/16/64, interrupt bits 8..15. `counts = t_us * 1e-6 * f_clk / prescaler`; `reload = 2**interrupt_bit - counts` for a rising edge, `2**(bit+1)` for falling | 8 MHz, /16, 1 ms -> 500 counts. **Open question:** the model reloads from `2**bit` (1024-500 = 524) while a 16-bit counter would reload from 65536 (65036). Confirm against the datasheet before use. |
| TM2 PWM | `actual_hz = f_clk / (2**bits * prescaler * divider)`; duty register `= round(duty% / 100 * 2**bits) - 1`; pick the divider that minimises the frequency error | 8 MHz, 1 kHz, 8-bit, prescaler 1, 50%: divider 31 -> 1008 Hz (closest), duty register 127 |
| LPWMG | `counts = f_clk / (prescaler * f_pwm)`; upper limit `= counts - 1` | 8 MHz, /8, 1 kHz -> upper 999 |
| LVDC | `level = round((V_target - 1.85 V) / 0.05 V)`; register `= level << 2` (field [7:2]); 64 levels, so 1.85 V .. 5.00 V in 50 mV steps | 2.00 V -> level 3 -> 0x0C |
| Comparator (GPC), PMB180B | `vref = VDD * (base + n) / denominator`; `base`/`denominator` by case: 00 -> 8/32, 01 -> 0/24, 10 -> 8/40, 11 -> 0/32 | VDD 5 V, 1.25 V -> case 00, n=0, ratio 8/32 |
| Comparator (GPC), PMS150G | Same shape, different table: 00 -> 9/32, 01 -> 1/24, 10 -> 9/40, 11 -> 1/32. Do not carry the PMB180B numbers across | VDD 5 V, 1.25 V -> case 00, n=0 gives 1.406 V; the 1.25 V point does not exist on this part |
| Charger | discrete current steps only: 50, 100, 200, 250, 300, 350, 400, 500 mA | 200 mA is an exact step |

## SCMCU SC8F072

| Peripheral | Formula | Checked example |
| --- | --- | --- |
| TMR0 | `counts = t_us * 1e-6 * (f_clk / 4) / prescaler`; 8-bit `reload = 256 - counts` | 8 MHz (fsys/4 = 2 MHz), /16, 1 ms -> 125 counts -> reload 131 |
| PWM10 | `counts = f_clk / (prescaler * f_pwm)`; `period = counts - 1`; `duty = round(duty% / 100 * counts) - 1` | 8 MHz, /8, 1 kHz -> period 999, duty 499 |
| ADC12 | `code = voltage / V_ref * 4095`, ref VDD or ldo 2.0/2.4/3.0 V | 2 V at 5 V -> 1638 |
| Comparator | `vref = VDD/4 + (n+1)/32 * VDD` for rbias 00; see the register summary for the other three cases | VDD 4 V, 1.5 V -> n=3 |
