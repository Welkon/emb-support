---
name: scmcu-space
title: SCMCU Space
summary: SCMCU firmware conventions for SCMCU IDE/XC8 projects: .scw build behavior, device-header selection, SCMCU C types/extensions, ISR discipline, and map-driven ROM/RAM review.
selectable: true
priority: 62
enforcement_scope: code-writing
focus_areas: [scmcu_ide, scw_project, device_header, sfr_volatile, scmcu_c_types, rom_budget, thin_isr]
extra_review_axes: [scw_include_paths, device_header_selection, sfr_aliasing, bit_bank_persistent_usage, library_rom_cost, cmscerr_map_review]
---
# SCMCU Space

Use this spec for SCMCU firmware projects built with SCMCU IDE / SCMCU-packaged XC8 and `.scw` project files.

Pair it with `embedded-space` for generic ROM-first embedded rules.

## IDE and `.scw` project behavior

- Treat `.scw` as the source of device and source-file metadata when the project uses SCMCU IDE.
- `.scw` `HeadFile=` entries are IDE browsing metadata. They are not sufficient proof that the compiler receives an include path.
- If a project must compile both from SCMCU IDE and command-line tooling, either prove the IDE passes the include directory or include project headers from source files with a path that is valid relative to the source, for example `../include/foo.h`.
- Keep the `.scw` source list aligned with the real target source set. Remove generated/template `main.c` files from the IDE project instead of adding compatibility code for them.
- Build outputs from SCMCU IDE often go to `output/`; command-line verification should keep its own artifacts under a project-specific build directory such as `build/xc8/<build-name>/`.

## Device headers and SFR ownership

- Centralize device-header selection in one project hardware header. Do not include IDE template headers directly in every product source.
- Use `<xc.h>` when the installed SCMCU/XC8 toolchain provides it and it selects the correct device. Otherwise fall back to the confirmed part header such as `<SC8P062BD.h>`.
- Treat official device headers as SFR truth. Project code should reference SFRs through project hardware aliases or tightly scoped hardware helpers, not scattered raw register names.
- If command-line defines are required by the build script but the official IDE does not pass them, provide safe target defaults in the project hardware header only for board facts already confirmed by hardware truth. Keep compile-time guards for conflicting values.
- Keep device-specific assumptions out of generic application modules. Board/chip register access belongs in the hardware/platform layer.

## SCMCU C types and arithmetic

- Prefer `<stdint.h>` fixed-width integer types in application code so ROM/RAM behavior is explicit across SCMCU C quirks.
- Remember the SCMCU C small-MCU type model from the guide: `bit` is one bit, `char` is 8-bit, `short`/`int` are 16-bit, `long` is 32-bit, and `float`/`double` are non-cheap implementation types.
- Do not use `float`/`double` on tight OTP firmware unless a task explicitly budgets and verifies the ROM/RAM cost.
- Keep voltage, percent, PWM, and timing math fixed-point/integer. Use bounded down-casts after range checks or fixed divisors, and verify compiler warnings in `cmscerr.err`.
- Treat endianness and object layout as compiler-specific. Do not encode product protocols by assuming a C struct/union layout unless the ABI and map/listing are part of the contract.

## `bit`, absolute address, bank, and persistent extensions

- Use native `bit` variables and absolute bit bindings only for SFR bits or a measured ROM/RAM win. Prefer byte masks for application state when warning behavior or review clarity is better.
- Use absolute `@` address bindings only for device/SFR declarations that mirror the official header, or for a documented hardware/debug reason. Do not hand-place normal application variables without map evidence.
- Use `bank1`/`bank2`/`bank3` placement only to solve a measured bank/RAM problem. Default application variables should remain compiler-placed.
- Use `persistent` only for deliberate reset-surviving state with a documented startup policy. Do not use it for ordinary runtime state.
- When using `extern`, keep exactly one definition and put only declarations in headers. Avoid public writable globals unless a hardware boundary requires them.

## `const`, tables, pointers, and libraries

- `const` data consumes program space. Keep lookup tables only when the map proves the table is smaller, safer, or clearer than direct logic.
- Be cautious with RAM and ROM pointers. Avoid generic pointer-heavy APIs on small SCMCU OTP targets unless they measurably reduce code size or isolate real hardware variation.
- Avoid `printf`/`sprintf`, `scanf`, `math.h`, broad `string.h` helpers, and other library-heavy paths unless the task explicitly budgets and verifies the ROM cost.
- Prefer direct state, direct calls, and shallow control flow over callback registries, task tables, and function-pointer dispatch on ROM-constrained parts.

## Functions, `main`, ISR, and control flow

- Keep function prototypes visible before use.
- Keep `main` no-argument/no-return style for SCMCU C firmware.
- Keep ISR code thin: one interrupt entry, check enable + flag, clear the flag, update only minimal `volatile` shared state, and return.
- Do not perform debounce, ADC policy, display scan policy, state-machine decisions, blocking waits, or watchdog feeding inside the ISR.
- Prefer shallow `if`/`else` and small `switch` statements with explicit `break`; document any intentional fall-through at the case site.
- Avoid `goto` in product firmware except for a tightly local cleanup/error path that is smaller and clearer on the map.
- `for(;;)` and `while(1)` are both valid infinite loops. Pick one project style and keep it consistent.

## Verification discipline

- After each firmware slice, build with the same SCMCU/XC8 toolchain used by the project and inspect `cmscerr.err`, the map file, ROM/RAM percentages, warning count, and top functions.
- Treat warnings as budget and correctness signals, not noise. SCMCU/XC8 warnings around SFR boolean conversions, narrowing, unused functions, or unreachable branches should be resolved or documented.
- When ROM/RAM pressure appears, inspect the map/listing/call graph before refactoring. Recheck table-vs-logic and helper-vs-inline choices with measured output.
- If a SCMCU C guide rule conflicts with project hardware truth or measured compiler output, keep hardware truth and measured output authoritative, then record the exception in the project-local spec.
