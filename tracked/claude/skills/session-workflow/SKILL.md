---
name: session-workflow
description: Autonomous batch implementation, split by interaction shape — brainstorm/spec/carve run conversationally in the session, then the session-workflow-impl workflow script drives implement + integrated review deterministically, pausing only at the human gates (spec approval in plan mode, per-wave merges, the final full gate). Sibling of session-flow, which stays the default; invoke THIS skill only when the user explicitly picks it for a well-scoped batch of bd issues, supplying the bead IDs.
---

# Session Workflow

## When to pick this skill

Pick this skill when the user explicitly chooses it for a well-scoped batch of bd issues — `session-flow` stays the default. v4 splits the pipeline by interaction shape: phases 1–3 (brainstorm → spec → carve) are conversational and run in-session per the protocol below; the `session-workflow-impl` script (deployed to `~/.claude/workflows/`) keeps only the batch-shaped work — implement + integrated post-merge review, with a bounded, non-looping review pipeline.

The script's gate payloads are AUTHORITATIVE for per-stage mechanics: every payload carries `next` (`{stage, stateFile, stateSha, freshFields}`) and a `note` saying what the human adds — read the payload, not this file.

## Phases 1–3 (in-session)

1. **Ground.** Read bead contracts (`bd show <id>`) and repo context directly. Flag dependency-blocked or clearly unrelated selections before going further.
2. **ONE parallel research dispatch.** N read-only question-generator agents (2 light / 3 standard / 5 full), each grounding candidate design questions in actual code. One shot, no rounds. Dimensions: design-ambiguity/intent and execution/risk/acceptance-verifiability always; error-model, security, and api-misuse at full.
3. **Consolidate IN-CONTEXT.** Dedupe the candidates, detect collisions between answers, attach a recommended default to every question. No consolidator agent.
4. **ONE batched AskUserQuestion sitting** (chain calls if more than 4 questions), recommended defaults marked. Follow-ups happen conversationally — they cost seconds, not an invocation.
5. **Write the spec immediately.** The spec is the convergence artifact; residual ambiguity goes in an explicit **assumption ledger** section, adjudicated once at approval. Approval runs via plan mode (the revdiff hook fires).
6. **On approval, carve and plan waves.** Write per-bead `--design`/`--acceptance` (sequential bd writes), derive waves (bd deps HARD serializer, predicted file overlap ADVISORY), extract `checklist` (the spec's pitfall items, plus the synthetic `e2e-assert-present` entry for each risk-flagged bead) and `verifyCommands` `{cheap, full}` from the spec, and present the wave plan.

## Launching the script

```
Workflow({ name: "session-workflow-impl", args: {
  stage: "implement", beadIds: [...], repoPath, archiveDir,
  specPath, waves: [[...], ...], checklist: [...],
  verifyCommands: {cheap: [...], full: [...]}, profile: "standard",
  runStats: { epicId: "<epic-id>" },  // optional — enables the phase-7 epic bd-note
} })
```

`profile` (light/standard/full) sets the research-dispatch N above and the script's reviewer width (3 per bead, 4 at phase 7). **Risk never inflates width** — concurrency / security / data-format / irreversible changes add rigor conjuncts instead (adversarial fix verification, the `e2e-assert-present` checklist item). Until `light` has defect-escape data, route its candidates to `standard`.

The state file is the carry: every gate persists to `<archiveDir>/sw-state-<batch>.json` and returns a slim payload. Re-invoke with `next.{stage, stateFile, stateSha}` plus `beadIds` + `repoPath` plus ONLY the fresh fields the payload names — its `freshFields` derive from the script's own `REQUIRED_ARGS` table and are authoritative. Never re-paste carried state; never edit the state file (a deliberate edit means inspecting it and re-invoking with its new sha).

## Resume chaining

ALWAYS pass `resumeFromRunId` of the previous invocation together with `scriptPath` from the first launch's tool result. Every world-reading agent's prompt and journal label carries a freshness token, so replay is safe — completed agents return cached results and `/workflows` accumulates completed stages across the whole stage lineage. Each stage (`implement`, `phase7`) starts its own lineage. Across sessions, hand off the last payload's `next` (`{stage, stateFile, stateSha}`) in the handoff bead — the script sha-verifies the state, re-validates everything it loads, and probes the world before acting.

## GATE 3 — per-wave merges (the session executes)

For each merge-ready bead, with the user's go: `wt merge --no-squash` (ff-only) → `bd close <id>` → `wt remove`. NO bookkeeping transcription: the next invocation DERIVES merged beads and `mainSha` from the world (closed status + tip ancestry). Squash/cherry-pick merges and foreign main advances come back as a `CONFIRM` payload — adjudicate via `mergeOverrides: {addMerged/dropMerged: [{id, reason}]}` and/or `confirmMainAdvance: true`. `staleWorktrees` entries are the SESSION's rebase duty (wt-reference sibling pattern); rebase them, then re-invoke the same `waveCursor` — the script detects the rebase and re-reviews in-run. For HELD beads: merge the passed ones first, then re-invoke at the SAME `waveCursor` with `operatorGuidance`; keep HELD worktrees on disk until phase 7. The mid-batch targeted verify (heavy tier) is SESSION-side at this gate — the script only ever runs the cheap tier.

## FINAL — PENDING-FULL-GATE, then the report

A clean combined fan pauses with the canonical full gate UNRUN: the SESSION runs it (background it — it may take ~an hour) against main at the pinned `gateMainSha`, without letting main move first, then re-invokes with `fullGateResult: "pass" | "fail"` (+ `fullGateDetail` on fail). Pass ⇒ `DONE` and the report. A FINAL `HELD` carries per-finding evidence; there is no in-script re-fan loop to steer — `operatorGuidance` feeds the single bounded escalation only.

## Failure shapes

Route them differently — never blanket-retry an unchanged invocation:

- A structured `error` payload names a fixable args/world problem: fix it and re-invoke.
- `CONFIRM` needs your adjudication (merge derivation or main advance) — answer its `freshFields`.
- `HELD` is a report, never an auto-continue: read the evidence, steer with `operatorGuidance`, or account the bead via `droppedBeads` at phase 7.
- A gate payload carrying `stateSaveFailed` means the segment's results are valid but the carry didn't persist — clear the named problem, then re-invoke with the PREVIOUS `stateSha`.

## Permission prep (before the first run)

Workflow subagents inherit the session's tool allowlist and prompt mid-run for anything outside it. Verify the deployed settings (shipped by the setforge profile via the tracked settings.json) allow `bd` and `wt switch`/`wt list`, and DENY `git push*` — the one machine-enforced hard rail. The irreversible merge verbs (`wt merge`, `wt remove`) are deliberately NOT allowlisted: an agent attempting one stalls at a permission prompt instead of succeeding silently, while the main session still executes the ritual on the user's confirmation. `bd close` is an exception — it rides the broad `bd` allow, so an agent CAN run it; that is accepted because closes are reversible (`bd reopen`) and the ritual's real authority lives in the merge verbs.

## Relationship to session-flow

Sibling. Phases 1–3 follow `session-flow` conventions (goal surfacing, revdiff, plan mode) with the research-dispatch assist; `session-flow` keeps session lifecycle (handoff/pickup, epic discovery) and stays the default. After FINAL the session returns to `session-flow` conventions (post-merge review of the engine-side gates, handoffs, self-improvement checkpoints).
