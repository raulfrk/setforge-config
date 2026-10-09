---
name: parallel-implementation
description: Coordinate delegated implementation with persistent worker ownership, appropriate checkout isolation, and verified integration. Load before delegating implementation; pure read-only investigation or review does not require this skill.
---

# Parallel implementation

Split implementation into lanes and start the ready ones together, as Parallel
execution in CLAUDE.md says. A lane is ready with disjoint ownership and proven
interfaces; defer dependent work until its interfaces are proven, since separate
worktrees do not make it ready. Keep primary ownership and configured
roles/models as required by global guidance.

## Assign workers

Use fresh `general-purpose` agents as persistent worker owners, not forks.
Continue the same worker with SendMessage for corrections in its lane; start a
fresh one for new or unrelated work (Usage efficiency in CLAUDE.md). Pick the
model at spawn by the Opus criteria in CLAUDE.md, defaulting to Sonnet
(`model: "sonnet"`); it cannot change later. Each brief
identifies the checkout and dirty baseline, exact ownership, interfaces and
dependencies, applicable instructions, current evidence, and independent
acceptance checks. Tell workers they are not alone: preserve others' changes
and avoid conflicting edits. Workers must not recursively spawn reviewers or
run the review gate.

## Choose isolation

Share a worktree only with proven interfaces, disjoint ownership, and no shared
generators, lockfiles, migrations, or generated artifacts. Otherwise use
separate worktrees made with `wt` or `git worktree add` from the local HEAD;
`isolation: "worktree"` cut from a stale origin/main and refused Bash on devbox
(2026-10-07).
Serialize conflicting mutations, including external shared state; separate
checkouts do not isolate external state. Do not add a role,
framework, or forced commit solely to coordinate the work.

## Integrate and accept

At a real handoff boundary, each worker provides one consolidated result:
completed behavior, exact changed files or diff reference, verification
commands and results, and unresolved blockers or questions. The primary
independently validates the handoff, integrates completed work, and verifies
interactions between the implementations.

Keep corrections with the existing owner under the global correction rules;
the primary retains acceptance and does not silently take over a worker's
lane. Use `review-gate` when the global risk triggers require independent
review; delegation alone does not require it.
