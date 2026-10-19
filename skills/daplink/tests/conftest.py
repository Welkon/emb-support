"""Shared fixtures: load dap.py, build an ELF, provide a fake probe/target.

The suite never touches real hardware. `gcc` is used once per session to build a
small DWARF-enabled ELF; tests that need DWARF are skipped when gcc is missing.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "dap.py"
if str(SCRIPT.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT.parent))

C_SOURCE = r"""
typedef struct { int x; short y; } pt_t;
volatile int g_counter = 7;
pt_t g_pt = {3, 4};
const char g_name[] = "hi";
enum color { RED = 1, GREEN = 2 };
enum color g_color = GREEN;
struct node { int val; struct node *next; };
struct node n2 = {2, 0};
struct node n1 = {1, &n2};
struct node *g_head = &n1;
int g_arr[4] = {10, 20, 30, 40};
int *g_ptr = (int *)&g_counter;
int state_ready = 1;

int add(int a, int b) { int local = a + b; return local; }
int main(void) { return add(g_counter, g_pt.x); }
"""


@pytest.fixture(scope="session")
def dap():
    spec = importlib.util.spec_from_file_location("dap", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def elf(tmp_path_factory):
    if not shutil.which("gcc"):
        pytest.skip("gcc is required to build the ELF fixture")
    d = tmp_path_factory.mktemp("elf")
    src = d / "fixture.c"
    src.write_text(C_SOURCE)
    out = d / "fixture.elf"
    subprocess.run(
        ["gcc", "-g", "-O0", "-no-pie", str(src), "-o", str(out)],
        check=True, capture_output=True,
    )
    return out


class FakeMemory:
    """Byte-addressed image of the ELF load segments, writable for tests."""

    def __init__(self, elf_path: Path):
        from elftools.elf.elffile import ELFFile
        self.bytes: dict[int, int] = {}
        with open(elf_path, "rb") as f:
            e = ELFFile(f)
            for seg in e.iter_segments():
                if seg["p_type"] != "PT_LOAD":
                    continue
                va = seg["p_vaddr"]
                for i, b in enumerate(seg.data()):
                    self.bytes[va + i] = b

    def read(self, addr: int, n: int) -> bytes:
        return bytes(self.bytes.get(addr + i, 0) for i in range(n))

    def write(self, addr: int, data: bytes) -> None:
        for i, b in enumerate(data):
            self.bytes[addr + i] = b


class FakeTarget:
    def __init__(self, mem: FakeMemory, pc: int, sp: int = 0x28000000, regions=None):
        self.mem = mem
        self.core = self
        self.part_number = "FAKE"
        self.cores: dict = {}
        self.memory_map = regions or []
        self.state = "HALTED"
        self.regs = {"pc": pc & ~1, "sp": sp, "lr": 0, "r0": 0, "r7": sp}
        for i in range(13):
            self.regs.setdefault(f"r{i}", 0)
        self.breakpoints: list[int] = []
        self.watchpoints: list[tuple[int, int]] = []
        self.session = SimpleNamespace(options={}, log_tracebacks=False)

    def read_core_register(self, name):
        if name not in self.regs:
            raise KeyError(name)
        return self.regs[name]

    def write_core_register(self, name, value):
        self.regs[name] = value

    def read_core_register_raw(self, reg):
        if isinstance(reg, int):
            reg = {13: "sp", 14: "lr", 15: "pc"}.get(reg, f"r{reg}")
        return self.regs[reg]

    def write_core_register_raw(self, reg, value):
        if isinstance(reg, int):
            reg = {13: "sp", 14: "lr", 15: "pc"}.get(reg, f"r{reg}")
        self.regs[reg] = value

    def read_core_registers_raw(self, reg_list):
        return [self.read_core_register_raw(r) for r in reg_list]

    def write_core_registers_raw(self, reg_list, data_list):
        for r, v in zip(reg_list, data_list):
            self.write_core_register_raw(r, v)

    def read_memory(self, addr, transfer_size=32, now=True):
        return int.from_bytes(self.mem.read(addr, transfer_size // 8), "little")

    def write_memory(self, addr, value, transfer_size=32):
        self.mem.write(addr, int(value).to_bytes(transfer_size // 8, "little"))

    def read32(self, addr):
        return int.from_bytes(self.mem.read(addr, 4), "little")

    def write32(self, addr, value):
        self.mem.write(addr, value.to_bytes(4, "little"))

    def read8(self, addr):
        return self.mem.read(addr, 1)[0]

    def read16(self, addr):
        return int.from_bytes(self.mem.read(addr, 2), "little")

    def write8(self, addr, value):
        self.mem.write(addr, bytes([value]))

    def read_memory_block8(self, addr, n):
        return self.mem.read(addr, n)

    def write_memory_block8(self, addr, data):
        self.mem.write(addr, bytes(data))

    def write_memory_block32(self, addr, values):
        self.mem.write(addr, b"".join(int(v).to_bytes(4, "little") for v in values))

    def find_breakpoint(self, addr):
        return None

    def get_state(self):
        return SimpleNamespace(name=self.state)

    def get_halt_reason(self):
        return SimpleNamespace(name="BREAKPOINT")

    def halt(self):
        self.state = "HALTED"

    def resume(self):
        self.state = "RUNNING"

    def step(self, **kwargs):
        self.state = "HALTED"

    def reset(self):
        self.state = "HALTED"

    def set_breakpoint(self, addr, type=None):
        self.breakpoints.append(addr & ~1)
        return True

    def remove_breakpoint(self, addr):
        if addr in self.breakpoints:
            self.breakpoints.remove(addr)

    def set_watchpoint(self, addr, size, type=None):
        self.watchpoints.append((addr, size))
        return True

    def remove_watchpoint(self, addr, size=None, type=None):
        pass


class FakeSession:
    def __init__(self, target: FakeTarget):
        self.target = target
        self.options: dict = {}
        self.probe = SimpleNamespace(unique_id="fake-probe")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture
def iso(dap, tmp_path, monkeypatch):
    """Redirect all persistent state into tmp_path."""
    monkeypatch.setattr(dap, "HOME", tmp_path)
    monkeypatch.setattr(dap, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(dap, "BP_REGISTRY", tmp_path / "breakpoints.json")
    monkeypatch.setattr(dap, "FLASH_BPS", tmp_path / "flash_bp.json")
    return tmp_path


@pytest.fixture
def fake(dap, elf, iso, monkeypatch):
    """Patch _session to return a fake target sitting at main()."""
    ei = dap.ElfInfo(str(elf))
    target = FakeTarget(FakeMemory(elf), pc=ei.symbols["main"])
    session = FakeSession(target)
    monkeypatch.setattr(dap, "_session", lambda a, **kw: session)
    return SimpleNamespace(dap=dap, target=target, session=session, mem=target.mem,
                           elf=elf, ei=ei, path=str(elf))
