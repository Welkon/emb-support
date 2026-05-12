---
name: embedded-space
title: Embedded Space
summary: Generic MCU firmware rules: hardware truth, explicit ownership, bounded timing, thin ISR design, safe state, and measured verification.
selectable: true
priority: 58
enforcement_scope: code-writing
focus_areas: [hardware_truth, state_ownership, isr_shared_state, time_base, c_interface_boundaries, board_binding, verification]
extra_review_axes: [register_truth, atomic_shared_state, timebase_jitter, state_ownership, hardware_leakage, integration_boundaries]
---
# Embedded Space

Use this spec for vendor-neutral MCU firmware. It defines general embedded rules that apply across 8-bit, 16-bit, and 32-bit MCU projects.

Pair it with vendor, chip-family, or project-local specs for compiler dialects, IDE behavior, memory budgets, package pinout, peripheral formulas, and board-specific constraints.

## Scope And Layering

- Keep this spec vendor-neutral and MCU-family-neutral.
- Do not add compiler dialect, IDE project-file, SFR header, absolute-address syntax, package pinout, memory-size threshold, vendor library, or chip-specific peripheral rules here.
- Put vendor/toolchain rules in selectable vendor specs such as `scmcu-space` or `padauk-space`.
- Put concrete chip/package/board facts in project truth (`hw.yaml`, `req.yaml`) or project-local specs.
- When multiple specs apply, use this order: hardware truth and measured behavior first, then project-local/chip/vendor specs, then this generic embedded-space guidance.

## Core Stance

- Prioritize correct product behavior and hardware safety before code shape.
- Start design from real hardware ownership, timing, and failure modes, not abstract architecture vocabulary.
- Prefer simple, reviewable control flow when it satisfies the product requirement.
- Add abstraction only when it isolates real hardware variation, removes real duplication, protects a clear invariant, or improves verification.
- Treat register writes, power-state transitions, sleep entry, wake recovery, and output enable paths as safety-relevant operations.

## Hardware Truth And Ownership

- Confirm the exact MCU, package, board net, active level, and peripheral mux before changing hardware behavior.
- One module should own each physical output, peripheral, and shared hardware resource at a time.
- Application logic should consume semantic state and call hardware/platform APIs; it should not scatter board pin or register decisions across unrelated modules.
- Board/platform code may know concrete pins, channels, and registers. Generic application modules should not.
- Before enabling an output or changing a mux, define the reset/default state, fault state, and owner for every affected pin.

## Time Base And Main Loop

- Use an explicit time base for debounce, filtering, display refresh, control loops, timeouts, and watchdog policy.
- Keep periodic work bounded. Each slice should have a stated cadence, owner, and worst-case expectation.
- Avoid blocking waits in the main loop unless the product timing and watchdog policy explicitly allow them.
- When multiple cadences are derived from one tick, keep dividers/counters direct and reviewable.
- Before relying on a time base, verify clock source, prescaler/reload settings, interrupt cadence, jitter tolerance, and sleep/wake interaction.

## ISR And Shared State

- Keep ISR work minimal: identify the source, clear/latch the interrupt condition, update the minimum shared state, and return.
- Do not put debounce policy, long ADC conversions, display policy, control state machines, blocking waits, logging, or watchdog feeding in an ISR unless a project-specific rule explicitly justifies it.
- Mark ISR-shared variables with the project's required volatile/atomic mechanism.
- Protect multi-byte or non-atomic shared state when it is accessed from both ISR and main context.
- Define what happens when interrupts are disabled, missed, nested, or delayed.

## State, Faults, And Outputs

- Model unknown, fault, startup, and safe/off states explicitly.
- Unknown or invalid inputs should not silently map to an active output state.
- Output enable decisions should be centralized enough that safety review can find every path that can turn hardware on.
- On startup, before sleep, after wake, and on fault, drive or release pins into documented safe states.
- Separate input sampling/filtering from product action decisions when that improves reviewability.

## C Interfaces And Module Boundaries

- Headers should expose the smallest stable surface: public types, handles, constants, and function declarations needed by callers.
- Keep writable module state private where practical.
- A module split should reflect real ownership: hardware resource, timing domain, state owner, protocol boundary, or independently verified behavior.
- Do not split code only because a file is long, and do not merge distinct hardware owners only to reduce file count.
- If using handles, callbacks, ops tables, or registration, document the real variation they represent and how failures/null operations are handled.
- Application code should not call through internal dispatch fields directly; public wrappers own validation and dispatch.

## Verification Discipline

- Verify with the toolchain, IDE, or build flow that will be used for the target artifact.
- Inspect compiler warnings, memory/resource usage, map/listing output where available, and generated artifacts relevant to startup and interrupts.
- For timing-sensitive work, verify tick cadence, ISR latency, sleep/wake recovery, and worst-case main-loop execution.
- For hardware outputs, verify reset behavior, enable/disable transitions, fault injection, and no unintended pulses.
- Record bench gaps and assumptions close to the task or project truth, not only in conversation.

## Avoid Without Project-Specific Justification

- Hidden ownership of pins or peripherals.
- Unbounded blocking in main-loop firmware.
- ISR paths that perform product policy or long work.
- Enabling outputs from unknown, invalid, or partially initialized state.
- Hardware behavior inferred from chip family name instead of package/board truth.
- Toolchain-specific syntax or memory-placement rules in generic modules.
