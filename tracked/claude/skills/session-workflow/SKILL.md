---
name: session-workflow
description: >-
  Strict SUBSET of session-flow. Only delta: implementation Phases 4–5 plus
  the Phase 6 merge-gate decision are driven by the session-workflow-impl.js
  Claude Code Workflow instead of run by hand. Everything else — Phases 1–3, the
  human-run merge action, Phase 7, and the whole session lifecycle — is
  unchanged from session-flow, which this skill defers to and does not replace.
when_to_use: >-
  Invoke when an approved spec plus a bd issue already exist and the
  implement → review → fix cycle should run via the parameterized workflow
  harness (mechanical, repeatable, multi-dimension review) up to a PASS/HELD
  merge gate. For the full lifecycle — brainstorm, spec, plan, handoff resume,
  epic discovery, session-end handoff, bd ↔ wt loop — use session-flow, which
  stays the default.
---

# Session Workflow

A strict SUBSET of `session-flow`. The ONLY delta: implementation Phases 4–5 plus the Phase 6 merge-gate DECISION run via the `session-workflow-impl.js` Claude Code Workflow harness rather than by hand. Use this when an approved spec and bd issue already exist and you want the research → plan → build → diff-audit → review → fix cycle run mechanically up to a computed merge gate. The harness returns a PASS/HELD gate; the human (or caller) still runs the actual `wt merge` and Phase 7 (see below).

## What is unchanged (defer to session-flow)

Do NOT duplicate these here — `session-flow` is the authority:

- **Phase 1 — Brainstorm**, **Phase 2 — Spec via plan mode**, **Phase 3 — Plan (writing-plans)**: identical. Run them via `session-flow` first.
- **Session lifecycle**: handoff resume, epic discovery (parse worktree slug `<project>-<bd-id>` → walk `--parent` to the epic), session-end handoff, the bd ↔ wt canonical loop, background-session worktree isolation.

This skill only changes HOW the implementation stages execute. Nothing else.

## The delta: workflow-backed implementation + merge gate

The harness implements one pipeline per implementation unit. Its five stages map onto Phase 4 (Research / Plan / Build) and Phase 5 (Diff-audit / Review-Fix); it ends by computing the Phase 6 merge GATE — it does NOT perform the merge:

1. **Research** — anticipatory pitfall research. Runs an inline per-dimension research prompt (modeled on the `pitfall-researcher` agent) to surface domain-specific failure modes before any code is written.
2. **Plan** — turn the spec plus researched pitfalls into the concrete build steps.
3. **Build** — run the pipeline step, then verify (tests / lint / build); quote real output.
4. **Diff-audit** — audit the produced diff against the spec and the researched pitfalls.
5. **Review / Fix** — multi-dimension review fan; fix findings; re-review. Capped at 3 iterations. Unresolved items at the cap are logged, never silently dropped.

### Hard merge gate

The harness returns a merge gate, not a merge. The gate is PASS ONLY when the worst-of-N review verdict is PASS AND zero checklist items remain present-or-unverified. The worst-of-N verdict is computed in code (BLOCK > CONCERNS > PASS), not by model judgment. Anything short of both conditions HOLDS the gate.

On a PASS gate the human (or caller) runs the Phase 6 merge action and Phase 7 by hand per `session-flow`: `wt merge --no-squash` (ff-only) → `bd close` → `wt remove`, then the post-merge review against merged HEAD. The harness never runs these.

## Launch

Once deployed (`setforge install` syncs the source to `~/.claude/workflows/session-workflow-impl.js`), invoke the harness BY NAME — not by source path:

- **Invoke**: `Workflow({ name: 'session-workflow-impl', args: { specPath, bdId, basePath } })`
  - `specPath` — path to the approved spec snapshot (required).
  - `bdId` — the bd issue carrying the contract (required).
  - `basePath` — repo / worktree root the pipeline operates in.

Keep these arg names verbatim; the workflow reads them directly. The source lives at `tracked/claude/workflows/session-workflow-impl.js`; the `name` resolves to the deployed copy under `~/.claude/workflows/`.

## See also

- `session-flow` — the superset. Owns Phases 1–3, the merge action, Phase 7, and the full session lifecycle; this skill changes only the implementation stages and the merge-gate decision.
- `pitfall-researcher` — the standalone risk-research agent; the Research phase uses an inline prompt modeled on it.
