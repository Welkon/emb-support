---
name: embedded-space
title: Embedded Space
summary: ROM-first embedded firmware rules for small MCUs: direct state, thin ISR design, and hardware-truth-first execution.
selectable: true
priority: 58
---
# Embedded Space

Use this spec when the project needs a reusable ROM-first embedded firmware rules pack for small MCUs.

## Core stance

- Prioritize correct product behavior first.
- When two solutions are both correct, choose the smaller, shallower, and more direct one.
- Prefer deleting logic over layering more protection code.
- Prefer direct state representation instead of encode/decode or normalize/re-encode chains.

## Implementation rules

- Keep the main loop visually short and flat.
- Prefer `Scan -> Handle -> Output` style control flow.
- Keep ISR work minimal: sample, latch time, set flags, clear the interrupt source, and exit.
- Prefer fixed-width integer logic, direct register writes, and file-local static state when that reduces total cost.
- Do not add helper layers unless they produce a clear ROM or maintenance win.

## Search and truth discipline

- Do not guess code behavior from memory. Locate the implementation first.
- Before changing hardware behavior, confirm register boundaries, IO mapping, and package truth.
- For timing or jitter issues, inspect ISR-to-main-loop shared state first.
- For ROM or RAM pressure, inspect the map file or equivalent size report before speculating.

## Avoid by default

- Recursive control flow
- Event buses, ownership frameworks, or generic callback dispatch on tiny MCUs unless measured smaller
- `printf` or `sprintf` style formatting in production firmware unless the ROM cost is accepted explicitly
- Round-trip conversion layers from hardware values into semantic models and back again

## Delivery checks

- Shared ISR state has the right `volatile` and atomicity story
- Register-backed behavior is tied to real hardware notes
- Unknown or unverified limits are marked as gaps instead of facts
