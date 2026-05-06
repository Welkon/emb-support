---
name: embedded-space
title: Embedded Space
summary: ROM-first embedded firmware rules for small MCUs: direct state, thin ISR design, hardware-truth-first execution, and controlled C interface boundaries.
selectable: true
priority: 58
enforcement_scope: code-writing
focus_areas: [rom_budget, direct_state, isr_shared_state, hardware_truth, c_interface_boundaries, board_binding]
extra_review_axes: [map_file_budget, atomic_shared_state, register_truth, interface_cost, state_ownership, hardware_leakage]
---
# Embedded Space

Use this spec when the project needs reusable ROM-first embedded firmware rules for small MCUs and C firmware that may need stable interfaces across hardware variants, repeated device instances, board-specific binding, or driver-like modules.

## Core Stance

- Prioritize correct product behavior first.
- When two solutions are both correct, choose the smaller, shallower, and more direct one.
- Prefer deleting logic over layering more protection code.
- Prefer direct state representation instead of encode/decode or normalize/re-encode chains.
- Start C interface design from data ownership and hardware variation, not class vocabulary.
- Use object-like C patterns only when they reduce duplicate behavior, isolate real variation, or keep application code independent from board wiring.
- Treat every function pointer, wrapper, registration table, and handle indirection as a cost that must buy a real maintenance or ROM win.

## Implementation Rules

- Keep the main loop visually short and flat.
- Prefer `Scan -> Handle -> Output` style control flow.
- Keep ISR work minimal: sample, latch time, set flags, clear the interrupt source, and exit.
- Prefer fixed-width integer logic, direct register writes, and file-local static state when that reduces total cost.
- Do not add helper functions or helper layers by default.
- Keep simple one-use logic inline unless extracting it reduces total cost or removes real duplication.
- Prefer a direct function, `switch`, or small `if` when there is only one implementation or the hot path must stay smaller.
- Do not put long policy logic behind an ops call when a table-driven or direct state update would be smaller and clearer.

## Helper Function Gate

- Helper functions are not the default way to make code look cleaner.
- Add a helper only when it removes repeated logic, isolates a verified hardware operation, shortens a hot path, reduces ROM/RAM, or gives one testable responsibility a clear name.
- Do not add a helper that is only a renamed single call, a pass-through wrapper, or a place to hide temporary variables.
- Do not add a helper if it increases call depth in ISR, scan loops, debounce paths, timing-critical output paths, or tiny MCU hot code without measured benefit.
- Keep approved helpers file-local `static` by default.
- Before keeping a new helper, be able to answer: what state does it own, what invariant does it protect, which duplication does it remove, or what hardware boundary does it isolate?

## Module Split Suggestions

- The agent may suggest module splits, but should not split code automatically just because a file is long.
- Suggest a split when one file contains distinct hardware roles, timing domains, state owners, or product features that can be verified independently.
- Suggest a split when application logic directly touches board pins, chip registers, bus transactions, or concrete driver types that should live behind board/platform or driver boundaries.
- Suggest a split when duplicated code would become one small instance-based module with clear per-instance state.
- Suggest a split when ISR sampling, debounce/filtering, state transitions, and output driving are mixed tightly enough that review or timing analysis is harder.
- Prefer in-file sections over new translation units when the code is tiny, the compiler has weak cross-file optimization, or the proposed split only creates pass-through helpers.
- A split proposal must name the new responsibility boundary, owned state, public API, affected callers, expected ROM/RAM impact, and verification path.
- Reject splits that only mirror abstract architecture names, increase public writable state, create circular includes, or move hardware details into application code.

## ROM Budget Gates

- This spec must stay chip-agnostic. Do not encode MCU-family, chip-model, or absolute flash/RAM-size thresholds here.
- Do not decide abstraction level from chip model, nominal flash size, or intuition. Use `build_summary.json`, `cmscerr.err`, `.map`, or an equivalent size report when available.
- If ROM/RAM usage is unknown, stay in conservative ROM-first mode until a build proves the budget.
- Treat total ROM as a ceiling, not a permission slip. The main gate is measured headroom against the current project budget and required reserve.
- Project-local specs, MCU-family specs, or `req/hw` truth may define absolute reserves or stricter gates. Use those over this generic policy.
- Strict mode: use flat, direct C by default when any required budget is unknown, project reserve is not declared, program ROM is `>= 80%` of its budget, data RAM is `>= 75%` of its budget, or the declared reserve would be crossed.
- Balanced mode: allow thin module boundaries, handles, and small lookup tables when program ROM is `< 70%` of its budget, data RAM is below its warning gate, and declared reserve remains intact. Helper functions still need the helper gate above.
- Interface mode: allow ops tables, base handles, board/platform indirection, and opaque structs when program ROM is `< 60%` of its budget, data RAM is below its warning gate, declared reserve remains intact after expected growth, and the variation is real.
- Relaxed mode is not granted by this generic spec. It requires a project-local or chip-family rule that explicitly states the available headroom, reserve, and acceptable abstraction cost.
- For every new abstraction that changes call shape, dispatch, or module boundaries, compare before/after build size when practical and record the ROM/RAM delta.
- If the abstraction adds `> 2%` program ROM, `> 1%` data RAM, or affects ISR/hot-loop timing, require a concrete product or maintenance reason instead of "cleaner architecture".

## C State And Visibility

- Put per-instance state in a struct and pass a pointer such as `me`, `self`, or a domain handle through the API.
- Move module-shared writable state to file-local `static` variables. Do not expose writable globals through headers.
- Use `static const` for file-local constants when the compiler supports it; prefer it over macro constants when type and scope matter.
- Headers should expose the smallest stable surface: public types, handles, and function declarations only.
- If a helper function passes the helper gate, keep it `static` unless another translation unit has a proven need to call it.
- If a struct layout is private, keep the concrete definition in the `.c` file and expose only an opaque handle.
- If static allocation forces a struct layout into a header, document which fields are private and keep application code from touching them directly.

## Construction And Board Binding

- Every object-like struct needs one init function that fills all required fields before use.
- Pass hardware resources into init functions. Do not bake board pins, channels, bus addresses, or active levels into generic driver logic.
- Board binding belongs in a board or platform init file. That file may know concrete hardware types; application code should not.
- Application code should depend on stable handles and interface functions, not concrete names such as GPIO LED, PWM LED, I2C LED, or a chip-specific register driver.
- For multiple instances, allocate one struct per real device and initialize each with its own resources instead of cloning code.

## Ops Tables And Handles

- Use an ops table only when there are multiple real implementations, a stable interface, or a callback decision that must be delayed.
- When a function takes three or more behavior callbacks, package them into a named `struct <domain>_ops` with clear typedefs for each function pointer type.
- Ops tables should normally be `static const`; object structs should hold a `const struct <domain>_ops *ops`.
- Public wrappers such as `led_on(handle)` should own dispatch. Application code should not call `obj->ops->on()` directly.
- Required ops are contract items: validate them during init or in the wrapper with the project's normal assert/error policy.
- Optional ops are capability items: document the fallback and null-check before dispatch.
- Use a base struct or opaque interface handle when application code must operate on mixed implementations through one API.
- If C-style inheritance is used, the base member should normally be the first member of the derived struct so upcast is mechanically obvious.
- Downcast only inside the implementation that owns the derived type.
- Prefer a `container_of` style helper based on `offsetof` when the compiler and headers support it. Do not hard-code member offsets.
- Do not let application code downcast handles to concrete hardware types.

## Layering

- Keep the normal dependency direction: application -> interface/base -> concrete driver -> platform or board binding -> registers/peripherals.
- The application layer asks for product behavior. It should not know how the hardware produces that behavior.
- The concrete driver may know its own peripheral mechanism, but should call a platform/board API when chip-specific register access must be isolated.
- Platform APIs should be functionally named, such as write pin, read pin, transfer I2C, set PWM, or send UART, not named after one chip's register layout.
- Add a layer only when it turns multiplicative work into additive work, for example N drivers x M chips becoming N drivers + M platform ports.

## Search And Truth Discipline

- Do not guess code behavior from memory. Locate the implementation first.
- Before changing hardware behavior, confirm register boundaries, IO mapping, and package truth.
- For timing or jitter issues, inspect ISR-to-main-loop shared state first.
- For ROM or RAM pressure, inspect the map file or equivalent size report before speculating.
- For interface changes, inspect every caller and implementation before changing a public handle, ops struct, or board binding.

## Registration

- On small bare-metal MCUs, prefer explicit board lists, fixed arrays, or direct init calls unless automatic registration is proven smaller and supported.
- Linker-section auto-registration is allowed only when the compiler attribute, linker script symbols, startup traversal, link order, and map output have all been verified.
- Do not introduce auto-registration just to avoid adding one line to board init.
- If initialization order matters, encode the order explicitly and review it against hardware dependencies.

## Avoid By Default

- Recursive control flow
- Event buses, ownership frameworks, or generic callback dispatch on tiny MCUs unless measured smaller
- `printf` or `sprintf` style formatting in production firmware unless the ROM cost is accepted explicitly
- Round-trip conversion layers from hardware values into semantic models and back again
- Function pointer dispatch when direct calls, `switch`, or fixed tables are smaller and equally clear
- Helper functions that only rename one expression, wrap one call, or make the code look layered
- Public writable globals, public concrete hardware structs, or application-layer downcasts
- Automatic registration without linker script, startup, and map evidence

## Delivery Checks

- Shared ISR state has the right `volatile` and atomicity story.
- Register-backed behavior is tied to real hardware notes.
- Unknown or unverified limits are marked as gaps instead of facts.
- Public C interfaces isolate a real hardware or implementation variation.
- Application code can use the public handle/API without concrete hardware names.
- Per-instance fields are initialized before first use.
- Module internals are hidden with `static` or an opaque layout.
- Required ops are checked and optional ops are safely handled.
- Every function pointer or dispatch layer is justified against ROM, RAM, stack, timing, and readability.
- Every new helper function is justified by duplication removal, hardware isolation, invariant protection, testability, or measured size/timing improvement.
- Board-specific resource binding is confined to board/platform code.
- Any automatic registration is backed by linker/startup evidence and map inspection.
