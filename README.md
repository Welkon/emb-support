# emb-support

Standalone companion repository for optional emb-agent assets.

`emb-agent` keeps core runtime behavior in-tree: startup flow, task routing, core protocols, analysis artifacts, and the `adapter derive|generate|export|publish` command surface.

This repository only carries reusable external assets that should stay installable and versionable outside the core runtime.

- `specs/`
  External rule packs selected during install or project bootstrap. Keep vendor/compiler/IDE conventions and special family guidance here. Current reusable specs include `padauk-space` and `scmcu-space`; generic MCU and low-ROM baseline specs live in `emb-agent` core.
- `skills/`
  Installable skill bundle source. The installer can preview and select individual skills from this directory.
- `adapters/`
  Shared chip-support catalog content reused by `support bootstrap|sync` and by maintainer-side adapter publication flows.

Typical split:

- Put core workflow behavior in `emb-agent`
- Put reusable external rules in `emb-support/specs`
- Put optional installable skills in `emb-support/skills`
- Put reusable chip-support assets in `emb-support/adapters`

## Contributing

Adapters, specs and skills are the point of this repository, so additions from outside the maintainers are welcome: a chip family's register rules, a vendor toolchain spec, or a skill a firmware team keeps rewriting. Each directory carries its own guidance (`adapters/ADDING-ADAPTERS.md`, `adapters/REPO-CONTRACT.md`); run what `tests/` covers before opening a pull request.

By opening a pull request you license your contribution under Apache-2.0, the terms below.

## License

Apache-2.0 — the full text is in [LICENSE](LICENSE).

Everything here is written to be copied and adapted, including commercially, so this catalog is permissive on purpose: a chip vendor or a firmware team has to be able to take an adapter into its own tree without asking anyone. `emb-agent` is a separate component under AGPL-3.0-or-later, and contributing here does not change the terms of the core runtime.
