#!/usr/bin/env python3
"""Extract Padauk device registers from the mini-C IDE `.INC` files.

The PADAUK tool ships one `INC_PDK/<PART>.INC` per part. The files carry no
licence statement, so they are not copied into this repository. This script
reads them where the IDE is installed and writes register names, addresses,
usable-bit masks, and the part's RAM/ROM budget.

Usage::

    inc_extract.py --inc-dir /path/PADAUK_Tool/1.05/INC_PDK \\
                   --out-dir skills/mcu-debug/references/sources/padauk \\
                   --ide-version 1.05
    inc_extract.py --check --inc-dir ... --out-dir ...
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys

# `NAME   IO_RW   0x11 : 0xF9`  — address and optional usable-bit mask.
REGISTER = re.compile(
    r"^\s*([A-Z][A-Z0-9_]*)\s+IO_(RW|WO|RO|RXW)\s+0x([0-9A-Fa-f]+)"
    r"(?:\s*:\s*0x([0-9A-Fa-f]+))?\s*(?://.*)?$",
    re.M,
)
BUDGET = re.compile(
    r"^\s*\.Assembly\s+(RAM_Size|ROM_Size|FPPA_NUM|ASM_INSTR)\s+(\S+)", re.M
)
# `.Assembly OPTION 2 LVR 4.0V 3.5V ...`, with variants OPTION_HIDE,
# OPTION_VIRTUAL[:n], OPTION_REG, OPTION_MISC2, OPTION_SKIP, OPTION_ROP.
OPTION = re.compile(
    r"^(\s*)(//)?\s*\.Assembly\s+((?:OPTION)[A-Z0-9_]*(?::\d+)?)\s*(.*?)\s*(?://.*)?$",
    re.M,
)
BIT_SPEC = re.compile(r"^[0-9,~]+$")
ROW_TOKENS = ("{", "}", "@", "+")


class Problem(Exception):
    """A file that cannot be turned into a trustworthy map."""


def parse(path: pathlib.Path):
    text = path.read_text(errors="replace")
    registers: list[tuple[str, int, str, int | None]] = []
    seen: set[tuple[str, int, str, int | None]] = set()
    for name, access, address, mask in REGISTER.findall(text):
        entry = (name, int(address, 16), access, int(mask, 16) if mask else None)
        # A few parts state the same name twice on purpose: two access widths at
        # two addresses (ADCDI) or a renamed port (PUD310 PB). Keep both rows;
        # drop only an exact repeat.
        if entry in seen:
            continue
        seen.add(entry)
        registers.append(entry)
    if not registers:
        raise Problem("no registers parsed")
    registers.sort(key=lambda item: (item[1], item[0]))
    budget = {key: value for key, value in BUDGET.findall(text)}
    return registers, budget


def parse_options(text: str):
    """Split `.Assembly OPTION*` lines into readable rows and verbatim notes.

    The `.INC` files use a dozen spellings and some lines are conditional inside
    a `.OPTION_RULE` block. A row is produced only when the line has the plain
    shape `kind [label] bits [%n] name values...`; everything else keeps its
    original text so nothing is guessed.
    """
    rows: list[tuple[str, str, str, str]] = []
    notes: list[str] = []
    # Two things make an option line conditional. A `.OPTION_RULE { ... }` block
    # holds rule-bound alternatives and has nested braces, so track depth. An
    # `ICE_INSTR ... END_INSTR` section restates the options the in-circuit
    # emulator exposes, which can differ in name, bits, or value list.
    depth = 0
    armed = False
    in_ice = False
    for line in text.splitlines():
        stripped = line.strip()
        if ".Assembly" in stripped and "ICE_INSTR" in stripped:
            in_ice = True
            continue
        if ".Assembly" in stripped and "END_INSTR" in stripped:
            in_ice = False
            continue
        if stripped.startswith(".OPTION_RULE"):
            armed = True
            continue
        if armed:
            depth += stripped.count("{") - stripped.count("}")
            if depth <= 0 and "{" not in stripped and "}" in stripped:
                armed = False
                depth = 0
        in_rule = armed and depth > 0
        match = OPTION.match(line)
        if not match:
            continue
        if match.group(2):
            continue  # a commented-out alternative
        kind = match.group(3)
        rest = match.group(4)
        marks = []
        if in_ice:
            marks.append("ICE")
        if in_rule:
            marks.append("rule")
        if marks:
            kind = f"{kind} ({', '.join(marks)})"
        tokens = rest.split()
        if not tokens:
            continue
        if any(token in ROW_TOKENS or token.startswith(ROW_TOKENS) for token in tokens):
            notes.append(f"{kind} {rest}".strip())
            continue
        base = kind.split(":")[0]
        if base in {"OPTION_DEFAULT", "OPTION_LOW", "OPTION_HIGH"}:
            notes.append(f"{kind} {rest}".strip())
            continue
        if base.startswith("OPTION_VIRTUAL"):
            percent = ""
            if tokens and tokens[0].startswith("%"):
                percent = tokens.pop(0)
            if len(tokens) < 2:
                notes.append(f"{kind} {rest}".strip())
                continue
            rows.append((kind, percent, tokens[0], " ".join(tokens[1:])))
            continue
        label = ""
        if tokens and not BIT_SPEC.fullmatch(tokens[0]) and not tokens[0].startswith("%"):
            label = tokens.pop(0)
        bits = []
        while tokens and BIT_SPEC.fullmatch(tokens[0]):
            bits.append(tokens.pop(0))
        percent = ""
        if tokens and tokens[0].startswith("%"):
            percent = tokens.pop(0)
        if len(tokens) < 2:
            notes.append(f"{kind} {rest}".strip())
            continue
        name = tokens.pop(0)
        span = " ".join(filter(None, [" ".join(bits), percent]))
        if label:
            span = f"{label}: {span}".strip()
        rows.append((kind, span or "—", name, " ".join(tokens)))
    return rows, notes


def mask_note(mask: int) -> str:
    bits = [str(bit) for bit in range(8) if mask & (1 << bit)]
    return ", ".join(bits)


def render(part: str, path: pathlib.Path, digest: str, ide: str) -> str:
    registers, budget = parse(path)
    lines = [
        f"# Padauk {part} Registers",
        "",
        "Generated by `skills/mcu-debug/scripts/padauk/inc_extract.py`; do not edit.",
        "Register names, addresses, usable-bit masks, and the memory budget only.",
        "No vendor source is copied.",
        "",
        f"- Part: `{part}`",
        f"- File: `INC_PDK/{path.name}`",
        f"- SHA-256: `{digest}`",
        f"- IDE: `{ide}`",
        f"- Registers: {len(registers)}",
    ]
    for key in ("ROM_Size", "RAM_Size", "FPPA_NUM"):
        if key in budget:
            lines.append(f"- {key}: `{budget[key]}`")
    lines += [
        "",
        "## Register map",
        "",
        "`Mask` lists the bits the part actually bonds out or implements; an empty",
        "cell means the file states none.",
        "",
        "| Register | Address | Access | Mask (bits) |",
        "| --- | --- | --- | --- |",
    ]
    for name, address, access, mask in registers:
        note = f"`0x{mask:02X}` ({mask_note(mask)})" if mask is not None else "—"
        lines.append(f"| `{name}` | `0x{address:02X}` | {access} | {note} |")

    rows, notes = parse_options(path.read_text(errors="replace"))
    if rows:
        lines += [
            "",
            "## Configuration options",
            "",
            "`Bits` is the configuration-word bit the option occupies, as the file",
            "states it; `%n` marks a virtual or shared encoding. `Values` is the",
            "list the IDE offers, in the file's order.",
            "",
            "| Kind | Bits | Option | Values |",
            "| --- | --- | --- | --- |",
        ]
        for kind, bits, name, values in rows:
            lines.append(f"| {kind} | {bits or '—'} | `{name}` | {values} |")
    if notes:
        lines += [
            "",
            "## Configuration notes",
            "",
            "Verbatim `.Assembly` lines that are not a plain option row: the default",
            "word, the low/high bit lists, register relocations, and conditional",
            "entries.",
            "",
            "```",
            *notes,
            "```",
        ]
    lines.append("")
    return "\n".join(lines)


def collect(inc_dir: pathlib.Path) -> dict[str, pathlib.Path]:
    picked: dict[str, pathlib.Path] = {}
    for path in sorted(inc_dir.glob("*.INC")):
        part = path.stem.upper()
        if part in picked:
            continue
        picked[part] = path
    return picked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inc-dir", required=True, type=pathlib.Path)
    parser.add_argument("--out-dir", required=True, type=pathlib.Path)
    parser.add_argument("--ide-version", default=None)
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if not args.inc_dir.is_dir():
        print(f"inc dir not found: {args.inc_dir}", file=sys.stderr)
        return 2

    ide = args.ide_version
    if ide is None and args.check and (args.out_dir / "index.json").exists():
        try:
            ide = json.loads((args.out_dir / "index.json").read_text()).get("ide_version")
        except ValueError:
            ide = None
    if ide is None:
        ide = "unknown"

    parts = collect(args.inc_dir)
    if args.only:
        wanted = {part.upper() for part in args.only}
        parts = {part: path for part, path in parts.items() if part in wanted}
    if not parts:
        print("no .INC files found", file=sys.stderr)
        return 2

    rendered: dict[str, str] = {}
    index = {"ide_version": ide, "parts": []}
    for part in sorted(parts):
        path = parts[part]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        try:
            text = render(part, path, digest, ide)
        except Problem as problem:
            print(f"{part}: {problem}", file=sys.stderr)
            return 2
        rendered[f"{part}.md"] = text
        registers, budget = parse(path)
        index["parts"].append(
            {
                "id": part,
                "file": f"INC_PDK/{path.name}",
                "sha256": digest,
                "registers": len(registers),
                "rom_size": budget.get("ROM_Size"),
                "ram_size": budget.get("RAM_Size"),
            }
        )
    rendered["index.json"] = json.dumps(index, indent=2) + "\n"

    if args.check:
        stale = []
        for name, text in sorted(rendered.items()):
            path = args.out_dir / name
            if not path.exists() or path.read_text() != text:
                stale.append(name)
        if not args.only:
            produced = {name.upper() for name in rendered}
            for path in sorted(args.out_dir.glob("*.md")):
                if path.name == "README.md":
                    continue
                if path.name.upper() not in produced:
                    stale.append(f"{path.name} (no longer produced)")
        if stale:
            print("padauk map is stale:", file=sys.stderr)
            for name in stale:
                print(f"  {name}", file=sys.stderr)
            return 1
        print(f"padauk map: ok ({len(parts)} parts)")
        return 0

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in sorted(rendered.items()):
        (args.out_dir / name).write_text(text)
    print(f"padauk map: {len(parts)} parts, {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
