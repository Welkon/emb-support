"""Evidence files: one place that writes, atomically.

A USB timeout used to leave a 0-byte JSON next to a CSV that looked complete.
Every artifact now goes to a temporary file and is renamed into place, so a
failed intent either leaves no file or leaves the previous one intact.
"""

from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path


def _atomic(path: Path, data: bytes) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return path


class Evidence:
    """Collects the artifacts of one intent and records their paths."""

    def __init__(self) -> None:
        self.files: dict[str, str] = {}

    def _record(self, kind: str, path: Path) -> Path:
        self.files[kind] = str(path)
        return path

    def bytes(self, kind: str, path, data: bytes) -> Path:
        return self._record(kind, _atomic(Path(path), data))

    def text(self, kind: str, path, text: str) -> Path:
        return self.bytes(kind, path, text.encode())

    def json(self, kind: str, path, obj) -> Path:
        return self.text(kind, path, json.dumps(obj, indent=2))

    def csv(self, kind: str, path, data: dict) -> Path:
        chans = sorted(data)
        n = min(len(data[c]["volts"]) for c in chans)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["time"] + [f"ch{c}" for c in chans])
        for i in range(n):
            writer.writerow([f"{data[chans[0]]['times'][i]:.12g}"] +
                            [f"{data[c]['volts'][i]:.9g}" for c in chans])
        return self.text(kind, path, buf.getvalue())

    def svg(self, kind: str, path, times, volts, **kwargs) -> Path:
        from .analysis import write_svg

        path = Path(path).expanduser()
        if path.suffix.lower() != ".svg":
            raise ValueError("plots support .svg output only")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.stem}.tmp{path.suffix}")
        write_svg(tmp, times, volts, **kwargs)
        os.replace(tmp, path)
        return self._record(kind, path)

    def npz(self, kind: str, path, data: dict) -> Path:
        from .analysis import save_npz

        path = Path(path).expanduser()
        if path.suffix != ".npz":
            path = path.with_suffix(".npz")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.stem}.tmp.npz")
        save_npz(tmp, data)
        os.replace(tmp, path)
        return self._record(kind, path)

    def manifest(self) -> dict:
        return dict(self.files)
