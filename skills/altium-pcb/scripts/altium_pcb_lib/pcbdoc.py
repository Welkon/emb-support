from __future__ import annotations

import argparse
import json
import math
import os
import re
import struct
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .common import *

FREE_SECTOR = 0xFFFFFFFF
END_OF_CHAIN = 0xFFFFFFFE
NO_STREAM = 0xFFFFFFFF
CFB_SIGNATURE = bytes([0xD0, 0xCF, 0x11, 0xE0, 0xA1, 0xB1, 0x1A, 0xE1])


def read_u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def read_u64(data: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


class Cfb:
    def __init__(self, data: bytearray):
        if len(data) < 512 or bytes(data[:8]) != CFB_SIGNATURE:
            raise ValueError("PcbDoc file does not look like an OLE compound file")
        self.data = data
        self.sector_size = 1 << read_u16(data, 30)
        self.mini_sector_size = 1 << read_u16(data, 32)
        self.num_fat_sectors = read_u32(data, 44)
        self.first_dir_sector = read_u32(data, 48)
        self.mini_stream_cutoff = read_u32(data, 56)
        self.first_difat_sector = read_u32(data, 68)
        self.num_difat_sectors = read_u32(data, 72)
        self.fat_entries = self._build_fat()
        self.entries = self._parse_directory_entries()
        roots = [entry for entry in self.entries if entry["type"] == 5]
        self.root_entry = roots[0] if roots else (self.entries[0] if self.entries else None)

    def _read_sector(self, sector_index: int) -> bytes:
        offset = (sector_index + 1) * self.sector_size
        end = offset + self.sector_size
        if offset < 0 or end > len(self.data):
            raise ValueError(f"CFB sector {sector_index} is outside file bounds")
        return bytes(self.data[offset:end])

    def _collect_difat_sector_ids(self) -> List[int]:
        difat: List[int] = []
        for index in range(109):
            sector_id = read_u32(self.data, 76 + index * 4)
            if sector_id != FREE_SECTOR:
                difat.append(sector_id)
        next_difat_sector = self.first_difat_sector
        remaining = self.num_difat_sectors
        max_entries = self.sector_size // 4 - 1
        while remaining > 0 and next_difat_sector not in {END_OF_CHAIN, FREE_SECTOR}:
            sector = self._read_sector(next_difat_sector)
            for index in range(max_entries):
                sector_id = read_u32(sector, index * 4)
                if sector_id != FREE_SECTOR:
                    difat.append(sector_id)
            next_difat_sector = read_u32(sector, self.sector_size - 4)
            remaining -= 1
        return difat[: self.num_fat_sectors]

    def _build_fat(self) -> List[int]:
        entries: List[int] = []
        for sector_id in self._collect_difat_sector_ids():
            sector = self._read_sector(sector_id)
            for offset in range(0, len(sector), 4):
                entries.append(read_u32(sector, offset))
        return entries

    def _read_chain(self, start_sector: int, expected_size: Optional[int] = None) -> bytes:
        if start_sector in {END_OF_CHAIN, FREE_SECTOR}:
            return b""
        seen = set()
        chunks = []
        current = start_sector
        while current not in {END_OF_CHAIN, FREE_SECTOR}:
            if current in seen:
                raise ValueError(f"CFB sector chain loop detected at sector {current}")
            if current >= len(self.fat_entries):
                raise ValueError(f"CFB sector {current} is outside FAT range")
            seen.add(current)
            chunks.append(self._read_sector(current))
            current = self.fat_entries[current]
        data = b"".join(chunks)
        return data[:expected_size] if expected_size is not None else data

    def _parse_directory_entries(self) -> List[Dict[str, Any]]:
        directory_data = self._read_chain(self.first_dir_sector)
        entries = []
        for offset in range(0, len(directory_data) - 127, 128):
            name_length = read_u16(directory_data, offset + 64)
            if name_length >= 2:
                name = directory_data[offset : offset + name_length - 2].decode("utf-16le", errors="ignore").rstrip("\x00")
            else:
                name = ""
            if not name:
                continue
            entries.append(
                {
                    "id": offset // 128,
                    "name": name,
                    "type": directory_data[offset + 66],
                    "left": read_u32(directory_data, offset + 68),
                    "right": read_u32(directory_data, offset + 72),
                    "child": read_u32(directory_data, offset + 76),
                    "starting_sector": read_u32(directory_data, offset + 116),
                    "size": read_u64(directory_data, offset + 120),
                }
            )
        return entries

    def _entry_by_id(self, entry_id: int) -> Optional[Dict[str, Any]]:
        return next((entry for entry in self.entries if entry["id"] == entry_id), None)

    def sorted_children(self, parent_id: int) -> List[Dict[str, Any]]:
        parent = self._entry_by_id(parent_id)
        result: List[Dict[str, Any]] = []

        def walk(entry_id: int) -> None:
            if entry_id == NO_STREAM:
                return
            entry = self._entry_by_id(entry_id)
            if not entry:
                return
            walk(entry["left"])
            result.append(entry)
            walk(entry["right"])

        if parent:
            walk(parent["child"])
        return result

    def find_entry_by_path(self, path: str) -> Optional[Dict[str, Any]]:
        if not self.root_entry:
            return None
        parts = [part for part in path.split("/") if part]
        if parts and parts[0] == self.root_entry["name"]:
            parts = parts[1:]
        current = self.root_entry
        for part in parts:
            current = next((entry for entry in self.sorted_children(current["id"]) if entry["name"] == part), None)
            if not current:
                return None
        return current

    def read_stream(self, entry: Dict[str, Any]) -> bytes:
        if not entry or entry["type"] != 2:
            raise ValueError("CFB entry is not a stream")
        if entry["size"] < self.mini_stream_cutoff:
            raise ValueError("CFB mini streams are not supported by this placement patcher")
        return self._read_chain(entry["starting_sector"], entry["size"])

    def stream_file_ranges(self, entry: Dict[str, Any]) -> List[Dict[str, int]]:
        if not entry or entry["type"] != 2:
            raise ValueError("CFB entry is not a stream")
        if entry["size"] < self.mini_stream_cutoff:
            raise ValueError("CFB mini streams cannot be patched in place")
        ranges = []
        seen = set()
        current = entry["starting_sector"]
        remaining = int(entry["size"])
        stream_offset = 0
        while current not in {END_OF_CHAIN, FREE_SECTOR} and remaining > 0:
            if current in seen:
                raise ValueError(f"CFB sector chain loop detected at sector {current}")
            if current >= len(self.fat_entries):
                raise ValueError(f"CFB sector {current} is outside FAT range")
            file_offset = (current + 1) * self.sector_size
            length = min(self.sector_size, remaining)
            ranges.append({"sector": current, "stream_offset": stream_offset, "file_offset": file_offset, "length": length})
            seen.add(current)
            stream_offset += length
            remaining -= length
            current = self.fat_entries[current]
        if remaining > 0:
            raise ValueError("CFB stream chain ended before declared stream size")
        return ranges


def build_record_chunks(stream: bytes) -> List[Dict[str, Any]]:
    records = []
    offset = 0
    while offset + 4 <= len(stream):
        length = read_u32(stream, offset)
        start = offset + 4
        end = start + length
        if length <= 0 or end > len(stream):
            break
        records.append(
            {
                "index": len(records),
                "offset": offset,
                "length": length,
                "start": start,
                "end": end,
                "text": stream[start:end].decode("latin1", errors="ignore"),
            }
        )
        offset = end
    return records


def locate_field_value(record_text: str, key: str) -> Optional[Dict[str, Any]]:
    match = re.search(rf"(^|\|){re.escape(key)}=([^|]*)", record_text)
    if not match:
        return None
    value_start = match.start() + len(match.group(1)) + len(key) + 1
    value = match.group(2)
    return {"start": value_start, "end": value_start + len(value), "value": value}


def parse_record_fields(record_text: str) -> Dict[str, str]:
    fields = {}
    for part in str(record_text or "").split("|"):
        separator = part.find("=")
        if separator <= 0:
            continue
        key = part[:separator].strip()
        value = re.sub(r"[\x00-\x1f]+$", "", part[separator + 1 :]).strip()
        if key:
            fields[key] = value
    return fields


def format_mil_for_original_length(mm: Any, original: str) -> Optional[str]:
    target_length = len(str(original or ""))
    mil = mm_to_mil(mm)
    if mil is None or target_length < 4:
        return None
    integer = f"{round(mil)}mil"
    if len(integer) <= target_length:
        return integer.rjust(target_length)
    max_numeric_length = target_length - 3
    if max_numeric_length <= 0:
        return None
    fixed0 = str(round(mil))
    if len(fixed0) <= max_numeric_length:
        return f"{fixed0.rjust(max_numeric_length)}mil"
    return None


def write_stream_bytes(file_data: bytearray, ranges: List[Dict[str, int]], stream_offset: int, data: bytes) -> None:
    remaining = len(data)
    source_offset = 0
    target_offset = stream_offset
    while remaining > 0:
        target_range = next(
            (
                item
                for item in ranges
                if target_offset >= item["stream_offset"] and target_offset < item["stream_offset"] + item["length"]
            ),
            None,
        )
        if not target_range:
            raise ValueError(f"Stream offset {target_offset} is outside CFB stream ranges")
        within_range = target_offset - target_range["stream_offset"]
        writable = min(remaining, target_range["length"] - within_range)
        file_offset = target_range["file_offset"] + within_range
        file_data[file_offset : file_offset + writable] = data[source_offset : source_offset + writable]
        source_offset += writable
        target_offset += writable
        remaining -= writable


def placement_maps(plan: Dict[str, Any]) -> Tuple[Dict[int, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    by_record = {}
    by_ref = {}
    for placement in make_list(plan.get("placements")):
        try:
            record = int(placement.get("source_record"))
            by_record[record] = placement
        except (TypeError, ValueError):
            pass
        ref = normalize_ref(placement.get("designator"))
        if ref:
            by_ref[ref] = placement
    return by_record, by_ref


def planned_placement_for_record(
    record: Dict[str, Any],
    fields: Dict[str, str],
    by_record: Dict[int, Dict[str, Any]],
    by_ref: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if record["index"] in by_record:
        return by_record[record["index"]]
    source_designator = normalize_ref(fields.get("SOURCEDESIGNATOR") or fields.get("DESIGNATOR") or fields.get("NAME") or fields.get("UNIQUEID"))
    return by_ref.get(source_designator) if source_designator else None


def should_skip_locked(fields: Dict[str, str], locked_refs: set, placement: Dict[str, Any]) -> bool:
    ref = normalize_ref(placement.get("designator"))
    if ref and ref in locked_refs:
        return True
    return component_locked({"fields": fields})


def resolve_output_path(input_path: Path, output: Optional[str], in_place: bool) -> Path:
    if in_place:
        return input_path
    if output:
        return Path(output).resolve()
    suffix = input_path.suffix or ".PcbDoc"
    return input_path.with_name(f"{input_path.stem}.placed{suffix}")


def apply_placement_plan_to_pcbdoc(input_path: Path, plan: Dict[str, Any], options: Dict[str, Any]) -> Dict[str, Any]:
    in_place = bool(options.get("in_place"))
    if in_place and options.get("confirm") is not True:
        raise ValueError("Refusing in-place PcbDoc update without --confirm")
    file_data = bytearray(input_path.read_bytes())
    cfb = Cfb(file_data)
    components_entry = cfb.find_entry_by_path("Root Entry/Components6/Data")
    if not components_entry:
        raise ValueError("PcbDoc Components6/Data stream was not found")
    ranges = cfb.stream_file_ranges(components_entry)
    stream = cfb.read_stream(components_entry)
    records = build_record_chunks(stream)
    by_record, by_ref = placement_maps(plan)
    locked_refs = {normalize_ref(item) for item in make_list(options.get("locked")) if normalize_ref(item)}
    patched = []
    skipped = []
    for record in records:
        fields = parse_record_fields(record["text"])
        placement = planned_placement_for_record(record, fields, by_record, by_ref)
        if not placement or not placement.get("suggested_center"):
            continue
        if placement.get("collision_status") == "unresolved":
            skipped.append({"designator": placement.get("designator", ""), "source_record": record["index"], "reason": "collision-unresolved"})
            continue
        if should_skip_locked(fields, locked_refs, placement):
            skipped.append({"designator": placement.get("designator", ""), "source_record": record["index"], "reason": "locked"})
            continue
        x_field = locate_field_value(record["text"], "X")
        y_field = locate_field_value(record["text"], "Y")
        if not x_field or not y_field:
            skipped.append({"designator": placement.get("designator", ""), "source_record": record["index"], "reason": "missing-x-y-fields"})
            continue
        suggested_center = placement["suggested_center"]
        next_x = format_mil_for_original_length(suggested_center.get("x_mm"), x_field["value"])
        next_y = format_mil_for_original_length(suggested_center.get("y_mm"), y_field["value"])
        if not next_x or not next_y or len(next_x) != len(x_field["value"]) or len(next_y) != len(y_field["value"]):
            skipped.append(
                {
                    "designator": placement.get("designator", ""),
                    "source_record": record["index"],
                    "reason": "coordinate-field-length-not-patchable",
                    "current": {"x": x_field["value"], "y": y_field["value"]},
                    "suggested_center": suggested_center,
                }
            )
            continue
        write_stream_bytes(file_data, ranges, record["start"] + x_field["start"], next_x.encode("latin1"))
        write_stream_bytes(file_data, ranges, record["start"] + y_field["start"], next_y.encode("latin1"))
        patched.append(
            {
                "designator": placement.get("designator", ""),
                "source_record": record["index"],
                "old_center": placement.get("old_center"),
                "suggested_center": suggested_center,
                "x": {"from": x_field["value"], "to": next_x.strip()},
                "y": {"from": y_field["value"], "to": next_y.strip()},
            }
        )

    output_path = resolve_output_path(input_path, options.get("output"), in_place)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(file_data)
    return {
        "status": "ok",
        "write_mode": "pcbdoc-in-place" if in_place else "pcbdoc-copy",
        "input": str(input_path),
        "output": str(output_path),
        "summary": {"requested": len(make_list(plan.get("placements"))), "patched": len(patched), "skipped": len(skipped)},
        "patched": patched,
        "skipped": skipped,
        "guarantees": {
            "patched_stream": "Root Entry/Components6/Data",
            "patch_mode": "in-place equal-length X/Y field replacement",
            "board_outline_modified": False,
            "routing_modified": False,
            "pads_modified": False,
            "nets_modified": False,
        },
    }
