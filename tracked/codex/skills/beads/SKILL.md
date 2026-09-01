---
name: beads
description: Manage private Beads project work and configuration with explicit creation approval, stealth initialization, reviewer-friendly decomposition, and a claim-verify-close lifecycle. Use when the user mentions Beads, bd, Beads issues or epics, or Beads project configuration.
---

# Beads

Use Beads as private project-management state. Keep the workflow proportional
to the work; do not turn issue tracking into a controller or coordination
framework.

## Establish the active project

Before any mutation, inspect the Git root, active Beads location, database, and
issue prefix with native commands such as:

```sh
git rev-parse --show-toplevel
bd where
bd info --json
bd config show
```

Confirm they describe the checkout the user selected. Stop on a mismatch. Use
native `bd` commands and consult `bd <command> --help` for exact syntax; never
use raw SQL or `bd edit`.

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

Inspect effective values and provenance before proposing configuration. For the
reviewer-friendly workflow, use only these project-policy values:

```text
epic.mode = milestone
commit.mode = per-bead
commit.format = type-prefix
custom.workflow.decomposition = reviewer-friendly
```

Operational safeguards are separate:

```text
dolt.local-only = true
dolt.auto-commit = on
no-git-ops = true
```

Preview the exact `bd config set-many` command before applying a requested
configuration change. Do not invent hierarchy, disclosure, linkage,
parallelism, review, authorization, handoff, workspace, repository-kind, or
execution-strategy keys. Leave Beads-generated metadata and compaction values
untouched.

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
