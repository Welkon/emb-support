# SCMCU SC8F072 GPIO Registers

ID: `mcu/scmcu-sc8f072-gpio`

## Purpose

GPIO register names, addresses, and bit names for `SC8F072`, so an adapter can
be written without opening the vendor header. This is the chip-fact half of
[`docs/adapters.md`](../../../../../emb-loom/docs/adapters.md): the project
adapter names the pin, this note supplies the register.

Extracted from a project copy of the vendor header `SC8F072.h` (XC8 dialect).
Names and addresses are hardware facts; no vendor source or comment is copied.

## Coverage

- Port read and write
- Direction, pull-up, open-drain, interrupt-on-change
- Analog select

## Register map

| Register | Address | Purpose |
| --- | --- | --- |
| `PORTA` | `0x86` | Port A read and write |
| `TRISA` | `0x85` | Port A direction, `1` = input |
| `WPUA` | `0x88` | Port A weak pull-up |
| `WPDA` | `0x87` | Port A pull-down |
| `IOCA` | `0x89` | Port A interrupt-on-change |
| `ODCONA` | `0x8C` | Port A open-drain |
| `ANSEL0` | `0x93` | Port A analog select |
| `PORTB` | `0x06` | Port B read and write |
| `TRISB` | `0x05` | Port B direction, `1` = input |
| `WPUB` | `0x08` | Port B weak pull-up |
| `WPDB` | `0x07` | Port B pull-down |
| `IOCB` | `0x09` | Port B interrupt-on-change |
| `ODCONB` | `0x0C` | Port B open-drain |
| `ANSEL1` | `0x94` | Port B analog select |

## Bits

- Port A has `RA0`..`RA5` (`6` pins), bit names `RA0`..`RA5`.
- Port B has `RB0`..`RB7` (`8` pins), bit names `RB0`..`RB7`.
- `TRISx`, `WPUx`, `IOCx`, `ODCONx` use the same bit index as `PORTx`.

## Notes that change adapter code

- `TRISx` is `1` for input, `0` for output. An adapter that inverts this passes
  a host test and fails on the bench only when a pin is driven against an
  external source.
- `PORTA` is in bank 1 (`0x86`), `PORTB` in bank 0 (`0x06`). XC8 resolves the
  bank through the absolute address; a hand-written assembly path must set
  `RP0`/`RP1`.
- A pin used as analog input needs its `ANSELx` bit set; a digital read returns
  the comparator or ADC state until then.
- Read-modify-write on `PORTx` reads the pin, not the latch. Drive a pin from a
  shadow byte when another bit of the same port is an input, otherwise a write
  can copy the input level onto an output.

## XC8 shim

The smallest useful `target.h` for this part:

```c
volatile unsigned char PORTA @ 0x86;
volatile unsigned char TRISA @ 0x85;
volatile unsigned char PORTB @ 0x06;
volatile unsigned char TRISB @ 0x05;
volatile unsigned char ANSEL0 @ 0x93;
volatile unsigned char ANSEL1 @ 0x94;
```

A project that keeps the full vendor header should include it once, from
`board/target.h`, and leave every other file on `BOARD_*` names.

## Maintenance boundaries

- Keep only GPIO facts here. Timers, PWM, comparator, and ADC stay in
  [`scmcu-sc8f072-registers.md`](scmcu-sc8f072-registers.md).
- Do not copy the vendor header into a repository. Re-state the facts, or keep
  the header in the project with its provenance.
- Bench behavior for a specific board belongs to the project, not here.
