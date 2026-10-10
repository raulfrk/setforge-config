---
name: revdiff-plan
description: Review the last Codex assistant message or proposed plan with inline RevDiff annotations in a dedicated Herdr tab. Use for "revdiff-plan", "review plan with revdiff", "annotate plan", "review last response", or "annotate codex output". Completed proposed-plan blocks are also reviewed automatically by the bundled Stop hook.
allowed-tools: [Bash, Read, Edit, Write, Grep, Glob]
---

# RevDiff Plan Review

Review Codex output as readable Markdown in RevDiff and address every returned
annotation. Inside Herdr, the review opens in a focused tab in the caller's
workspace and returns focus to the caller afterward.

## Resolve bundled paths

Codex supplies the absolute path of this loaded `SKILL.md` in the skill
metadata. Resolve the directory containing that exact file:

```bash
SKILL_DIR="<absolute directory containing this loaded SKILL.md>"
SCRIPT_DIR="$SKILL_DIR/scripts"
PLUGIN_ROOT="$(cd "$SKILL_DIR/../.." && pwd)"
PLAN_LAUNCHER="$PLUGIN_ROOT/skills/revdiff/scripts/launch-revdiff.sh"
```

Do not guess a checkout path or fall back to `~/.codex/skills`. Marketplace
plugins load from a versioned Codex cache.

## Automatic completed-plan flow

The bundled Stop hook is the primary flow for Plan mode:

1. It detects a complete `<proposed_plan>...</proposed_plan>` block in the
   current assistant turn.
2. It stores the canonical Markdown in an ephemeral `plan-rev-*.md` snapshot.
3. The first review is presented as a mapped file-backed text projection. On
   desktop it uses an 80-column reading width starting at column zero; on
   narrow panes it reserves RevDiff chrome and uses the remaining width.
4. The Markdown TOC starts hidden for every RevDiff process. `t` toggles it.
5. If the user annotates, the hook blocks the turn and asks Codex to emit the
   complete revised plan with the exact previous-revision marker it provides.
6. The next review presents the immediately previous and current projections as
   a native one-file diff in an ephemeral Git repository.
7. Projection line numbers are translated back to canonical Markdown lines
   before Codex receives the annotations.
8. Quitting without annotations accepts the plan and removes its snapshot.

The transcript fallback verifies the embedded session ID and selects only the
latest assistant message in the current turn; rollout filenames are not an
identity contract. Launcher failures, missing revision snapshots, and an
annotation exit code with no annotation text block completion with a diagnostic.
They do not mean the user accepted the plan. Diagnose or report the failure;
do not implement the plan or repeatedly re-emit it to retry an unresolved error.

When the terminal width stabilizes after a resize or client switch, the review
automatically reopens at the new width. Existing annotations, including an
empty annotation set, are preserved without returning control to Codex. Press
`q` to finish the review.

Never invent, reuse, or substitute a `plan-rev-*.md` marker. Copy only the
marker emitted for the current review loop.

## Manual review flow

Use this when the user explicitly requests a review of the last response and
the Stop hook did not open one.

### 1. Extract the last response

Resolve the requested conversation's rollout from available identity metadata.
Before extracting, verify that its embedded `session_meta.payload.id` matches
the requested immutable thread ID, or the current thread ID when reviewing this
conversation. Do not select a rollout by modification time: the extractor's
automatic discovery and `--skip-current` are only heuristics and can select
another conversation. Ask for the target only when it remains genuinely unclear.

Pass the verified path explicitly and write the output to a canonical Markdown
snapshot:

```bash
TMPBASE="${TMPDIR:-/tmp}"
CURRENT_PLAN=$(mktemp "$TMPBASE/revdiff-plan-XXXXXX.md")
REVIEW_ROLLOUT="<verified absolute rollout path>"
$SCRIPT_DIR/extract-last-message.sh "$REVIEW_ROLLOUT" > "$CURRENT_PLAN"
```

Check that the extracted text is the requested response, not a subsequent
progress update. If necessary, select that exact message from the verified
rollout before opening the review.

### 2. Open the first review

Run the plugin's public launcher. Markdown routing selects the responsive
document flow automatically:

```bash
$PLAN_LAUNCHER "--only=$CURRENT_PLAN"
```

The launcher remains pending until the TUI exits. Allow sufficient overall
runtime for human review while bounding each tool wait to the harness limit.
Do not background it or end the turn before collecting its required result.
If the command yields, retain its session handle and collect its output and
exit status; do not confuse a running process with completion. Exit `10` means annotations were
captured and is a successful review result; exit `0` with no output means the
review is accepted. Treat other nonzero exits as launcher failures.

### 3. Address annotations

Annotation headers identify the canonical file and line, followed by the
comment. Interpret the meaning in context: answer questions directly, apply
concrete requested plan changes, and clarify material ambiguity. Keywords and
punctuation are hints, not a classification rule; "why is this needed?" is a
question without requiring `??`.

For plan changes, write the complete revision to a new canonical Markdown file;
do not edit the reviewed snapshot in place. A question alone does not require
an extra explanation TUI. Follow any complete-plan and exact previous-revision
marker instructions supplied by the current automatic review loop.

### 4. Review each revision against the preceding one

```bash
PREVIOUS_PLAN="$CURRENT_PLAN"
CURRENT_PLAN=$(mktemp "$TMPBASE/revdiff-plan-XXXXXX.md")
# Write the complete revised Markdown to "$CURRENT_PLAN".
$PLAN_LAUNCHER \
  "--compare-old=$PREVIOUS_PLAN" \
  "--compare-new=$CURRENT_PLAN"
```

The launcher renders both inputs at the same current width and opens a native
one-file comparison. Each iteration compares only with the immediately
preceding plan. Reflow follows stabilized terminal-width changes; `O` exports
annotations and `q` finishes the review. Continue until the launcher completes
successfully without annotations.

### 5. Clean up and report

Remove every manual temp snapshot after the review completes, then present the
final plan if it changed. Preserve snapshots while a review is still active so
the next comparison has the correct baseline.

For a timeout or lost result, follow the RevDiff
[recovery guidance](../revdiff/references/advanced-workflows.md#recover-after-launcher-timeout-or-a-manual-flush).
Preserve snapshots and unresolved completion status until the original review's
result is established; do not launch a duplicate review.
