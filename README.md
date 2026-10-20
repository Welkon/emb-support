# emb-support

Standalone companion repository for optional emb-agent assets.

`emb-agent` keeps core runtime behavior in-tree: startup flow, task routing, core protocols, analysis artifacts, and the core chip-support template.

This repository only carries reusable external assets that should stay installable and versionable outside the core runtime.

- `specs/`
  External rule packs selected during install or project bootstrap. Keep vendor/compiler/IDE conventions and special family guidance here. Current reusable specs include `padauk-space` and `scmcu-space`; generic MCU and low-ROM baseline specs live in `emb-agent` core.
- `skills/`
  Installable skill bundle source. The installer can preview and select individual skills from this directory.

Typical split:

- Put core workflow behavior in `emb-agent`
- Put reusable external rules in `emb-support/specs`
- Put optional installable skills in `emb-support/skills`
- Put chip facts and register notes in an installable skill (`skills/*/references/`)

## What moved out

`adapters/` was retired in 2026-10. Nothing consumed it: `emb-agent` has no
`support`/`adapter` command, `runtime/config.json` had no reader for
`default_chip_support_source`, and projects author their own
`.emb-agent/chip-support/routes/*.cjs` from the `tool-chip-support` template.

- register summaries, source digests and the sleep/wake pattern now live in
  `skills/mcu-debug/references/sources/`
- the arithmetic of the removed calculators is kept as formulae in
  `skills/mcu-debug/references/sources/calculators.md`
- `specs/` is unchanged and remains the distribution source for
  `emb-agent install --spec <name>`

## Contributing

Specs and skills are the point of this repository, so additions from outside the maintainers are welcome: a vendor toolchain spec, a skill a firmware team keeps rewriting, or reviewed register notes for a chip family. Run `node tests/run-tests.cjs` before opening a pull request.

By opening a pull request you license your contribution under Apache-2.0, the terms below.

## License

Apache-2.0 — the full text is in [LICENSE](LICENSE).

Everything here is written to be copied and adapted, including commercially, so this catalog is permissive on purpose: a chip vendor or a firmware team has to be able to take an adapter into its own tree without asking anyone. `emb-agent` is a separate component under AGPL-3.0-or-later, and contributing here does not change the terms of the core runtime.
