# Repo Contract

This repository must satisfy the current `emb-agent support sync` source contract.

## Three-Layer Classification

The repo maintains only three primary classification layers:

- `chip-support/`
  Executable capabilities
- `extensions/`
  Chip and tool definitions
- `docs/sources/`
  Lightweight knowledge summaries

If a new "primary classification" grows outside these three, it generally means the classification has drifted again.

## Synced Content

Only these are synced to the target project or runtime:

- `chip-support/**/*.cjs`
- `extensions/tools/specs/*.json`
- `extensions/tools/families/*.json`
- `extensions/tools/devices/*.json`
- `extensions/chips/profiles/*.json`
- `extensions/chips/devices/*.json`
- `docs/sources/**/*.md`

## Non-Synced Content

These are for repository maintenance only and do not enter target projects:

- `README.md`
- `docs/ADDING-ADAPTERS.md`
- `docs/REPO-CONTRACT.md`
- `package.json`
- `scripts/`
- `tests/`
- Any custom files not in the sync list above

## Directory Layout Requirements

The repo root must match at least one of:

- `chip-support/`
- `extensions/tools/`
- `extensions/chips/`

Otherwise `support sync` will reject the source layout as invalid.

## Naming Constraints

- Route file names must equal the tool name, e.g., `chip-support/routes/timer-calc.cjs`
- family/device/chip file names should use slugs directly
- Routes bind `tool -> binding -> algorithm`
- Algorithm files do not need to match tool names; they can be named by peripheral model
- Do not treat routes as "one copy per chip"; routes should be stable; chip differences should sink into `bindings/params`

## Classification Responsibilities

- `chip-support/core/`
  Shared parsing, profile reading, common utility functions
- `chip-support/algorithms/`
  Algorithms reusable across multiple chips
- `chip-support/routes/`
  Entry points actually loaded by runtime per `toolName`
- `extensions/tools/*`
  family/device/tool bindings and constraints
- `extensions/chips/profiles/*`
  Chip-level package, pin, mux, related tools, and lightweight references
- `docs/sources/*`
  Conclusive knowledge referenced by `source_refs` / `component_refs`

## Current Limitations

- `extensions/tools/specs|families|devices` and `extensions/chips/profiles` are the recommended layout; runtime still supports legacy `extensions/chips/devices`
- If only parameters differ, do not copy an algorithm; push differences into the profile `bindings/params` instead
- `chip profile` `packages / pins` are a recommended truth layer; they do not participate in route selection but are used by upper-layer agents for pin, package, and mux reasoning
- `extensions/**/*.json` may use `source_refs` / `component_refs`, pointing to summaries under `docs/sources/`
- This repo allows `npm run generate` to write AI-generated results directly back to the repo root; generated content must still pass `npm run validate` before commit
