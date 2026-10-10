---
name: technical-investigation
description: Investigate nontrivial failures, develop platform-dependent diagnostics, or prove material technical assumptions before dependent implementation. Skip routine changes, ordinary verification, and simple factual lookups.
---

# Technical investigation

Use this workflow to resolve an actual failure or material implementation
uncertainty. Preserve the requested outcome and scope; use existing capabilities
and evidence. Do not add a harness, dependency, recovery mechanism, or other
software without a current requirement or demonstrated or demonstrably reachable
failure that a direct approach cannot adequately address.

## Establish the evidence

For platform-dependent output, obtain a representative sample before implementing
its parser or assertions. Compare fields required by the contract; do not treat
volatile observations as configuration drift. Verify the exact user-facing
command on the target platform when available. Distinguish diagnostic failure
from failure of the behavior under test, and state unverified assumptions.
Use bounded reads and reuse unchanged evidence.

Distinguish fixture readiness from the behavior under investigation. Verify
only relevant setup prerequisites before the behavior run, and retain useful
setup diagnostics at an early observation point. A setup failure is not a
failed behavior proof; a setup repair is not evidence that the behavior works.
Keep each proof focused on one observable pass/fail question.

## Prove the uncertain path

Before fully implementing functionality whose success depends on a material
technical uncertainty, state the unresolved question and why existing evidence
does not answer it. Use the smallest runnable proof that could disprove the
approach: an existing test or native command when sufficient, otherwise a
disposable spike. Before running it, state the expected result and success
threshold in a progress update.

Separate the narrow material-assumption proof from complete public acceptance.
Do not make every eventual UI journey a prerequisite for proving a storage or
protocol assumption. Keep the original user-facing checks explicitly pending;
CLI acknowledgments or component tests never substitute for those checks.

After two inconclusive attempts without a behavior-level signal, reassess the
experiment's scope and fixture before another full attempt. Prefer a smaller
question or an established public path, with stated new evidence and unchanged
legitimate acceptance criteria. Do not keep varying setup blindly; retain the
required review and authorization checkpoints below.

Do not create or modify production code that depends on the unproved assumption
until the experiment meets its stated success threshold. Independent, already
proved work can continue within its existing authorization and ownership.
If the experiment fails or is inconclusive, stop dependent implementation and
report the blocker, or revise the approach and prove the revised critical path.
After an inconclusive material spike, use `review-gate` for the required
independent checkpoint before choosing another implementation attempt; a review
cannot waive the runnable proof.

Keep spike code disposable and separate from production; never silently promote
it into the final design. Do not spike routine work whose behavior is already
established by the repository and tests. A successful proof alone does not justify
an addition; finish the requested implementation with its required acceptance
checks through the current public entrypoint.

## Diagnose slow or stalled operations

Separate setup, compilation, fixture waits, test execution, and transport/logging
time before choosing an optimization. Estimate runtime from measured stages;
a live PID alone does not establish progress. At a missed milestone, inspect
the current stage and call path, then justify the next action, simplify, or
report the blocker. Before another retry, experiment, or review round, identify
the new evidence it should produce and why it advances the original outcome.

Start with focused checks and affected public-path proof. Schedule required
broad, timing, or mutation gates after the candidate and review corrections
are stable, respecting any user-restricted execution window. Do not impose an
overnight-only rule or relax agreed thresholds. Reuse unaffected checks with
their original candidate bindings; never relabel older evidence with a new SHA.
Do not add a cache, runner, framework, or tracking artifact merely to organize
the investigation, or interrupt a healthy run to regenerate its evidence.

## Verify experiment destinations

Before an experiment can mutate live state, verify its actual write destinations
match the isolated scope or an existing explicit authorization. Resolve the
relevant paths and runtime targets; environment settings alone do not prove
isolation. Stop before mutation on a mismatch.

Verification experiments, including setup and cleanup, must use isolated
targets; never modify production or shared live state for verification. If safe
verification is unavailable, report what remains unverified.

Use the relevant installed tool skill for concrete target-resolution procedures,
such as Herdr session/pane identity or SetForge ownership and deployment. Do not
duplicate those procedures or infer authority for a wider live target from
permission to run the experiment.
