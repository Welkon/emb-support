---
name: low-rom-space
title: Low ROM Space
summary: ROM/RAM-constrained MCU firmware rules: direct state, bounded slicing, helper gates, map-driven abstraction, and resource-budget review.
selectable: true
priority: 60
enforcement_scope: code-writing
focus_areas: [rom_budget, ram_budget, direct_state, time_base_slicing, helper_gate, abstraction_cost, map_file_review]
extra_review_axes: [map_file_budget, helper_cost, dispatch_cost, table_cost, stack_cost, registration_cost, resource_headroom]
---
# Low ROM Space

Use this spec when an MCU project has tight or unknown ROM/RAM headroom and feature code must be justified against measured build output.

Pair it with `embedded-space` for generic MCU safety/ownership rules and with vendor specs such as `scmcu-space` or `padauk-space` for compiler and IDE conventions.

## Core Stance

- When two correct implementations exist, choose the smaller, shallower, and more direct one until the build proves there is room for abstraction.
- Prefer deleting logic over layering more protection code.
- Prefer direct state representation instead of encode/decode or normalize/re-encode chains.
- Treat every wrapper, helper, table, function pointer, registration mechanism, and handle indirection as a cost that must buy a real product, safety, verification, or maintenance benefit.
- Do not decide from chip model, nominal flash size, or intuition. Use the current build's memory report, map/listing, or equivalent evidence.

## Budget Gates

- Project-local specs or hardware/requirement truth may define stricter ROM/RAM limits. Use those over this generic policy.
- If ROM/RAM usage is unknown, stay in conservative mode until a build proves the budget.
- Treat total ROM/RAM as ceilings, not permission slips. The real gate is measured headroom against required reserve.
- Conservative mode: use flat, direct C by default when required budget is unknown, project reserve is not declared, program ROM is `>= 80%`, data RAM is `>= 75%`, or declared reserve would be crossed.
- Balanced mode: allow thin module boundaries, handles, and small lookup tables when program ROM is `< 70%`, data RAM is below its warning gate, and declared reserve remains intact.
- Interface mode: allow ops tables, base handles, board/platform indirection, and opaque structs when program ROM is `< 60%`, data RAM is below its warning gate, declared reserve remains intact after expected growth, and the variation is real.
- Relaxed mode requires a project-local or chip-family rule that explicitly states available headroom, reserve, and acceptable abstraction cost.

## Direct Implementation Rules

- Keep the main loop visually short and flat.
- Prefer `Scan -> Handle -> Output` style control flow.
- Prefer fixed-width integer logic, direct calls, direct register/platform calls, and file-local static state when that reduces total cost.
- Keep simple one-use logic inline unless extracting it reduces total cost or protects a real invariant.
- Prefer a direct function, `switch`, or small `if` when there is only one implementation or the hot path must stay small.
- Do not hide long policy logic behind an ops call when direct state update would be smaller and clearer.

## Time Base And Slicing Under Tight Budget

- Prefer one shared hardware/software time base before adding schedulers, delay loops, extra timer channels, dynamic queues, callback registries, or per-feature timing frameworks.
- Keep timer ISR work tiny: update a tick counter or phase flag, latch the minimum timing state, clear the source, and exit.
- Split periodic work in the main loop with fixed counters or phase slots.
- Each slice should have a bounded job, owned state, and stated period.
- Derive secondary cadences from the shared tick with counters or masks instead of introducing another timing mechanism by default.
- Verify timer reload/prescaler truth, ISR jitter tolerance, and worst-case slice runtime before relying on the schedule.

## Helper Function Gate

- Helper functions are not the default way to make code look cleaner.
- Add a helper only when it removes repeated logic, isolates a verified hardware operation, shortens a hot path, reduces ROM/RAM, protects an invariant, or gives one testable responsibility a clear name.
- Do not add a helper that only renames one expression, wraps one call, or hides temporary variables.
- Do not add a helper if it increases call depth in ISR, scan loops, debounce paths, timing-critical output paths, or hot code without measured benefit.
- Keep approved helpers file-local `static` by default.
- Before keeping a new helper, be able to answer: what state does it own, what invariant does it protect, what duplication does it remove, or what hardware boundary does it isolate?

## Tables, Constants, And Data Shape

- Lookup tables consume memory. Keep a table only when it is smaller, safer, clearer, or measurably faster than direct logic for this target.
- For each nontrivial table, inspect map/listing output after the build and compare against simple branch logic when practical.
- Avoid round-trip conversion layers from hardware values into semantic models and back again unless they remove real duplicated policy.
- Keep state representation close to the product decision that consumes it.

## Module Splits And Interfaces

- Do not split code automatically just because a file is long.
- Suggest a split when one file contains distinct hardware roles, timing domains, state owners, or product features that can be verified independently.
- Prefer in-file sections over new translation units when the code is tiny, the compiler has weak cross-file optimization, or the proposed split only creates pass-through helpers.
- A split proposal must name the responsibility boundary, owned state, public API, affected callers, expected ROM/RAM impact, and verification path.
- Reject splits that only mirror abstract architecture names, increase public writable state, create circular includes, or move hardware details into application code.

## Ops Tables, Callbacks, And Registration

- Use an ops table only when there are multiple real implementations, a stable interface, or a callback decision that must be delayed.
- Public wrappers should own dispatch. Application code should not call internal ops fields directly.
- Required ops are contract items: validate them during init or in the wrapper with the project's normal error policy.
- Optional ops are capability items: document the fallback and null-check before dispatch.
- Prefer explicit board lists, fixed arrays, or direct init calls unless automatic registration is proven smaller and supported.
- Linker-section auto-registration is allowed only when compiler attributes, linker script symbols, startup traversal, link order, and map output have all been verified.
- Do not introduce auto-registration just to avoid adding one line to board init.

## Resource Review Discipline

- After every feature slice, inspect the build summary, warnings, ROM/RAM usage, and map/listing top functions.
- For every new abstraction that changes call shape, dispatch, table size, or module boundaries, compare before/after build size when practical.
- If an abstraction adds `> 2%` program ROM, `> 1%` data RAM, or affects ISR/hot-loop timing, require a concrete product or verification reason instead of "cleaner architecture".
- For ROM/RAM pressure, inspect the map/listing before speculating.
- Record size traps and surprising compiler behavior in the project-local spec or task AAR.

## Avoid By Default

- Recursive control flow.
- Event buses, ownership frameworks, or generic callback dispatch unless measured smaller or required by real variation.
- `printf`/`sprintf`-style formatting in production firmware unless the ROM cost is explicitly accepted.
- Function pointer dispatch when direct calls, `switch`, or fixed tables are smaller and equally clear.
- Helper functions that only rename one expression or wrap one call.
- Public writable globals, public concrete hardware structs, or application-layer downcasts.
- Automatic registration without linker/startup/map evidence.
