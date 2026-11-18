"""Read the CSV that the ATK-Logic GUI exports from a protocol decode.

The GUI's decoded rows are not stored in the ``.atkdl`` project — only the
decoder configuration is. What survives a GUI session is this export:

    序号,开始,时间,名称,数值,
    0,150 ns,249.950000 µs,Duty cycles,1.200240%,

Columns are index, start, duration (or time), annotation name, value. The file
is written in the Windows code page, so it is read as UTF-8 first and GB18030
afterwards. Nothing here guesses: values without a known unit are reported as
text, and the annotation kind keeps its own unit.
"""

from __future__ import annotations

import re
from pathlib import Path

from .common import SkillError

_UNITS = (
    ("%", "percent", 1.0),
    ("ns", "ns", 1.0),
    ("µs", "ns", 1000.0),
    ("μs", "ns", 1000.0),
    ("us", "ns", 1000.0),
    ("ms", "ns", 1_000_000.0),
    (" s", "ns", 1_000_000_000.0),
    ("s", "ns", 1_000_000_000.0),
    ("khz", "hz", 1000.0),
    ("mhz", "hz", 1_000_000.0),
    ("hz", "hz", 1.0),
    ("bit", "bit", 1.0),
)
_NUMBER = re.compile(r"^\s*(-?[0-9]*\.?[0-9]+)\s*(.*?)\s*$", re.IGNORECASE)


def _read_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030", "utf-16"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "latin-1"


def _quantity(text: str) -> tuple[float, str] | None:
    match = _NUMBER.match(text.strip())
    if not match:
        return None
    value = float(match.group(1))
    suffix = match.group(2).strip().lower().replace(" ", "")
    if not suffix:
        return value, "number"
    for unit, canonical, scale in _UNITS:
        if suffix == unit.strip().lower().replace(" ", ""):
            return value * scale, canonical
    return None


def _is_header(fields: list[str]) -> bool:
    joined = ",".join(fields).lower()
    if any(token in joined for token in ("序号", "name", "名称", "value", "数值")):
        return True
    # A data row starts with an index.
    return not fields[0].strip().isdigit()


def summarise(path: str | Path) -> dict:
    source = Path(path)
    if not source.is_file():
        raise SkillError(
            "gui_csv_not_found",
            f"{source} does not exist",
            ["export the decode from the GUI (Export CSV) and pass that file"],
        )
    text, encoding = _read_text(source)
    kinds: dict[str, dict] = {}
    rows = 0
    skipped = 0
    header: list[str] | None = None
    for index, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        fields = [field.strip() for field in line.split(",")]
        while fields and not fields[-1]:
            fields.pop()
        if index == 0 and _is_header(fields):
            header = fields
            continue
        if len(fields) < 3:
            skipped += 1
            continue
        name = fields[-2] if len(fields) >= 2 else "annotation"
        value_text = fields[-1]
        rows += 1
        kind = kinds.setdefault(
            name,
            {
                "name": name,
                "count": 0,
                "unit": None,
                "min": None,
                "max": None,
                "mean": None,
                "samples": [],
                "_sum": 0.0,
                "_numeric": 0,
                "textSamples": [],
            },
        )
        kind["count"] += 1
        if len(kind["samples"]) < 3:
            kind["samples"].append(
                {"start": fields[1] if len(fields) > 1 else None,
                 "duration": fields[2] if len(fields) > 2 else None,
                 "value": value_text}
            )
        quantity = _quantity(value_text)
        if quantity is None:
            if len(kind["textSamples"]) < 3:
                kind["textSamples"].append(value_text)
            continue
        value, unit = quantity
        if kind["unit"] is None:
            kind["unit"] = unit
        if kind["unit"] != unit:
            # Mixed units inside one annotation kind: keep the text, do not mix.
            if len(kind["textSamples"]) < 3:
                kind["textSamples"].append(value_text)
            continue
        kind["_numeric"] += 1
        kind["_sum"] += value
        kind["min"] = value if kind["min"] is None else min(kind["min"], value)
        kind["max"] = value if kind["max"] is None else max(kind["max"], value)

    summary = []
    for kind in kinds.values():
        if kind["_numeric"]:
            kind["mean"] = kind["_sum"] / kind["_numeric"]
        for key in ("_sum", "_numeric"):
            kind.pop(key)
        summary.append(kind)
    summary.sort(key=lambda item: -item["count"])
    return {
        "file": str(source),
        "encoding": encoding,
        "header": header,
        "rows": rows,
        "skipped": skipped,
        "kinds": summary,
    }
