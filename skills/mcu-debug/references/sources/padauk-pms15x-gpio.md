# Padauk PMS15x / PFS15x GPIO Registers

ID: `mcu/padauk-pms15x-gpio`

## Purpose

GPIO register names, bit conventions, and the mini-C idioms that compile to
them, for the Padauk PMS150/PMS150G/PMS15A/PFS154 class. This is the chip-fact
half of the port adapter; the behaviour half is the datasheet.

Extracted from the vendor demo tree `vendor-sdks/padauk-mcu-demo` on the nexus
Forgejo (mini-C sources under `src/zh-sc`). Names and bit conventions are
hardware facts; no vendor source is copied.

## Registers

| Register | Purpose | Bit = 1 | Bit = 0 |
| --- | --- | --- | --- |
| `PA` | Port A data | pin driven or read high | pin driven or read low |
| `PAC` | Port A control (direction) | **output** | **input** |
| `PAPH` | Port A pull-high enable | pull-up on | pull-up off |
| `PADIER` | Port A digital input enable | pin readable as digital | pin left analog |
| `PB`, `PBC`, `PBPH`, `PBDIER` | Port B, same four roles | | |

Parts with a Port B follow the same naming: `PB` / `PBC` / `PBPH` / `PBDIER`.

## The polarity trap

`PAC` is **1 = output**, the inverse of the `TRIS`/`PAL` convention on many
other 8-bit parts. An adapter ported from a PIC-style file will drive nothing
and read everything.

Padauk's own demo spells both forms out, which is the clearest statement of the
convention:

```c
$ PA.0 out,high;   // PAC.0 = 1; PA.0 = 1;
$ PA.0 out,low;    // PAC.0 = 1; PA.0 = 0;
$ PA.4 in,pull;    // PAC.4 = 0; PAPH.4 = 1;
$ PA.4 in,X_PH;    // PAC.4 = 0; PAPH.4 = 0;
```

## Pins

- A part exposes only the pins its package bonds out. `PMS15A` has no `PA.1` or
  `PA.2`; the demo says so in a comment because the register bits exist.
- `PMS150G` has no ADC, so a pin cannot be moved to analog; `ADCC` is absent.
- Pins that are neither bonded nor used still need a defined level (pull-up, or
  driven low) or the part leaks current in sleep.

## mini-C idioms

mini-C is not C. These do not compile with a standard compiler, which matters
for how an adapter is tested:

| Idiom | Meaning |
| --- | --- |
| `$ PA.0 out,high;` | set direction and level for one pin |
| `$ PA.4 in,pull;` | input with pull-up |
| `$ PADIER 0x01;` | digital input enable mask |
| `$ MISC WDT_256K;` | watchdog period |
| `.delay 400;` | delay in microseconds |
| `.ADJUST_IC SYSCLK=IHRC/16, IHRC=16MHz, VDD=5V;` | clock and supply trim |
| `bit LED : PA.0` | name a pin |
| `PAC.0 = 1; PA.0 = 1;` | register form; the same code without the `$` |

`.ADJUST_IC` must match the supply voltage; `VDD=3.3V` and `VDD=5V` are not
interchangeable for timing.

## Writing an adapter

Because mini-C is not C, a Padauk adapter cannot go through the fake-register
host test that `docs/adapters.md` describes. Two honest options:

1. **Peripheral function in mini-C.** Keep the adapter as a mini-C function and
   treat it as bench-verified only. The catalog unit still has its own host
   test; only the adapter is unverifiable off-target.
2. **Pin macros in C.** Keep the unit call out of mini-C by exposing board
   macros, and compile the glued adapter on the host with a plain `uint8_t`
   register block. This works when the build allows a C file next to the mini-C
   sources; it is not always possible.

State which one applies in the project's `board/README.md`.

## Provenance

| Field | Value |
| --- | --- |
| Source tree | `vendor-sdks/padauk-mcu-demo` (nexus Forgejo) |
| Files consulted | `src/zh-sc/基本示例/IO type/PMS15A/PMS15A_IO/PMS15A_IO.C`, `.../PMS15A_Sleep/`, `.../PMS15A_Interrupt/`, `src/zh-sc/进阶示例/Soft_Filter/AD_filter_10/ADC.C`, `src/zh-sc/进阶示例/ScanKey/` |
| Licence | not stated in the tree; facts only, no source copied |

## Boundaries

- No addresses. mini-C source names registers; the address is the IDE's device
  definition, not a project fact. Do not invent one.
- No timing. `.ADJUST_IC` and delay accuracy come from the part and the supply.
- Per-part differences (which pins exist, whether ADC exists) belong to the
  project's `board/README.md`, with the datasheet as the reference.
