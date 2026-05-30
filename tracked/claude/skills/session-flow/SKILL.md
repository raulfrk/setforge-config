---
name: session-flow
description: Dynamic 7-phase work flow (brainstorm → spec → plan → implement → review → fix+merge → post-merge) for single OR multiple beads, with parallel multi-bead waves, goal-wrapped review, learning mode, and host-configurable merge policy. Session lifecycle (auto-resume via handoff hook + pickup skill, epic discovery, session-end handoff). Superset of superpowers — adds bd, wt, revdiff, and handoff conventions on top. Deviation requires explicit user override. - Invoke at session start (SessionStart hook reminds you). Also invoke when starting any non-trivial task, resuming from a handoff, or when the user says 'work', 'implement', 'start working', or 'resume'.
---

Base directory for this skill: /home/raul/.claude/skills/session-flow

## Session start

1. SessionStart hooks fire `bd prime` (live workflow context) and `handoff-discovery` (scans `~/handoff`, path-matches open handoffs against the session's start dir, injects any match as context — see "Auto-resume" below).
2. This skill loads (you're reading it now). Also invoke `superpowers:using-superpowers` to establish skill-invocation discipline for the session.
3. **If the handoff hook injected a match** → invoke the `pickup` skill (it owns the resume gate: read the matched handoff(s), present context + ready beads, you pick one or several, it closes the consumed handoff, claims, and enters the flow). The hook only ever PRESENTS — it never auto-claims.
4. **Otherwise — select work:**
   - Multi-select from `bd ready`, OR the user passes bead IDs directly.
   - **One bead** → single-bead flow (Phases 1–7 over that bead).
   - **N beads** → multi-bead flow (the combined pipeline below; the gate runs ONCE over the batch).
   - If the selection mixes dependency-blocked or clearly unrelated beads → flag it, propose a grouping/sequence (or dropping some), and confirm with the user before brainstorming.
5. **Discover the current epic** (when resuming a worktree without a fresh selection) — parse the worktree slug for the bd ID → `bd show <id>` → walk `--parent` until `type == "epic"`. Works for both layouts: a single-repo project (many epics, one DB) and a monorepo (one epic per project, one shared DB).

## The 7-phase flow (STRICT GATE)

Every task MUST follow all 7 phases in order. SKIP ONLY after the user EXPLICITLY says so for THIS task — "just do it", "skip the flow", or a direct equivalent.

These signals are NOT skip-permission — they mean run the flow, just leanly: "do all N in one go", "be quick", "knock these out", "batch these", or any speed / efficiency / batching phrasing. Doing several items "in one go" means run the flow ONCE over the whole batch — one brainstorm, one spec, one plan covering all of them — never skip the phases. Do NOT treat a prior message as the consent.

If you think a task is simple enough to skip, you do NOT decide — ask via AskUserQuestion THIS turn and wait for an explicit yes.

There is no size-based "light tier": a one-line change runs the same seven phases, just proportionally briefer. The only relief valve is the explicit per-task skip above.

### Phase 1 — Brainstorm

Invoke `superpowers:brainstorming`. Explore intent, requirements, constraints with the user. **Never assume the user's decisions — ask via AskUserQuestion for every uncertainty.** Co-author the design — surface trade-offs, ask exhaustively, ground every option in concrete context. Produces or sharpens the bd issue(s). For a multi-bead session, this is ONE combined brainstorm covering all selected beads.

**Brainstorm goal (premature-convergence guard).** For complex or multi-bead brainstorms, present BOTH:
- a `/goal` sentence the user can paste — e.g. *"every design ambiguity across the selected beads is resolved and no open questions remain, or stop when I say stop"* (the evaluator forces another turn whenever the design is declared done while ambiguity remains), AND
- the plain-brainstorm alternative,
- PLUS a one-line recommendation on whether the task is complex enough to warrant the goal. `/goal` is user-typed in an interactive TUI — you cannot invoke it; you only surface the sentence.

**Pitfall research (before the spec).** At the end of brainstorm — before writing the Phase 2 spec — dispatch the `pitfall-researcher` agent (via the Agent tool) for each load-bearing risk dimension the work touches (concurrency, security, error-model, resource-leak, API-misuse, etc.). Its per-dimension smell/bug checklists populate the spec's "Bugs and code smells to avoid" section, which Phase 5 review then checks against. For a multi-bead session, run it once over the combined scope; dispatch multiple dimensions in parallel.

### Phase 2 — Spec via plan mode

`EnterPlanMode`. Write the spec VERBATIM into the plan body — no summary, no reflow. User reviews via revdiff (plan-review hook fires automatically). For a multi-bead session this is ONE combined spec covering all beads.

On approval:
- **Carve** the combined spec into each selected bead's own `--design` / `--acceptance`. Each bead keeps an independent, self-runnable contract (a carved bead's acceptance must not depend on a sibling being merged first unless a real bd dep exists). The bd issue is the durable contract; the spec file is a historical snapshot.

When writing the spec, include a "Bugs and code smells to avoid" section listing implementation pitfalls specific to the domain — populated from the Phase 1 pitfall-research checklists where available. Phase 5 review checks against these.

When revising a spec after review, open with a "Changes in this revision" section listing what changed and why — so the reviewer can focus on deltas without rereading the entire document.

### Phase 3 — Plan

Invoke `superpowers:writing-plans`. Implementation plan as a normal response (NOT plan mode). Walk implementation against actual code; verify symbol names exist; catch typos before code is written. MANDATORY before Phase 4 regardless of change size. For a multi-bead session, write **one plan per carved bead** (cross-bead ordering/overlap lives in the wave plan, Phase 4).

### Phase 4 — Implement

Invoke `superpowers:executing-plans`. TDD where the contract isn't obvious (`superpowers:test-driven-development`).

**Single bead** → single-stream implementation in the bead's worktree.

**Multiple beads** → the parallel pipeline:

1. **Wave plan.** Auto-derive parallel waves and present for approval (the user can override):
   - **bd dependencies = HARD serializer** — a bead cannot start before its blocker.
   - **predicted file overlap = ADVISORY** — flag it ("beads X, Y both touch `foo.py` — conflict likely") but still run them in parallel; conflicts are resolved at merge.
2. **Per-bead execution unit** — assess per bead-set and state the choice: either (a) each worktree runs its own Phase 4–6 autonomously (subagent implements → per-bead review fan → fixes, arriving merge-ready), or (b) worktrees code in parallel and review is centralized. Pick by how independent the beads are.
3. **Mechanism** — parallelism runs via **in-session subagents** (Task/Agent dispatch from the orchestrator), NOT separate agent-view agents. One worktree per bead (`wt switch --create` each before dispatch; see wt-reference's parallel-dispatch pattern).
4. **Autonomy** — balance per bead-set; present the level with the wave plan. Default for an approved wave: run to merge-ready and report at real gates (semantic merge conflicts, the pre-merge review handoff, blocking failures).

### Phase 5 — Review fan

Review approach is host-local — configured in the `host-local-workflow` section below.

The fan is **goal-wrapped** (iterate-to-clean). **Always surface a copy-paste `/goal` condition** that drives the host-local fan to convergence — e.g. *"the reviewing-* fan reports no Important+ findings on this diff, or stop after N turns"* — regardless of session type (`/goal` works in interactive, agent-view, and remote sessions). You emit the condition; the user pastes it, and the evaluator forces re-review until the fan comes back clean.

Additionally, when running non-interactively (no one is there to paste), also run the fan directly via subagents and loop it yourself until clean — but still surface the `/goal` condition so the user can drive it themselves when present.

**Placement:** for multi-bead work, each bead gets its review fan in its own worktree **before that bead merges**; then ONE combined goal-wrapped fan runs post-integration (Phase 7). For multi-artifact changes, review each artifact type's diff separately.

### Phase 6 — Address findings + merge

Fix ALL findings inline (CRITICAL, IMPORTANT, and MINOR) unless the fix is large or clearly out-of-scope — in that case, file a new bd with dep link. Review-fix commits stay SEPARATE — never squash into the implementation commit.

**Before each bead merges, always ask: "review this with revdiff?"** (revdiff is available on all hosts). In **learning mode** (see below), run the annotated-diff protocol instead of a plain ask.

**Merge** per the host's configured policy (see "Merge policy" below). On conflicts: resolve and continue the merge, reporting what you resolved afterward; pause and ask ONLY when a resolution is semantically load-bearing (two real behaviors collide and the wrong pick changes intent).

### Phase 7 — Post-merge review

Re-invoke the same goal-wrapped fan against merged HEAD on the target branch — ONE combined pass over the integrated result. Catches integration-emergent issues. Mandatory for multi-worktree; recommended for single-stream non-trivial.

## Multi-bead pipeline (summary)

Select beads (multi-select / IDs) → ONE combined brainstorm → ONE spec (plan mode) → carve into per-bead `--design`/`--acceptance` → per-bead `writing-plans` → auto wave plan (deps HARD, overlap ADVISORY; user-approved) → parallel implement via in-session subagents → per-bead revdiff + per-bead review fan before each merge → policy merge (resolve+report conflicts, escalate semantic) → ONE combined goal-wrapped fan post-integration → `bd close` each + `wt remove`.

## Learning mode

Some projects optimize for understanding over speed (e.g. borrowsmith). **Detection:** ask when the project is selected ("learning-focused session?"); default to yes for known learning projects.

When ON, the review step becomes a teaching protocol (per bead, parallel still allowed):
1. Write the bead's diff to a temp file with **inline explanatory annotations** — what changed, why, and the reasoning.
2. Open **revdiff** on that annotated diff for back-and-forth: the user asks questions until they fully understand the change and its rationale.
3. Then proceed to merge.

When OFF, use the standard per-bead "review with revdiff?" ask (Phase 6).

## Merge policy

Host-configurable via the `merge-policy` user-section below. Modes:
- **`ff-only`** — fast-forward only, linear history (default for single-bead, linear work).
- **`merge-commit`** — real merge commit (parallel siblings whose history can't fast-forward).
- **`amend`** — fold the change into an existing commit.

This host's default is in the user-section. Parallel multi-bead auto-switches to `merge-commit` when siblings can't fast-forward. Conflict authority is in Phase 6 (resolve + report; escalate only semantic collisions).

## bd ↔ wt canonical loop

1. `bd ready` → pick next unblocked issue (or multi-select for a batch).
2. `bd show <id>` → load the contract.
3. `bd update <id> --claim` → mark in_progress before any work.
4. `wt switch --create <project>-<bd-id>[-suffix]` → isolated worktree. Slug embeds the bd ID. (Multi-bead: one worktree per bead.)
5. Run Phases 1–7 inside the worktree(s).
6. Merge per the configured policy (default `wt merge --no-squash` ff-only) → target.
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

## Auto-resume (handoff discovery)

A SessionStart hook (`handoff-discovery`) makes resume frictionless — no need to type "resume from handoff". It is local-only (the `~/handoff` repo is a local concept; the hook no-ops where `~/handoff` is unreachable).

The hook:
- Reads open handoff beads from `~/handoff` (creating + initializing the repo if missing).
- Path-matches each handoff's tagged sub-project path against the session's start dir (`$CLAUDE_PROJECT_DIR`) using a true path-boundary test ("at or below"). One match → inject it; several (a monorepo root over multiple sub-projects) → inject all matching; zero → stay silent.
- Injects matching handoff(s) as context pointing to the `pickup` skill. It never auto-claims.

The `pickup` skill owns the gate: present the matched handoff(s) + each project's `bd ready`, let the user pick one or several (several → feeds the multi-bead flow), close the consumed handoff bead(s), claim, and enter the flow.

## Session end + handoff

1. If current bd is closed → done. No handoff needed.
2. If current bd is paused (in_progress but session ending):
   - Claude proposes a handoff proactively, OR
   - User invokes `/handoff` explicitly.
3. **Create handoff bead in `~/handoff/`** — ALWAYS in the handoff repo, NEVER in the current project's beads database (auto-inits `~/handoff/` as git repo + beads on first use). See the `handoff` skill for the full field shape; critically, it records the **exact sub-project working path** so `handoff-discovery` can disambiguate (essential in a monorepo where several projects share one repo root).
4. Handoff bead stays open until the next session consumes it — the `pickup` skill closes it after the user picks what to resume, never before the gate.
5. **Discovery at next session**: SessionStart → `bd prime` + `handoff-discovery` hook → path-matched handoff(s) injected → invoke `pickup` → present context → user picks → claim and begin.

## Superpowers routing table

| Phase | Skill to invoke | When |
|---|---|---|
| 1 | `superpowers:brainstorming` | Before creative work |
| 2 | `EnterPlanMode` (built-in) | Spec / multi-option decisions |
| 3 | `superpowers:writing-plans` | Before Phase 4 |
| 4 | `superpowers:executing-plans` | Implementation (single-stream) |
| 4 (parallel) | `superpowers:dispatching-parallel-agents` / `superpowers:subagent-driven-development` | Multi-bead waves / in-session parallel |
| 5 | Host-local (see `host-local-workflow`) | After implementation |
| 6 | `superpowers:verification-before-completion` | Before claiming success |
| 7 | Same as Phase 5 | Against merged HEAD |

Also: `superpowers:test-driven-development` (when test IS the spec), `superpowers:subagent-driven-development` (in-session parallel sub-tasks), `superpowers:receiving-code-review` (processing review feedback).

<!-- setforge:user-section start host-local host-local-workflow -->

<!-- setforge:user-section end host-local host-local-workflow hash=01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b -->

<!-- setforge:user-section start host-local merge-policy -->
**Merge policy (this host).** Default merge mode: `ff-only`. Parallel multi-bead auto-switches to `merge-commit` when siblings cannot fast-forward.
<!-- setforge:user-section end host-local merge-policy hash=87509232c71003f90bd3905c33b5e7de9cfbbde95ddc73d73a85aa44f01e7729 -->
