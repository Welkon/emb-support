"""Pure debug primitives: ELF metadata, DWARF types, CFI unwinding, C expressions.

Extracted from dap.py so the CLI layer stays thin and this part can be tested
in isolation. No probe or session state is used here.
"""

from __future__ import annotations

import bisect
import re
from pathlib import Path


class ElfInfo:
    """Symbols + DWARF line table + executable ranges, loaded lazily per command."""

    def __init__(self, path: str):
        from elftools.elf.elffile import ELFFile
        self.path = str(Path(path).expanduser())
        self.symbols: dict[str, int] = {}
        self.sym_list: list[tuple[int, int, str]] = []
        self.lines: list[tuple[int, str, int]] = []
        self.exec_ranges: list[tuple[int, int]] = []
        with open(self.path, "rb") as f:
            elf = ELFFile(f)
            for seg in elf.iter_segments():
                if seg["p_type"] == "PT_LOAD" and (seg["p_flags"] & 1):
                    self.exec_ranges.append((seg["p_paddr"], seg["p_paddr"] + seg["p_memsz"]))
            for sec in elf.iter_sections():
                if sec["sh_type"] not in ("SHT_SYMTAB", "SHT_DYNSYM"):
                    continue
                for sym in sec.iter_symbols():
                    typ = sym["st_info"]["type"]
                    if sym.name and sym["st_value"] and typ in ("STT_FUNC", "STT_OBJECT", "STT_NOTYPE"):
                        addr = sym["st_value"] & ~1
                        self.symbols.setdefault(sym.name, addr)
                        self.sym_list.append((addr, sym["st_size"], sym.name))
            self.sym_list.sort()
            self.sym_addrs = [s[0] for s in self.sym_list]
            try:
                dwarf = elf.get_dwarf_info()
                for cu in dwarf.iter_CUs():
                    lp = dwarf.line_program_for_CU(cu)
                    if lp is None:
                        continue
                    files = lp["file_entry"]
                    for entry in lp.get_entries():
                        st = entry.state
                        if st is None:
                            continue
                        try:
                            name = files[st.file - 1].name
                            if isinstance(name, bytes):
                                name = name.decode(errors="replace")
                        except Exception:
                            name = "?"
                        self.lines.append((st.address, name, st.line))
            except Exception:
                pass
            self.lines.sort()
            self.line_addrs = [x[0] for x in self.lines]

    def in_code(self, addr: int) -> bool:
        return any(lo <= addr < hi for lo, hi in self.exec_ranges)

    def frame_name(self, addr: int) -> str:
        if not self.sym_addrs:
            return hex(addr)
        i = bisect.bisect_right(self.sym_addrs, addr) - 1
        if i < 0:
            return hex(addr)
        start, size, name = self.sym_list[i]
        if size and addr - start >= size:
            return hex(addr)
        return f"{name}+0x{addr - start:x}" if addr != start else name

    def line_for(self, addr: int) -> tuple[str, int] | None:
        if not self.line_addrs:
            return None
        i = bisect.bisect_right(self.line_addrs, addr) - 1
        if i < 0:
            return None
        a, name, line = self.lines[i]
        if addr - a > 0x1000:
            return None
        return name, line

def _uleb(data: bytes, i: int) -> tuple[int, int]:
    result = shift = 0
    while i < len(data):
        b = data[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return result, i

def _sleb(data: bytes, i: int) -> tuple[int, int]:
    result = shift = 0
    while i < len(data):
        b = data[i]
        i += 1
        result |= (b & 0x7F) << shift
        shift += 7
        if not (b & 0x80):
            if b & 0x40:
                result -= 1 << shift
            break
    return result, i

def _expr_bytes(attr) -> bytes | None:
    if attr is None or attr.value is None:
        return None
    v = attr.value
    if isinstance(v, bytes):
        return v
    try:
        return bytes(v)
    except Exception:
        return None

def _cu_addr_size(cu) -> int:
    try:
        return int(cu.header["address_size"])
    except Exception:
        return 4

def _dwarf_ops(data: bytes, addr_size: int = 4) -> list[tuple]:
    out: list[tuple] = []
    i = 0
    while i < len(data):
        op = data[i]
        i += 1
        if op == 0x03:
            out.append(("addr", int.from_bytes(data[i:i + addr_size], "little")))
            i += addr_size
        elif 0x50 <= op <= 0x6F:
            out.append(("reg", op - 0x50))
        elif 0x70 <= op <= 0x8F:
            v, i = _sleb(data, i)
            out.append(("breg", op - 0x70, v))
        elif op == 0x91:
            v, i = _sleb(data, i)
            out.append(("fbreg", v))
        elif op == 0x9C:
            out.append(("cfa",))
        elif op == 0x23:
            v, i = _uleb(data, i)
            out.append(("plus", v))
        else:
            break
    return out

class DwarfReader:
    """Minimal DWARF reader: globals, locals and typed value formatting."""

    def __init__(self, path: str):
        from elftools.elf.elffile import ELFFile
        self._f = open(path, "rb")
        self.elf = ELFFile(self._f)
        self.dwarf = self.elf.get_dwarf_info()
        self.globals: dict[str, object] = {}
        self.type_index: dict[str, tuple] = {}
        self.subprograms: list[tuple[int, int, object, object]] = []
        for cu in self.dwarf.iter_CUs():
            for die in cu.iter_DIEs():
                try:
                    parent = die.get_parent()
                    if die.tag == "DW_TAG_variable" and parent is not None and parent.tag == "DW_TAG_compile_unit":
                        loc = die.attributes.get("DW_AT_location")
                        if _expr_bytes(loc) is not None:
                            self.globals[die.attributes["DW_AT_name"].value.decode(errors="replace")] = (die, cu)
                    elif die.tag == "DW_TAG_subprogram":
                        lo = die.attributes.get("DW_AT_low_pc")
                        hi = die.attributes.get("DW_AT_high_pc")
                        if lo is None or hi is None:
                            continue
                        lo_addr = lo.value
                        hi_addr = hi.value if hi.form == "DW_FORM_addr" else lo_addr + hi.value
                        self.subprograms.append((lo_addr, hi_addr, die, cu))
                    if die.tag in ("DW_TAG_base_type", "DW_TAG_typedef", "DW_TAG_structure_type",
                                   "DW_TAG_union_type", "DW_TAG_enumeration_type"):
                        nm = die.attributes.get("DW_AT_name")
                        if nm is not None:
                            self.type_index.setdefault(nm.value.decode(errors="replace"), (die, cu))
                except Exception:
                    continue
        self.subprograms.sort()

    def die_for_pc(self, pc: int):
        for lo, hi, die, cu in self.subprograms:
            if lo <= pc < hi:
                return die, cu
        return None, None

    @staticmethod
    def _name(die) -> str:
        a = die.attributes.get("DW_AT_name")
        return a.value.decode(errors="replace") if a else "?"

    def _sizeof(self, die, cu, depth: int = 0):
        if die is None or depth > 6:
            return None
        tag = die.tag
        if tag in ("DW_TAG_typedef", "DW_TAG_const_type", "DW_TAG_volatile_type", "DW_TAG_restrict_type"):
            return self._sizeof(self._type(die, cu), cu, depth + 1)
        a = die.attributes.get("DW_AT_byte_size")
        if a is not None and isinstance(a.value, int):
            return a.value
        if tag == "DW_TAG_pointer_type":
            return 4
        if tag == "DW_TAG_array_type":
            elem = self._type(die, cu)
            es = self._sizeof(elem, cu, depth + 1)
            count = None
            for child in die.iter_children():
                if child.tag == "DW_TAG_subrange_type":
                    c = child.attributes.get("DW_AT_count")
                    ub = child.attributes.get("DW_AT_upper_bound")
                    if c is not None:
                        count = c.value
                    elif ub is not None and isinstance(ub.value, int):
                        count = ub.value + 1
            if es and count:
                return es * count
        return None

    @staticmethod
    def _type(die, cu):
        ref = die.attributes.get("DW_AT_type")
        if ref is None:
            return None
        try:
            return cu.get_DIE_from_refaddr(ref.value)
        except Exception:
            return None

    def fmt(self, die, cu, addr: int, read, depth: int = 0) -> object:
        if die is None or depth > 6:
            return None
        tag = die.tag
        if tag in ("DW_TAG_typedef", "DW_TAG_const_type", "DW_TAG_volatile_type", "DW_TAG_restrict_type"):
            return self.fmt(self._type(die, cu), cu, addr, read, depth + 1)
        if tag == "DW_TAG_base_type":
            size = die.attributes.get("DW_AT_byte_size")
            enc = die.attributes.get("DW_AT_encoding")
            size = size.value if size else 4
            raw = read(addr, size)
            if raw is None:
                return None
            enc = enc.value if enc else 5
            if enc in (4,):  # float
                import struct as _s
                return _s.unpack("<f" if size == 4 else "<d", raw)[0]
            if enc in (2,):  # bool
                return bool(int.from_bytes(raw, "little"))
            if enc in (7,):  # unsigned
                return int.from_bytes(raw, "little")
            if enc in (8,):  # signed char
                return int.from_bytes(raw, "little", signed=True)
            return int.from_bytes(raw, "little", signed=True) if enc in (5, 6) else int.from_bytes(raw, "little")
        if tag == "DW_TAG_enumeration_type":
            size = die.attributes.get("DW_AT_byte_size")
            raw = read(addr, size.value if size else 4)
            if raw is None:
                return None
            val = int.from_bytes(raw, "little")
            for child in die.iter_children():
                if child.tag == "DW_TAG_enumerator":
                    cv = child.attributes.get("DW_AT_const_value")
                    if cv is not None and cv.value == val:
                        return self._name(child)
            return val
        if tag == "DW_TAG_pointer_type":
            size = die.attributes.get("DW_AT_byte_size")
            raw = read(addr, size.value if size else 4)
            if raw is None:
                return None
            return hex(int.from_bytes(raw, "little"))
        if tag in ("DW_TAG_structure_type", "DW_TAG_class_type", "DW_TAG_union_type"):
            out = {}
            for child in die.iter_children():
                if child.tag != "DW_TAG_member":
                    continue
                cname = self._name(child)
                mloc = child.attributes.get("DW_AT_data_member_location")
                off = mloc.value if mloc is not None and isinstance(mloc.value, int) else 0
                out[cname] = self.fmt(self._type(child, cu), cu, addr + off, read, depth + 1)
            return out
        if tag == "DW_TAG_array_type":
            elem = self._type(die, cu)
            count = None
            for child in die.iter_children():
                if child.tag == "DW_TAG_subrange_type":
                    c = child.attributes.get("DW_AT_count")
                    ub = child.attributes.get("DW_AT_upper_bound")
                    if c is not None:
                        count = c.value
                    elif ub is not None and isinstance(ub.value, int):
                        count = ub.value + 1
            if not count or count > 256:
                return None
            size = self._sizeof(elem, cu) or 4
            return [self.fmt(elem, cu, addr + i * size, read, depth + 1) for i in range(count)]
        return None

    def _location(self, die, cu, regs, base):
        data = _expr_bytes(die.attributes.get("DW_AT_location"))
        if data is None:
            return None
        ops = _dwarf_ops(data, _cu_addr_size(cu))
        if not ops:
            return None
        op = ops[0]
        if op[0] == "addr":
            return op[1]
        if op[0] == "reg":
            names = {13: "sp", 14: "lr", 15: "pc"}
            return regs.get(names.get(op[1], f"r{op[1]}"))
        if op[0] == "breg":
            names = {13: "sp", 14: "lr", 15: "pc"}
            val = regs.get(names.get(op[1], f"r{op[1]}"))
            return None if val is None else val + op[2]
        if op[0] == "fbreg":
            return base + op[1]
        if op[0] == "cfa":
            return base
        return None

    def globals_at(self, read) -> list[dict]:
        out = []
        for name, (die, cu) in self.globals.items():
            data = _expr_bytes(die.attributes.get("DW_AT_location"))
            ops = _dwarf_ops(data, _cu_addr_size(cu)) if data else []
            if not ops or ops[0][0] != "addr":
                continue
            addr = ops[0][1]
            out.append({"name": name, "address": hex(addr),
                        "value": self.fmt(self._type(die, cu), cu, addr, read)})
        return out

    def locals_env(self, pc: int, regs: dict, cfa: int | None = None) -> dict:
        """name -> (die, cu, address) for the function containing pc."""
        die, cu = self.die_for_pc(pc)
        if die is None:
            return {}
        base = cfa if cfa is not None else regs.get("sp", 0)
        fb_data = _expr_bytes(die.attributes.get("DW_AT_frame_base"))
        if fb_data is not None:
            ops = _dwarf_ops(fb_data, _cu_addr_size(cu))
            if ops and ops[0][0] == "breg" and ops[0][1] == 13:
                base = regs.get("sp", 0) + ops[0][2]
            elif ops and ops[0][0] == "reg" and ops[0][1] == 13:
                base = regs.get("sp", 0)
        out = {}
        for child in die.iter_children():
            if child.tag not in ("DW_TAG_variable", "DW_TAG_formal_parameter"):
                continue
            addr = self._location(child, cu, regs, base)
            if addr is not None:
                out[self._name(child)] = (child, cu, addr)
        return out

    def globals_env(self) -> dict:
        out = {}
        for name, (die, cu) in self.globals.items():
            data = _expr_bytes(die.attributes.get("DW_AT_location"))
            ops = _dwarf_ops(data, _cu_addr_size(cu)) if data else []
            if ops and ops[0][0] == "addr":
                out[name] = (die, cu, ops[0][1])
        return out

    def locals_at(self, pc: int, regs: dict, read, cfa: int | None = None) -> list[dict]:
        die, cu = self.die_for_pc(pc)
        if die is None:
            return []
        env = self.locals_env(pc, regs, cfa)
        out = []
        for name, (child, ccu, addr) in env.items():
            out.append({"name": name, "address": hex(addr),
                        "arg": child.tag == "DW_TAG_formal_parameter",
                        "value": self.fmt(self._type(child, ccu), ccu, addr, read)})
        return out

    def lookup(self, name: str):
        if name in self.globals:
            return self.globals[name]
        return None

_REG_NAMES = {13: "sp", 14: "lr", 15: "pc"}

class CfiUnwinder:
    """DWARF CFI (.debug_frame / .eh_frame) unwinder for ARM Cortex-M."""

    def __init__(self, path: str):
        from elftools.elf.elffile import ELFFile
        self._f = open(path, "rb")
        self.elf = ELFFile(self._f)
        self.dwarf = self.elf.get_dwarf_info()
        self.fdes: list[tuple[int, int, object]] = []
        for getter in ("CFI_entries", "EH_CFI_entries"):
            try:
                entries = getattr(self.dwarf, getter)()
            except Exception:
                continue
            try:
                for e in entries:
                    if e.__class__.__name__ != "FDE":
                        continue
                    lo = e["initial_location"]
                    hi = lo + e["address_range"]
                    self.fdes.append((lo, hi, e))
            except Exception:
                continue
        self.fdes.sort(key=lambda x: x[0])

    def find(self, pc: int):
        for lo, hi, e in self.fdes:
            if lo <= pc < hi:
                return e
        return None

    def unwind(self, pc: int, regs: dict, read32, limit: int = 32) -> list[dict]:
        frames: list[dict] = []
        cur_pc = pc & ~1
        cur = dict(regs)
        for _ in range(limit):
            fde = self.find(cur_pc)
            info = {"pc": cur_pc, "regs": dict(cur), "cfa": None, "exact": False}
            if fde is None:
                frames.append(info)
                break
            try:
                line = None
                for ln in fde.get_decoded().table:
                    if ln["pc"] <= cur_pc:
                        line = ln
                    else:
                        break
                cfa_rule = line.get("cfa") if line else None
                if cfa_rule is None or cfa_rule.reg is None:
                    frames.append(info)
                    break
                cfa = cur.get(_REG_NAMES.get(cfa_rule.reg, f"r{cfa_rule.reg}"), 0) + (cfa_rule.offset or 0)
                info["cfa"] = cfa
                info["exact"] = True
                frames.append(info)
                ra_reg = fde.cie["return_address_register"]
                rule = line.get(ra_reg)
                ra = None
                if rule is not None:
                    if rule.type == "OFFSET":
                        ra = read32(cfa + rule.arg)
                    elif rule.type == "VAL_OFFSET":
                        ra = cfa + rule.arg
                    elif rule.type == "SAME_VALUE":
                        ra = cur.get(_REG_NAMES.get(ra_reg, f"r{ra_reg}"))
                    elif rule.type == "REGISTER":
                        ra = cur.get(_REG_NAMES.get(rule.arg, f"r{rule.arg}"))
                if ra is None:
                    ra = cur.get("lr")
                if not ra or ra in (0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
                    break
                caller = dict(cur)
                for rnum, r in line.items():
                    if not isinstance(rnum, int):
                        continue
                    nm = _REG_NAMES.get(rnum, f"r{rnum}")
                    if r.type == "OFFSET":
                        caller[nm] = read32(cfa + r.arg)
                    elif r.type == "VAL_OFFSET":
                        caller[nm] = cfa + r.arg
                    elif r.type == "UNDEFINED":
                        caller[nm] = 0
                    elif r.type == "REGISTER":
                        caller[nm] = cur.get(_REG_NAMES.get(r.arg, f"r{r.arg}"), 0)
                caller["sp"] = cfa
                caller["lr"] = ra
                caller["pc"] = ra & ~1
                cur_pc = ra & ~1
                cur = caller
            except Exception:
                break
        return frames

def _tref(dr, die, cu) -> dict | None:
    if die is None:
        return None
    cache = getattr(dr, "_tref_cache", None)
    if cache is None:
        cache = dr._tref_cache = {}
    key = (id(cu), die.offset)
    if key in cache:
        return cache[key]
    out: dict = {"die": die, "cu": cu, "name": DwarfReader._name(die), "kind": "other", "size": None}
    cache[key] = out  # break recursion for self-referential structs
    tag = die.tag
    if tag in ("DW_TAG_typedef", "DW_TAG_const_type", "DW_TAG_volatile_type", "DW_TAG_restrict_type"):
        base = _tref(dr, DwarfReader._type(die, cu), cu)
        out.update(base or {})
        out["name"] = DwarfReader._name(die) or (base or {}).get("name")
        return out
    if tag == "DW_TAG_base_type":
        enc = die.attributes.get("DW_AT_encoding")
        bs = die.attributes.get("DW_AT_byte_size")
        out.update(kind="base", size=bs.value if bs else 4,
                   signed=(enc.value in (5, 6, 8)) if enc else True,
                   encoding=enc.value if enc else 5)
    elif tag == "DW_TAG_pointer_type":
        out.update(kind="ptr", size=4, target=_tref(dr, DwarfReader._type(die, cu), cu))
    elif tag == "DW_TAG_enumeration_type":
        bs = die.attributes.get("DW_AT_byte_size")
        vals = {}
        for ch in die.iter_children():
            if ch.tag == "DW_TAG_enumerator":
                cv = ch.attributes.get("DW_AT_const_value")
                if cv is not None:
                    vals[cv.value] = DwarfReader._name(ch)
        out.update(kind="enum", size=bs.value if bs else 4, values=vals)
    elif tag in ("DW_TAG_structure_type", "DW_TAG_class_type", "DW_TAG_union_type"):
        bs = die.attributes.get("DW_AT_byte_size")
        members = {}
        for ch in die.iter_children():
            if ch.tag != "DW_TAG_member":
                continue
            mloc = ch.attributes.get("DW_AT_data_member_location")
            off = mloc.value if mloc is not None and isinstance(mloc.value, int) else 0
            members[DwarfReader._name(ch)] = (off, _tref(dr, DwarfReader._type(ch, cu), cu))
        out.update(kind="struct", size=bs.value if bs else 0, members=members)
    elif tag == "DW_TAG_array_type":
        elem = _tref(dr, DwarfReader._type(die, cu), cu)
        count = None
        for ch in die.iter_children():
            if ch.tag == "DW_TAG_subrange_type":
                c = ch.attributes.get("DW_AT_count")
                ub = ch.attributes.get("DW_AT_upper_bound")
                if c is not None:
                    count = c.value
                elif ub is not None and isinstance(ub.value, int):
                    count = ub.value + 1
        esize = (elem or {}).get("size") or 4
        out.update(kind="array", elem=elem, count=count, size=(count or 0) * esize)
    elif tag == "DW_TAG_void_type":
        out.update(kind="void", size=0)
    return out

def _type_by_name(dr, name: str) -> dict | None:
    entry = getattr(dr, "type_index", {}).get(name)
    if entry is not None:
        return _tref(dr, entry[0], entry[1])
    synth = {
        "uint8_t": (1, False), "int8_t": (1, True), "char": (1, True),
        "uint16_t": (2, False), "int16_t": (2, True), "short": (2, True),
        "uint32_t": (4, False), "int32_t": (4, True), "int": (4, True),
        "uint64_t": (8, False), "int64_t": (8, True), "size_t": (4, False),
    }.get(name)
    if synth:
        return {"die": None, "cu": None, "name": name, "kind": "base",
                "size": synth[0], "signed": synth[1], "encoding": 5 if synth[1] else 7}
    return None

def _tr_size(tr: dict | None) -> int:
    return int((tr or {}).get("size") or 4)

def _read_tr(addr: int, tr: dict | None, read):
    if tr is None:
        raw = read(addr, 4)
        return None if raw is None else int.from_bytes(raw, "little")
    kind = tr["kind"]
    if kind == "base":
        raw = read(addr, _tr_size(tr))
        if raw is None:
            return None
        enc = tr.get("encoding", 5)
        if enc == 4:
            import struct as _s
            return _s.unpack("<f" if len(raw) == 4 else "<d", raw)[0]
        return int.from_bytes(raw, "little", signed=bool(tr.get("signed")))
    if kind == "enum":
        raw = read(addr, _tr_size(tr))
        if raw is None:
            return None
        v = int.from_bytes(raw, "little")
        return tr.get("values", {}).get(v, v)
    if kind == "ptr":
        raw = read(addr, 4)
        return None if raw is None else int.from_bytes(raw, "little")
    if kind == "struct":
        out = {}
        for name, (off, mtr) in (tr.get("members") or {}).items():
            out[name] = _read_tr(addr + off, mtr, read)
        return out
    if kind == "array":
        n = tr.get("count") or 0
        if n > 256:
            n = 256
        esize = _tr_size(tr.get("elem"))
        return [_read_tr(addr + i * esize, tr.get("elem"), read) for i in range(n)]
    raw = read(addr, 4)
    return None if raw is None else int.from_bytes(raw, "little")

class Val:
    __slots__ = ("v", "tr", "addr", "cu")

    def __init__(self, v=None, tr=None, addr=None, cu=None):
        self.v = v
        self.tr = tr
        self.addr = addr
        self.cu = cu

    def load(self, read):
        if self.addr is not None:
            self.v = _read_tr(self.addr, self.tr, read)
        return self.v

TOKEN_RE = re.compile(
    r"\s*(?:(?P<num>0[xX][0-9a-fA-F]+|\d+)"
    r"|(?P<chr>'(?:\\.|[^'\\])')"
    r"|(?P<id>[A-Za-z_]\w*)"
    r"|(?P<op>->|<<|>>|<=|>=|==|!=|&&|\|\||[-+*/%&|^~!<>()\[\].,]))")

PREC = {"||": 1, "&&": 2, "|": 3, "^": 4, "&": 5, "==": 6, "!=": 6,
        "<": 7, "<=": 7, ">": 7, ">=": 7, "<<": 8, ">>": 8,
        "+": 9, "-": 9, "*": 10, "/": 10, "%": 10}

class ExprParser:
    def __init__(self, text: str, env: dict, dr, read):
        self.toks = []
        pos = 0
        while pos < len(text):
            m = TOKEN_RE.match(text, pos)
            if not m:
                if text[pos:].strip() == "":
                    break
                raise ValueError(f"Cannot parse: {text[pos:pos + 12]}")
            pos = m.end()
            if m.lastgroup:
                self.toks.append((m.lastgroup, m.group(m.lastgroup)))
        self.i = 0
        self.env = env
        self.dr = dr
        self.read = read
        self._cast: dict | None = None

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def take(self, value=None):
        tok = self.peek()
        if value is not None and tok[1] != value:
            raise ValueError(f"Expected {value}, got {tok[1]}")
        self.i += 1
        return tok

    def parse(self) -> Val:
        v = self.binary(0)
        return v

    def binary(self, min_prec: int) -> Val:
        lhs = self.unary()
        while True:
            kind, op = self.peek()
            if kind != "op" or op not in PREC or PREC[op] < min_prec:
                break
            self.take()
            rhs = self.binary(PREC[op] + 1)
            lhs = self.apply(op, lhs, rhs)
        return lhs

    def apply(self, op: str, a: Val, b: Val) -> Val:
        av = a.load(self.read)
        bv = b.load(self.read)
        if op in ("&&", "||"):
            return Val(v=int(bool(av) and bool(bv)) if op == "&&" else int(bool(av) or bool(bv)))
        if op in ("==", "!=", "<", "<=", ">", ">="):
            r = {"==": av == bv, "!=": av != bv, "<": av < bv,
                 "<=": av <= bv, ">": av > bv, ">=": av >= bv}[op]
            return Val(v=int(r))
        # pointer arithmetic
        if (a.tr or {}).get("kind") == "ptr" and op in ("+", "-") and isinstance(bv, int):
            step = _tr_size((a.tr or {}).get("target"))
            return Val(v=av + bv * step if op == "+" else av - bv * step, tr=a.tr, cu=a.cu)
        if (b.tr or {}).get("kind") == "ptr" and op == "+" and isinstance(av, int):
            step = _tr_size((b.tr or {}).get("target"))
            return Val(v=bv + av * step, tr=b.tr, cu=b.cu)
        if op == "+":
            return Val(v=av + bv)
        if op == "-":
            return Val(v=av - bv)
        if op == "*":
            return Val(v=av * bv)
        if op == "/":
            return Val(v=int(av / bv) if bv else 0)
        if op == "%":
            return Val(v=av % bv if bv else 0)
        if op == "<<":
            return Val(v=av << bv)
        if op == ">>":
            return Val(v=av >> bv)
        if op == "&":
            return Val(v=av & bv)
        if op == "|":
            return Val(v=av | bv)
        if op == "^":
            return Val(v=av ^ bv)
        raise ValueError(f"Unsupported operator {op}")

    def unary(self) -> Val:
        kind, tok = self.peek()
        if kind == "op" and tok in ("!", "~", "-", "+", "*", "&"):
            self.take()
            val = self.unary()
            if tok == "!":
                return Val(v=int(not val.load(self.read)))
            if tok == "~":
                return Val(v=~val.load(self.read))
            if tok == "-":
                return Val(v=-val.load(self.read))
            if tok == "+":
                return val
            if tok == "*":
                if (val.tr or {}).get("kind") != "ptr":
                    raise ValueError("* requires a pointer")
                return Val(tr=val.tr.get("target"), addr=val.load(self.read), cu=val.cu)
            if tok == "&":
                if val.addr is None:
                    raise ValueError("& requires an lvalue")
                return Val(v=val.addr, tr={"kind": "ptr", "size": 4, "target": val.tr, "die": None, "cu": val.cu},
                           cu=val.cu)
        # cast: (type*)x  or  (type)x
        if kind == "op" and tok == "(":
            save = self.i
            self.take("(")
            k2, t2 = self.peek()
            if k2 == "id":
                self.take()
                stars = 0
                while self.peek() == ("op", "*"):
                    self.take()
                    stars += 1
                if self.peek() == ("op", ")"):
                    self.take()
                    base = _type_by_name(self.dr, t2)
                    if base is None and t2 not in ("void",):
                        self.i = save
                    else:
                        tr = base
                        for _ in range(stars):
                            tr = {"kind": "ptr", "size": 4, "target": tr, "die": None, "cu": None}
                        self._cast = tr
                        inner = self.unary()
                        self._cast = None
                        v = inner.load(self.read)
                        if tr and tr.get("kind") == "base" and isinstance(v, int) and tr.get("size", 4) < 8:
                            mask = (1 << (8 * tr["size"])) - 1
                            v = v & mask
                        return Val(v=v, tr=tr, cu=inner.cu)
            self.i = save
        return self.postfix(self.primary())

    def postfix(self, val: Val) -> Val:
        while True:
            kind, op = self.peek()
            if (kind, op) in (("op", "."), ("op", "->")):
                self.take()
                k2, name = self.take()
                if k2 != "id":
                    raise ValueError("missing member name")
                if op == "->":
                    if (val.tr or {}).get("kind") != "ptr":
                        raise ValueError("-> requires a pointer")
                    val = Val(tr=val.tr.get("target"), addr=val.load(self.read), cu=val.cu)
                tr = val.tr or {}
                if tr.get("kind") != "struct":
                    raise ValueError(f"{tr.get('name')} is not a struct")
                if name not in (tr.get("members") or {}):
                    raise ValueError(f"struct has no member {name}; available: {', '.join(list(tr.get('members') or {})[:8])}")
                off, mtr = tr["members"][name]
                if val.addr is None:
                    raise ValueError("member access requires an lvalue")
                val = Val(tr=mtr, addr=val.addr + off, cu=val.cu)
                continue
            if (kind, op) == ("op", "["):
                self.take()
                idx = self.binary(0).load(self.read)
                self.take("]")
                tr = val.tr or {}
                if tr.get("kind") == "array":
                    esize = _tr_size(tr.get("elem"))
                    val = Val(tr=tr.get("elem"), addr=(val.addr or 0) + idx * esize, cu=val.cu)
                elif tr.get("kind") == "ptr":
                    esize = _tr_size(tr.get("target"))
                    val = Val(tr=tr.get("target"), addr=val.load(self.read) + idx * esize, cu=val.cu)
                else:
                    raise ValueError("[] requires an array or pointer")
                continue
            return val

    def primary(self) -> Val:
        kind, tok = self.peek()
        if kind == "num":
            self.take()
            return Val(v=int(tok, 0))
        if kind == "chr":
            self.take()
            body = tok[1:-1]
            esc = {"n": 10, "t": 9, "r": 13, "0": 0, "\\": 92, "'": 39}
            return Val(v=esc.get(body, ord(body[0])))
        if kind == "id":
            self.take()
            if tok in self.env:
                return self.env[tok]
            if self._cast is not None and tok == "void":
                return Val(v=0)
            raise ValueError(f"Unknown identifier {tok} (use vars globals/locals to list symbols)")
        if kind == "op" and tok == "(":
            self.take()
            v = self.binary(0)
            self.take(")")
            return v
        raise ValueError(f"Unexpected token {tok!r}")

def eval_expr(dr, expr: str, env: dict, read) -> Val:
    p = ExprParser(expr, env, dr, read)
    val = p.parse()
    if p.peek()[0] is not None:
        raise ValueError(f"Unparsed expression: {p.peek()[1]}")
    return val
