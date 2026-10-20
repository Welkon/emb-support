# XC8 build flow (merged from the former `xc8-build` skill)

The canonical script is `scripts/xc8/build_xc8.py`.

<codex_skill_adapter>
- This skill is invoked by mentioning `$mcu-debug`.
- If the user gives a build name, reuse it.
- If the user asks to compile but gives no build name, choose a short purpose-based name such as `rom-check`, `stage1`, `fix-check`, or `user-test`.
</codex_skill_adapter>

<objective>
Run the repository's tested command-line XC8 build flow.

Use the bundled skill scripts instead of inventing a new compiler command line.
Keep all new command-line artifacts in:

`build/xc8/<build-name>/`
</objective>

<when_to_use>
- User asks to compile, build, or rebuild firmware.
- User asks whether the firmware still compiles after a change.
- User asks for ROM usage, RAM usage, compiler warnings, or map output.
- User asks for a named build output set that can be compared or shared across the team.
</when_to_use>

<files_to_check>
- `references/xc8-build.md`
- `scripts/build_xc8.py`
- `scripts/xc8/toolchain.env.sample`
</files_to_check>

<process>
1. If you need to confirm toolchain path, output layout, or file naming, read `references/xc8-build.md`.

2. The canonical implementation is:

```bash
python3 scripts/xc8/build_xc8.py -BuildName <build-name>
```

The script auto-discovers a single `.scw` file at project root.
If the repository has multiple SCMCU project files, pass one explicitly:

```bash
python3 scripts/xc8/build_xc8.py -BuildName <build-name> -ProjectFile <project-file>.scw
```

If an agent or user needs to override project metadata explicitly, use:

```bash
python3 scripts/xc8/build_xc8.py -BuildName <build-name> -Chip <chip> -IncludeDir <include-dir> -Define <name=value> -SourceFile <file1> -SourceFile <file2>
```

Optional override behavior:

- `-Chip` overrides `Device=...` for command-line verification only
- `-SourceFile` replaces the project-file source list
- `-AppendSourceFile` appends extra files after the project-file source list
- `-IncludeDir` appends project-local include directories
- `-Define` appends C preprocessor defines, with or without the `-D` prefix
- `-ImagePrefix` overrides the default output prefix

SCMCU IDE caution:

- Do not assume a `-Chip` override means the `.scw` device must be changed. Some projects intentionally keep a debug/erasable `.scw` device while command-line verification targets the production-compatible part. `build_summary.json` reports `chip_relation`; project-level `.emb-agent/project.json` `chip_substitutes` entries override built-in known SCMCU debug substitutes such as `SC8P062BD` / `SC8F072`.
- Do not assume the command-line HEX is what the user flashes. If `.emb-agent/project.json` sets `flash_flow: official_ide_only`, report source/project setting changes; use the build output as verification evidence.
- Inspect `build_summary.json` `scw_config`, `scw_config_decode`, `hex_config`, and `config_words_emitted` when WDT, reset-pin mode, LVR, or sleep behavior depends on configuration bits. For SCMCU `.cfg` files that are present under the IDE root, the summary decodes critical fields such as `WDT` and `EXT_RESET`.

3. If working from Windows PowerShell instead, use:

```powershell
py -3 scripts\xc8\build_xc8.py -BuildName <build-name>
```

Toolchain path override order:

- explicit `-Xc8Exe`
- environment variable `XC8_EXE`
- explicit `-ToolchainRoot`
- environment variable `SCMCU_IDE_ROOT`
- automatic probe of common SCMCU IDE install paths

There is no hardcoded machine-local toolchain path in this skill flow.
The user or CI environment must provide one of the overrides above.
If Python is not on `PATH`, call the interpreter with its full path instead of adding a repo-level wrapper.
Project metadata priority is: explicit CLI overrides, then SCMCU project file, then minimal generic defaults for build policy fields only.

If you need to inspect what the script can auto-detect on the current machine, use:

```bash
python3 scripts/xc8/build_xc8.py -ListToolchainCandidates
```

If the user asks for a shell or CI sample, point them to `scripts/xc8/toolchain.env.sample`.

4. After a successful build, inspect:
- `build/xc8/<build-name>/cmscerr.err`
- `build/xc8/<build-name>/<project-stem>_<build-name>.map`
- `build/xc8/<build-name>/build_summary.json`
- configuration-bit fields in `build_summary.json` when sleep/wake/reset behavior is under review

The script clears only the previous command-line `cmscerr.err` / map / HEX for this exact build name before retrying, then treats post-cleanup existence as freshness proof (wall-clock mtime is diagnostic only because WSL filesystems can be skewed). `success` requires zero recognized compiler errors as well as the fresh artifacts, and summary failure produces a non-zero script exit. Read `flash_readiness`: `ide_config_required` means the command-line HEX omitted `.scw` configuration words and must not be presented as the final flash image.

5. Report at least:
- build succeeded or failed
- any compiler errors, or the most relevant warnings
- `Program space`
- `Data space`
- the output directory
- the `cmscerr.err` path
- the `.map` path
- the `build_summary.json` path

6. If the user asks about code size or hot spots, use the `.map` file to extract:
- total program usage
- total data usage
- estimated function sizes for changed modules
The script now emits a parsed summary JSON after each build so an agent can read build status, warning/error counts, memory usage, and top function estimates without reparsing raw files.

7. Do not write new command-line build artifacts to the repository root or to ad-hoc folders such as `output_stage1/`.

8. Do not delete or rewrite the legacy `output/` directory unless the user explicitly asks.

9. If the user asks how to configure the compiler path for their machine, prefer `XC8_EXE` or `SCMCU_IDE_ROOT` over a repo `.env` file. This is machine-local toolchain config, not shared project config.
</process>

<output_expectations>
Default answer shape:

- one short line for build result
- one short line for ROM/RAM summary
- one short line for artifact location

If the build fails, include the key error lines and stop there.
</output_expectations>


---

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

- `scripts/xc8/toolchain.env.sample`

## Script Ownership

Canonical implementation lives in the repo-local skill:

- `scripts/xc8/build_xc8.py`

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
python3 scripts/xc8/build_xc8.py -BuildName stage1
```

List autodetected toolchains:

```bash
python3 scripts/xc8/build_xc8.py -ListToolchainCandidates
```

WSL / Linux with explicit project file:

```bash
python3 scripts/xc8/build_xc8.py -BuildName stage1 -ProjectFile gdss.scw
```

WSL / Linux with explicit chip and source files:

```bash
python3 scripts/xc8/build_xc8.py -BuildName stage1 -Chip SC8F072 -SourceFile src/bt3l.c -SourceFile src/ir.c
```

Windows PowerShell:

```powershell
$env:SCMCU_IDE_ROOT = 'D:\path\to\SCMCU_IDE'
py -3 scripts\xc8\build_xc8.py -BuildName stage1
```

Windows PowerShell with direct compiler path:

```powershell
$env:XC8_EXE = 'D:\path\to\xc8.exe'
py -3 scripts\xc8\build_xc8.py -BuildName stage1
```

Windows PowerShell with explicit Python path:

```powershell
$env:XC8_EXE = 'D:\path\to\xc8.exe'
& 'C:\path\to\python.exe' scripts\xc8\build_xc8.py -BuildName stage1
```

WSL / Linux with direct compiler path:

```bash
export XC8_EXE=/mnt/d/path/to/xc8.exe
python3 scripts/xc8/build_xc8.py -BuildName stage1
```

WSL / Linux with IDE root:

```bash
export SCMCU_IDE_ROOT=/mnt/d/path/to/SCMCU_IDE
python3 scripts/xc8/build_xc8.py -BuildName stage1
```

Explicit parameter override:

```powershell
py -3 scripts\xc8\build_xc8.py -BuildName stage1 -ToolchainRoot 'D:\path\to\SCMCU_IDE'
```

```powershell
py -3 scripts\xc8\build_xc8.py -BuildName stage1 -Xc8Exe 'D:\path\to\xc8.exe'
```

Codex skill:

```text
$mcu-debug
```

Direct skill script entrypoint:

```bash
python3 scripts/xc8/build_xc8.py -BuildName stage1
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

- `build_summary.json`: parsed build result, warning/error counts, ROM/RAM summary, top function estimates, `.scw` config string, decoded SCMCU config settings when available, project flash flow, chip substitute relation, config words emitted into the command-line HEX, execution diagnostics, and fresh-artifact status
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
- If you update the build flow, edit `scripts/xc8/build_xc8.py`.
- If you need to change chip, source files, include paths, defines, or output prefix, update the SCMCU project file instead of editing the Python script.
- If an agent needs a temporary or synthetic build that does not belong in the SCMCU project file, pass `-Chip`, `-SourceFile`, `-AppendSourceFile`, `-IncludeDir`, `-Define`, or `-ImagePrefix` on the command line.
- After each build, the script parses `cmscerr.err`, `.map`, and HEX config records when present, then writes `build_summary.json`.
- The build summary also records which toolchain path was used and whether it came from explicit config or autodetect.
- Device substitutions are not automatically errors. Some SCMCU projects intentionally use an erasable/debug-compatible `.scw` device while command-line verification targets the OTP production-compatible chip; record that as project-local truth. The summary reports `chip_relation`; project-level `.emb-agent/project.json` `chip_substitutes` entries are preferred, and the built-in `SC8P062BD` / `SC8F072` pair is flagged for review instead of treated as an automatic mismatch.
- Projects can set `.emb-agent/project.json` `flash_flow` to `official_ide_only` when the user burns from SCMCU IDE; command-line HEX should then be treated as verification evidence, not the recommended flash artifact.
- Configuration-bit verification is separate from C compilation. If `scw_config` is non-empty but `config_words_emitted` is false, command-line output did not emit config words; use the official IDE/programmer settings as the configuration source of truth. When the SCMCU IDE `.cfg` definition exists, `scw_config_decode.critical` reports fields such as `WDT=DISABLE` and `EXT_RESET=DISABLE` directly.
- `success` requires a zero compiler return code, zero recognized compiler errors (including `Error[141]`/fatal spellings), and an error log, map, and HEX that exist after the mandatory per-build cleanup. `verification_ok` additionally requires no warnings. `flash_readiness` stays `ide_config_required` whenever required configuration words were omitted, even when C compilation succeeded. A failed summary returns a non-zero process exit code even if the vendor compiler incorrectly returned zero.
- The current function-size data is estimated from symbol start/end addresses in the map file. Treat it as a useful heuristic, not an exact linker-reported size table.
- For team reuse, prefer machine-level, shell-level, or CI-level environment variables instead of a repo `.env` file. This is host-specific toolchain configuration, not project data.
- If users only know the IDE install root, use `SCMCU_IDE_ROOT`.
- If users only know the compiler executable path, use `XC8_EXE`.
- If Python is not on `PATH`, call the interpreter with its full path.
