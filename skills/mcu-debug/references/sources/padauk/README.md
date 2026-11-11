# Padauk register maps

Generated register maps for the PADAUK mini-C IDE device files (`INC_PDK/*.INC`).
One file per part, plus `index.json`.

These are **facts, not vendor source**: register names, addresses, the usable-bit
mask, and the part's RAM/ROM budget, extracted from the files the IDE installs.
The `.INC` files carry no licence statement and are not copied here. A project
that compiles against them keeps its own copy with provenance.

## Regenerate

```sh
python3 skills/mcu-debug/scripts/padauk/inc_extract.py \
  --inc-dir /path/PADAUK_Tool/1.05/INC_PDK \
  --out-dir skills/mcu-debug/references/sources/padauk \
  --ide-version 1.05
```

Check a committed map against an installed IDE:

```sh
python3 skills/mcu-debug/scripts/padauk/inc_extract.py --check \
  --inc-dir /path/PADAUK_Tool/1.05/INC_PDK \
  --out-dir skills/mcu-debug/references/sources/padauk
```

`--check` fails when a part changed, disappeared, or a new part appeared. Run it
after an IDE update and regenerate with the new `--ide-version`.

## Reading a map

- `Address` is the data-memory address the `.INC` states.
- `Mask` is the bits the file marks as usable for that register. For a port
  register this is the pins the part implements: `PA 0x10 : 0xF9` means bits 0
  and 3-7, so `PA.1` and `PA.2` do not exist on that part even though the
  register has the bits.
- `Access` is the file's own `IO_RW` / `IO_WO` / `IO_RO` / `IO_RXW` marker.
- A name that appears on several rows is conditional. `PUD310` states `PB` at
  `0x13` with no mask and at `0x14` with `0x83` or `0x03`; the part has more than
  one configuration and the `.INC` covers them together. Read the source file
  before using one of those rows.

## Configuration options

Each map also lists the `.Assembly OPTION*` entries: the configuration word the
IDE writes, beside the code.

- `Bits` is the bit the option occupies, as the file states it. `%n` marks a
  virtual or shared encoding; `—` means the file gives no bit.
- `(ICE)` marks a line from the `ICE_INSTR ... END_INSTR` section. Those restate
  what the in-circuit emulator exposes, and they can differ: on `PMS150G` the IC
  default word is `0x02FC` while the ICE default is `0x0107`, and `LVR` lists
  `2.0V|2.2V` in one order on the IC and another on the ICE.
- `(rule)` marks a line inside a `.OPTION_RULE { ... }` block: the value applies
  only when the named rule holds.

Quote an option row together with its marker. A plain row is the IC behaviour;
an `(ICE)` row describes the emulator, not the shipped part.

Lines that are not a plain option row — the default word, the `OPTION_LOW` /
`OPTION_HIGH` bit lists, register relocations such as `OPTION_REG ROP + 3`, and
`{ ... }` groups — are reproduced verbatim under "Configuration notes" instead
of being parsed. Guessing at their meaning would be worse than quoting them.

## Register conventions

See [`../padauk-pms15x-gpio.md`](../padauk-pms15x-gpio.md) for what the GPIO
registers mean, including the direction polarity (`PAC` bit = 1 is **output**)
and the mini-C idioms that compile to them.

## Boundaries

- No behaviour and no timing. `.ADJUST_IC`, delay loops, and the pull-up values
  are part and supply facts, not register facts.
- No pin numbering or package data. The `.INC` has the register bits; the
  datasheet has which bit reaches which package pin.
- Do not hand-edit a generated file. Change the extractor or the IDE, then
  regenerate.

## Provenance

| Field | Value |
| --- | --- |
| Source | `PADAUK_Tool/1.05/INC_PDK/*.INC` |
| IDE version | `1.05` |
| Parts | 127 |
| Per-file hash | `SHA-256` line in each file and in `index.json` |
