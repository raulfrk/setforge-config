---
name: session-flow
description: >-
  Strict 7-phase work flow (brainstorm → spec → plan → implement → review →
  fix+merge → post-merge) + session lifecycle (handoff resume, epic discovery,
  session-end handoff). Superset of superpowers — adds bd, wt, revdiff, and
  handoff conventions on top. Deviation requires explicit user override.
when_to_use: >-
  Invoke at session start (SessionStart hook reminds you). Also invoke when
  starting any non-trivial task, resuming from a handoff, or when the user
  says 'work', 'implement', 'start working', or 'resume'.
---

# Session Flow

## Session start

1. SessionStart hook fires `bd prime` (live workflow context).
2. This skill loads (you're reading it now). Also invoke `superpowers:using-superpowers` to establish skill-invocation discipline for the session.
3. **Check handoff repo** — `cd ~/handoff && bd ready`. If a handoff bead exists:
   a. Read its content (project path, epic ID, context, suggested next-steps).
   b. Close the handoff bead (consumed).
   c. Navigate to the project dir. Run `bd show <epic-id>` and `bd ready`.
   d. **Present context** — summarize what the handoff says: last session state, active decisions, what was in-progress.
   e. **Interactive gate** — use `AskUserQuestion` to present ready beads as options. The handoff's suggested task appears first, marked `(Recommended)`. Other ready beads listed as additional options. User picks which to work on (or provides a different direction via "Other").
   f. Claim the chosen bead and enter the 7-phase flow.
   If no handoff repo or no open beads → step 4.
4. **Discover the current epic** — parse worktree slug for bd ID → `bd show <id>` → walk `--parent` until `type == "epic"`.
5. If no handoff and no worktree context: `bd ready` for next unblocked issue.

## The 7-phase flow (STRICT GATE)

Every task MUST follow all 7 phases in order. Escape hatch: user says "just do it" / "skip the flow" for THIS task only. If you judge a task simple enough to skip phases, ask the user first via AskUserQuestion — never skip without explicit consent.

### Phase 1 — Brainstorm

Invoke `superpowers:brainstorming`. Explore intent, requirements, constraints with the user. **Never assume the user's decisions — ask via AskUserQuestion for every uncertainty.** Co-author the design — surface trade-offs, ask exhaustively, ground every option in concrete context. Produces or sharpens a bd issue.

### Phase 2 — Spec via plan mode

`EnterPlanMode`. Write the spec VERBATIM into the plan body — no summary, no reflow. User reviews via revdiff (plan-review hook fires automatically). On approval → capture into the bd issue's `--design` / `--acceptance` / `--notes`. The bd issue is the durable contract; the spec file is a historical snapshot.

When writing the spec, include a "Bugs and code smells to avoid" section listing implementation pitfalls specific to the domain. Phase 5 review checks against these.

When revising a spec after review, open with a "Changes in this revision" section listing what changed and why — so the reviewer can focus on deltas without rereading the entire document.

**⚠ After ExitPlanMode approval, your NEXT action MUST be invoking `superpowers:writing-plans` (Phase 3). Do not edit files, dispatch agents, or take any implementation action first. ExitPlanMode's "start coding" message refers to the planning-then-coding sequence, not immediate file edits.**

### Phase 3 — Plan

Invoke `superpowers:writing-plans`. Implementation plan as a normal response (NOT plan mode). Walk implementation against actual code; verify symbol names exist; catch typos before code is written. MANDATORY before Phase 4 regardless of change size — a two-line change still gets a writing-plans invocation; the output will be proportionally brief.

### Phase 4 — Implement

Invoke `superpowers:executing-plans`. Single-stream by default. Parallel when work decomposes into independent threads — two modes: (a) **cross-worktree** via the bd ↔ wt loop (one bd per worktree, sibling branches), or (b) **in-session multi-agent** via `superpowers:dispatching-parallel-agents` or `superpowers:subagent-driven-development` when the user asks for parallel work or tasks are naturally independent. TDD where the contract isn't obvious (`superpowers:test-driven-development`).

> **See also:** `session-workflow` is a strict SUBSET — when an approved spec + bd issue already exist, it drives implementation Phases 4–5 plus the Phase 6 merge-gate decision (it computes the PASS/HELD gate; it does NOT run the merge). The merge action and all of Phase 7 stay manual. Use this skill (session-flow) for the full lifecycle (default); reach for `session-workflow` to mechanize just those implementation stages and the gate decision.

### Phase 5 — Review fan

Review approach is host-local — configured in the `host-local-workflow` section below. For multi-artifact changes, review each artifact type's diff separately.

### Phase 6 — Address findings + merge

Fix ALL findings inline (CRITICAL, IMPORTANT, and MINOR) unless the fix is large or clearly out-of-scope — in that case, file a new bd with dep link. Review-fix commits stay SEPARATE — never squash into the implementation commit. `wt merge --no-squash` (ff-only).

### Phase 7 — Post-merge review

Re-invoke the same reviewing approach against merged HEAD on the target branch. Catches integration-emergent issues. Mandatory for multi-worktree; recommended for single-stream non-trivial.

## bd ↔ wt canonical loop

1. `bd ready` → pick next unblocked issue.
2. `bd show <id>` → load the contract.
3. `bd update <id> --claim` → mark in_progress before any work.
4. `wt switch --create <project>-<bd-id>[-suffix]` → isolated worktree. Slug embeds the bd ID.
5. Run Phases 1–7 inside the worktree.
6. `wt merge --no-squash` (ff-only) → merge to target.
7. `bd close <id>`.
8. `wt remove` → delete worktree.

## Background session worktree isolation

Background sessions (bg jobs) have a harness-level isolation guard (`bgIsolation`) that blocks file edits until the session enters a worktree. The guard only knows about `EnterWorktree`, not `wt`. Use both together:

1. `wt switch --create <project>-<bd-id>[-suffix] --yes` → creates worktree at `~/projects/worktrees/<slug>` with pre-start hooks.
2. `EnterWorktree --path ~/projects/worktrees/<slug>` → enters the wt-created worktree, satisfying the bg guard.
3. Edit files normally inside the worktree.
4. On completion: commit, then `wt merge --no-squash --yes`.
5. `ExitWorktree --action keep` → returns session to original dir. `wt remove` cleans up.

Never use bare `EnterWorktree` (without `--path`) in a bg session — it creates worktrees at `.claude/worktrees/`, bypassing wt's configured location, hooks, and tracking. The CLAUDE.md "General tools" section carries this rule so it survives context growth; this section provides the full sequence.

## Session end + handoff

1. If current bd is closed → done. No handoff needed.
2. If current bd is paused (in_progress but session ending):
   - Claude proposes a handoff proactively, OR
   - User invokes `/handoff` explicitly.
3. **Create handoff bead in `~/handoff/`** — ALWAYS in the handoff repo, NEVER in the current project's beads database (auto-inits `~/handoff/` as git repo + beads on first use):
   - `--title`: `Handoff: <project-name> (<project-path>)` — routing only, no next-action detail (that goes in description/acceptance)
   - `--description`: project dir path; active worktree + branch; **epic ID** (text reference — not a bd `--parent` link, since the handoff repo is a separate beads database); why session ended; original paused bd reference
   - `--design`: active decisions / context next session needs
   - `--acceptance`: specific next-step actions the next session should take
   - `--notes`: outstanding research; open user Qs; any context that helps the next session resume quickly
4. Handoff bead stays open until the next session consumes it (step 3 above closes it immediately after reading).
5. **Discovery at next session**: SessionStart → `bd prime` → check `~/handoff/` for open beads → read content → close handoff bead → `cd <project-dir>` → `bd show <epic-id>` + `bd ready` → present handoff context → **interactive gate** via `AskUserQuestion` (handoff's suggested task marked Recommended, other ready beads as options) → user picks → claim and begin.

## Superpowers routing table

| Phase | Skill to invoke | When |
|---|---|---|
| 1 | `superpowers:brainstorming` | Before creative work |
| 2 | `EnterPlanMode` (built-in) | Spec / multi-option decisions |
| 3 | `superpowers:writing-plans` | Before Phase 4 |
| 4 | `superpowers:executing-plans` | Implementation (single-stream) |
| 4 (parallel) | `superpowers:dispatching-parallel-agents` | When user asks for parallel work or tasks decompose |
| 5 | Host-local (see `host-local-workflow`) | After implementation |
| 6 | `superpowers:verification-before-completion` | Before claiming success |
| 7 | Same as Phase 5 | Against merged HEAD |

Also: `superpowers:test-driven-development` (when test IS the spec), `superpowers:subagent-driven-development` (in-session parallel sub-tasks), `superpowers:receiving-code-review` (processing review feedback).

<!-- setforge:user-section start host-local host-local-workflow -->

<!-- setforge:user-section end host-local host-local-workflow hash=01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b -->
