# Sources

`docs/sources/` holds reusable "distilled knowledge" — not raw document archives.

What belongs here:

- MCU manual extraction summaries
- Package/pin/peripheral constraint summaries
- Common external component constraint summaries
- High-reuse summaries for specific part numbers
- Shared conclusions that chip-support/profile generation repeatedly references

What does NOT belong here:

- Raw PDFs
- Large scanned documents
- Project-private debug notes
- One-off drafts serving a single project

## Reference Style

Recommended usage in `extensions/**/*.json`:

- `source_refs`
- `component_refs`

These two fields hold IDs only, no inline long text.

Example:

```json
{
  "source_refs": ["mcu/scmcu-sc8f072"],
  "component_refs": ["components/<part-number>"]
}
```

Corresponding file paths:

- `docs/sources/mcu/scmcu-sc8f072.md`
- `docs/sources/components/<part-number>.md`
- `docs/sources/components/tq322.md`

## Components Directory Guidance

`docs/sources/components/` holds only specific part number summaries:

- `<part-number>.md`
  For high-frequency, cross-project reusable part summaries, e.g. `vs1838b`, `hx1838`, `hc-sr501`

Recommended principles:

1. Only add a part to this catalog when it appears repeatedly across multiple projects
2. If you only have "this class of device usually behaves like this" generalizations, do not write them as shared truth
3. If a part appears in only one project, don't rush to add it to this catalog

Part-specific documents should record:

- Explicit pin names/polarity
- Supply voltage range
- Output type
- Timing or hold time
- Constraints directly relevant to MCU selection/pin/timer/wakeup capability

Do NOT add:

- Category-level summary files
- Generalizations that only express "most devices behave like this"

Do NOT record:

- Large verbatim datasheet excerpts
- Single-project private soldering experience
- Low-information parameters that won't influence agent decisions or tool selection

## Design Goals

- Give chip-support/profile lightweight traceable sources
- Avoid re-reading the entire manual on every generation
- Don't bloat the chip-support catalog into a document warehouse
- Let maintainers review "conclusions" rather than entire PDFs
