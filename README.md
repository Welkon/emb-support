# emb-support

Standalone companion repository for optional emb-agent assets.

`emb-agent` keeps core runtime behavior in-tree: startup flow, task routing, core protocols, analysis artifacts, and the `adapter derive|generate|export|publish` command surface.

This repository only carries reusable external assets that should stay installable and versionable outside the core runtime.

- `specs/`
  External rule packs selected during install or project bootstrap. Keep syntax rules, vendor-specific conventions, and special project guidance here. Current reusable specs include `embedded-space`, `padauk-space`, and `scmcu-space`.
- `skills/`
  Installable skill bundle source. The installer can preview and select individual skills from this directory.
- `adapters/`
  Shared chip-support catalog content reused by `support bootstrap|sync` and by maintainer-side adapter publication flows.

Typical split:

- Put core workflow behavior in `emb-agent`
- Put reusable external rules in `emb-support/specs`
- Put optional installable skills in `emb-support/skills`
- Put reusable chip-support assets in `emb-support/adapters`
