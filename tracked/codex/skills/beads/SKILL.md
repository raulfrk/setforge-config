---
name: beads
description: Manage private Beads project work and configuration with explicit creation approval, stealth initialization, repository adaptation, reviewer-friendly decomposition, and a claim-verify-close lifecycle. Use when the user mentions Beads, bd, Beads issues or epics, Beads project configuration, bootstrapping Beads, or adapting an existing Beads repository.
---

# Beads

Use Beads as private project-management state. Keep the workflow proportional
to the work; do not turn issue tracking into a controller or coordination
framework.

## Establish the active project

Before any mutation, resolve the current Git root and primary worktree:

```sh
git rev-parse --show-toplevel
git worktree list --porcelain
```

Resolve the primary worktree from the first `worktree` entry returned by
`git worktree list --porcelain`. Before canonicalizing anything, require
`BEADS_DIR` to be unset. If the primary `.beads` path exists, require it to be a
real directory rather than a symlink and reject a `redirect` file there; an
absent path is valid at this stage. When the current checkout differs from the
primary, reject any worktree-local `.beads` path before canonicalization. After
those lexical checks, run `bd where --json`. Treat the recognized
`no beads project found` result as normal absence, not permission to initialize.
If discovery succeeds, canonicalize the paths and require the returned Beads
`path` to equal the primary worktree's canonical `<git-root>/.beads`. This is
the expected native location from both the primary checkout and a linked Git
worktree. Stop on any mismatch.

Only after path validation succeeds, inspect project configuration with
`bd config show`. Do not parse `bd info --json`; in Beads 1.1.2 it emits
human-readable output. Use native `bd` commands and consult
`bd <command> --help` for exact syntax; never use raw SQL or `bd edit`.

For configuration meaning, provenance, and the sole approved command, read
[the project configuration reference](references/project-config.md). For a new
repository use the `beads-bootstrap` skill. For conversion of existing state
use the `beads-adapt` skill.

## Authorization

Never initialize a database or create a Bead without first showing the exact
proposal and receiving user approval. A creation proposal includes its title,
type, purpose, acceptance criteria, and any parent or dependency relationships.

Once the user selects existing work or explicitly requests a bounded graph or
configuration change, perform ordinary non-destructive updates without another
approval ceremony. Apply the global destructive-action safeguards to deletion.

## Initialize privately

Every approved initialization uses:

```sh
bd init --stealth --non-interactive --skip-agents --skip-hooks \
  --prefix <project-prefix>
```

Do not silently reinitialize an existing database. After initialization,
verify that `.beads/` is untracked and ignored by the repository-local
`.git/info/exclude`, not by a tracked project file:

```sh
git check-ignore -v .beads
git ls-files .beads
git status --short --untracked-files=all
```

The second command must produce no output, and Git status must not expose the
database.

## Configure the project

Inspect effective values and provenance before proposing configuration. Read
[the project configuration reference](references/project-config.md), present
its canonical command exactly as shown, and wait for approval before applying
it. Do not reproduce the command here or invent additional policy keys. Leave
Beads-generated metadata and compaction values untouched.

When preservation matters, capture the complete issue graph with:

```sh
bd --readonly list --all --limit 0 \
  --include-gates --include-infra --include-templates --json
```

Normalize issues by issue ID and dependencies by dependency ID before comparing
snapshots.

## Work an existing Bead

For selected existing work:

1. Read the Bead and its acceptance criteria, then claim it with
   `bd update <id> --claim` before implementation.
2. Keep progress and relevant evidence in the private Bead when useful.
3. Run the acceptance checks and inspect their observable results.
4. Close with `bd close <id> --reason <verified-result>` only after the checks
   succeed. If verification fails, keep it open and report the failure.

## Decompose for review

When `custom.workflow.decomposition` is `reviewer-friendly`, propose child
Beads only when independently reviewable pieces materially improve review. The
user approves each child creation. Use the shallowest useful hierarchy with at
most three nesting levels. Avoid file-based splits, one-child epics,
placeholder layers, and dependencies that do not represent real ordering.

With `commit.mode = per-bead`, one leaf Bead produces one coherent commit. If
that would not be reviewable, propose decomposition before implementation.

## Keep tracking private

Do not place Bead IDs, commands, or mechanics in production code, comments,
docstrings, downstream project documentation, branches, commits, pull
requests, or release notes. A private Bead may record the resulting Git commit
SHA. This skill and the SetForge profile documentation may describe the policy
because they configure the private workflow rather than expose a downstream
project's tracking state.
