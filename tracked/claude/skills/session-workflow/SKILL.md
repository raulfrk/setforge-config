---
name: session-workflow
description: Autonomous batch implementation via the session-workflow-impl workflow — the full 7-phase methodology driven by a deterministic script, pausing only at the human gates (brainstorm answers, spec approval, per-wave merges, the final full gate). Sibling of session-flow, which stays the default; invoke THIS skill only when the user explicitly picks it for a well-scoped batch of bd issues, supplying the bead IDs.
---

# Session Workflow

Pick this skill when a batch of bd issues is well-scoped enough to run autonomously — the `session-workflow-impl` workflow script (deployed to `~/.claude/workflows/`) drives intake → spec → implement → integration deterministically, and the main session's only jobs are relaying the human gates, the merge ritual, and the session-side duties below.

The script's gate payloads are AUTHORITATIVE for per-stage mechanics: every payload carries `next` (`{stage, stateFile, stateSha, freshFields}`) and a `note` saying what the human adds — read the payload, not this file.

## Launching

```
Workflow({ name: "session-workflow-impl", args: {
  stage: "intake", beadIds: [...], repoPath: "<project root>",
  archiveDir: "<spec/state/report home, OUTSIDE repoPath>", profile: "standard",
} })
```

`archiveDir` is required at launch — gate state persists there from round 1. `specFileName` joins at the converged GATE 1, exactly as its note instructs. Optional at any invocation: `convergeMode: "thorough" | "fast" | "freeze"` (fast = consolidate aggressively, surface blocking questions only; freeze = stop asking, derive the rest, halve the review-loop backstop) and `maxOperatorRounds` (default 3).

## The gate loop

One rule above all: **the state file is the carry**. Every gate persists its full state to `<archiveDir>/sw-state-<batch>.json` and returns a slim payload; re-invoke with `next.stage` + `next.stateFile` + `next.stateSha` plus ONLY the fresh human input the payload's `note` names. Never re-paste carried state; never edit the state file (a deliberate edit means inspecting it and re-invoking with its new sha). One run per batch — the state file is keyed by the bead set.

- **GATE 1 — brainstorm (≤3 operator rounds by default).** Only BLOCKING questions arrive — semantically deduped by a consolidator; REFINEMENT questions are auto-answered by a delegate citing the posture distilled from your answers (its ledger rides every payload). Present the questions (AskUserQuestion; end with a free-text "anything else to add?"), re-invoke with the new `gate1Answers` only. Answer `"DEFER"` on an expands-contract question to push it to a GATE 2 follow-up proposal. Past the round cap, leftover blocking questions become explicit spec assumptions.
- **GATE 2 — spec approval.** Review the spec file via revdiff / plan mode, plus three payload sections: `assumptions` (cap leftovers + freeze derivations), `delegateLedger` (now ratified — object by re-invoking at stage `spec` with `delegateRatifications: {id: "reopen"}`), and `followUpProposals` (file approved ones with bd YOURSELF — the script never files). On approval re-invoke with `specApproved: true`; on edits, re-invoke at stage `spec` with direction in `gate1Answers.extraNotes`.
- **GATE 3 — per-wave merges (the session executes).** For each merge-ready bead, with the user's go: `wt merge --no-squash` (ff-only) → `bd close <id>` → `wt remove`. NO bookkeeping transcription: the next invocation DERIVES merged beads and `mainSha` from the world (closed status + tip ancestry). Squash/cherry-pick merges and foreign main advances come back as a `CONFIRM` payload — adjudicate via `mergeOverrides: {addMerged/dropMerged: [{id, reason}]}` and/or `confirmMainAdvance: true`. `staleWorktrees` entries are the SESSION's rebase duty (wt-reference sibling pattern); rebase them, then re-invoke the same `waveCursor` — the script detects the rebase and re-reviews in-run. For HELD beads: merge the passed ones first, then re-invoke at the SAME `waveCursor` with `operatorGuidance`; keep HELD worktrees on disk until phase 7.
- **FINAL — `PENDING-FULL-GATE`, then the report.** A clean combined fan pauses with the canonical full gate UNRUN: the SESSION runs it (background it — it may take ~an hour) against main at the pinned `gateMainSha`, without letting main move first, then re-invokes with `fullGateResult: "pass" | "fail"` (+ `fullGateDetail` on fail). Pass ⇒ `DONE`; fail ⇒ findings re-enter the loop. A FINAL `HELD` is re-invocable via its `next` (triage bookkeeping and the fix record carried).

## Routing

| Profile | Research dims | Reviewers | Rounds backstop |
|---|---|---|---|
| `light` | 2 | 1 | 4 |
| `standard` | 3 | 3 | 6 |
| `full` | all 5 | 8 | 10 |

The backstop is NOT the review exit — every profile's loops run converge-until-clean (a zero-finding full-fan round exits); the backstop only catches runaway loops as HELD (`freeze` halves it, floor 2). Pick by batch size and risk; **risk is a hard veto**: any concurrency / security / data-format / irreversible change forces `full`, whatever the size. Until `light` has defect-escape data on real batches, route its candidates to `standard`. Every generative and judging agent runs on the session model; only verbatim-echo agents down-tier.

## Permission prep (before the first run)

Workflow subagents inherit the session's tool allowlist and prompt mid-run for anything outside it. Verify the deployed settings (shipped by the setforge profile via the tracked settings.json) allow `bd` and `wt switch`/`wt list`, and DENY `git push*` — the one machine-enforced hard rail. The irreversible merge verbs (`wt merge`, `wt remove`) are deliberately NOT allowlisted: an agent attempting one stalls at a permission prompt instead of succeeding silently, while the main session still executes the ritual on the user's confirmation. `bd close` is an exception — it rides the broad `bd` allow, so an agent CAN run it; that is accepted because closes are reversible (`bd reopen`) and the ritual's real authority lives in the merge verbs.

## Re-entry and recovery

- **Within a session**, a crashed or stopped invocation resumes with `Workflow({scriptPath, resumeFromRunId})` — completed agents return cached results. The journal is same-session only.
- **Across sessions**, hand off `{stage, stateFile, stateSha}` (the last payload's `next`) in the handoff bead. Stages re-run from their start — side effects are idempotent by contract — and the script sha-verifies the state, re-validates everything it loads, and probes the world before acting (stale carries are refused, not absorbed).
- **Route the failure shapes differently.** A structured `error` payload names a fixable args/world problem: fix it and re-invoke. `CONFIRM` needs your adjudication (merge derivation or main advance) — answer its `freshFields`. `HELD` is a report, never an auto-continue: read the evidence, steer with `operatorGuidance`, or account the bead via `droppedBeads` at phase 7. Never blanket-retry an unchanged invocation.

## Relationship to session-flow

`session-flow` owns interactive work, session lifecycle (handoff/pickup, epic discovery), and stays the default. This skill owns nothing of that — it is the throughput tool the user explicitly reaches for, and after FINAL the session returns to `session-flow` conventions (post-merge review of the engine-side gates, handoffs, self-improvement checkpoints).
