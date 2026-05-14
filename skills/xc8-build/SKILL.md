---
name: "xc8-build"
description: "Build firmware with the repo-local Python XC8 build script. The script stays generic by defaulting to SCMCU project-file metadata, while still allowing explicit overrides for chip, source files, and image prefix when an agent or user needs to drive a custom build. Keep artifacts under build/xc8/<build-name>/ and inspect cmscerr.err plus map output for ROM/RAM usage, warnings, and function sizes. Use when the user asks to compile, rebuild, verify code size, inspect map output, or produce a named firmware build."
metadata:
  short-description: "Build firmware and inspect ROM/RAM/map output"
---

<codex_skill_adapter>
- This skill is invoked by mentioning `$xc8-build`.
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
- `BUILD.md`
- `scripts/build_xc8.py`
- `references/toolchain.env.sample`
</files_to_check>

<process>
1. If you need to confirm toolchain path, output layout, or file naming, read `BUILD.md`.

2. The canonical implementation is:

```bash
python3 .codex/skills/xc8-build/scripts/build_xc8.py -BuildName <build-name>
```

The script auto-discovers a single `.scw` file at project root.
If the repository has multiple SCMCU project files, pass one explicitly:

```bash
python3 .codex/skills/xc8-build/scripts/build_xc8.py -BuildName <build-name> -ProjectFile <project-file>.scw
```

If an agent or user needs to override project metadata explicitly, use:

```bash
python3 .codex/skills/xc8-build/scripts/build_xc8.py -BuildName <build-name> -Chip <chip> -IncludeDir <include-dir> -Define <name=value> -SourceFile <file1> -SourceFile <file2>
```

Optional override behavior:

- `-Chip` overrides `Device=...` for command-line verification only
- `-SourceFile` replaces the project-file source list
- `-AppendSourceFile` appends extra files after the project-file source list
- `-IncludeDir` appends project-local include directories
- `-Define` appends C preprocessor defines, with or without the `-D` prefix
- `-ImagePrefix` overrides the default output prefix

SCMCU IDE caution:

- Do not assume a `-Chip` override means the `.scw` device must be changed. Some projects intentionally keep a debug/erasable `.scw` device while command-line verification targets the production-compatible part. `build_summary.json` reports `chip_relation`; known SCMCU debug substitutes include `SC8P062BD` / `SC8F072` when the project has recorded that board truth.
- Do not assume the command-line HEX is what the user flashes. If the user burns from SCMCU IDE, report source and project setting changes; use the build output as verification evidence.
- Inspect `build_summary.json` `scw_config`, `hex_config`, and `config_words_emitted` when WDT, reset-pin mode, LVR, or sleep behavior depends on configuration bits.

3. If working from Windows PowerShell instead, use:

```powershell
py -3 .\.codex\skills\xc8-build\scripts\build_xc8.py -BuildName <build-name>
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
python3 .codex/skills/xc8-build/scripts/build_xc8.py -ListToolchainCandidates
```

If the user asks for a shell or CI sample, point them to `references/toolchain.env.sample`.

4. After a successful build, inspect:
- `build/xc8/<build-name>/cmscerr.err`
- `build/xc8/<build-name>/<project-stem>_<build-name>.map`
- `build/xc8/<build-name>/build_summary.json`
- configuration-bit fields in `build_summary.json` when sleep/wake/reset behavior is under review

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
