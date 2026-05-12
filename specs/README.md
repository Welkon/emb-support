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
