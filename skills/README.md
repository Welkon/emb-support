# skills catalog

`index.json` is the machine-readable catalog that `emb-agent` reads (locally, or
cloned from this repository) to answer `emb-agent skills list --available`,
`skills recommend`, and `skills install <name>`.

| field | meaning |
| --- | --- |
| `name` | bundle directory name; the key used by `skills install <name>` |
| `path` | bundle path relative to this directory |
| `description` | full description (agent-facing) |
| `short_description` | one-line summary (listings/menus) |
| `interface` | host display metadata (`display_name`, `short_description`) |
| `detect` | relevance rules (see below) |

## `detect` relevance rules

Every group is optional; a skill is "relevant now" when **any** group matches.

| group | matched against |
| --- | --- |
| `mcu_vendor` | declared `mcu.vendor` in the project's `.emb-agent/hw.yaml` |
| `mcu_family` | case-insensitive substring of the declared MCU model |
| `project_files` | file names/dirs at project depth ≤ 2 (`*` wildcard allowed) |
| `tools` | executable names expected to be found on `PATH` |

Relevance advice is data-driven by design: emb-agent core contains no chip
knowledge, it only compares project signals against these lists. A match never
installs anything — installing an external skill stays an explicit, per-skill
opt-in step.

Matches are reported with the reason, for example
`declared MCU PIC18F47Q10 matches family PIC18; xc8-cc found on PATH`.

## Adding a skill

1. Create `skills/<name>/SKILL.md` (frontmatter needs `name` and `description`).
2. Add an `index.json` entry with `path`, descriptions and `detect` rules.
3. Add `./<name>/SKILL.md` to `.emb-agent-plugin/plugin.json`.
4. Run `node tests/run-tests.cjs`.
