# Build Notes

## Goal

Keep command-line compiler artifacts out of the repository root.

The recommended layout for manual and agent-triggered XC8 builds is:

```text
build/xc8/<build-name>/
```

Examples:

- `build/xc8/stage1/`
- `build/xc8/probe/`
- `build/xc8/rom-check/`

The legacy `output/` directory is the SCMCU IDE path.
For command-line work, do not write new artifacts to the repository root or to ad-hoc folders such as `output_stage1/`.

## Toolchain

This repository has been validated with the SCMCU-packaged XC8 toolchain.
The Python script reads the actual device and source list from the SCMCU project file instead of hardcoding them.

Toolchain path override priority:

1. explicit script parameter `-Xc8Exe`
2. environment variable `XC8_EXE`
3. explicit script parameter `-ToolchainRoot`
4. environment variable `SCMCU_IDE_ROOT`
5. automatic probe of common SCMCU IDE install roots

There is no built-in machine path anymore.
Each user or CI environment must provide one of the overrides above.

Common autodetect search patterns:

- `SCMCU_IDE*`
- `WorkToolsAndLib/SCMCU_IDE*`
- `Tools/SCMCU_IDE*`
- `Program Files/SCMCU_IDE*`
- `Program Files (x86)/SCMCU_IDE*`

Reference-only env sample:

- `.codex/skills/xc8-build/references/toolchain.env.sample`

## Script Ownership

Canonical implementation lives in the repo-local skill:

- `.codex/skills/xc8-build/scripts/build_xc8.py`

The script reads project metadata from a SCMCU `.scw` file:

- `Device=...`
- `SourceFile=...`
- `IncludeDir=...`
- `Define=...`
- `OptValue=...`
- `RuntimeValue=...`
- `WarningValue=...`
- `config=...`

If the repo root contains exactly one `.scw` file, it is discovered automatically.
If there are multiple `.scw` files, pass `-ProjectFile`.

Agent or user overrides are also supported:

- `-Chip` overrides `Device=...` for command-line verification
- `-SourceFile` replaces the project-file source list
- `-AppendSourceFile` appends extra source files
- `-IncludeDir` appends project-local include directories
- `-Define` appends C preprocessor defines
- `-ImagePrefix` overrides the default output prefix

Project metadata priority:

1. explicit CLI overrides
2. SCMCU project file
3. generic script defaults for `OptValue` / `RuntimeValue` / `WarningValue`

## Recommended Entry Points

WSL / Linux:

```bash
python3 .codex/skills/xc8-build/scripts/build_xc8.py -BuildName stage1
```

List autodetected toolchains:

```bash
python3 .codex/skills/xc8-build/scripts/build_xc8.py -ListToolchainCandidates
```

WSL / Linux with explicit project file:

```bash
python3 .codex/skills/xc8-build/scripts/build_xc8.py -BuildName stage1 -ProjectFile gdss.scw
```

WSL / Linux with explicit chip and source files:

```bash
python3 .codex/skills/xc8-build/scripts/build_xc8.py -BuildName stage1 -Chip SC8F072 -SourceFile src/bt3l.c -SourceFile src/ir.c
```

Windows PowerShell:

```powershell
$env:SCMCU_IDE_ROOT = 'D:\path\to\SCMCU_IDE'
py -3 .\.codex\skills\xc8-build\scripts\build_xc8.py -BuildName stage1
```

Windows PowerShell with direct compiler path:

```powershell
$env:XC8_EXE = 'D:\path\to\xc8.exe'
py -3 .\.codex\skills\xc8-build\scripts\build_xc8.py -BuildName stage1
```

Windows PowerShell with explicit Python path:

```powershell
$env:XC8_EXE = 'D:\path\to\xc8.exe'
& 'C:\path\to\python.exe' .\.codex\skills\xc8-build\scripts\build_xc8.py -BuildName stage1
```

WSL / Linux with direct compiler path:

```bash
export XC8_EXE=/mnt/d/path/to/xc8.exe
python3 .codex/skills/xc8-build/scripts/build_xc8.py -BuildName stage1
```

WSL / Linux with IDE root:

```bash
export SCMCU_IDE_ROOT=/mnt/d/path/to/SCMCU_IDE
python3 .codex/skills/xc8-build/scripts/build_xc8.py -BuildName stage1
```

Explicit parameter override:

```powershell
py -3 .\.codex\skills\xc8-build\scripts\build_xc8.py -BuildName stage1 -ToolchainRoot 'D:\path\to\SCMCU_IDE'
```

```powershell
py -3 .\.codex\skills\xc8-build\scripts\build_xc8.py -BuildName stage1 -Xc8Exe 'D:\path\to\xc8.exe'
```

Codex skill:

```text
$xc8-build
```

Direct skill script entrypoint:

```bash
python3 .codex/skills/xc8-build/scripts/build_xc8.py -BuildName stage1
```

## Output Files

Each build directory contains the full compiler output set, for example:

- `cmscerr.err`
- `build_summary.json`
- `<project-stem>_<build-name>.map`
- `<project-stem>_<build-name>.hex`
- `<project-stem>_<build-name>.lst`
- `<project-stem>_<build-name>.obj`
- `<project-stem>_<build-name>.sym`
- `*.p1`
- `*.pre`
- `*.d`
- `startup.*`

Primary files to inspect after a build:

- `build_summary.json`: parsed build result, warning/error counts, ROM/RAM summary, top function estimates, `.scw` config string, and config words emitted into the command-line HEX when present
- `cmscerr.err`: warnings, errors, memory summary
- `<project-stem>_<build-name>.map`: section placement, symbol table, estimated function sizes
- `<project-stem>_<build-name>.hex`: useful for CI/build artifacts, but not necessarily the image a user flashes when their workflow is official SCMCU IDE burning

## Invocation Shape

The Python script builds an XC8 command with this structure:

```text
xc8.exe
  --outdir=build\xc8\<build-name>
  --objdir=build\xc8\<build-name>
  -obuild\xc8\<build-name>\<project-stem>_<build-name>.cof
  -mbuild\xc8\<build-name>\<project-stem>_<build-name>.map
  --summary=default,-psect,-class
  --fill=0xFFFF
  --output=intel
  <source files from project file>
  --chip=<device from project file>
  -P
  --runtime=default,<RuntimeValue from project file>
  --opt=<OptValue from project file>
  -E+build\xc8\<build-name>\cmscerr.err
  -D__DEBUG=1
  -g
  --asmlist
  --warn=<WarningValue from project file>
  --stack=compiled:auto:auto:auto
  --addrqual=request
  --mode=pro
  -I.
  -I<toolchain-data-dir>\include
```

## Notes

- `compile_flags.txt` is useful for editor tooling and ad-hoc syntax checks, but it is not a complete firmware build command.
- If you need to compare ROM usage across experiments, use a new `-BuildName` each time so the output directories stay isolated.
- If you want to rebuild the same experiment, rerun the same `-BuildName`. The script will reuse that directory.
- If you update the build flow, edit `scripts/build_xc8.py`.
- If you need to change chip, source files, include paths, defines, or output prefix, update the SCMCU project file instead of editing the Python script.
- If an agent needs a temporary or synthetic build that does not belong in the SCMCU project file, pass `-Chip`, `-SourceFile`, `-AppendSourceFile`, `-IncludeDir`, `-Define`, or `-ImagePrefix` on the command line.
- After each build, the script parses `cmscerr.err`, `.map`, and HEX config records when present, then writes `build_summary.json`.
- The build summary also records which toolchain path was used and whether it came from explicit config or autodetect.
- Device substitutions are not automatically errors. Some SCMCU projects intentionally use an erasable/debug-compatible `.scw` device while command-line verification targets the OTP production-compatible chip; record that as project-local truth. The summary reports `chip_relation`; the known SCMCU debug substitute pair `SC8P062BD` / `SC8F072` is flagged for review instead of treated as an automatic mismatch.
- Configuration-bit verification is separate from C compilation. If `scw_config` is non-empty but `config_words_emitted` is false, command-line output did not emit config words; use the official IDE/programmer settings as the configuration source of truth.
- The current function-size data is estimated from symbol start/end addresses in the map file. Treat it as a useful heuristic, not an exact linker-reported size table.
- For team reuse, prefer machine-level, shell-level, or CI-level environment variables instead of a repo `.env` file. This is host-specific toolchain configuration, not project data.
- If users only know the IDE install root, use `SCMCU_IDE_ROOT`.
- If users only know the compiler executable path, use `XC8_EXE`.
- If Python is not on `PATH`, call the interpreter with its full path.
