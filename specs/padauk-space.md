---
name: padauk-space
title: Padauk Space
summary: Padauk or 应广 firmware conventions: Mini-C syntax limits, naming rules, code partition order, and ISR discipline.
selectable: true
priority: 64
---
# Padauk Space

Use this spec for Padauk firmware projects that must obey Mini-C or simplified-C style constraints.

Pair it with `embedded-space` when you also want the generic ROM-first embedded rules.

## File structure

Keep source files ordered like this:

1. IO definitions
2. Constant definitions
3. Variable definitions grouped by function
4. Initialization functions
5. Functional helpers
6. Main program
7. Interrupt handlers

## Mini-C and syntax constraints

- Do not rely on case-sensitive naming. Use explicit, readable English names with underscores.
- Prefer `while`; do not use `for`.
- Do not use the ternary operator.
- Treat `bit` values as `0` or `1` only.
- Use `EQU`, `#DEFINE`, and `#UNDEF` deliberately; do not create opaque macro layers.
- Confirm compiler support before relying on arrays or pointer-heavy patterns.

## Naming and state rules

- Counter variables should end with `_cnt`.
- Flag variables should end with `_flag`.
- Constants should use uppercase with underscores.
- Keep shared state simple and comment each variable with its real hardware role.

## ISR and low-power discipline

- Interrupt handlers must stay short, fast, and reviewable.
- Save and restore context correctly.
- Clear interrupt flags promptly.
- Sleep entry conditions, peripheral shutdown, and wake recovery must be explicit.
- Key scanning, debounce, and action execution should stay separated.

## Hardware-oriented checks

- Verify package-specific pin truth before deriving behavior from pad names.
- Keep timing slices explicit; avoid blocking the main loop.
- Use repeated sampling or debounce for voltage and charge-state decisions.
- Mark unsupported or uncertain compiler features as gaps instead of assuming portability.
