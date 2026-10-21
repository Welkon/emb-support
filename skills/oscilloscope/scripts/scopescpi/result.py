"""The one result shape every intent returns.

Verbs fill a Result instead of building ad-hoc dicts. `to_dict()` refuses to
emit strings that look like instrument commands, so "results carry values, not
commands" is a property of the type, not only a test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_COMMAND = re.compile(r"^[:*][A-Za-z]")


def _check(value: Any, path: str = "result") -> None:
    if isinstance(value, str):
        if _COMMAND.match(value.strip()):
            raise ValueError(
                f"refusing to emit an instrument command in {path}: {value!r}")
    elif isinstance(value, dict):
        for key, item in value.items():
            _check(key, f"{path}.<key>")
            _check(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _check(item, f"{path}[{index}]")


@dataclass
class Result:
    idn: str = ""
    family: str = ""
    ok: bool = True
    values: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    unsupported: list = field(default_factory=list)

    def set(self, key: str, value: Any) -> "Result":
        self.values[key] = value
        return self

    def add_evidence(self, kind: str, path) -> "Result":
        self.evidence[kind] = str(path)
        return self

    def warn(self, message: str) -> "Result":
        self.warnings.append(message)
        return self

    def to_dict(self) -> dict:
        out: dict = {"ok": self.ok}
        if self.idn:
            out["idn"] = self.idn
        if self.family:
            out["family"] = self.family
        out.update(self.values)
        out.update(self.evidence)
        if self.warnings:
            out.setdefault("warnings", [])
            if isinstance(out["warnings"], list):
                out["warnings"] = self.warnings + out["warnings"]
            else:
                out["warnings"] = self.warnings
        if self.unsupported:
            out["unsupported"] = self.unsupported
        _check(out)
        return out
