# Beads project configuration

This is the canonical project-policy vocabulary for private Beads databases.
Inspect effective values and provenance with `bd config show`; observed values
are runtime truth, and unexpected provenance is configuration drift.

| Key and value | Class | Meaning | Enforcement owner | Expected project provenance | Runtime discovery |
| --- | --- | --- | --- | --- | --- |
| `epic.mode=milestone` | Workflow convention | Epics represent reviewable milestones. | Codex Beads workflow | `database` | `bd config show` |
| `commit.mode=per-bead` | Workflow convention | Each leaf Bead produces one coherent commit. | Codex Beads workflow | `database` | `bd config show` |
| `commit.format=type-prefix` | Workflow convention | Commit subjects use the established type prefix. | Codex Beads workflow | `database` | `bd config show` |
| `custom.workflow.decomposition=reviewer-friendly` | Workflow convention | Split work only when independently reviewable pieces improve review. | Codex Beads workflow | `database` | `bd config show` |
| `dolt.local-only=true` | Native safeguard | Do not wire a Dolt sync remote during initialization. | Beads | `config.yaml` | `bd config show` |
| `dolt.auto-commit=on` | Native safeguard | Commit each Beads database mutation locally. | Beads | `config.yaml` | `bd config show` |
| `no-git-ops=true` | Native safeguard | Prevent Beads from managing the repository's Git state. | Beads | `config.yaml` | `bd config show` |

Present this command exactly as written and obtain the approval required by the
calling skill before running it:

```sh
bd --sandbox config set-many epic.mode=milestone commit.mode=per-bead commit.format=type-prefix custom.workflow.decomposition=reviewer-friendly dolt.local-only=true dolt.auto-commit=on no-git-ops=true
```

These seven settings are the complete custom project policy. The only
`custom.*` setting is `custom.workflow.decomposition`. Do not invent additional
hierarchy, disclosure, linkage, parallelism, review, authorization, handoff,
workspace, repository-kind, or execution-strategy settings. Leave generated
metadata, defaults, and compaction settings unchanged.

For configuration semantics, consult the pinned
[Beads 1.1.2 configuration documentation](https://github.com/gastownhall/beads/blob/v1.1.2/docs/CONFIG.md).
The installed `bd <command> --help` output is authoritative for command syntax.
