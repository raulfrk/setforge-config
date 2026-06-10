---
name: session-workflow
description: Autonomous batch implementation via the session-workflow-impl workflow — the full 7-phase methodology driven by a deterministic script, pausing only at three human gate kinds (brainstorm answers, spec approval, per-wave merges). Sibling of session-flow, which stays the default; invoke THIS skill only when the user explicitly picks it for a well-scoped batch of bd issues, supplying the bead IDs.
---

# Session Workflow

Pick this skill when a batch of bd issues is well-scoped enough to run autonomously — the `session-workflow-impl` workflow script (deployed to `~/.claude/workflows/`) drives intake → spec → implement → integration deterministically, and the main session's only jobs are relaying the three human gates and executing the merge ritual.

The script's gate payloads are AUTHORITATIVE for all per-stage argument mechanics: every payload carries `nextArgs` (the exact args object for the next invocation) and a `note` saying what the human adds — read the payload, not this file.

## Launching

Invoke the workflow by name with the opening args:

```
Workflow({ name: "session-workflow-impl", args: {
  stage: "intake", beadIds: [...], repoPath: "<project root>", profile: "standard",
} })
```

`archiveDir` (spec/report destination, OUTSIDE repoPath) and `specFileName` join at the spec gate, exactly as the converged GATE 1 note instructs.

## The gate loop

One rule above all: **merge, never replace**. Re-invoke with the payload's `nextArgs` object WHOLE, adding only what its `note` names. Hand-pruning carried fields is the corruption class the script's validators exist to refuse.

- **GATE 1 — brainstorm (loops to convergence).** Present every question from the payload to the user (AskUserQuestion; chain calls when more than four), ALWAYS ending the batch with a free-text "do you have anything else to add?". Merge the answers (and any additions) into `gate1Answers`, re-invoke with `nextArgs`. Repeat until the payload says `converged: true`.
- **GATE 2 — spec approval.** Present the spec file to the user via revdiff / plan mode. On approval set `specApproved: true` in `nextArgs` and re-invoke; on edits, fold the user's direction into `gate1Answers.extraNotes` and re-run the spec stage so the artifact regenerates.
- **GATE 3 — per-wave merges (the main session executes; agents are denied these verbs).** For each merge-ready bead, with the user's go: `wt merge --no-squash` (ff-only) → `bd close <id>` → `wt remove`. Append merged ids to `nextArgs.mergedBeads` and record the new `mainSha` (the payload froze `preWaveSha` automatically at wave 1). For HELD/BLOCKED beads: merge the passed ones first, then re-invoke at stage `implement` with the SAME `waveCursor` and a fenced `operatorGuidance` entry per bead, crafted from the bd note's unresolved-finding details. A BLOCKED bead's worktree is mid-rebase BY DESIGN — resolve the markers (or leave them) before retrying; keep every HELD bead's worktree on disk until phase 7.
- **FINAL — the run report.** `DONE` means the combined fan converged and the full canonical gate passed. `HELD` is re-invocable with its own `nextArgs` (triage bookkeeping, fix record, and the post-fix main tip all carried) — verify `mainSha` still matches the live tip first.

## Routing

| Profile | Research dims | Reviewers | Rounds backstop |
|---|---|---|---|
| `light` | 2 | 1 | 4 |
| `standard` | 3 | 3 | 6 |
| `full` | all 5 | 8 | 10 |

The backstop is NOT the review exit — every profile's loops run converge-until-clean (a zero-finding full-fan round exits); the backstop only catches runaway loops as HELD. Pick by batch size and risk; **risk is a hard veto**: any concurrency / security / data-format / irreversible change forces `full`, whatever the size. Until `light` has defect-escape data on real batches, route its candidates to `standard`. Every generative and judging agent runs on the session model; only verbatim-echo agents down-tier.

## Permission prep (before the first run)

Workflow subagents inherit the session's tool allowlist and prompt mid-run for anything outside it. Verify the deployed settings allow `bd` and `wt switch`/`wt list`, and DENY `git push*` — the one machine-enforced hard rail. Merge-gate verbs (`wt merge`, `wt remove`, `bd close`) are deliberately NOT allowlisted: an agent attempting one stalls at a permission prompt instead of succeeding silently, while the main session still executes the ritual on the user's confirmation. These rules ship with the setforge profile (the tracked settings.json); this skill only states the requirement.

## Re-entry and recovery

- **Within a session**, a crashed or stopped invocation resumes with `Workflow({scriptPath, resumeFromRunId})` — completed agents return cached results. The journal is same-session only.
- **Across sessions**, hand off `{stage, intakeRound/waveCursor, args}` (the last payload's `nextArgs`) in the handoff bead. Stages re-run from their start — side effects are idempotent by contract — and the script's world-state probe refuses stale carries rather than acting on them.
- **Route the three failure shapes differently.** A structured `error` payload names a fixable args/world problem: fix it and re-invoke. `BLOCKED` needs human adjudication (a real semantic collision) before any re-invoke. `HELD` is a report, never an auto-continue: read the evidence, steer with `operatorGuidance`, or accept and account the bead via `droppedBeads` at phase 7. Never blanket-retry an unchanged invocation.

## Relationship to session-flow

`session-flow` owns interactive work, session lifecycle (handoff/pickup, epic discovery), and stays the default. This skill owns nothing of that — it is the throughput tool the user explicitly reaches for, and after FINAL the session returns to `session-flow` conventions (post-merge review of the engine-side gates, handoffs, self-improvement checkpoints).
