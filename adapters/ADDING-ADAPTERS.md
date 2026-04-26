# Adding Chip Support

## Recommended Order

1. Define family
2. Define device
3. Define chip
4. Add `packages / pins` in the chip profile
5. Declare `bindings` in the device/family profile
6. Add new algorithm files only when existing ones are insufficient
7. Reuse existing routes first; only modify a route when the tool entry dispatch model is incompatible

## Recommended Contribution Workflow

1. Sync or verify that your local `emb-agent` engine is working
2. From this repo root, run `npm run generate -- --from-project --project /abs/path/to/project`
3. Review the generated `extensions/**` and `chip-support/routes/**` diff
4. Manually fill in algorithm parameters, evidence, `notes`, `source_refs`, `component_refs` as needed
5. Run `npm run validate`
6. Submit PR and wait for maintainer review

If not generating from project truth, you can also use:

```bash
npm run generate -- --from-doc <doc-id> --project /abs/path/to/project --vendor Padauk
```

The generation entry point does not implement inference logic itself; it delegates to `emb-agent`'s `adapter generate` engine.

## Files Required

For example, adding a new `vendor-family`:

```text
extensions/tools/families/vendor-family.json
extensions/tools/devices/vendor-device.json
extensions/chips/profiles/vendor-chip.json
chip-support/routes/timer-calc.cjs
chip-support/routes/pwm-calc.cjs
chip-support/routes/lpwmg-calc.cjs
chip-support/routes/lvdc-threshold.cjs
chip-support/routes/charger-config.cjs
chip-support/routes/comparator-threshold.cjs
chip-support/routes/adc-scale.cjs
```

The route files above are the "fixed entry points for the tool in the catalog" — they are not "copy one set per new chip."

Not all tools must be implemented. Only implement the tools actually relevant to that chip.

If only parameters differ, typically you need neither a new route nor a new algorithm file — just feed parameters to the existing algorithm via the profile `bindings`.

### Chip Profile Truth Layers

`chip profile` should maintain two truth layers:

- `packages`
  Package-level physical pin table, e.g., SOP8/QFN16 with Pin1..PinN to signal mapping
- `pins`
  Logical pad capability table, e.g., what mux options `ra0` supports, which package pins it lands on, whether it has external interrupt

Also recommend adding two lightweight reference fields:

- `source_refs`
  Pointers to `docs/sources/mcu/*.md` MCU/manual extraction summaries
- `component_refs`
  Pointers to `docs/sources/components/*.md` specific external component part summaries

These two fields contain IDs only, not long descriptive text.

`component_refs` only references specific part number summaries, e.g., `components/<part-number>`.

Only add an entry to `docs/sources/components/` when a specific component appears repeatedly across projects and its polarity, timing, output type, hold time, or power constraints would directly influence agent decisions.

If you only have "this class of device usually behaves like this" experience-based conclusions, do not write them as shared truth. That kind of content belongs in project-side facts or agent reasoning, not the shared catalog.

## Chip-Support Return Contract

At minimum, return:

- `tool`
- `status`
- `implementation`
- `chip_support_path`
- `route`
- `inputs`
- `notes`

If results were computed, also include:

- `outputs`
- `candidates`
- `warnings`
- `register_hints`

## Failure Rules

- Do not fabricate register values
- Do not pretend to support a family/device
- Do not return `ok` because a route is missing

When implementation is missing, explicitly return `route-required` or a more specific error — that is safer.
