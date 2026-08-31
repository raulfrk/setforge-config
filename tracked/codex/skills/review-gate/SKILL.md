---
name: review-gate
description: Review a completed implementation plan before presentation or completed file-changing work before handoff, commit, or push. Use after deterministic preparation is complete, including after changes caused by returned RevDiff annotations.
---

# Review gate

Run independent read-only reviews, validate their findings, and keep fixes
minimal. The primary agent owns decisions and edits; reviewers never edit.

## Select the mode and evidence

- **Plan mode:** review the complete draft before its first presentation. Supply
  the user request, repository facts, recorded decisions, spike evidence, and
  full draft.
- **Implementation mode:** run after deterministic checks. Supply the execution
  contract, final diff and paths, and actual verification output. The execution
  contract is the approved plan plus accepted revisions, or the user request
  and recorded decisions when no formal plan exists.

## Build the reviewer lanes

Always use distinct tasks with narrow briefs.

Build the complete evidence package before launching anything. In plan mode,
this includes the complete draft—not a placeholder, outline, or summary. A
review that did not receive the complete current draft does not count.

| Mode | Mandatory core tasks | Specialists |
| --- | --- | --- |
| Plan | requirements/correctness (`review_critical`); verification/feasibility (`review_general`); simplicity/reuse (`review_general`) | zero to seven |
| Implementation | plan compliance (`review_critical`); requirements/correctness (`review_critical`); tests/verification (`review_general`); simplicity/reuse (`review_general`) | zero to six |

The plan-compliance reviewer compares every execution-contract commitment with
the diff and verification. It returns a concise ledger with one row per
requirement: `implemented`, `deviated`, or `not-applicable`; supporting evidence;
deviation approval when relevant; and any finding. It must reject unsupported
`not-applicable` claims and flag missing commitments, unauthorized deviations,
unproved claims, and extra scope. It returns `CLEAN` only when every commitment
is covered and every deviation is explicitly justified. Its brief must name
`plan compliance` and explicitly request this ledger; a general requirements or
correctness review does not fill this lane. The ledger covers the implementation
contract; it does not treat completion of the current review gate as a
self-referential implementation commitment.

Choose specialists only for concrete risk surfaces shown by the requirements,
repository, diff, dependencies, or spike results. Combine overlapping lenses.
When a concrete risk needs focused expertise beyond the core lenses—for
example credential exposure across logs and exceptions—launch one bounded
specialist; do not fold that work into a core brief merely to reduce the task
count. This is risk-driven selection, not a permanent specialist panel.
Secrets or credentials crossing transport, logs, or exception surfaces are a
distinct specialist risk and always require one such lane.
Use `review_critical` for irreversible or correctness-sensitive risks and
`review_general` for other domain, product, or operational risks. Do not fill
the specialist allowance or create a permanent taxonomy.

Never exceed ten selected reviewer lanes. Combine or omit overlapping
specialist risks when the limit is reached. Spawn each core lane once, launch
all selected lanes before waiting, and keep their thread identities for later
rounds. When spawning a configured reviewer type, use `fork_turns="none"` and
put the complete evidence in its brief; a full-history fork cannot select that
reviewer type. Record each lane's role and thread ID when it is first spawned.
For every later round, including one caused by RevDiff annotations, launch each
already-known selected lane with the platform's follow-up operation targeting
that recorded thread (`followup_task`; some event streams call it `send_input`).
Issue every follow-up in one parallel batch before waiting. Never call
`spawn_agent` for an already-known lane. A specialist may be spawned later only
when a new concrete risk first appears; record it in the same mapping so it is
reused thereafter.

A follow-up dispatch event may repeat the lane's previous completed status or
message. That dispatch output is stale lifecycle state, not the result of the
new review. After dispatching the complete batch, wait for a fresh completion
from every targeted thread before counting the round complete.

Require each lane to return `CLEAN` or findings with severity, location,
evidence, impact, and the smallest justified correction. A reuse finding must
name concrete repetition or an existing reusable capability and show lower net
complexity.

## Resolve the gate

Wait for every selected task. A finding from one lane never short-circuits the
batch: keep waiting until every selected lane has returned before validating
findings, changing files, or launching follow-ups. Validate each finding
independently; reject false positives and do not apply unsafe or speculative
changes.

A reviewer suggestion is evidence to evaluate, not a new requirement. Do not
expand scope, add implementation-coupled tests, or introduce structure merely
to satisfy a reviewer when the execution contract and observable verification
are already covered.

The primary agent must independently validate factual findings with safe
repository inspection or commands when possible. A command run only by a
reviewer is not primary-agent validation. If validation is blocked, report that
instead of silently accepting the claim.

Treat a finding as actionable only when it demonstrates an unmet current
requirement, a violated established repository convention, or a reproducible
failure. Hypothetical alternate implementations, defense-in-depth beyond the
stated threat model, and stronger test contracts than the reviewed draft or
diff require are advisory at most; reject them when they add net complexity.

If no verified actionable findings remain, the gate is clean. Rejected and
advisory findings do not block it and do not trigger another round.

When actionable findings remain, the primary agent updates the complete plan
or applies implementation fixes sequentially, then reruns the relevant
deterministic checks. Send the complete updated evidence to every current lane
with `followup_task`; repeat the full current draft, diff, and verification
rather than referring to prior content as unchanged or sending only a delta.
Keep each follow-up brief distinct by repeating that lane's recorded role and
required output alongside the common evidence. Launch all follow-ups before
waiting, and repeat until the gate is clean. Every rerun includes every current
lane, including lanes that were previously clean; following up only finding
lanes does not count. Do not replace core lanes with freshly spawned reviewers.

Resolve ordinary reviewer disagreement through primary-agent validation. Stop
and report a blocker only when independently verified requirements remain
irreconcilable, no safe fix exists, or required validation cannot run. Never
loop without making progress or declare a blocked gate clean.

Before handoff, confirm that all current lanes completed the latest round and
that no verified actionable finding remains. After a clean plan gate, present
the complete plan. After a clean implementation gate, explicitly offer RevDiff
review by name in the final handoff. The gate does not authorize a commit or
push.

## RevDiff returns

Capital `O` is an internal RevDiff reflow and does not trigger this skill. Act
only after the completed review returns annotations.

Do not inspect or incorporate annotation contents before they are returned. If
a known fixture or path represents later feedback, defer reading its contents
until the initial gate is complete, and explicitly tell every initial reviewer
not to inspect that path. Merely saying that feedback will be applied later is
not sufficient because reviewers can inspect the shared workspace themselves.

If returned annotations cause any plan change, build the complete replacement,
reselect specialists from the updated risk surface, then use `followup_task` for
every selected lane already in the recorded mapping and `spawn_agent` only for a
newly required specialist with no recorded thread. Resolve findings until clean
before presenting the replacement again.

If returned annotations cause any file change, rerun deterministic checks,
reselect implementation lanes, then use `followup_task` for every selected lane
already in the recorded mapping and `spawn_agent` only for a newly required
specialist with no recorded thread. Resolve the gate until clean before offering
RevDiff again.
