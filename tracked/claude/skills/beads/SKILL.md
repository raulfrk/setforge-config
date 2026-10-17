---
name: beads
description: Manage private Beads issues and project configuration, or perform required tracker discovery. Use beads-bootstrap for new setup.
---

# Beads

Use Beads as private project-management state. Keep the workflow proportional
to the work; do not turn issue tracking into a controller or coordination
framework.

## Establish the active project

When global guidance requires tracker discovery, load this skill before running
it. Complete the canonical-path checks below before inspecting project
configuration or issues. If no project exists, continue without initializing or
proposing one.

Establish the current Git root and primary worktree once per task and checkout.
Reuse a validated discovery while the relevant environment and paths remain
unchanged, including when a supporting skill needs it. Recheck after a change
that can affect the result:

```sh
git rev-parse --show-toplevel
git worktree list --porcelain
```

Resolve the primary worktree from the first `worktree` entry returned by `git
worktree list --porcelain`. Before canonicalizing anything, require
`BEADS_DIR` to be unset. If the primary `.beads` path exists, require it to be
a real directory rather than a symlink and reject a `redirect` file there; an
absent path is valid at this stage. When the current checkout differs from the
primary, reject any worktree-local `.beads` path before canonicalization.
After those lexical checks, run `bd where --json` from the current checkout
root. Treat exit 1 with JSON `"error": "no_beads_directory"` as normal absence,
not permission to initialize. If discovery succeeds, canonicalize the paths
and require the returned Beads `path` to equal the primary worktree's
canonical `<git-root>/.beads`. This is the expected native location from both
the primary checkout and a linked Git worktree. Stop on any mismatch.

Only after path validation succeeds, inspect project configuration with
`bd config show`. Do not parse `bd info --json`; in Beads 1.1.2 it emits
human-readable output. Use native `bd` commands and consult
`bd <command> --help` for exact syntax; never use raw SQL or `bd edit`.

For configuration meaning, provenance, and the sole approved command, read
[the project configuration reference](references/project-config.md). For a new
repository use the `beads-bootstrap` skill.

## Authorization

Initialization, creation, and configuration require explicit authorization of
the exact operation or bounded batch. Reuse authorization already supplied in
the conversation or by a standing user instruction; do not ask again when
entering a supporting skill or reference.

Standing authorization: in a repository that already has a Beads project, create
one Bead for each fix, feature, bug or other trackable work item without asking.
Create it before or as the work starts, claim it, and keep it open until its
acceptance checks pass.

Standing authorization also covers child Beads one level under the current
task's Bead, for subtasks inside its scope. Record anything found along the way
outside that scope in a "Follow-ups" list in the parent Bead's notes, not as a
new Bead; the user decides which become Beads. Initialization, configuration,
deeper nesting, and other graph expansion still need the authorization above.

When details are missing, present the repository, prefix or settings as applicable,
and each proposed Bead's title, type, purpose, acceptance criteria, and parent or
dependency relationships before asking. Ask again only when the target or scope
materially changes. Do not infer additional graph expansion from approval of a
specific operation.

Once the user selects existing work or explicitly requests a bounded graph or
configuration change, perform ordinary non-destructive updates without another
approval ceremony. Apply the global destructive-action safeguards to deletion.

## Initialize privately

Before approved initialization, load `beads-bootstrap` for the stealth
initialization command and complete verification procedure. Do not silently
reinitialize an existing database.

## Configure the project

Inspect effective values and provenance before proposing configuration. Read
[the project configuration reference](references/project-config.md), present
its canonical command exactly as shown, and obtain any missing approval before
applying it. Existing explicit approval of that command satisfies this
requirement. Do not reproduce the command here.

When preservation matters, capture the complete issue graph with:

```sh
bd --readonly list --all --limit 0 \
  --include-gates --include-infra --include-templates --json
```

Normalize issues by issue ID and dependencies by dependency ID before comparing
snapshots.

## Work an existing Bead

Discovery is not an issue read. For work that maps to an existing Bead:

1. Read that exact Bead, its acceptance criteria, dependencies, and current notes
   before substantive work, claiming, and the first update or close in the session.
   Do not combine claim-before-read as `bd update <id> --claim && bd show <id>`.
2. Refresh after a handoff or context recovery when authoritative issue state is
   not fully present, after an external change, and at a meaningful work phase
   when the last exact read predates that phase. Before changing acceptance text,
   appending progress, or closing, refresh if the complete authoritative state is
   not current in context. Reuse a current complete read; do not reread solely
   because another turn passed.
3. Run the acceptance checks and inspect their observable results. Do not rerun
   valid checks merely to reconstruct context.
4. Close with `bd close <id> --reason <verified-result>` only after the checks
   succeed. If verification fails, keep it open and report the failure.

For material tracked work, use the owning leaf as the durable resume point, not
a per-command transcript. When a material decision, verified result or failure,
phase change, or unattended long-running operation changes what should happen
next, keep a concise current checkpoint in `notes`; use native comments for
chronological decisions and evidence, linking retained reports instead of copying
them. Refer to existing acceptance criteria rather than repeating them.

The current checkpoint identifies the original outcome and stage, candidate Git
binding, verified evidence and its applicability, remaining criteria or
uncertainty, authorization/HOLD boundaries, and next safe action with any live
process handle. Include non-obvious decision rationale. For a detour, state
whether it blocks the original work or is an approved follow-up and the condition
for returning; completing it does not complete the original outcome.

Before replacing notes containing history, preserve that history in native
comments with its original provenance and verify preservation. Do not discard
decisions, approvals, criteria, or evidence. Do not consolidate another active
owner's notes without an agreed handoff. Use `bd comments --help` for exact
syntax; comments do not replace current issue state.

After compaction, restart, or handoff, read the latest checkpoint and compare it
with actual Git and process state before resuming. Reconcile discrepancies; a note
is not proof that a process finished. Read relevant comments or linked artifacts
when a material decision or acceptance question remains unresolved.

Keep updates decision-relevant and reference retained artifacts instead of
copying full reports. Update an epic or sibling only when its own status,
dependency, acceptance criteria, or decision materially changes; do not
broadcast the same checkpoint across the graph. If an exact read is truncated,
use bounded field-specific JSON projections to recover acceptance criteria and
relevant recent notes before relying on it.

## Decompose for review

When `custom.workflow.decomposition` is `reviewer-friendly`, create child
Beads only when independently reviewable pieces materially improve review. One
level under the task's Bead is pre-authorized (Authorization); a deeper level
needs approval, individually or as an exact bounded batch. Use the shallowest
useful hierarchy with at most three nesting levels. Avoid file-based splits, one-child epics,
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
