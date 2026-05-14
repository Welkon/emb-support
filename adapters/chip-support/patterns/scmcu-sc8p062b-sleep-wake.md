# SCMCU SC8P062B Sleep / PORTB Wake Pattern

Status: board-validated pattern captured from RH-SZZ-002 bring-up.
Scope: SCMCU SC8P062B-family firmware using SCMCU IDE / SCMCU-packaged XC8.

## Preferred sleep entry

Use the official-example style `asm("sleep")` path before inventing a STOP sequence.

Minimum reviewed sequence:

1. Stop product outputs and periodic peripherals that should not run in sleep.
2. Configure only real wake pins in `IOCB`.
3. Enable `RBIE` and keep `GIE` enabled as in the vendor example path.
4. Read `PORTB` to latch the port-change baseline.
5. Disable software WDT with `SWDTEN=0` only after confirming CONFIG does not force WDT on.
6. Execute `asm("clrwdt")`, `asm("sleep")`, then `asm("nop")`.
7. On wake, restore GPIO direction/pull-up/peripheral state before product policy resumes.

## PORTB wake ISR skeleton

The ISR should only clear the wake condition and return:

```c
if (RBIF && RBIE) {
    volatile unsigned char latch = PORTB;
    (void)latch;
    RBIF = 0;
}
```

Do not run debounce, ADC policy, display policy, WDT service, or the product state machine inside this wake ISR path.

## Configuration-bit prerequisites

Confirm these in the official SCMCU IDE/programmer settings when that is the flashing source:

- `WDT = DISABLE` so `SWDTEN=0` can prevent periodic watchdog wake.
- `EXT_RESET = DISABLE` when the reset-capable key pin must act as normal GPIO / wake input.

A command-line XC8 build can compile successfully while its HEX omits configuration words; inspect build summaries but treat the official IDE configuration as the burn source when the project uses IDE flashing.

## GPIO state rule

Separate runtime blanking from sleep-current state:

- Runtime charlieplex/display blank: high-Z is often required to avoid ghosting.
- Sleep: non-wake GPIO should be driven or biased to deterministic states to avoid floating-input current, unless board truth says otherwise.

## Known RH-SZZ-002 validation

- Target build chip: `SC8P062BD`.
- Debug substitute allowed by board truth: `SC8F072` erasable device.
- Wake sources: `RB2/KEY` and `RB0/USB_DET`.
- Sleep instruction: `asm("sleep")`.
- Measured final standby current: `<35uA` on the assembled board.
