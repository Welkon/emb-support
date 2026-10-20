# Espressif ESP32-C3

ID: `mcu/espressif-esp32-c3`

## Purpose

This summary supports complete family / device / chip profile modeling for `ESP32-C3`, prioritizing the chip truth layer first, then incrementally adding executable tool bindings on top.

## Shared Conclusions

- Core: `32-bit RISC-V` single-core SoC, up to `160 MHz`
- Storage: `384 KB ROM`, supports external SPI Flash; on-chip data storage is `400 KB SRAM + 8 KB RTC fast SRAM`
- IO scale: Common variants have up to ~`22` available `GPIO`; exact pin count varies by package/variant
- Timer resources: At least `2 x 54-bit` general-purpose timers and `1 x 52-bit` systimer
- PWM resources: `LEDC PWM`, providing `6` output channels
- Communication: `UART`, `SPI`, `I2C`, `I2S`, `TWAI`, `RMT`, `USB Serial/JTAG`
- Analog: `12-bit SAR ADC` and on-chip temperature sensor
- System: `watchdog`, `GDMA`, `GPIO matrix`, `IO MUX`
- Power: `PMU`, `brownout detector`, `RTC` retention, and multiple wakeup sources
- Wireless: `Wi-Fi` and `BLE`
- Security: `AES`, `SHA`, `RSA`, `HMAC`, `RNG`, `eFuse`, Flash encryption
- Capability gaps: No independent hardware `comparator`, no built-in `charger`

## Peripheral Groups

### Communication

- `UART`: 2 controllers
- `SPI`: Includes Flash-related SPI and 1 general-purpose GP-SPI
- `I2C`: 1 controller
- `I2S`: 1 controller
- `TWAI`: CAN 2.0 compatible
- `RMT`: 2 TX, 2 RX
- `USB Serial/JTAG`: Full-speed USB 2.0 debug/download path

### System

- `LEDC`: 6-channel PWM
- `TIMG`: 2 x 54-bit general-purpose timers
- `SYSTIMER`: 1 x 52-bit system timer
- `Watchdog`: Multiple digital/analog/XTAL32K watchdogs
- `GDMA`: Shared among SPI2, I2S, AES, SHA, ADC, and other peripherals
- `GPIO Matrix`: Highly remappable peripheral signals to physical pins

### Analog

- `ADC`: 2 x 12-bit SAR ADC, with `ADC1` as primary
- `Temperature Sensor`: On-chip temperature sensor
- `Brownout`: Supply droop detection with interrupt/reset protection

### Power and Low-Power

- Sleep modes: `Active`, `Modem-sleep`, `Light-sleep`, `Deep-sleep`
- Primary clocks: `XTAL`, `PLL`, `RC_FAST`, `RC_SLOW`, `XTAL32K`
- `RTC fast SRAM`: Retained in Deep-sleep, used for wake stub / fast wakeup
- Wakeup sources: GPIO, RTC timer, 32k crystal-related sources; Light-sleep also supports Wi-Fi / BLE / UART wakeup

### Security

- `AES`, `SHA`, `RSA`, `HMAC`
- `RNG`
- `eFuse`
- `Flash Encryption`
- `Assist Debug`

## Key Information Currently Landed in the Repo

- Added `ESP32-C3` chip profile
- Added chip profile with complete `QFN32` primary package pin table
- Added primary `GPIO0-GPIO21` logical pin summary
- Added `Espressif ESP32-C3` family / device placeholder profiles
- Currently landed three basic executable bindings: `timer-calc`, `pwm-calc`, `adc-scale`
- Current executable coverage focuses on first-order calculations for `GPTimer`, `LEDC`, `SAR ADC`; does not mean all chip peripherals are fully adapted
- For emb's other existing routes, current explicit dispositions:
  - `comparator-threshold`: `ESP32-C3` has no independent analog comparator
  - `charger-config`: No on-chip charger / charge management module
  - `lvdc-threshold`: Brownout only retains capability facts; no directly computable user discrete threshold table
  - `lpwmg-calc`: No independent LPWMG peripheral; low-power PWM scenarios still fall under `LEDC`
- Current knowledge summary derived from notebook extraction of `esp32-c3_datasheet_cn.pdf` and `esp32-c3_technical_reference_manual_cn.pdf`

## Maintenance Boundaries

- Only keep extracted facts reusable across profiles here
- `related_tools` does not represent the full chip capability set, only the tool entry points emb currently recommends
- If further deepening `LEDC`, `GPTimer`, `SAR ADC` adaptation, supplement finer register-level summaries, calibration parameters, and SDK/register dual-view descriptions
- If expanding the emb tool surface later, prioritize `uart`, `spi`, `i2c`, `rmt`, `twai`, `gpio-matrix`, `power/clock`
- Brownout is currently recorded only as a chip capability fact; it does not equal adapted `lvdc-threshold` support
