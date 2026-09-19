# KiCad CAD operations go through Konnect

KiCad placement, routing, design-rule and manufacturing work is **not** built here. It is
delegated to [Konnect](https://github.com/mixelpixx/Konnect), an MCP server and KiCad
plugin that drives KiCad through the official IPC API and exposes layout, routing
(through Freerouting), ERC/DRC, library and export tools to an agent. This repository
keeps a reference to it, not a copy of it.

## Why there is no skill bundle for it

`skills/index.json` entries point at an in-repo bundle directory — `path: './<name>'` —
which `emb-agent skills install <name>` resolves from this repository. Konnect is a
standalone Rust binary that a user installs into KiCad and drives over MCP, so there is
no bundle here to install and no `path` to point at. Shipping one would mean vendoring a
third-party project, which the licence position rules out.

## Licence position

| Project | Licence |
| --- | --- |
| `emb-support` (this repository) | Apache-2.0 |
| `emb-agent` | AGPL-3.0-or-later |
| Konnect | AGPL-3.0 |

Reference only: this document names Konnect and says how to reach it, and ships none of
its code. Vendoring AGPL-3.0 sources into an Apache-2.0 repository would put the combined
work under AGPL-3.0, so it is out of bounds here. The reading half of Konnect's KiCad
S-expression handling was ported into `emb-agent` instead, where AGPL-3.0-or-later makes
that compatible; the source commit is recorded in those module headers.

## What each side does

- **emb-agent** answers *what the board is*. `ingest board --file <board>.kicad_pcb`
  publishes `analysis.board-layout.json` with `format: "kicad-pcb"`: layers, stackup and
  the board's settings, footprints, pads, tracks, arcs, vias, zones with their keepout
  rules, the board outline, text, graphics, dimensions, 3D model references, component
  classes and the title block, plus the counters a consumer checks them against. A
  `.kicad_sch` runs through the standard schematic pipeline (parsed, visual netlist,
  advice, MCU candidates). It reads; it never writes CAD.
- **Konnect** performs the CAD operations, through KiCad's own engine while KiCad is
  running: placement, routing, design-rule checks, layer and netclass work, library and
  footprint handling, and manufacturing exports.
- **The human decides.** Anything that should become project truth goes through
  emb-agent's proposal path and is recorded as such.

## Revisit when

- Konnect's licence or MCP surface changes, or those tools are published as reusable
  crates, which would make a bounded dependency discussion possible;
- a KiCad CAD writer is wanted without a running KiCad — it would still belong to a
  consumer of emb-agent's evidence, not to this repository;
- or a KiCad project needs something Konnect does not cover, in which case the missing
  piece belongs next to whatever consumes it, not in `skills/`.
