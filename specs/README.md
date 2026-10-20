# emb-support specs

External specs live here as flat markdown files.

These specs are selected the same way as installable skills: the user chooses which ones to import during `emb-agent` installation or project initialization.

This directory should only contain reusable external rule packs such as:

- vendor-specific syntax or toolchain conventions
- special MCU-family guidance
- optional domain specs that are not part of emb-agent's core MCU baseline

Layering rule:

- keep generic MCU rules such as `embedded-space` in emb-agent core
- keep resource-pressure behavior such as `low-rom-space` in emb-agent core so it can auto-trigger from build evidence
- put vendor/compiler/IDE conventions in vendor specs such as `scmcu-space` or `padauk-space`
- put concrete chip/package/board facts in project truth or project-local specs

It should not duplicate emb-agent core runtime protocols or internal workflow behavior.

Layout rule:

- keep selectable specs as `*.md` files directly under `specs/`
- do not wrap external sources in `.emb-agent/registry/`
- use markdown frontmatter when a spec needs explicit `name`, `title`, `summary`, or `apply_when` metadata
- use `enforcement_scope: code-writing` for specs that should be obeyed only while editing, generating, or refactoring source code

Distribution contract:

- `specs/<name>.md` is fetched directly when the user runs `emb-agent install --spec <name>`:
  `bin/install.js` falls back to
  `raw.githubusercontent.com/Welkon/emb-support/main/specs/<name>.md`.
  Moving a spec into a subdirectory, renaming the file, or changing the `name`
  field breaks that download at install time, on the user's machine.
- The `specs` job in `.github/workflows/repo-checks.yml` enforces this: flat
  layout, `name` equal to the file stem, `title` and `summary` present.
- `README.md` is the only file here that is not a selectable spec.

Current specs:

- `scmcu-space` — imported by the SCMCU projects in `workspace/` (RH-SGT-003,
  RH-ZX-004/006/007 hold a byte-identical copy).
- `padauk-space` — no project imports it yet. It stays because the `mcu-debug`
  skill still does CACHIP/Padauk work (burner flow, TK3 touch), and the spec is
  the only place the Mini-C conventions are written down. Retire it if that work
  stops, not before.
