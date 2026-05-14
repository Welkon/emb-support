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

- Treat `.scw` as the source of device and source-file metadata when the project uses SCMCU IDE, but do not assume the `.scw` device string is always the production package. Some SCMCU projects deliberately use an erasable/debug-compatible device (for example an `SC8F` part) while source and review target an `SC8P` OTP part. Record such substitutions as project-local hardware truth instead of flagging them as automatic blockers. Known board-truth example: `SC8P062BD` production-target reviews may intentionally use `SC8F072` as a repeatedly erasable/debug substitute.
- `.scw` `HeadFile=` entries are IDE browsing metadata. They are not sufficient proof that the compiler receives an include path.
- If a project must compile both from SCMCU IDE and command-line tooling, either prove the IDE passes the include directory or include project headers from source files with a path that is valid relative to the source, for example `../include/foo.h`.
- Keep the `.scw` source list aligned with the real target source set. Remove generated/template `main.c` files from the IDE project instead of adding compatibility code for them.
- Build outputs from SCMCU IDE often go to `output/`; command-line verification should keep its own artifacts under a project-specific build directory such as `build/xc8/<build-name>/`.
- Ask how the user flashes the board. If they burn from the official SCMCU IDE, command-line build artifacts are verification evidence only; report source/project settings to change rather than asking them to flash a generated HEX.

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
- For PORT change wake from sleep, the ISR may be the official-example minimal wake latch: check `RBIF && RBIE`, read `PORTB` to end mismatch, clear `RBIF`, then return. Product debounce and wake policy still belong in the main loop.
- Prefer shallow `if`/`else` and small `switch` statements with explicit `break`; document any intentional fall-through at the case site.
- Avoid `goto` in product firmware except for a tightly local cleanup/error path that is smaller and clearer on the map.
- `for(;;)` and `while(1)` are both valid infinite loops. Pick one project style and keep it consistent.

## Sleep and low-power bring-up

- Start low-power work by searching the vendor examples shipped with the SCMCU IDE. For SCMCU parts, the validated path may use `asm("sleep")` even when the manual chapter describes STOP/sleep behavior generically.
- Prefer the official PORTB wake sequence unless project-local evidence proves otherwise: configure `IOCB` for only the wake pins, enable `RBIE`, set `GIE` according to the example path, read `PORTB` to latch the baseline, clear/feed WDT, execute `asm("sleep")`, then restore peripherals after wake.
- Keep wake pins minimal. Inputs that are not true wake sources should not be left floating or weak-pulled during sleep just because they are sampled while running.
- Distinguish runtime blanking from sleep-current GPIO. Charlieplex/display nets may need high-Z while running to avoid ghosting, but sleep may require non-wake pins fixed to deterministic outputs to avoid floating-input current.
- Confirm CONFIG bits before trusting software sleep: if CONFIG forces WDT on, `SWDTEN=0` cannot prevent periodic wake; if external reset is enabled, reset-capable pins may not work as normal key inputs.
- Measure whole-board current against the hardware bill of materials. Charger IC standby current, dividers, pull-ups, and protection parts can dominate MCU sleep current; set the acceptance target from board truth, not only MCU datasheet sleep current.

## Verification discipline

- After each firmware slice, build with the same SCMCU/XC8 toolchain used by the project and inspect `cmscerr.err`, the map file, ROM/RAM percentages, warning count, and top functions.
- Treat warnings as budget and correctness signals, not noise. SCMCU/XC8 warnings around SFR boolean conversions, narrowing, unused functions, or unreachable branches should be resolved or documented.
- Review configuration-bit evidence separately from C compile success. A command-line build can succeed while the official IDE/project configuration used for burning still controls WDT, reset-pin mode, LVR, or debug-device substitution.
- When ROM/RAM pressure appears, inspect the map/listing/call graph before refactoring. Recheck table-vs-logic and helper-vs-inline choices with measured output.
- If a SCMCU C guide rule conflicts with project hardware truth or measured compiler output, keep hardware truth and measured output authoritative, then record the exception in the project-local spec.
