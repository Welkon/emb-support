---
name: "altium-pcb"
description: "Operate on Altium PCB layout artifacts from parsed board evidence. Use when Codex needs to plan or apply conservative PcbDoc component placement, prepare Altium MCP live-apply commands, inspect PCB layout constraints, or run future PCB-side Altium automation while preserving the board outline, routing, pads, nets, and locked components unless a command explicitly scopes otherwise."
metadata:
  short-description: "Operate on Altium PCB layout artifacts"
---

# Altium PCB

## Overview

Use the bundled Python helper for Altium PCB-side layout automation. Keep emb-agent core read-only: use core board ingestion to create board evidence, then use this skill for CAD operations.

The helper is conservative by design:

- It reads parsed board layout JSON from `ingest board`.
- It treats explicit `--locked` refs, PCB locked components, and connectors as fixed anchors by default.
- It estimates footprint envelopes from pads, component body model names, footprint names, and role fallbacks.
- It avoids same-side envelope overlap and clips suggestions to recognized board bounds.
- It emits deterministic placement scores and requires AI layout-intent review before live export/apply by default.
- It applies `.PcbDoc` edits only by equal-length `X`/`Y` field replacement in `Components6/Data`.
- It never modifies board outline, pads, nets, or routing.

## Default Workflow

1. Create or refresh board evidence:

```bash
emb-agent ingest board --file docs/board.PcbDoc
```

2. Generate a placement plan:

```bash
python3 .codex/skills/altium-pcb/scripts/altium_pcb.py plan \
  --parsed .emb-agent/cache/boards/<analysis.board-layout.json> \
  --locked U1,J1 \
  --output .emb-agent/cache/boards/placement-plan.json
```

3. Review the JSON plan before writing a board copy. Apply to a copy by default:

```bash
python3 .codex/skills/altium-pcb/scripts/altium_pcb.py apply \
  --file docs/board.PcbDoc \
  --plan .emb-agent/cache/boards/placement-plan.json \
  --locked U1,J1 \
  --output docs/board.placed.PcbDoc
```

Use `--in-place --confirm` only when the user explicitly asks to overwrite the original `.PcbDoc`.

4. Review `placement_plan.placements[].ai_review.review_prompt`. Mark a placement accepted only after AI layout-intent review passes:

```json
{
  "ai_review": {
    "required": true,
    "status": "accepted",
    "decision": "accepted",
    "score": 82,
    "reason": "Functional placement is acceptable after review"
  }
}
```

The deterministic score is not the final quality decision. It is a hard-gate and ranking signal for the AI review.

5. To prepare live Altium execution through `altium-mcp`, export accepted placement calls instead of applying directly:

```bash
python3 .codex/skills/altium-pcb/scripts/altium_pcb.py export-mcp \
  --plan .emb-agent/cache/boards/placement-plan.json \
  --locked U1,J1 \
  --output .emb-agent/cache/boards/placement.altium-mcp.json
```

`export-mcp` skips pending/rejected AI review placements by default. Use `--allow-unreviewed` only for controlled experiments; it cannot override unresolved collisions unless `--include-unresolved` is also explicitly passed. Run live preflight against Altium before executing the calls.

6. Calibrate the exported live calls against component coordinates read from the currently open Altium board:

```bash
python3 .codex/skills/altium-pcb/scripts/altium_pcb.py preflight-live \
  --plan .emb-agent/cache/boards/placement-plan.json \
  --live-components .emb-agent/cache/boards/altium-live-components.json \
  --locked U1,J1 \
  --anchor U1,J1 \
  --output .emb-agent/cache/boards/placement.live-preflight.json
```

`--live-components` must be JSON saved from `altium-mcp get_all_component_data`. If `--anchor` is omitted, the helper uses locked and connector fixed components from the placement plan.

7. Prepare a final live apply bundle after reviewing the preflight:

```bash
python3 .codex/skills/altium-pcb/scripts/altium_pcb.py apply-live \
  --preflight .emb-agent/cache/boards/placement.live-preflight.json \
  --locked U1,J1 \
  --confirm \
  --output .emb-agent/cache/boards/placement.live-apply.json
```

`apply-live` is emit-only: it does not directly contact Altium. It refuses blocked preflights, requires `--allow-warnings` for `ready-with-warnings`, and emits both a `set_component_positions` batch request and sequential `set_component_position` fallback requests for the reviewed board.

## Rules

- Do not call this skill a generic autorouter. It places components only.
- Do not move components listed in `--locked` or components marked locked in the PCB.
- Do not change board outline, existing routing, pads, nets, tracks, vias, or text.
- Do not apply a plan with unresolved collisions unless the user explicitly accepts that risk; the helper skips unresolved placements during apply.
- Do not export or live-apply AI-review-pending placements unless the user explicitly asks for `--allow-unreviewed` experimentation.
- AI review may reject a candidate for poor engineering intent, but it must not override hard gates: board outline, locked components, live locks, and unresolved collisions remain deterministic blockers.
- Do not execute `export-mcp` output against a live Altium board until fixed anchor coordinates have been compared against `altium-mcp get_all_component_data`; board-origin offsets can differ.
- Do not execute live calls from `apply-live` unless the intended Altium board is open and the preflight anchor offsets match that same board.
- Run Altium DRC and a mechanical review after any placement apply.
- If `board.bounds` is missing from the parsed layout, treat output as advisory and avoid writing a board file unless the user accepts manual review.

## Commands

Generate a plan:

```bash
python3 scripts/altium_pcb.py plan \
  --parsed analysis.board-layout.json \
  --locked U1,J1 \
  --limit 200 \
  --clearance-mm 0.5 \
  --edge-margin-mm 1.0 \
  --output placement-plan.json
```

Apply a plan:

```bash
python3 scripts/altium_pcb.py apply \
  --file board.PcbDoc \
  --plan placement-plan.json \
  --output board.placed.PcbDoc
```

Inspect a plan summary without writing:

```bash
python3 scripts/altium_pcb.py plan --parsed analysis.board-layout.json
```

Export a reviewed placement plan for `altium-mcp`:

```bash
python3 scripts/altium_pcb.py export-mcp \
  --plan placement-plan.json \
  --locked U1,J1 \
  --output placement.altium-mcp.json
```

Calibrate live Altium calls:

```bash
python3 scripts/altium_pcb.py preflight-live \
  --plan placement-plan.json \
  --live-components altium-live-components.json \
  --locked U1,J1 \
  --anchor U1,J1 \
  --output placement.live-preflight.json
```

Prepare live execution requests:

```bash
python3 scripts/altium_pcb.py apply-live \
  --preflight placement.live-preflight.json \
  --locked U1,J1 \
  --confirm \
  --output placement.live-apply.json
```
