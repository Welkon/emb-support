# SCMCU SC8 register maps

Generated register maps for the SCMCU SC8 family (XC8 dialect). One file per
part, plus `index.json`.

These are **facts, not vendor source**: register names, addresses, and bit
positions, extracted from the headers that the SCMCU IDE installs. The headers
themselves carry no licence statement and are not copied here. A project that
needs to compile against them keeps its own copy under `board/vendor/` with
provenance.

## Regenerate

```sh
python3 skills/mcu-debug/scripts/scmcu/sfr_extract.py \
  --include-dir /path/to/SCMCU_IDE/data/include \
  --out-dir skills/mcu-debug/references/sources/scmcu \
  --ide-version V2.00.16
```

Check a committed map against an installed IDE:

```sh
python3 skills/mcu-debug/scripts/scmcu/sfr_extract.py --check \
  --include-dir /path/to/SCMCU_IDE/data/include \
  --out-dir skills/mcu-debug/references/sources/scmcu
```

`--check` fails when a part changed, disappeared, or a new part appeared. Run it
after an IDE update and regenerate with the new `--ide-version`.

## Address encoding

Most parts use an 8-bit address. 23 parts use a banked address:

```
| `TRISC` | `0x105` | ... |
```

The high byte is the bank, the low byte is the offset inside it. Do not truncate
to the low byte: `0x105` is not `0x05` (`TRISB`).

## Reading a map

- A part file lists every register the header declares, sorted by address, with
  its bits.
- `—` in the Bits column means the header declares no named bits for that
  register. It does not mean the register has no fields.
- A register that is absent from the map is absent from this header. Do not
  conclude the part lacks the feature; check the datasheet.
- Field semantics (what `PS2:PS0` means, how a prescaler is encoded) are not
  here. They belong to a hand-written note such as
  [`../scmcu-sc8f072-registers.md`](../scmcu-sc8f072-registers.md) or
  [`../scmcu-sc8f072-gpio.md`](../scmcu-sc8f072-gpio.md).

## Provenance

| Field | Value |
| --- | --- |
| Source | `SCMCU_IDE/data/include/SC8*.h` |
| IDE version | `V2.00.16` |
| Parts | 41 |
| Per-file hash | `SHA-256` line in each file and in `index.json` |

`index.json` also records the header file name per part, so a map can be traced
back to the exact file it came from.

## Boundaries

- XC8 line only. The `mcu/sfr/*.sfr` files that ship with the same IDE are a
  different format and a different product line; they are not covered here.
- No behaviour, no timing, no configuration bits. Only the register map.
- Do not hand-edit a generated file. Change the extractor or the header, then
  regenerate.
