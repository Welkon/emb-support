#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


KNOWN_DEBUG_CHIP_SUBSTITUTES = {
    frozenset(("SC8P062BD", "SC8F072")): (
        "SC8F072 erasable/debug device can substitute for SC8P062BD "
        "when recorded as project-local board truth"
    ),
}


def default_project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--build-name", "-BuildName", dest="build_name", default="local")
    parser.add_argument("--toolchain-root", "-ToolchainRoot", dest="toolchain_root", default="")
    parser.add_argument("--xc8-exe", "-Xc8Exe", dest="xc8_exe", default="")
    parser.add_argument(
        "--list-toolchain-candidates",
        "-ListToolchainCandidates",
        dest="list_toolchain_candidates",
        action="store_true",
    )
    parser.add_argument("--chip", "-Chip", dest="chip", default="")
    parser.add_argument("--source-file", "-SourceFile", dest="source_files", action="append", default=[])
    parser.add_argument("--include-dir", "-IncludeDir", dest="include_dirs", action="append", default=[])
    parser.add_argument("--define", "-Define", dest="defines", action="append", default=[])
    parser.add_argument(
        "--append-source-file",
        "-AppendSourceFile",
        dest="append_source_files",
        action="append",
        default=[],
    )
    parser.add_argument("--image-prefix", "-ImagePrefix", dest="image_prefix", default="")
    parser.add_argument("--project-file", "-ProjectFile", dest="project_file", default="")
    parser.add_argument(
        "--project-root",
        "-ProjectRoot",
        dest="project_root",
        default=str(default_project_root()),
    )
    return parser.parse_args()


def common_toolchain_search_roots() -> list[Path]:
    roots: list[Path] = []
    if os.name == "nt":
        for drive in ("C", "D", "E", "F"):
            roots.append(Path(f"{drive}:\\"))
    else:
        for root in ("/mnt/c", "/mnt/d", "/mnt/e", "/mnt/f", "/opt", "/usr/local"):
            roots.append(Path(root))
    return [root for root in roots if root.exists()]


def detect_toolchain_candidates() -> list[dict[str, str]]:
    patterns = (
        "SCMCU_IDE*",
        "WorkToolsAndLib/SCMCU_IDE*",
        "Tools/SCMCU_IDE*",
        "Program Files/SCMCU_IDE*",
        "Program Files (x86)/SCMCU_IDE*",
    )
    seen: set[str] = set()
    candidates: list[dict[str, str]] = []

    for root in common_toolchain_search_roots():
        for pattern in patterns:
            for match in sorted(root.glob(pattern), reverse=True):
                xc8_path = match / "data" / "bin" / "xc8.exe"
                include_dir = match / "data" / "include"
                if not xc8_path.exists() or not include_dir.exists():
                    continue
                key = str(xc8_path)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(
                    {
                        "root": str(match),
                        "xc8_exe": str(xc8_path),
                        "include_dir": str(include_dir),
                    }
                )

    return candidates


def print_toolchain_candidates() -> int:
    candidates = detect_toolchain_candidates()
    if not candidates:
        print("Toolchain candidates: none")
        return 1

    print(f"Toolchain candidates: {len(candidates)}")
    for item in candidates:
        print(f"- root: {item['root']}")
        print(f"  xc8: {item['xc8_exe']}")
        print(f"  include: {item['include_dir']}")
    return 0


def choose_toolchain(args: argparse.Namespace) -> tuple[str, str, str]:
    xc8_exe = args.xc8_exe or os.environ.get("XC8_EXE", "")
    toolchain_root = args.toolchain_root or os.environ.get("SCMCU_IDE_ROOT", "")

    if xc8_exe:
        xc8_path = Path(xc8_exe)
        include_dir = xc8_path.parent.parent / "include"
        source = "explicit-xc8-exe"
    elif toolchain_root:
        toolchain_path = Path(toolchain_root)
        xc8_path = toolchain_path / "data" / "bin" / "xc8.exe"
        include_dir = toolchain_path / "data" / "include"
        source = "explicit-toolchain-root"
    else:
        candidates = detect_toolchain_candidates()
        if not candidates:
            raise RuntimeError(
                "Missing toolchain path. Pass -Xc8Exe or -ToolchainRoot, set XC8_EXE / SCMCU_IDE_ROOT, or install SCMCU IDE under a common path such as WorkToolsAndLib/SCMCU_IDE*."
            )
        candidate = candidates[0]
        xc8_path = Path(candidate["xc8_exe"])
        include_dir = Path(candidate["include_dir"])
        source = "autodetect"

    if not xc8_path.exists():
        raise RuntimeError(f"XC8 not found: {xc8_path}")
    if not include_dir.exists():
        raise RuntimeError(f"XC8 include dir not found: {include_dir}")

    return str(xc8_path), str(include_dir), source


def discover_project_file(project_root: Path, project_file: str) -> Path | None:
    if project_file:
        path = Path(project_file)
        if not path.is_absolute():
            path = project_root / path
        path = path.resolve()
    else:
        matches = sorted(project_root.glob("*.scw"))
        if not matches:
            return None
        if len(matches) != 1:
            raise RuntimeError("Multiple .scw files found. Pass -ProjectFile explicitly.")
        path = matches[0].resolve()

    if not path.exists():
        raise RuntimeError(f"Project file not found: {path}")
    return path


def load_emb_agent_project_config(project_root: Path) -> dict[str, object]:
    config_path = project_root / ".emb-agent" / "project.json"
    if not config_path.exists():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"_load_error": str(config_path)}
    if not isinstance(data, dict):
        return {}
    return data


def normalize_chip_substitutes(project_config: dict[str, object]) -> list[dict[str, str]]:
    raw_items = project_config.get("chip_substitutes", []) if isinstance(project_config, dict) else []
    if not isinstance(raw_items, list):
        return []

    normalized: list[dict[str, str]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        target = str(item.get("target", "")).strip()
        substitute = str(
            item.get("substitute", "") or item.get("debug_device", "") or item.get("alias", "")
        ).strip()
        reason = str(item.get("reason", "")).strip()
        if target and substitute:
            normalized.append({"target": target, "substitute": substitute, "reason": reason})
    return normalized


def normalize_source_file(path: str) -> str:
    return path.replace("/", "\\")


def normalize_include_dir(path: str) -> str:
    return path.replace("/", "\\")


def normalize_define(value: str) -> str:
    if value.startswith("-D"):
        return value
    return f"-D{value}"


def dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def read_project_file(project_file: Path) -> dict[str, object]:
    chip = ""
    opt_value = "-local,-asmfile,+asm,-speed,+space,-debug"
    runtime_value = ""
    warning_value = "-9"
    config_value = ""
    sources: list[str] = []
    include_dirs: list[str] = []
    defines: list[str] = []

    for raw_line in project_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("["):
            continue
        if line.startswith("Device="):
            chip = line.split("=", 1)[1].strip()
        elif line.startswith("OptValue="):
            opt_value = line.split("=", 1)[1].strip()
        elif line.startswith("RuntimeValue="):
            runtime_value = line.split("=", 1)[1].strip()
        elif line.startswith("WarningValue="):
            warning_value = line.split("=", 1)[1].strip()
        elif line.startswith("config="):
            config_value = line.split("=", 1)[1].strip()
        elif line.startswith("SourceFile="):
            source = line.split("=", 1)[1].strip()
            if source:
                sources.append(normalize_source_file(source))
        elif line.startswith("IncludeDir="):
            include_dir = line.split("=", 1)[1].strip()
            if include_dir:
                include_dirs.append(normalize_include_dir(include_dir))
        elif line.startswith("Define="):
            define = line.split("=", 1)[1].strip()
            if define:
                defines.append(normalize_define(define))

    if not chip:
        raise RuntimeError(f"Device not found in project file: {project_file}")
    if not sources:
        raise RuntimeError(f"SourceFile list not found in project file: {project_file}")

    return {
        "chip": chip,
        "scw_chip": chip,
        "opt_value": opt_value,
        "runtime_value": runtime_value,
        "warning_value": warning_value,
        "config_value": config_value,
        "sources": sources,
        "include_dirs": include_dirs,
        "defines": defines,
        "image_prefix": project_file.stem,
    }


def merge_project_config(
    args: argparse.Namespace,
    project_root: Path,
    project_file: Path | None,
) -> dict[str, object]:
    emb_project_config = load_emb_agent_project_config(project_root)

    if project_file is not None:
        project = read_project_file(project_file)
    else:
        project = {
            "chip": "",
            "opt_value": "-local,-asmfile,+asm,-speed,+space,-debug",
            "runtime_value": "",
            "warning_value": "-9",
            "config_value": "",
            "sources": [],
            "include_dirs": [],
            "defines": [],
            "scw_chip": "",
            "image_prefix": project_root.name,
        }

    if args.chip:
        project["chip"] = args.chip
    if args.source_files:
        project["sources"] = [normalize_source_file(path) for path in args.source_files]
    if args.append_source_files:
        project["sources"].extend(normalize_source_file(path) for path in args.append_source_files)
    project["sources"] = dedupe_keep_order(project["sources"])
    if args.include_dirs:
        project["include_dirs"].extend(normalize_include_dir(path) for path in args.include_dirs)
    project["include_dirs"] = dedupe_keep_order(project["include_dirs"])
    if args.defines:
        project["defines"].extend(normalize_define(value) for value in args.defines)
    project["defines"] = dedupe_keep_order(project["defines"])
    if args.image_prefix:
        project["image_prefix"] = args.image_prefix

    project["chip_substitutes"] = normalize_chip_substitutes(emb_project_config)
    project["flash_flow"] = str(emb_project_config.get("flash_flow", "")).strip() if isinstance(emb_project_config, dict) else ""

    if not project["chip"]:
        raise RuntimeError("Chip not set. Pass -Chip or provide Device= in the SCMCU project file.")
    if not project["sources"]:
        raise RuntimeError("Source files not set. Pass -SourceFile or provide SourceFile= entries in the SCMCU project file.")

    return project


def build_args(build_name: str, include_dir: str, project: dict[str, object]) -> list[str]:
    image_base = f"{project['image_prefix']}_{build_name}"
    out_prefix = f"build\\xc8\\{build_name}"
    args = [
        f"--outdir={out_prefix}",
        f"--objdir={out_prefix}",
        f"-o{out_prefix}\\{image_base}.cof",
        f"-m{out_prefix}\\{image_base}.map",
        "--summary=default,-psect,-class",
        "--fill=0xFFFF",
        "--output=intel",
    ]
    args.extend(project["sources"])
    args.extend([
        f"--chip={project['chip']}",
        "-P",
        f"--runtime=default,{project['runtime_value']}",
        f"--opt={project['opt_value']}",
        f"-E+{out_prefix}\\cmscerr.err",
        "-D__DEBUG=1",
        *project["defines"],
        "-g",
        "--asmlist",
        f"--warn={project['warning_value']}",
        "--stack=compiled:auto:auto:auto",
        "--addrqual=request",
        "--mode=pro",
        "-I.",
    ])
    for project_include in project["include_dirs"]:
        args.append(f"-I{project_include}")
    args.append(f"-I{include_dir}")
    return args


def normalize_space_key(label: str) -> str:
    return label.lower().replace(" ", "_")


def parse_cmscerr(err_path: Path) -> dict[str, object]:
    space_re = re.compile(
        r"^\s*(.+?)\s+used\s+([0-9A-F]+h)\s+\(\s*([0-9]+)\)\s+of\s+([0-9A-F]+h)\s+([A-Za-z]+)\s+\(\s*([0-9.]+)%\)"
    )
    warnings: list[str] = []
    errors: list[str] = []
    memory: dict[str, object] = {}

    if not err_path.exists():
        return {
            "exists": False,
            "warnings": {"count": 0, "samples": []},
            "errors": {"count": 0, "samples": []},
            "memory": memory,
        }

    for raw_line in err_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.rstrip()
        if "(warning)" in line:
            warnings.append(line)
        if "(error)" in line:
            errors.append(line)
        match = space_re.match(line)
        if match:
            label = match.group(1).strip()
            memory[normalize_space_key(label)] = {
                "label": label,
                "used_hex": match.group(2),
                "used": int(match.group(3)),
                "total_hex": match.group(4),
                "total": int(match.group(4)[:-1], 16),
                "unit": match.group(5),
                "percent": float(match.group(6)),
                "raw": line.strip(),
            }

    return {
        "exists": True,
        "warnings": {"count": len(warnings), "samples": warnings[:8]},
        "errors": {"count": len(errors), "samples": errors[:8]},
        "memory": memory,
    }


def parse_map(map_path: Path) -> dict[str, object]:
    start_re = re.compile(r"^\s*_(?!_)(\w+)\s+(maintext|text\d+)\s+([0-9A-F]+)\s*$")
    end_re = re.compile(r"^\s*__end_of_(\w+)\s+(maintext|text\d+)\s+([0-9A-F]+)\s*$")
    starts: dict[str, tuple[str, int]] = {}
    ends: dict[str, tuple[str, int]] = {}
    functions: list[dict[str, object]] = []

    if not map_path.exists():
        return {"exists": False, "top_functions": []}

    for raw_line in map_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.rstrip()
        start_match = start_re.match(line)
        if start_match:
            starts[start_match.group(1)] = (
                start_match.group(2),
                int(start_match.group(3), 16),
            )
            continue
        end_match = end_re.match(line)
        if end_match:
            ends[end_match.group(1)] = (
                end_match.group(2),
                int(end_match.group(3), 16),
            )

    for name, (psect, start_addr) in starts.items():
        end_info = ends.get(name)
        if end_info is None:
            continue
        end_psect, end_addr = end_info
        if end_psect != psect or end_addr < start_addr:
            continue
        size = end_addr - start_addr
        functions.append(
            {
                "name": name,
                "psect": psect,
                "start_hex": f"{start_addr:X}",
                "end_hex": f"{end_addr:X}",
                "size": size,
                "size_hex": f"{size:X}",
            }
        )

    functions.sort(key=lambda item: int(item["size"]), reverse=True)
    return {"exists": True, "top_functions": functions[:8]}


def parse_hex_config_words(hex_path: Path) -> dict[str, object]:
    """Extract non-0xFFFF config words from Intel HEX output when present.

    SCMCU/PIC14 HEX files encode word address 0x2007 as byte address 0x400E.
    Command-line XC8 builds may omit config words even when `.scw` has config=.
    """
    if not hex_path.exists():
        return {"exists": False, "words": {}}

    extended_linear = 0
    bytes_by_addr: dict[int, int] = {}

    for raw_line in hex_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line.startswith(":") or len(line) < 11:
            continue
        try:
            count = int(line[1:3], 16)
            addr = int(line[3:7], 16)
            rectype = int(line[7:9], 16)
            data = bytes.fromhex(line[9:9 + count * 2])
        except ValueError:
            continue

        if rectype == 0x00:
            base = (extended_linear << 16) + addr
            for offset, value in enumerate(data):
                bytes_by_addr[base + offset] = value
        elif rectype == 0x04 and len(data) == 2:
            extended_linear = (data[0] << 8) | data[1]

    words: dict[str, str] = {}
    for byte_addr in range(0x4000, 0x4020, 2):
        low = bytes_by_addr.get(byte_addr)
        high = bytes_by_addr.get(byte_addr + 1)
        if low is None or high is None:
            continue
        word = low | (high << 8)
        if word != 0xFFFF:
            words[f"{byte_addr // 2:04X}"] = f"{word:04X}"

    return {"exists": True, "words": words}


def parse_scw_config_words(config_value: str) -> list[int]:
    words: list[int] = []
    for raw in str(config_value or "").split(","):
        value = raw.strip()
        if not value:
            continue
        try:
            words.append(int(value, 16))
        except ValueError:
            return []
    return words


def scmcu_toolchain_root_from_xc8(xc8_exe: str) -> Path | None:
    path = Path(xc8_exe)
    # SCMCU IDE layout: <root>/data/bin/xc8.exe
    if len(path.parents) >= 3 and path.parent.name.lower() == "bin" and path.parent.parent.name.lower() == "data":
        return path.parent.parent.parent
    return None


def parse_scmcu_cfg_options(cfg_path: Path) -> dict[str, dict[str, list[tuple[int, int, int]]]]:
    sections: dict[str, dict[str, list[tuple[int, int, int]]]] = {}
    current = ""
    if not cfg_path.exists():
        return sections

    for raw_line in cfg_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        section_match = re.match(r"^\[([^\]]+)\]$", line)
        if section_match:
            current = section_match.group(1).strip()
            sections.setdefault(current, {})
            continue
        if not current or "=" not in line:
            continue
        name, spec_text = line.split("=", 1)
        name = name.strip()
        if name == "DISPMODE":
            continue
        specs: list[tuple[int, int, int]] = []
        for raw_spec in spec_text.split(":"):
            parts = [part.strip() for part in raw_spec.split(",")]
            if len(parts) != 3:
                continue
            try:
                specs.append((int(parts[0]), int(parts[1]), int(parts[2])))
            except ValueError:
                specs = []
                break
        if specs:
            sections.setdefault(current, {})[name] = specs

    return sections


def decode_scmcu_config(config_value: str, project: dict[str, object], xc8_exe: str) -> dict[str, object]:
    words = parse_scw_config_words(config_value)
    decode_chip = str(project.get("scw_chip") or project.get("chip") or "").strip()
    if not config_value:
        return {"available": False, "reason": "no scw config value", "words": []}
    if not words:
        return {"available": False, "reason": "config value is not parseable hex words", "words": []}
    if not decode_chip:
        return {"available": False, "reason": "chip is unknown", "words": [f"{word:04X}" for word in words]}

    toolchain_root = scmcu_toolchain_root_from_xc8(xc8_exe)
    if toolchain_root is None:
        return {
            "available": False,
            "reason": "toolchain root could not be derived from xc8 path",
            "chip": decode_chip,
            "words": [f"{word:04X}" for word in words],
        }

    cfg_path = toolchain_root / "mcu" / "config" / f"{decode_chip}.cfg"
    sections = parse_scmcu_cfg_options(cfg_path)
    if not sections:
        return {
            "available": False,
            "reason": "SCMCU config definition not found or empty",
            "chip": decode_chip,
            "definition_file": str(cfg_path),
            "words": [f"{word:04X}" for word in words],
        }

    settings: dict[str, str] = {}
    unmatched: list[str] = []
    for section, options in sections.items():
        matched_options: list[str] = []
        for option_name, specs in options.items():
            ok = True
            for word_index, bit_index, expected in specs:
                if word_index >= len(words):
                    ok = False
                    break
                bit_value = (words[word_index] >> bit_index) & 1
                if bit_value != expected:
                    ok = False
                    break
            if ok:
                matched_options.append(option_name)
        if len(matched_options) == 1:
            settings[section] = matched_options[0]
        elif len(matched_options) > 1:
            settings[section] = "/".join(matched_options)
        else:
            unmatched.append(section)

    critical_names = ("WDT", "EXT_RESET", "LVR_SEL", "ICSPPORT_SEL")
    return {
        "available": True,
        "chip": decode_chip,
        "definition_file": str(cfg_path),
        "words": [f"{word:04X}" for word in words],
        "settings": settings,
        "critical": {name: settings.get(name, "") for name in critical_names if name in settings},
        "unmatched": unmatched,
    }


def find_project_chip_substitute_reason(project: dict[str, object], scw_chip: str, effective_chip: str) -> str:
    for item in project.get("chip_substitutes", []):
        if not isinstance(item, dict):
            continue
        target = str(item.get("target", "")).strip()
        substitute = str(item.get("substitute", "")).strip()
        reason = str(item.get("reason", "")).strip()
        if {target, substitute} == {scw_chip, effective_chip}:
            return reason or "project-local chip substitute"
    return ""


def summarize_chip_relation(project: dict[str, object]) -> dict[str, object]:
    scw_chip = str(project.get("scw_chip", ""))
    effective_chip = str(project.get("chip", ""))
    same = bool(scw_chip and scw_chip == effective_chip)
    overridden = bool(scw_chip and effective_chip and scw_chip != effective_chip)
    reason = ""
    source = ""
    known_debug_substitute = False

    if overridden:
        reason = find_project_chip_substitute_reason(project, scw_chip, effective_chip)
        if reason:
            source = "project"
        else:
            reason = KNOWN_DEBUG_CHIP_SUBSTITUTES.get(frozenset((scw_chip, effective_chip)), "")
            if reason:
                source = "built-in"
        known_debug_substitute = bool(reason)

    return {
        "scw_chip": scw_chip,
        "effective_chip": effective_chip,
        "same": same,
        "overridden": overridden,
        "known_debug_substitute": known_debug_substitute,
        "source": source,
        "reason": reason,
    }


def build_summary(
    build_name: str,
    project_file: Path | None,
    project: dict[str, object],
    output_dir: Path,
    map_path: Path,
    err_path: Path,
    hex_path: Path,
    toolchain_source: str,
    xc8_exe: str,
    returncode: int,
) -> dict[str, object]:
    cmscerr = parse_cmscerr(err_path)
    map_info = parse_map(map_path)
    hex_config = parse_hex_config_words(hex_path)
    scw_config_decode = decode_scmcu_config(str(project.get("config_value", "")), project, xc8_exe)
    chip_relation = summarize_chip_relation(project)
    warnings_count = int(cmscerr["warnings"]["count"])
    errors_count = int(cmscerr["errors"]["count"])
    success = returncode == 0

    return {
        "build_name": build_name,
        "success": success,
        "returncode": returncode,
        "verification_ok": success and warnings_count == 0 and errors_count == 0,
        "project_file": None if project_file is None else str(project_file),
        "chip": project["chip"],
        "scw_chip": project.get("scw_chip", ""),
        "chip_overridden": chip_relation["overridden"],
        "chip_relation": chip_relation,
        "toolchain_source": toolchain_source,
        "xc8_exe": xc8_exe,
        "image_prefix": project["image_prefix"],
        "source_files": project["sources"],
        "include_dirs": project["include_dirs"],
        "defines": project["defines"],
        "chip_substitutes": project.get("chip_substitutes", []),
        "flash_flow": project.get("flash_flow", ""),
        "scw_config": project.get("config_value", ""),
        "scw_config_decode": scw_config_decode,
        "hex_config": hex_config,
        "config_words_emitted": bool(hex_config.get("words")),
        "output_dir": str(output_dir),
        "map_file": str(map_path),
        "hex_file": str(hex_path),
        "error_log": str(err_path),
        "warnings": cmscerr["warnings"],
        "errors": cmscerr["errors"],
        "memory": cmscerr["memory"],
        "map": map_info,
    }


def write_summary_file(summary_path: Path, summary: dict[str, object]) -> None:
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def print_summary(summary: dict[str, object], summary_path: Path) -> None:
    if summary["project_file"] is None:
        print("Project file: <not used>")
    else:
        print(f"Project file: {summary['project_file']}")
    print(f"Toolchain source: {summary['toolchain_source']}")
    print(f"XC8 exe: {summary['xc8_exe']}")
    chip_relation = summary.get("chip_relation", {})
    if summary.get("scw_chip") and summary.get("chip_overridden"):
        if chip_relation.get("known_debug_substitute"):
            print(
                f"SCW device: {summary['scw_chip']} -> effective chip: {summary['chip']} "
                "(known debug substitute; verify project truth)"
            )
        else:
            print(
                f"SCW device: {summary['scw_chip']} -> effective chip: {summary['chip']} "
                "(override; verify compatibility)"
            )
    else:
        print(f"Chip: {summary['chip']}")
    if summary.get("flash_flow"):
        print(f"Flash flow: {summary['flash_flow']}")
    if summary.get("scw_config"):
        print(f"SCW config: {summary['scw_config']}")
    config_decode = summary.get("scw_config_decode", {})
    critical_config = config_decode.get("critical", {}) if isinstance(config_decode, dict) else {}
    if critical_config:
        rendered_config = ", ".join(f"{name}={value}" for name, value in critical_config.items())
        print(f"SCW config decode: {rendered_config}")
    hex_words = summary.get("hex_config", {}).get("words", {})
    if hex_words:
        rendered_words = ", ".join(f"{addr}={value}" for addr, value in hex_words.items())
        print(f"HEX config words: {rendered_words}")
    elif summary.get("scw_config"):
        print("HEX config words: <not emitted by this command-line build>")
    print(f"Build output: {summary['output_dir']}")
    print(f"Map file: {summary['map_file']}")
    print(f"Error log: {summary['error_log']}")

    program = summary["memory"].get("program_space")
    if program is not None:
        print(
            f"Program space: {program['used']}/{program['total']} {program['unit']} ({program['percent']:.1f}%)"
        )
    data = summary["memory"].get("data_space")
    if data is not None:
        print(
            f"Data space: {data['used']}/{data['total']} {data['unit']} ({data['percent']:.1f}%)"
        )

    print(f"Warnings: {summary['warnings']['count']}")
    print(f"Errors: {summary['errors']['count']}")
    print(f"Verification ok: {summary['verification_ok']}")

    top_functions = summary["map"].get("top_functions", [])
    if top_functions:
        top_line = ", ".join(
            f"{item['name']}={item['size']}"
            for item in top_functions[:5]
        )
        print(f"Top functions: {top_line}")

    for line in summary["errors"]["samples"][:4]:
        print(f"Error sample: {line}")
    for line in summary["warnings"]["samples"][:4]:
        print(f"Warning sample: {line}")

    print(f"Summary JSON: {summary_path}")


def main() -> int:
    args = parse_args()
    if args.list_toolchain_candidates:
        return print_toolchain_candidates()

    project_root = Path(args.project_root).resolve()
    build_name = args.build_name
    project_file = discover_project_file(project_root, args.project_file)
    project = merge_project_config(args, project_root, project_file)
    output_dir = project_root / "build" / "xc8" / build_name
    image_base = f"{project['image_prefix']}_{build_name}"
    map_path = output_dir / (image_base + ".map")
    hex_path = output_dir / (image_base + ".hex")
    err_path = output_dir / "cmscerr.err"
    summary_path = output_dir / "build_summary.json"

    xc8_exe, include_dir, toolchain_source = choose_toolchain(args)
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [xc8_exe]
    cmd.extend(build_args(build_name, include_dir, project))

    returncode = 0
    try:
        subprocess.run(cmd, cwd=str(project_root), check=True)
    except subprocess.CalledProcessError as exc:
        returncode = exc.returncode

    summary = build_summary(
        build_name=build_name,
        project_file=project_file,
        project=project,
        output_dir=output_dir,
        map_path=map_path,
        err_path=err_path,
        hex_path=hex_path,
        toolchain_source=toolchain_source,
        xc8_exe=xc8_exe,
        returncode=returncode,
    )
    write_summary_file(summary_path, summary)
    print_summary(summary, summary_path)
    return returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
