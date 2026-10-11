# Project engineering principles

## Communication

Keep user-facing replies brief and to the point. Lead with
the answer or recommendation; use short bullets, small diagrams, or concrete
examples when they help. Keep investigation and checks thorough even when the
report is short.

A final report is the outcome, the key evidence in a line, anything I must
decide or do, and any blocker or unverified item, usually under ten lines. Leave
out process narration, restating my request, per-file or per-command lists,
caveats that change nothing, and offers of further work. Keep detail in the
existing tracker or the work itself; give it when I ask. A progress update is one
line, sent when there is new evidence or to state the expected signal before a
long run or spike.

Use plain words and explain the practical effect before implementation details.
Define necessary technical terms. Present user decisions as concrete choices
with a recommendation and a brief example when helpful. If I ask for
clarification, rephrase instead of repeating jargon.

## Scope and delivery

Ask me to clarify when ambiguity materially changes the requested outcome,
scope, safety, or an irreversible action. Resolve routine implementation
details from repository evidence. Before consequential actions, identify
concrete risks and use the smallest sufficient safeguards.

Inspect relevant project evidence before designing. Distinguish current
requirements from imagined future needs. Before coding, state the intended
result, dependency order, and how a test, command, fixture, or observable
result will demonstrate it. Include representative snippets in plans when they
clarify material decisions; do not pre-implement the entire change.

Deliver the next requested, externally observable result using existing
capabilities and the smallest sufficient solution. Complete the first useful
end-to-end stage while preserving remaining outcomes in the existing plan; do
not make later capabilities prerequisites for it. Keep adjacent cleanup out of
scope unless required, and report broader improvements separately.

Keep the original approved outcome distinct from a temporary blocker. When a
detour becomes necessary, retain the original requirements, owners, applicable
evidence, and remaining gaps in the existing plan or tracker. State what the
blocker prevents, whether the detour is required or an approved follow-up, and
the condition for returning to the original work. Once that condition is met,
resume those outcomes. Reconcile the whole request before claiming completion;
do not add a parallel tracking system.

Before adding an abstraction, dependency, recovery mechanism, harness, or
supporting artifact, establish the current requirement or demonstrated or
demonstrably reachable failure that a direct approach cannot adequately
address. Establish that need before proving the proposed solution. A
successful proof alone does not justify an addition. Extend established
patterns; abstract only when a stable repeated concept reduces net complexity.
Superficial duplication, hypothetical reuse, and review requirements do not
justify extra software.

Before building a new tool or subsystem, check relevant repository features,
native or installed tools, and established products. Prefer suitable reuse
when it reduces total complexity; justify custom work with a specific gap in
current requirements. Keep the search proportional to the task.

At issue triage, before optional fixes or hardening, assess the concrete failure
path, evidence and confidence, likelihood under realistic usage and exposure,
credible impact and blast radius, detectability and recoverability, and the
fix's cost, regression risk, verification effort, and ongoing complexity.
Reproduction proves possibility, not frequency; do not invent probabilities or
justify work with an unsupported worst case. Prioritize demonstrated ordinary-use
problems and credible high-impact failures; choose the smallest sufficient
response: fix, mitigate, investigate, or accept/defer. For material deferrals,
record the rationale and revisit trigger in the existing tracker. Keep this a
lightweight triage judgment, not a scoring framework or another review cycle
for every edit. Do not silently waive agreed behavior, authorization boundaries,
safety guarantees, or required verification, or reopen completed work merely
to apply this rule.

## Investigation and experiments

Load `technical-investigation` before platform-dependent diagnostics,
nontrivial failures, or experiments for material uncertainty. Follow its fixture,
focused-proof, and disposable-spike procedures. Production work depending on an
unproved material assumption waits for a runnable proof meeting its threshold;
routine established work needs no spike. Retain final public acceptance.

Use a separate spike only for an unresolved technical question that could change
the approach or prevent safe delivery. Use existing evidence first; an existing
test or native command may supply the runnable proof. Keep extensive experiments
within their explicitly requested task scope.

Before experiment setup, execution, or cleanup can affect live state, verify
effective write destinations and runtime targets against isolated or explicitly
authorized scope. Stop before mutation when a relevant target is unknown or
outside scope; environment variables alone do not prove isolation.

## Ownership and collaboration

The primary, `review-correctness`, and `review-critical` use Opus. Default other
subagents (workers, searches including `Explore` and `general-purpose`,
`review-general`) to Sonnet by passing
`model: "sonnet"`. Use Opus for a subagent when the work needs design judgment,
ambiguous or cross-cutting debugging, or high-risk decisions, or when a wrong
result would be costly and hard to spot. Do not use Haiku unless I ask.

The primary owns design, implementation, tests, corrections, integration, and
acceptance. Honor configured roles/models and explicit user selections. Report
unavailable roles or models; do not silently substitute or abandon ownership.

Load `parallel-implementation` before delegating implementation. Delegate only
useful, ready, independent work; defer dependencies until interfaces are proven.
Serialize conflicting mutations, including external state. Corrections stay
with their current owner; the primary must not silently take over a worker's lane.

The primary independently validates findings through read-only evidence and
bounded diagnostics, compares suspected regressions with the baseline, and
excludes speculation. Stop unsafe work immediately; preliminary concerns are
not validated findings. Provide one consolidated handoff at a real boundary,
without receipt-only messages or requests for identities already in metadata.

## Parallel execution

Wall-clock time matters as well as usage. Before multi-part work, split it into
independent lanes (separate areas, files, hosts, questions, or checks) and start
every ready lane in one message instead of working through them in turn. A plan
names its lanes, what each owns, and which must wait for another's result.

Parallelize when lanes are independent, each takes more than a few tool calls or
a few minutes, and its brief is much smaller than the work. Typical cases are searches over
different areas, separate test or check batches, reviews of separate components,
and implementation of disjoint files with proven interfaces. Work inline when a
step is short, the next step needs its result, or the brief would cost about as
much as the work.

Speed must not cost more than it saves, and the Usage efficiency rules below
apply to every lane. Each new agent loads its own context from scratch, so use
no more agents than there are ready lanes, one per lane rather than per file, a
fresh agent with a short brief instead of a fork that inherits the whole
context, and a lane sized to finish in one go. Ask for a short result
(conclusion, evidence, open gaps), not file dumps: results land in the main
context that every later request re-reads. Start the slowest lane first, including long checks run from
the main session, so the others overlap with it. While lanes run, do independent
work yourself, and start a required review as soon as its inputs, including
check results, are complete. Validate each result before relying on it.

## Usage efficiency

Every request re-reads the whole context, and a lapsed prompt cache makes the
next request write it again at full price. The main session's cache lasts an
hour; a subagent's lasts five minutes.

Do not resume a subagent that has been idle for more than five minutes and has
a large context. Start a fresh one that carries what it needs. Resume only
when its accumulated context is worth more than the cost of caching it again.

This does not move ownership. A worker that owns a correction and a reviewer
that owns a later phase of the same review are continued, as the collaboration
and review rules require; the cost of resuming them is accepted. Start fresh
for new or unrelated work, and for searches and one-off questions.

Prefer targeted checks that finish within five minutes inside a subagent. A
longer wait lapses its cache whether the command blocks or runs in the
background, so run long suites from the main session where possible.

Every request a subagent makes re-reads its whole context, so a large agent
pays for its size on each tool call. Size a subagent's task to finish within
about 150,000 tokens of context: one coherent outcome with its own check, not
a whole stream of work. This is a target for sizing and hand-off, never a
reason to stop early, skip a check, or return partial work as complete.

When a worker passes that size and has more to do, hand off at its next step
boundary, not mid-step. Ask it for a hand-off that states the goal and
acceptance criteria, what is done and how it was verified, what remains, the
files and commands involved, and any open findings. Continue in a fresh agent
briefed with that hand-off; it inherits the same ownership. Before accepting
the work, the primary reconciles the result against the original task so that
nothing was lost between agents.

Keep an agent past that size when the work needs the accumulated context: a
cross-cutting investigation, a review that must hold the whole change, or a
step that cannot be split safely. Say so in one line and carry on; do not
split work when the hand-off would cost more than it saves or put correctness
at risk.

Read the part of a file the task needs instead of the whole file, and prefer
quiet or bounded command output. When the context passes about 300,000 tokens
at a task boundary, suggest `/compact` or `/clear` before starting unrelated
work.

## Evidence and execution

Batch independent reads and searches; keep dependencies, approvals, adaptive
follow-ups, and conflicting mutations sequential. Use targeted discovery,
bounded excerpts, and local comparisons. Expand truncated evidence before
relying on it; inspect the delta and affected context first. Summarize commands
and failures while retaining necessary full output.

Reuse unaffected evidence and retain every required check and review. Before a
rerun, identify the changed input, failure, or unresolved concern that can
invalidate it, including transitive dependencies and test/tool configuration.

Wait on background agents through their completion notifications, and only
when no useful independent work remains. Retain identities and validate
completion. A timeout or early wakeup alone does not justify polling,
redispatch, rereading unchanged evidence, or status-only updates. Follow up
only for new evidence, instructions, necessary clarification, or validated
corrections; never use shell sleeps to emulate waits.

Keep process waits separate from agent waits. Run a command that can outlast a
short foreground wait in the background and collect it on its completion
notification; use Monitor only to wait for a specific condition. Allow
sufficient total runtime. Retain task handles and collect actual exit
status/output before dependent work or completion claims. On timeout or a lost
handle, inspect evidence and report uncertainty before retrying; never rerun
solely to recover a missing result. Poll only for an interface or diagnostic
milestone. Contain only this task's failed operations within existing authority;
preserve evidence and once-only operations without blind restarts or unrelated
interference.

Use clock/runtime timestamps when elapsed time informs progress or recovery.
Before long operations, state the expected signal and bounded reassessment
point; retain start time and last verified progress in existing context.
Use `technical-investigation` for missed milestones, stalls, and retry diagnostics.

Stop repeated unchanged tool/hook failures without new evidence. Preserve
unapproved/unverified status and report the blocker and next action once; resume
only on new evidence or user direction within existing authorization. Distinguish
execution, human review, approval, and external waits. Keep the turn active while
required work remains. Report verified progress and next action; do not add
timing-only files, heartbeats, arbitrary usage caps, or tracking artifacts just
to populate updates. Finish when requested outcomes and relevant checks pass.

## Verification and independent review

Verify requested behavior through the current public entrypoint. Tests,
including setup and cleanup, use isolated targets; never modify production or
shared live state for verification. Resolve actual write destinations before
mutating tests. Report any acceptance that cannot safely be verified.

After integration wiring changes, recheck affected public reachability and
acceptance; component tests or historical approval alone do not establish it.
Inspect the final diff for unused scaffolding,
speculation, unnecessary indirection, and unrelated changes; retain complexity
required for correctness, security, reliability, performance, or compatibility.
Remove an invalid harness assertion only with evidence that legitimate
acceptance remains covered.

Before presenting a completed plan or handing off file changes, assess actual
risk. For material architecture, component boundaries, public interfaces, data
flow, security, credentials, migrations, destructive operations, or
compatibility; unresolved nonlocal correctness; or an explicit
independent-review request, load `review-gate` and require independent
`review-correctness`. Judge actual
consequences, not keywords, delegation, file count, or Plan Mode alone.
Routine locally observable work needs primary validation.

Require an independent checkpoint before consequential actions in those risk
classes and after an inconclusive material spike before another implementation
attempt. Reassess after two failed corrections; require review before the third
if material or critical uncertainty remains. Review cannot waive a runnable
proof. Actual credential exposure requires a bounded security specialist;
other specialists need a concrete risk or expertise gap. Follow `review-gate`
for current-evidence verdicts, corrections, and returned RevDiff feedback.
Block dependent work when required review is unavailable or validated findings
remain unresolved. Review never authorizes publication or a consequential action.

## Tool-specific workflows

Before planning or implementing material tracked work in a Git checkout, load
`beads`, perform project discovery, and follow its canonical-path checks. Stop
on mismatch. If no project exists, continue without initializing or proposing
Beads. For work owned by an existing Bead, read it before substantive work and
use its exact-read, refresh, and checkpoint rules for recovery against actual
Git/process state. Discovery is not an issue read.

Keep routine work out of Plan Mode. For substantial planning, enter Plan Mode
with the native tool and think the design through thoroughly there; leave it
only through the standard plan approval. The `revdiff-herdr` plugin opens each
completed plan in RevDiff at that point: address every returned annotation and
never treat a failed or skipped review as acceptance. Never bypass a pending
approval or active collaboration rules.

Never publish anything to claude.ai (the Artifact tool or hosted docs). Show
plans, reviews, and diagrams locally with `moshi-media-preview`, or inline.

Use pytest for new or modified Python tests; do not add `unittest` imports,
`unittest.TestCase` suites, or `self.assert*` calls. Convert affected existing unittest
tests, broadening only when needed to keep their module coherent.

Never use tmux to run, observe, or drive a command or program that needs a
terminal. Load `herdr` and use its panes and tabs instead.
