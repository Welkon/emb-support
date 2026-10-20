# Sources

`references/sources/` holds reusable "distilled knowledge" — not raw document archives.

What belongs here:

- MCU manual extraction summaries
- Package/pin/peripheral constraint summaries
- Common external component constraint summaries
- High-reuse summaries for specific part numbers
- Shared conclusions that firmware work keeps coming back to

What does NOT belong here:

- Raw PDFs
- Large scanned documents
- Project-private debug notes
- One-off drafts serving a single project

## Naming and style

One flat file per subject, named after the part:

- `<chip>-registers.md`: register and field layout.
- `<chip>.md`: wider peripheral notes for that chip.
- `<part>.md`: a specific component, e.g. `tq322.md`.
- `calculators.md`: the arithmetic that turns a requirement into a register value.

Cite the source you verified against at the top of the file. A file that states a
formula must also give one checked example with its derivation, not only the
result.

## Component notes

Only add a part when it appears across several projects.

Record: pin names and polarity, supply range, output type, timing or hold time,
and the constraints that affect MCU selection, pin choice, timers or wakeup.

Do not add category-level summaries ("most devices behave like this"), large
verbatim datasheet excerpts, or single-project soldering notes.

## Design goals

- Give the skill lightweight traceable sources instead of a datasheet warehouse.
- Avoid re-reading the entire manual for every task.
- Let a maintainer review conclusions rather than entire PDFs.
