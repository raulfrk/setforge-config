---
name: session-flow
description: Dynamic 7-phase work flow (brainstorm → spec → plan → implement → review → fix+merge → post-merge) for single OR multiple beads, with parallel multi-bead waves, goal-wrapped review, learning mode, and host-configurable merge policy. Session lifecycle (opt-in handoff resume via the pickup skill, epic discovery, session-end handoff). Superset of superpowers — adds bd, wt, revdiff, and handoff conventions on top. Deviation requires explicit user override. - Invoke when starting any non-trivial task, resuming from a handoff, or when the user says 'work', 'implement', 'start working', or 'resume'.
---

Base directory for this skill: /home/raul/.claude/skills/session-flow

## Session start

1. This skill loads when you invoke it — no SessionStart hook fires it; work-mode is opt-in. Also invoke `superpowers:using-superpowers` to establish skill-invocation discipline for the session.
2. **Resolve the review surface** (do this once, up front). Read the `review-surface` setting — `webdiff` (default) or `revdiff`. If unset, default to `webdiff`; if `webdiff` resolves but no browser/hub is reachable, fall back to `revdiff` (prompt only when genuinely ambiguous). Every later human review gate — Phase-1 mockup, Phase-2 plan-review, Phase-5/6 diff review, and learning mode — inherits this surface. See "Review surface" below.
3. **Check for a paused handoff** → invoke the `pickup` skill. It scans `~/handoff`, path-matches open handoffs against the session's start dir, and owns the resume gate (present the matched handoff(s) + ready beads; you pick one or several; it closes the consumed handoff, claims, and enters the flow). If nothing matches it says so and falls through to fresh selection. NEVER auto-claim — the user always picks.
4. **Select work** (no handoff, or you declined resume):
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

**Brainstorm goal (premature-convergence guard) — surface `/goal`, then END THE TURN.** For complex or multi-bead brainstorms, surface it once and END THE TURN so the evaluator engages. **When you surface it depends on the method:** a question-led brainstorm surfaces it FIRST (before grounding or any clarifying question); the **brain-dump-first technique** (below) surfaces it at the **clarifying-questions / convergence boundary** — *after* the brain-dump, discussion, and mockups — because surfacing it at brainstorm-start forces premature convergence (you build a strawman before the user has dumped). When you do surface it:
1. Present the copy-paste `/goal` sentence the user can paste — e.g. *"every design ambiguity across the selected beads is resolved and no open questions remain, or stop when I say stop"* (the evaluator forces another turn whenever the design is declared done while ambiguity remains).
2. Present the plain-brainstorm alternative.
3. Give a one-line recommendation on whether the task is complex enough to warrant the goal.
4. **END THE TURN.** Do NOT proceed to clarifying questions, and do NOT call `EnterPlanMode`, until the user has set or declined the goal. `/goal` is user-typed in an interactive TUI — you cannot invoke it; you surface the sentence, then stop so the user can paste it. Surfacing it mid-turn and continuing in the same turn defeats the evaluator (it engages only between turns).

**Brainstorm technique for complex / open-ended designs (brain-dump → elicit → mockup).** When scope is large or the user is still figuring requirements out, do NOT open with a question barrage — it converges prematurely and reads as an interrogation. Instead:
1. **Brain-dump first.** Invite the user to dump freely — vision, components, constraints, non-goals — in their own order, before any structured questions. Offer a light scaffold, but let them lead.
2. **Actively elicit per component.** As each component surfaces, prod for the missing detail before moving on — what & why, interface/shape (config / API / CLI), behavior on the key paths, edge cases, interactions, non-goals. Do NOT let a component pass at one sentence. Once eliciting, the `AskUserQuestion`-exhaustive rule still applies — batch grounded questions, just don't revert to an opening barrage.
3. **Mock up for alignment.** Show concrete "here's what it would look like" artifacts (mockups, CLI/API/UX sketches, diagrams) and iterate them with the user in **manual revdiff** — sanctioned design exploration, distinct from the Phase-2 spec (which lives in the plan file, reached via the plan-review hook). Abstract agreement is NOT alignment — the mockup confirms you built the same picture.
4. **Then surface `/goal`** (per *Brainstorm goal* above). The brain-dump-first method intentionally **delays the goal to here** — the clarifying-questions / convergence boundary — so it guards against declaring-done-with-ambiguity without pre-empting the dump. Surfacing it at brainstorm-start would force a strawman before the user has led.

**Track component state throughout** (`SETTLED` / `LEANING` / `OPEN`) so the open set is the visible work-list and shrinks each pass.

**Pitfall research (before the spec).** At the end of brainstorm — before writing the Phase 2 spec — dispatch the `pitfall-researcher` agent (via the Agent tool) for each load-bearing risk dimension the work touches (concurrency, security, error-model, resource-leak, API-misuse, etc.). Its per-dimension smell/bug checklists populate the spec's "Bugs and code smells to avoid" section, which Phase 5 review then checks against. For a multi-bead session, run it once over the combined scope; dispatch multiple dimensions in parallel.

### Phase 2 — Spec via plan mode

When the brainstorm design converges, the FIRST action of Phase 2 is
`EnterPlanMode` — BEFORE drafting any spec text; the verbatim spec is written
into the plan file, never a standalone temp file.

`EnterPlanMode`. Open the plan with the PART-0 decision layer from the
"Presentation contract" section below (decision ledger + pictures + cut
line); it REPLACES the older plain-language summary section. Then write
the spec VERBATIM into the plan body below the cut line — no summarizing
or reflowing the spec ITSELF. User reviews via revdiff (plan-review hook fires automatically) — do NOT open revdiff on a spec file MANUALLY: the spec lives in the plan file and revdiff is reached via the plan-review hook on `ExitPlanMode`. If you used manual revdiff for design exploration during the Phase-1 brainstorm, transition to plan mode the moment the design converges; manual-revdiff-on-a-spec is the tell that you skipped `EnterPlanMode`. For a multi-bead session this is ONE combined spec covering all beads.

On approval:
- **Carve** the combined spec into each selected bead's own `--design` / `--acceptance`. Each bead keeps an independent, self-runnable contract (a carved bead's acceptance must not depend on a sibling being merged first unless a real bd dep exists). The bd issue is the durable contract; the spec file is a historical snapshot.

When writing the spec, include a "Bugs and code smells to avoid" section listing implementation pitfalls specific to the domain — populated from the Phase 1 pitfall-research checklists where available. Phase 5 review checks against these.

When revising a spec after review, place a "Changes in this revision" section directly under the PART-0 layer, listing what changed and why — so the reviewer can focus on deltas without rereading the entire document.

Before requesting approval, run a **decision-coverage check**: walk every Phase-1 `AskUserQuestion` answer and confirm each is reflected in the spec — and survives into the carved `--design` / `--acceptance`. A decision the user explicitly made that silently fails to land in the spec won't get built; without this check, review (or the user) becomes the last line of defense instead of the spec.

### Phase 3 — Plan

Invoke `superpowers:writing-plans`. Implementation plan as a normal response (NOT plan mode). The plan opens with the Presentation contract's PART-0 layer — a ledger of what is being approved NOW (verified surprises, new deps, execution mechanics), pictures, and the cut line. Walk implementation against actual code; verify symbol names exist; catch typos before code is written. MANDATORY before Phase 4 regardless of change size. For a multi-bead session, write **one plan per carved bead** (cross-bead ordering/overlap lives in the wave plan, Phase 4).

### Phase 4 — Implement

Invoke `superpowers:executing-plans`. TDD where the contract isn't obvious (`superpowers:test-driven-development`).

**Single bead** → single-stream implementation in the bead's worktree.

**Multiple beads** → the parallel pipeline:

1. **Wave plan.** Auto-derive parallel waves and present for approval (the user can override) as a wave DIAGRAM (one box per worktree, arrows per dependency) plus a mechanics ledger per the Presentation contract — not prose paragraphs:
   - **bd dependencies = HARD serializer** — a bead cannot start before its blocker.
   - **predicted file overlap = ADVISORY** — flag it ("beads X, Y both touch `foo.py` — conflict likely") but still run them in parallel; conflicts are resolved at merge.
2. **Per-bead execution unit** — assess per bead-set and state the choice: either (a) each worktree runs its own Phase 4–6 autonomously (subagent implements → per-bead review fan → fixes, arriving merge-ready), or (b) worktrees code in parallel and review is centralized. Pick by how independent the beads are.
3. **Mechanism** — parallelism runs via **in-session subagents** (Task/Agent dispatch from the orchestrator), NOT separate agent-view agents. One worktree per bead (`wt switch --create` each before dispatch; see wt-reference's parallel-dispatch pattern).
4. **Autonomy** — balance per bead-set; present the level with the wave plan. Default for an approved wave: run to merge-ready and report at real gates (semantic merge conflicts, the pre-merge revdiff offer (Phase 6) — which "merge-ready" includes making, never bypassing — blocking failures).
5. **Gate + blast-radius discipline** — every gate command quotes its real exit code (`cmd; echo EXIT=$?`, or `set -o pipefail` before any pipeline); dispatched agents must quote explicit exit codes — a bare `cmd | tail` pipeline status is not evidence. A cross-cutting change (output-stream move, rename, flag or user-visible text change) additionally requires `rg` of the moved token/symbol across the WHOLE test tree — including e2e files the bead's own gates never execute — before reporting merge-ready (complements Phase 7's post-merge pass; does not replace it).

### Phase 5 — Review fan

Use the custom multi-aspect review fans, picked by artifact type:
- `reviewing-python-code` — Python source / pyproject / CI / pre-commit (4 aspect agents: spec, substance, specifics, prose).
- `reviewing-claude-md` — docs / skills / agents under `tracked/claude/` (5 aspect agents).
- `reviewing-markdown` — generic `.md` outside `tracked/claude/` (1 prose agent).
- `reviewing-rust-code` — Rust source / Cargo manifests / toolchain + lint configs / Rust CI (3 aspect agents: spec, substance, specifics; runs clippy + fmt once and feeds the output to the agents).
- `reviewing-bd-leaks` — ALWAYS, regardless of artifact type (1 agent: bd-leak-reviewer). Scans the whole diff + commit messages + PR body for leaked Beads / bd task-tracker references in shipping artifacts. Invoke it in parallel with whichever artifact fans apply; the artifact fans do not scan for tracker leaks themselves.

Mixed-artifact changes invoke every applicable fan in parallel; review each artifact type's diff separately. `reviewing-bd-leaks` runs in every case.

Fan outcomes and mid-wave status updates are presented verdict-table-first (one line per bead or aspect, findings below) per the Presentation contract.

The fan is **goal-wrapped** (iterate-to-clean). Before dispatching it:
1. **Surface a copy-paste `/goal` review condition** that drives the fan to convergence — e.g. *"the reviewing-* fan reports no Important+ findings on this diff (each finding fixed or triaged to a follow-up bead), or stop after N turns"* — regardless of session type (`/goal` works in interactive, agent-view, and remote sessions). If a finding is too large to fix in-session and the user **defers** it to a follow-up bead, the named diff can no longer be made clean and the goal will not auto-clear — tell the user to `/goal clear` (the legitimate "scope changed" exception to the usual don't-suggest-clear rule).
2. **END THE TURN** so the user can paste it; the evaluator then forces re-review until the fan comes back clean. As in Phase 1, surfacing the condition and continuing in the same turn defeats the evaluator.

Additionally, when running non-interactively (no one is there to paste), also run the fan directly via subagents and loop it yourself until clean — but still surface the `/goal` condition so the user can drive it themselves when present.

**A clean fan ≠ merge-authorized.** The review-fan `/goal` and its "don't pause to ask" directive govern the automated fan loop ONLY — neither discharges the Phase-6 human revdiff gate. A clean fan means the diff converged, not that it may merge. With a review-`/goal` active, still surface the "review this with revdiff?" offer before merging; it is the gate the goal converges toward, not a pause to skip.

**Placement:** for multi-bead work, each bead gets its review fan in its own worktree **before that bead merges**; then ONE combined goal-wrapped fan runs post-integration (Phase 7). For multi-artifact changes, review each artifact type's diff separately.

### Phase 6 — Address findings + merge

Fix ALL findings inline (CRITICAL, IMPORTANT, and MINOR) unless the fix is large or clearly out-of-scope — in that case, file a new bd with dep link. Review-fix commits stay SEPARATE — never squash into the implementation commit.

**Before each bead merges, always ask WHICH review surface to use: `revdiff` (terminal TUI) or `webdiff` (served web page — each change with its authored rationale beside the syntax-highlighted hunk, inline annotations, and a Submit button that auto-resumes you).** Both are available on all hosts; pick by what the diff needs — revdiff for a fast in-terminal pass, webdiff when rationale-beside-code, colour, or phone/iPad review matters. Under an APPROVED wave plan the offers may be batched per sub-wave instead of per bead. In **learning mode** (see below), run the annotated-diff protocol instead of a plain ask.

This gate is MANDATORY: a clean review fan, an active review-`/goal`, and "run to merge-ready" autonomy do NOT discharge it — they cover the automated fan, while the revdiff/webdiff offer is the separate human gate that still fires before any merge. In a background session it opens in the attached tmux popup (revdiff) or over the tailnet (webdiff) — never downgrade to an inline-only proposal because the session is backgrounded. **A bead is not merge-ready until this offer has been made and resolved.**

**Merge** per the host's configured policy (see "Merge policy" below). For multi-bead waves the merge gate runs per bead, SERIALLY at the orchestrator: rebase the worktree onto the target, run the full unit suite plus the bead's expensive integration subset (expensive subsets never run inside parallel implementers — shared daemons/hosts saturate), then merge and `bd close`. On conflicts: resolve and continue the merge, reporting what you resolved afterward; pause and ask ONLY when a resolution is semantically load-bearing (two real behaviors collide and the wrong pick changes intent).

### Phase 7 — Post-merge review

Re-invoke the same goal-wrapped fan against merged HEAD on the target branch — ONE combined pass over the integrated result. Catches integration-emergent issues. Mandatory for multi-worktree; recommended for single-stream non-trivial.

## Multi-bead pipeline (summary)

Select beads → ONE combined brainstorm → ONE spec (plan mode) → carve per-bead contracts → per-bead plans → wave plan (deps HARD, overlap ADVISORY; user-approved) → parallel implement → per-bead fan + serial merge gate (revdiff offers may batch per sub-wave) → ONE combined fan post-integration → `bd close` each.

## Learning mode

Some projects optimize for understanding over speed. **Detection:** learning mode is **opt-in** — default to the standard flow, and offer it ("learning-focused session?") only when a project's own project-scoped instructions mark it learning-default, or the user asks. Do not auto-enable it by project name.

When ON, the review step becomes a teaching protocol (per bead, parallel still allowed):
1. Write the bead's diff to a temp file with **inline explanatory annotations** — what changed, why, and the reasoning.
2. Open **revdiff** on that annotated diff for back-and-forth: the user asks questions until they fully understand the change and its rationale.
3. Then proceed to merge.

When OFF, use the standard per-bead "review with revdiff?" ask (Phase 6).

## Review surface

Every human review gate — Phase-1 mockup, Phase-2 plan-review, Phase-5/6 diff review, learning mode — renders through ONE configurable surface, resolved once at session start (step 2):

- **`webdiff`** (default) — a served web page over the tailnet: each change with its authored rationale beside the syntax-highlighted hunk, embedded diagrams/charts, a section overview map, per-section reviewed-ticks with close-gating, inline annotations, and a Submit button that auto-resumes you. Best when rationale-beside-code, colour, diagrams, or phone/iPad review carry the meaning.
- **`revdiff`** — terminal TUI; the **no-browser fallback**, and the right pick for a fast in-terminal pass.

The `review-surface` setting (`webdiff` | `revdiff`) is a **plain documented setting** read at session start — NOT a user-section and NOT external config. Resolution: use the set value; if unset, default to `webdiff`; if `webdiff` is selected but no browser/hub is reachable, fall back to `revdiff`. The user can override per session or per review. Both surfaces emit annotations in the same `## file:line (type)` markdown (one shared parser), so a single review can even hand off between them.

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

## Session end + handoff

1. If current bd is closed → done. No handoff needed.
2. If current bd is paused (in_progress but session ending):
   - Claude proposes a handoff proactively, OR
   - User invokes `/handoff` explicitly.
3. **Create handoff bead in `~/handoff/`** — ALWAYS in the handoff repo, NEVER in the current project's beads database (auto-inits `~/handoff/` as git repo + beads on first use). See the `handoff` skill for the full field shape; critically, it records the **exact sub-project working path(s)** — one `Workdir:` line per dir the work touches — so the `pickup` scan can disambiguate (essential in a monorepo where several projects share one repo root, or when one handoff spans several repos).
4. Handoff bead stays open until the next session consumes it — the `pickup` skill closes it after the user picks what to resume, never before the gate.
5. **Discovery at next session**: the next session invokes `pickup` (or `session-flow`, which checks pickup at step 2) → pickup scans `~/handoff`, path-matches → presents context → user picks → claim and begin. No hook fires this; resume is opt-in.

## Superpowers routing table

| Phase | Skill to invoke | When |
|---|---|---|
| 1 | `superpowers:brainstorming` | Before creative work — surface `/goal` + END TURN before any clarifying question |
| 2 | `EnterPlanMode` (built-in) | Spec / multi-option decisions |
| 3 | `superpowers:writing-plans` | Before Phase 4 |
| 4 | `superpowers:executing-plans` | Implementation (single-stream) |
| 4 (parallel) | `superpowers:dispatching-parallel-agents` / `superpowers:subagent-driven-development` | Multi-bead waves / in-session parallel |
| 5 | `reviewing-*` fan by artifact type (see Phase 5) | After implementation — surface `/goal` review condition + END TURN before dispatching the fan |
| 6 | `superpowers:verification-before-completion` | Before claiming success |
| 7 | Same as Phase 5 | Against merged HEAD |

Also: `superpowers:test-driven-development` (when test IS the spec), `superpowers:subagent-driven-development` (in-session parallel sub-tasks), `superpowers:receiving-code-review` (processing review feedback).

## Presentation contract (decision-first artifacts)

Applies to: Phase-2 specs, Phase-3 per-bead plans, Phase-4 wave plans, the
pickup skill's resume summaries, Phase-5/7 fan reports, and multi-step
status updates. Every such artifact opens with a PART-0 decision layer:

1. **Header** — one sentence: what + why.
2. **Decision ledger** — numbered table, one line per decision or state the
   reader must ratify.
3. **Picture** — at least one ASCII before/after mockup or flow diagram
   WHENEVER the change alters CLI output, a prompt, a file the user reads,
   or a flow's order.
4. **Cut line** — a literal "Decide here" stop marker (template below):
   everything requiring ratification sits above it.
5. **Budget** — PART 0 fits one screen (~40 lines). The FULL verbatim body
   (spec text, per-bead plans, findings) sits below the cut line and is
   never replaced by the summary.

Template emitted into artifacts (the glyphs live ONLY in emitted
artifacts — this skill's own prose stays emoji-free):

```
# ⚡ PART 0 — THE 2-MINUTE VERSION
<one sentence: what + why>
| # | Decision |          <- numbered ledger, one line each
<ASCII mockup / diagram>  <- required iff a user-facing surface changes
## 🛑 Decide here          <- cut line
---
# PART 1 — FULL DETAIL    <- verbatim body, never summarized away
```

Precedence: the Phase 1 / Phase 5 `/goal` surface-then-END-TURN rules take
precedence over any presentation boundary — this contract changes how
artifacts LOOK, never when turns end.

## Self-improvement

While using this skill, stay alert for any *generic* way it could be better — clearer wording, a missing case, a smoother step, a recurring friction it should prevent. Not only failures; any worthwhile improvement, noticed anytime.

- **Don't edit mid-task.** Capture the observation; keep working.
- **At a completion checkpoint** (a finished unit of work before the next, or session end), pause and, if anything surfaced, propose it as a diff to THIS file via revdiff — one edit per idea, citing what prompted it.
- **Generic only.** Global config used across every project; never bake in project-specific detail (paths, repo/profile names, bead IDs) unless this artifact is itself project-scoped.
- **Never auto-apply.** Propose via revdiff; the user approves every edit. Never write it yourself.
- **Off-limits — never propose edits to:** hard rails, the safety/environment sections, system paths, `setforge:user-section` marker lines or their `hash=`, and *this self-improvement protocol itself* (the mechanism may not rewrite its own leash).
- **Substantive, not noise.** Rare and load-bearing; not cosmetic rewording; never re-propose a declined idea.

**Precedence note (this skill):** the Phase 1 / Phase 5 `/goal` surface-then-END-TURN always takes precedence at a brainstorm or review boundary. A self-improvement pause waits for an actual task-completion or session-end checkpoint and never preempts a `/goal` surface.

<!-- setforge:user-section start host-local merge-policy -->
**Merge policy (this host).** Default merge mode: `ff-only`. Parallel multi-bead auto-switches to `merge-commit` when siblings cannot fast-forward.
<!-- setforge:user-section end host-local merge-policy hash=87509232c71003f90bd3905c33b5e7de9cfbbde95ddc73d73a85aa44f01e7729 -->
