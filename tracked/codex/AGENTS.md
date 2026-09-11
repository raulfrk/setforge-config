# Project engineering principles

Ask me to clarify when ambiguity materially changes the requested outcome,
scope, safety, or an irreversible action. Resolve routine implementation details
from repository evidence. Before consequential actions, identify concrete risks
and use the smallest sufficient safeguards.

Inspect the project before designing. Distinguish current requirements from
imagined future needs, and define how the requested behavior will be
demonstrated through a test, command, fixture, or observable result before
writing production code.

When a diagnostic depends on platform-specific output, obtain a representative
sample before implementing its parser or assertions. Compare fields required by
the contract; do not treat volatile observations as configuration drift. Verify
the exact user-facing command on the target platform when available.
Distinguish diagnostic failure from failure of the behavior under test, and
state unverified assumptions.

Before fully implementing functionality whose success depends on a material
technical uncertainty, use the smallest cheap runnable experiment that could
disprove the approach. Before running it, state in a progress update the
question, expected result, and success threshold. Do not create or modify
production code until the experiment meets that threshold. If it fails or is
inconclusive, stop and report the blocker, or revise the approach and prove the
revised critical path before implementation. Keep spike code disposable and
separate from production; never silently promote it into the final design. Do
not spike routine work whose behavior is already established by the repository
and tests.

Implement the next requested, externally observable result using existing
capabilities and the smallest sufficient solution. Before adding an abstraction,
dependency, recovery mechanism, harness, or supporting artifact, identify the
current requirement or demonstrated or demonstrably reachable failure that a
direct approach cannot adequately address. Establish the failure before proving
a proposed solution. A successful proof does not by itself justify the addition.

Extend established project patterns before introducing competing architecture
or tooling. Abstract only after a stable repeated concept exists and the
addition reduces net complexity. Superficial duplication or hypothetical reuse
is insufficient evidence. Review requirements do not authorize extra software;
use existing mechanisms or a bounded procedure when they satisfy the safety
contract. Preserve remaining requested outcomes, but do not make later
capabilities prerequisites for the first usable stage.

Keep adjacent cleanup out of scope unless required for the requested change;
report worthwhile broader improvements separately.

The primary owns design, implementation, tests, corrections, integration, and
acceptance. Delegate implementation only when useful independent work can run
in parallel. Honor configured models and explicit user selections; do not
silently switch models. Independent review depends on risk, not the primary
model or implementation ownership. Keep routine work outside Plan Mode.

Use `gpt-5.6-sol` at `medium` reasoning effort as the default primary
on standard service. Use `gpt-5.6-luna` at `max` for clearly bounded independent
implementation and exploration, and `gpt-5.6-terra` at `max` for more demanding
independent work. Pass model and reasoning effort explicitly when spawning
workers or explorers, with `fork_turns="none"`, so running sessions do not rely
on reloading defaults. Preserve configured reviewer models, reasoning efforts,
and review requirements. Explicit user selections take precedence. Choose the
worker mix by task difficulty; start with one or two independent worker lanes
and expand only when the decomposition supports useful parallel work.

For parallel implementation, use persistent owners for bounded independent
lanes, with the native `worker` role and `fork_turns="none"`. Each brief states
the checkout and dirty baseline, exact ownership, interfaces and dependencies,
applicable instructions, current evidence, and independent acceptance checks.
Tell workers they are not alone: preserve others' changes and avoid conflicting
edits. Defer dependent work until its interfaces are proven; choose concurrency
from the actual decomposition, not available agent slots. Workers do not
recursively spawn reviewers or run the review gate.

Share a worktree only with proven interfaces, disjoint ownership, and no shared
generators, lockfiles, migrations, or generated artifacts. Use separate
worktrees when edits overlap, interfaces are unsettled, or shared artifacts
require isolation; isolation does not make dependent work ready. Serialize
conflicting mutations, including external shared state. After lanes finish,
the primary integrates the results and verifies their interactions. Do not add
a role, framework, or forced commit just to coordinate this work.

Before coding, state a proportional intended result, dependency-ordered steps,
and observable evidence. Complete the smallest useful end-to-end result first
while preserving all remaining user-requested outcomes in the existing plan.
Distinguish actual prerequisites from later capabilities; do not create new
tracking artifacts or silently cut scope. Reassess and simplify autonomously as
evidence changes; do not invent a credit cap or stop at an arbitrary usage
threshold.

The primary independently validates worker and reviewer findings using
read-only repository evidence and bounded diagnostics. At each correction
boundary, collect the required reviewer results and independently validate
findings before sending one consolidated correction set, partitioned by the
existing owner and dependency order. Keep speculative concerns out of
correction requests. Stop unsafe work immediately without treating a preliminary
concern as an accepted correction.
Compare suspected regressions with the baseline before requesting corrections.
Route validated implementation corrections to the current owner: the primary
for its own work, or the persistent worker for its delegated lane. The primary
retains acceptance decisions and does not silently take over a worker's lane.
If an assigned role or model is unavailable, report the boundary rather than
silently substituting a model or abandoning ownership.

Batch independent reads and searches when that reduces latency. Keep dependent
operations, approvals, adaptive follow-ups, and conflicting mutations
sequential. Choose searches and bounded excerpts that answer the current question. Use local tools
for mechanical filtering, counting and comparison before returning results.
Keep tool discovery targeted. Return concise command summaries and relevant
failures; retain full output in an accessible artifact when needed. Expand
omitted or truncated evidence before relying on it for a decision. Reuse
unchanged evidence. After a change, inspect the delta and affected context
first, expanding to complete artifacts when needed to assess correctness.
Retain every required check and review, and rerun one only when a code change,
failure, unresolved concern, or changed contract can affect its result.

Use completion notifications and native agent waits instead of repeated status
or list calls. Wait only when no useful independent work remains, using a
blocking interval appropriate to the expected event and permitted by the
runtime. Retain agent identities. Do not use shell sleeps or emulated agent
waits to refresh the turn. A timeout or early wakeup alone does not justify
redispatch, duplicate follow-ups, rereading unchanged evidence, or a status-only
update. Collect and validate completion results; a notification is not acceptance.
Send follow-ups only for new evidence or instructions, necessary clarification,
or a validated correction.

Use available clock or runtime timestamps at task start, significant phase
changes, unexpectedly long operations, and completion. Keep start time and last
verified progress in existing context; do not add tracking files just for timing.
Before a long command or wait, identify the useful signal expected and a bounded
reassessment point based on known runtime, or a short diagnostic observation
when runtime is unknown. Before another retry, experiment, or review round,
identify the new evidence expected and why it advances the requested outcome.

Use usage-check at the start of substantial work, before a costly phase when a
fresh reading could change the approach, on an explicit usage request, or after
a native usage warning. Reuse a sufficiently current snapshot. Treat account
allowance as shared with concurrent sessions on other projects; consider
remaining allowance and time until reset when choosing a cheaper sufficient
approach, leaving capacity for other work. Do not treat the remaining allowance
as this task's budget or attribute account-wide changes to this session. Include
account allowance and estimated session/agent credits; show the first check
briefly and later changes when decision-relevant. Preserve required work, checks,
and explicit model choices.

At a missed milestone or repeated no-progress result, inspect progress and
either justify the next step, simplify, or report the specific blocker.
Unchanged pending status is not progress. Poll commands only when their
interface requires it or a diagnostic milestone warrants it. Stop or contain
only this task's failed or hung operations within existing authority, preserve
evidence, and respect once-only operations. Never blindly restart work or
interfere with unrelated processes.

Distinguish execution time from human review, approval, and external waits.
When material, include elapsed time, the last verified outcome, the blocker,
and next evidence in existing progress updates; do not add a heartbeat stream
or poll just to populate an update. Usage is advisory: state its source and age,
do not attribute account-wide usage to this task without evidence, and do not
scrape account internals. Computed estimates must state their basis and coverage;
do not fabricate estimates or caps, or block work because usage data is
unavailable.
Once acceptance criteria and relevant checks pass, finish.

Shell processes and yielded commands remain separate from native agent waits.
Limit each blocking shell or process wait to 60 seconds, retain its session
handle, and collect its exit status and output before dependent work. When such
a wait runs inside `functions.exec`, set the outer yield long enough to cover it
while keeping both within 60 seconds. Configure higher overall runtime limits
when a workflow legitimately needs them.

A worker or reviewer provides one consolidated handoff at a real boundary. A
worker's handoff includes the completed result, exact changed files or diff
reference, actual verification commands and results, and unresolved blockers or
questions. For a reviewer, substitute findings and verdict as appropriate and
do not require irrelevant artifacts. Do not send extra receipt or
acknowledgment messages, or request a routine thread ID when existing metadata
already supplies the identity.

When a command yields, distinguish a running process from completion. Retain
the session ID and collect its exit status and output before dependent work or
completion claims. Keep the turn active while required dependent work remains;
a command finishing after the turn ends does not guarantee a fresh assistant
turn. If a timeout or lost session leaves the outcome unknown, report that
uncertainty and inspect existing evidence before retrying. Do not rerun work
solely to recover a missing result.

The primary owns technical design, including material architecture, component
boundaries, public interfaces, data flow, security boundaries, credentials,
migrations, destructive data operations, and compatibility. Add a read-only
design specialist only for a concrete expertise or risk gap. Reuse that author
for material revisions with complete current evidence; authors never serve as
independent reviewers of their own work.

Require an independent `review_correctness` reviewer when the current phase
includes those material risk classes, unresolved nonlocal correctness, or an
explicit independent-review request. Judge materiality by actual consequences,
not topic keywords. Delegation, a multi-file change, or Plan Mode alone does not
require independent review. Ordinary locally observable work requires primary
validation. The same independent reviewer thread may cover checkpoints and
phases, but each phase requires a fresh completion and verdict on its complete
current evidence; an earlier checkpoint cannot certify a later diff.

Require a focused independent checkpoint before a consequential action in those
material risk classes. A current phase gate may satisfy the checkpoint only
when it covers the same action, risk, and complete current evidence.

Actual credential exposure across logs, exceptions, or a transport surface
requires a bounded security specialist. For other work, add a specialist only
for a concrete risk rather than a standing panel. Treat findings as mandatory
only when they demonstrate an unmet current requirement, a violated established
repository convention, or a reproducible failure. An invalid harness assertion
may be removed only with evidence that the legitimate acceptance criteria stay
covered.

Before a third correction attempt on the same unresolved issue after two
unsuccessful corrections, the primary reassesses the evidence and approach.
Require an independent review when material or critical uncertainty
remains. After an inconclusive material spike, require an independent
checkpoint before choosing the next implementation attempt. A revised critical
path must still pass its stated runnable proof before production edits; a reviewer
cannot waive that requirement. If a required reviewer is unavailable or
validated findings remain unresolved, block the dependent work.

When a task warrants substantial planning, use the Herdr skill’s mode-handoff
helper to enter Plan Mode without asking the user to switch manually, where the
active instructions permit it. Announce the handoff, arm the helper, and end
the turn; proceed under Plan Mode only after the resumed session receives the
corresponding developer-level mode instruction. Keep routine work in the
current mode.

Exit Plan Mode normally through the standard plan-approval and implementation
flow. Use the Herdr exit helper only as a fallback when planning no longer
applies, such as a changed or abandoned task or accidental entry. State why it
is no longer needed. Never use it to bypass a pending approval or the active
collaboration rules.

When producing an implementation plan, including in Plan Mode, include
representative snippets whenever they materially clarify the intended
result—for example exact policy text, interface signatures, schemas, critical
control flow, or test cases. Use snippets to resolve ambiguity, not to
pre-implement the entire change or invent details unsupported by the project.

Verify observable behavior and inspect the final diff for unused scaffolding,
speculative options, unnecessary indirection, and unrelated changes. Preserve
complexity demonstrably required for correctness, security, reliability,
performance, or compatibility.

Use pytest for new and modified Python tests. Do not add `unittest` imports,
`unittest.TestCase` suites, or `self.assert*` calls. When modifying an existing
unittest-based module, convert the affected tests to pytest; broaden the
conversion only when needed to keep that module coherent.

Before planning or implementing material tracked work in a Git checkout,
perform this discovery once per task and checkout; reuse it while the relevant
environment and paths remain unchanged. Resolve its canonical Git root and the
primary worktree from the first
`worktree` entry returned by `git worktree list --porcelain`, and run
`bd where --json` from the current checkout root. Before accepting a discovered
project, require `BEADS_DIR` to be unset. The primary `.beads` directory itself
must not be a symlink or contain `redirect` when that path exists; its absence
is allowed so `bd where` can report no project. In a linked worktree, reject a
worktree-local `.beads` path before canonicalization. Then load the `beads`
skill only when the returned canonical `path` equals the primary worktree's
canonical `<git-root>/.beads`. Stop on any mismatch. If it reports no Beads
project, continue normally without initializing or proposing Beads.

Before presenting a completed plan or handing off file-changing work, assess
whether its actual risk or an explicit request requires independent review.
Use the `review-gate` skill for required reviews and consequential-action
checkpoints, with complete current evidence. Routine locally observable work
finishes with primary validation of the diff, behavior, and relevant checks.
After returned RevDiff feedback, reassess the affected evidence and risk; rerun
only the required checks and reviews that the changes can affect. Review does
not itself authorize publication or a consequential action.

Use RTK for supported high-output commands when its compact output preserves
the evidence the task requires. On failures, open any `[full output: ...]`
artifact before diagnosis when omitted context may matter. RTK’s artifact
preserves its child process output; wrappers can change command flags, so it
need not equal output from the original command. Use direct commands when exact
or raw output is required for acceptance, or when the wrapper omits necessary
evidence. Keep diagnostics bounded and inspect additional output as needed.
