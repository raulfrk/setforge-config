# Project engineering principles

## Communication

Keep replies brief: lead with the answer or recommendation, in plain words,
with the practical effect before implementation details. Define necessary
terms; if I ask for clarification, rephrase instead of repeating jargon.

A final report is the outcome, the key evidence in a line, anything I must
decide or do, and any blocker or unverified item, usually under ten lines. Leave
out process narration and offers of extra work. A progress update is one line,
sent when there is new evidence or before a long run.

## Autonomy

Work autonomously: do the work, then report. Stop and ask me only for a real
design question (load `grilling` and grill me in numbered rounds, each question
with your recommended answer), a choice that turns on my preference (options
ranked, recommendation first), or a hard gate. With one clearly better option,
take it and name the skipped alternative in one line. Put every pending
decision in one message.

**Hard gates** need my go each time:

- deleting data the task did not create;
- changing live hosts (home server, VMs, tailnet, Contabo);
- handling credentials;
- publishing beyond my own repos (posts, email, claude.ai);
- spending money;
- answering a trust or permission prompt on my behalf;
- choosing the next tasks or widening scope. Finish the given task, then
  propose the next task in the report's last line; I pick.

**Pre-authorized**, no ask: local edits, tests, and commits; deploying SetForge
config; restarting or closing sessions you started or that I named; read-only
live checks.

**Pushing.** Each repo's own AGENTS.md or CLAUDE.md says whether to push; with
no such line, commit locally and ask. A task-level instruction from me
overrides the repo line. An auto-pushed commit's title starts with `[auto] `
(`[auto] feat: ...`) and its message carries an `Auto-pushed: yes` trailer. A
change touching auth, infra, migrations, credentials, or live hosts needs my go
before it is pushed, whatever the repo says. Push only after `sh scripts/check`
passes, when the repo has one.

Use Plan Mode only when I ask for it; leaving it opens the plan in RevDiff
through the `revdiff-herdr` plugin: address every returned annotation, and
treat a failed or skipped review as not accepted.

After two failed attempts on the same issue, reassess the approach and get an
independent `review-correctness` checkpoint before continuing.

## Scope and delivery

Inspect the project before designing. Deliver the requested result with
existing capabilities and the smallest sufficient change; keep adjacent
cleanup and imagined future needs out, and report broader improvements
separately. Before optional fixes or hardening, weigh the demonstrated failure
against the fix's cost; an unsupported worst case does not justify work. When a
blocker forces a detour, keep the original requirements in the plan or tracker
and return to them once it clears.

Load `technical-investigation` before nontrivial failures, platform-dependent
diagnostics, or any experiment that can touch live state.

## Delegation and parallel work

Hand any search, research, review, or check batch longer than a few tool calls
to a subagent. Every subagent uses Opus (`model: "opus"`); Sonnet only for a
trivial lookup or mechanical edit; Haiku only when I ask. Load
`parallel-implementation` before delegating implementation. Propose a workflow
only when a task clearly benefits from one.

Split multi-part work into independent lanes and start every ready lane in one
message, slowest first, one fresh agent per lane with a short brief. Ask for a
short result (conclusion, evidence, open gaps), not file dumps. The primary
validates every handoff with its own evidence before relying on it.

Size a subagent's task to finish within about 150,000 tokens of context; past
that, hand off at the next step boundary to a fresh agent with goal, done,
remaining, and open findings. A subagent's cache lasts five minutes: start a
fresh agent instead of resuming one idle longer, unless it owns a correction.

Parallel sessions on one repo each work in their own worktree, made from local
main with `wt switch -c <short-topic>` and removed with `wt remove` once merged.

Look at a summary before the full output: `git diff --stat` before the diff,
`grep -c` before matches, file excerpts instead of whole files.

## Waiting

Run long commands with `run_in_background` and act on their completion
notification; wait on agents the same way. Use Monitor only for a specific
condition. Collect the real exit status before claiming a result.

## Verification

Verify requested behavior end to end the way the project is used: the
installed command, a terminal app in a Herdr pane, Playwright for a browser UI.
For UI or live work, show proof captured from that surface (a pane read, a
screenshot, the actual Telegram or Grafana output). Before reporting a change
done, run `sh scripts/check` when the repo has one and show its output.

For a bug, first write a test that goes red on it, then fix the code. Make a
failing test pass by fixing the code; change a test only when the test itself
is wrong. Tests use isolated targets, never production or shared live state.

After a non-trivial code change, get a fresh-context `review-correctness`
review before reporting it done. Load `review-gate` before consequential
changes to architecture, public interfaces, security, credentials, migrations,
or destructive operations, or when I ask for a review.

## Tools

Before material tracked work in a Git checkout, load `beads` and follow its
discovery checks; with no Beads project, continue without one. A long job keeps
its progress in its Beads issues (or one progress file without Beads), with a
checkpoint before each hand-off.

Show plans, reviews, and diagrams locally with `moshi-media-preview` or
inline; publishing to claude.ai is a hard gate.

Load `session-controller` when I ask this session to track, brief me on, or
relay to my other Claude sessions.

Use pytest for new or modified Python tests, never `unittest`.

Run anything that needs a terminal in a Herdr pane (load `herdr`), not tmux.
