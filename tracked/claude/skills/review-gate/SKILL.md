---
name: review-gate
description: Coordinate independent reviews and consequential-action checkpoints for material risk or an explicit review request, validate findings, and keep corrections scoped.
---

# Review gate

The primary owns design, implementation, corrections, integration, and acceptance.
Reviewers are independent and never edit or review their own design/work. Honor
configured roles/models and explicit user selections.

The reviewer agents have no file-editing tools, but they keep Bash and inherit
the primary's runtime permissions, so the role is not enforced filesystem
isolation. Prohibit edits and other mutations in every reviewer brief, and
compare the working tree with the reviewed baseline before accepting a result.

## Decide whether a gate is required

Require independent `review-correctness` for actual material effects on
architecture, component boundaries, public interfaces, data flow, security,
credentials, migrations, destructive operations, or compatibility; unresolved
nonlocal correctness; or an explicit independent-review request. Judge
consequences, not keywords, file count, delegation, or Plan Mode alone.
Routine locally observable work finishes with primary validation.

Read [technical-checkpoints.md](references/technical-checkpoints.md) for material
design/actions, repeated corrections, or inconclusive material spikes. It owns
the independent checkpoint requirements before consequential actions, after an
inconclusive spike, and before a third correction when material/critical
uncertainty remains. A reviewer cannot waive the required runnable proof.
Block dependent work when required review is unavailable or validated findings
remain unresolved.

Read [revdiff-returns.md](references/revdiff-returns.md) when annotations return.
Do not inspect or incorporate feedback before it returns. If a known fixture
contains later feedback, tell every initial reviewer not to inspect it. Do not
discard actionable feedback after return.

## Select the phase and evidence

Review a complete draft plan before its first presentation (in Plan Mode,
before calling ExitPlanMode), and a completed
implementation after its deterministic checks, before handoff, commit, or push.
Provide the full current plan or accessible diff, execution contract, relevant
repository evidence, and actual check results. The contract is the approved plan
and accepted revisions, or the user request and recorded decisions without a
formal plan.

For a consequential-action checkpoint, provide the complete evidence, exact
proposed action, and risk question. A current phase gate satisfies it only when
it covers that same action, risk, and evidence.

Group independently safe corrections for one coherent candidate into one
checkpoint; setup details do not each require a full review cycle. Assess
whether fixture changes affect the material assumption, boundary, or acceptance
claim. Never batch past a required consequential-action or spike checkpoint.
No new evidence bundle, manifest, recovery tool, or coordination software is
required when existing revisions, diffs, and command evidence suffice.

## Assign the review

Use one `review-correctness` agent per coherent change, started fresh rather
than as a fork so it does not inherit the primary's reasoning. Reuse it for
checkpoints and later phases by continuing that same agent with SendMessage,
requiring a fresh completion on each phase's complete current evidence. Record phase, role,
identity, evidence version, and verdict; prior plan approval cannot certify a
later implementation.

The brief covers requirements/correctness, verification adequacy, plan compliance,
scope, and simplicity. Implementation review must flag missing commitments,
unauthorized deviations, unproved claims, and extra scope. Ask for `CLEAN` or
findings with severity, location, evidence, impact, and smallest justified
correction. A reuse finding must identify actual repetition or an existing
capability and demonstrate lower net complexity.

Add specialists only for a concrete risk or expertise gap. Actual credential
exposure in logs, exceptions, or transport requires a bounded security specialist.
Mentioning credentials alone does not. Use `review-critical` for security,
compliance, irreversible, or other high-risk concerns and `review-general` for
other domain/product/operational concerns; do not create a standing panel.

Launch all selected reviewers in one message before waiting. Collect every selected completion
before validating the batch, changing files, or dispatching follow-ups. Stale
completed status repeated by a follow-up dispatch is not a fresh result.
Reviewers, workers, and design authors must not recursively run this gate or
spawn reviewers.

## Validate and correct

The primary independently validates factual findings with bounded read-only
evidence; a reviewer-only command is not primary validation. Compare suspected
regressions with baseline. Report blocked validation rather than assuming it
passed. Reject false positives and speculative or unsafe corrections.

Mandatory findings demonstrate an unmet current requirement, established
repository convention, or reproducible failure. Hypothetical alternatives,
extra defense beyond the threat model, and stronger contracts are advisory at
most. Reject additions that increase complexity without a current need.
Reviewer suggestions cannot expand the execution contract or require
implementation-coupled tests. Remove invalid harness assertions only with
evidence that legitimate acceptance remains covered; never discard valid
isolation, security, compatibility, or behavioral checks just to pass.

If no verified mandatory findings remain, the gate is clean; rejected or
advisory findings do not trigger another round. Otherwise, send one consolidated
correction set partitioned by owner and dependency. The primary revises its own
plans/work; persistent workers correct their own lanes. Preserve ownership and
rerun deterministic checks only when changes, failures, or unresolved concerns
can affect them.

For follow-up, provide the current revision, relevant delta/checks, and full
replacement plan or accessible current diff/contract. Reference unchanged
evidence already in that reviewer's context rather than repasting it. Do not
repeat review for identical evidence renamed/repackaged or a routine launcher
change that cannot affect the action or risk.

Rerun `review-correctness` when material evidence for the phase changes. Rerun
only affected specialists, recording applicability of retained verdicts. When a
shared assumption changes or impact is unclear, rerun all selected specialists.
Launch selected follow-ups together and collect their fresh completions before
the next correction; reuse identities.

Resolve ordinary disagreement through primary validation. Report a blocker
when independently verified requirements are irreconcilable, no safe correction
exists, or required validation cannot run; never loop without progress or call
a blocked gate clean.

## Accept and hand off

The primary independently validates worker handoff evidence and final
interactions. A required gate needs a fresh independent verdict for this phase
and current evidence, fresh affected specialist completions, applicable retained
verdicts, no verified mandatory findings, and no reviewer-made changes.
After a clean gate, present the complete plan or verified implementation.
Leaving Plan Mode opens the plan for review (RevDiff or the web-plan page)
through the `revdiff-herdr` plugin; otherwise open RevDiff only when
explicitly requested.
Review does not authorize a commit, push, publication, or consequential action.
