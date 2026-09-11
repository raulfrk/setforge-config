---
name: review-gate
description: Coordinate independent reviews and consequential-action checkpoints for material risk or an explicit review request, validate findings, and keep corrections scoped.
---

# Review gate

Determine whether the current phase needs independent review, coordinate any
required read-only reviews, validate findings, and keep fixes minimal. The
primary owns design, implementation, tests, corrections, integration, and
acceptance. Delegate implementation only when useful independent work can run
in parallel. Honor configured models and explicit user selections. Delegation,
a multi-file change, and Plan Mode alone do not require independent review.
Reviewers never edit and cannot independently review their own design or work.

Read-only is a behavioral instruction for reviewers, not a sandbox guarantee.
On Codex 0.153.2, subagents inherit the primary agent's runtime permissions even
when a role file declares `sandbox_mode = "read-only"`. Keep the role setting as
intent, explicitly prohibit reviewer edits in every brief, and verify from the
reviewer rollouts that they performed no edit or other mutating tool call.

Read [references/technical-checkpoints.md](references/technical-checkpoints.md)
when the work may involve material design, a consequential material action,
repeated corrections, or an inconclusive material spike. Read
[references/revdiff-returns.md](references/revdiff-returns.md) when RevDiff
feedback returns after an initial gate. If a known fixture or path contains
feedback intended for later, do not inspect or incorporate it before it returns,
and explicitly instruct every initial reviewer not to inspect that fixture or
path. Never discard or defer actionable RevDiff feedback after it returns. Route
implementation corrections to the existing owner; reviewers and design authors
remain read-only.

## Select the mode and evidence

Use this skill when actual material risk or an explicit request requires
independent review, including a consequential-action checkpoint. For routine
locally observable work, primary validation of the diff, behavior, and relevant
checks suffices without invoking this skill. When review is required, assess a
completed plan before presentation and completed file-changing work after its
deterministic checks, before handoff, commit, or push.

- **Plan mode:** assess the complete draft before its first presentation. Keep
  the user request, repository facts, recorded decisions, spike evidence, and
  full draft available.
- **Implementation mode:** assess the final state after deterministic checks.
  Keep the execution contract, exact current diff and paths, and actual
  verification output available. The execution contract is the approved plan
  plus accepted revisions, or the user request and recorded decisions when no
  formal plan exists.

Require an independent `review_correctness` reviewer only when the
actual proposed change and its consequences materially affect architecture,
component boundaries, public interfaces, data flow, security boundaries,
credentials, migrations, destructive data operations, or compatibility, or
when nonlocal correctness remains unresolved, or the user explicitly requests
independent review. Judge materiality from the change
and its consequences, not keywords, file names, or the topic alone. Routine UI
work and ordinary feature work with locally observable evidence still require
primary validation but do not require an independent reviewer. Plan Mode alone
does not make a phase material.

## Build the review

When independent review is required, use one `review_correctness` thread
for the coherent change. The same independent thread may cover checkpoints and
successive phases, but each phase requires a fresh completion and verdict on
its complete current evidence. An earlier checkpoint or plan verdict cannot
certify a later diff. Record the phase, role, identity, evidence version, and
verdict. The design author cannot serve as this reviewer.

Its brief covers current requirements and correctness, verification adequacy,
plan compliance, scope, and simplicity. In implementation mode it must flag
missing commitments, unauthorized deviations, unproved claims, and extra scope.
It returns `CLEAN` only when the complete current plan or implementation is
ready. In plan mode include the complete draft—not a placeholder, outline, or
summary. In implementation mode make the complete current diff, execution
contract, and actual check results accessible.

Ordinary source revisions, the relevant diff, and relevant command evidence are
sufficient when they show the reviewed behavior. The gate itself does not
require new evidence bundles, manifests, recovery tooling, or coordination
software. Do not repeat a review solely because identical evidence was renamed
or repackaged, or because a routine launcher correction cannot affect the
reviewed action or risk. Relevant changed evidence still requires the fresh
review specified below.

Add a specialist only for a concrete extra risk or verification need. Actual
credential exposure across logs, exceptions, or another transport surface
always requires a bounded security specialist. A change that merely mentions
credentials requires no specialist without a concrete exposure risk. Use
`review_critical` for compliance, irreversible, security, or other high-risk
review and `review_general` for other domain, product, or operational risks.
Do not create a standing panel or taxonomy.

When spawning a configured reviewer type, use `fork_turns="none"`. Launch all
selected reviewers before waiting, keep their identities, and collect a fresh
completion from every selected reviewer before validating findings or making a
correction. Follow-up dispatch output is stale lifecycle state when it repeats
an old completed status; it is not a fresh result.

Require each reviewer to return `CLEAN` or findings with severity, location,
evidence, impact, and the smallest justified correction. A reuse finding must
name concrete repetition or an existing reusable capability and show lower net
complexity.

## Resolve the gate

If independent review is not required, complete primary validation and record
why the current phase is routine and locally observable. The gate is then clean
without launching a reviewer.

When reviewers are required, wait for every selected task. A finding from one
lane never short-circuits the batch: keep waiting until every selected lane has
returned before validating findings, changing files, or launching follow-ups.
Validate each finding independently; reject false positives and do not apply
unsafe or speculative changes.

A reviewer suggestion is evidence to evaluate, not a new requirement and cannot
enlarge the execution contract. Do not
expand scope, add implementation-coupled tests, or introduce structure merely
to satisfy a reviewer when the execution contract and observable verification
are already covered.

The primary agent must independently validate factual findings with safe
repository inspection or commands when possible. A command run only by a
reviewer is not primary-agent validation. If validation is blocked, report that
instead of silently accepting the claim.

Treat a finding as mandatory only when it demonstrates an unmet current
requirement, a violated established repository convention, or a reproducible
failure. Hypothetical alternate implementations, defense-in-depth beyond the
stated threat model, and stronger test contracts than the reviewed draft or
diff require are advisory at most; reject them when they add net complexity.
Remove an invalid harness assertion only when evidence shows why it is invalid
and the legitimate acceptance criteria remain covered. Do not discard valid
isolation, security, compatibility, or behavioral checks merely to obtain a
clean result.

If no verified mandatory findings remain, the gate is clean. Rejected and
advisory findings do not block it and do not trigger another round.

When mandatory plan findings remain, the primary updates the complete plan.
When implementation findings remain, route validated corrections to the current
owner: the primary for its own work or the persistent worker for its delegated
lane. Compare suspected regressions with the baseline before requesting changes.
Reviewers and workers must not recursively spawn reviewers or run this gate.
Rerun deterministic checks only when changes, failures, or unresolved concerns
can affect their results.

For follow-up review, provide the current revision, relevant delta and checks,
plus the full replacement plan or an accessible current diff and execution
contract. Unchanged evidence already available in the same reviewer thread may
be referenced instead of pasted again. Require a fresh completion; stale
dispatch state does not count.

Rerun the `review_correctness` reviewer whenever material evidence for the
current phase changes. Rerun only specialists affected by a change and record
why retained specialist verdicts still apply. If a shared assumption changes or
the impact is unclear, rerun every selected specialist. Launch all selected
follow-ups before waiting and collect them all before the next correction.
Reuse recorded identities rather than spawning replacements.

Resolve ordinary reviewer disagreement through primary-agent validation. Stop
and report a blocker only when independently verified requirements remain
irreconcilable, no safe fix exists, or required validation cannot run. Never
loop without making progress or declare a blocked gate clean.

Before handoff, the primary independently validates the final worker evidence
with read-only inspection or bounded diagnostics. When review was required,
confirm a fresh independent verdict for this phase and current evidence, fresh
completions from every selected affected specialist, documented applicability
for retained specialist verdicts, and no verified mandatory finding. After a
clean plan gate, present the complete plan. After a clean implementation gate,
report the verified result. Offer or open RevDiff when requested or useful in
the current review flow; it is not a mandatory extra step. The gate does not
authorize a commit or push.
