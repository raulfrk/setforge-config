---
name: revdiff-plan
description: Review the last Claude Code assistant message or a plan with inline RevDiff annotations in a dedicated Herdr tab. Use for "revdiff-plan", "review plan with revdiff", "annotate plan", "review last response", or "annotate claude output". Plans are also reviewed automatically by the bundled hook when leaving Plan Mode.
allowed-tools: [Bash, Read, Edit, Write, Grep, Glob]
---

# RevDiff Plan Review

Review Claude Code output as readable Markdown in RevDiff and address every
returned annotation. Inside Herdr, the review opens in a focused tab in the
caller's workspace and returns focus to the caller afterward.

## Resolve bundled paths

```bash
SCRIPT_DIR="${CLAUDE_SKILL_DIR}/scripts"
PLUGIN_ROOT="$(cd "${CLAUDE_SKILL_DIR}/../.." && pwd)"
PLAN_LAUNCHER="$PLUGIN_ROOT/skills/revdiff/scripts/launch-revdiff.sh"
```

Do not guess a checkout path or fall back to `~/.claude/skills`. Marketplace
plugins load from a versioned plugin cache.

## Automatic completed-plan flow

The bundled PreToolUse hook on ExitPlanMode is the primary flow for Plan Mode:

1. It receives the complete plan passed to ExitPlanMode.
2. It stores the canonical Markdown in an ephemeral `plan-rev-*.md` snapshot.
3. The first review is presented as a mapped file-backed text projection. On
   desktop it uses an 80-column reading width starting at column zero; on
   narrow panes it reserves RevDiff chrome and uses the remaining width.
4. The Markdown TOC starts hidden for every RevDiff process. `t` toggles it.
5. If the user annotates, the hook blocks ExitPlanMode and asks Claude to call
   it again with the complete revised plan and the exact previous-revision
   marker it provides.
6. The next review presents the immediately previous and current projections as
   a native one-file diff in an ephemeral Git repository.
7. Projection line numbers are translated back to canonical Markdown lines
   before Claude receives the annotations.
8. Quitting without annotations removes the snapshot and continues to Claude
   Code's own plan approval prompt.

Launcher failures, missing revision snapshots, and an annotation exit code with
no annotation text also continue to the native approval prompt, with a
diagnostic saying the plan was not reviewed. They do not mean the user reviewed
the plan in RevDiff. Report the failure; do not repeatedly call ExitPlanMode to
retry an unresolved error.

When the terminal width stabilizes after a resize or client switch, the review
automatically reopens at the new width. Existing annotations, including an
empty annotation set, are preserved without returning control to Claude. Press
`q` to finish the review.

Never invent, reuse, or substitute a `plan-rev-*.md` marker. Copy only the
marker emitted for the current review loop.

## Manual review flow

Use this when the user explicitly requests a review of the last response and
the hook did not open one.

### 1. Extract the last response

The transcript of a session is
`~/.claude/projects/<cwd-slug>/<session-id>.jsonl`. For this conversation the
ID is `${CLAUDE_SESSION_ID}`; for another one, resolve its ID first and ask for
the target only when it remains genuinely unclear. Do not select a transcript
by modification time: the newest file can belong to another conversation.

Pass the verified path and session ID explicitly and write the output to a
canonical Markdown snapshot:

```bash
TMPBASE="${TMPDIR:-/tmp}"
CURRENT_PLAN=$(mktemp "$TMPBASE/revdiff-plan-XXXXXX.md")
REVIEW_TRANSCRIPT="<verified absolute transcript path>"
$SCRIPT_DIR/extract-last-message.sh "$REVIEW_TRANSCRIPT" "<session-id>" > "$CURRENT_PLAN"
```

Check that the extracted text is the requested response, not a subsequent
progress update; text from the turn still in progress may not be in the
transcript yet. If necessary, write that exact message to the snapshot yourself
before opening the review.

### 2. Open the first review

Run the plugin's public launcher. Markdown routing selects the responsive
document flow automatically:

```bash
$PLAN_LAUNCHER "--only=$CURRENT_PLAN"
```

The launcher remains pending until the TUI exits, which can exceed the Bash
tool's foreground limit. Run it with `run_in_background`, keep the task handle,
and collect its output and exit status from the completion notification; do
not confuse a running process with completion. Exit `10` means annotations were
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
