# Advanced RevDiff workflows

Read only the section needed for a conditional workflow. Resolve `$SCRIPT_DIR`
from the loaded `SKILL.md` as described there; never substitute a repository or
home-directory guess for the versioned plugin-cache path.

## Review an external unified diff

For a GitHub PR diff, patch file, remote-only branch diff, or pasted unified
diff, pipe the content through the public launcher:

```bash
gh pr diff 123 | $SCRIPT_DIR/launch-revdiff.sh --stdin
git format-patch -1 --stdout | $SCRIPT_DIR/launch-revdiff.sh --stdin
cat /tmp/feature.patch | $SCRIPT_DIR/launch-revdiff.sh --stdin
```

RevDiff recognizes a unified diff as a real multi-file review and falls back to
raw text for malformed input. `--stdin` is mutually exclusive with refs,
`--staged`, `--only`, `--all-files`, `--include`, `--exclude`, and
`--annotations`. Skip ref detection and process returned annotations under their
real file paths.

## Preload an in-session review

When earlier comments in the conversation should be opened in RevDiff, write
them to a private temporary file in the output format documented in
[usage.md](usage.md), then append `--annotations=<temp-path>` to the normal
launcher command.

Retain the exact preload and its known authorship. Compare returned annotations
against that baseline: unchanged assistant suggestions and reordering are not
user instructions. Existing explicit user directions remain valid, but do not
repeat completed work. Clarify any consequential edit whose authorship or intent
cannot be established.

## Explain proposed edits inline

For requested changes with agent explanations, show the actual candidate diff.
Attach short `AGENT RATIONALE:` notes to changed lines using the preload format
above. Explain the reason, relevant evidence, and any relocated instruction's
destination. Keep the original preload to distinguish your notes from later user
feedback; an unchanged agent note is not approval.

Use an existing Git review context for `--annotations`. The installed launcher
can fail to resolve preloaded annotations for a standalone `--only` file outside
Git. For an isolated candidate, keep the user's current file contents as the index
baseline and review only the unstaged task delta; no baseline commit is needed.
Do not stage over existing user changes to manufacture that baseline. `--stdin`
cannot be combined with `--annotations`.

## Load stored review history

For requests such as "use my latest revdiff annotations" or recovery after a
lost connection, run:

```bash
$SCRIPT_DIR/read-latest-history.sh
```

The helper honors `$REVDIFF_HISTORY_DIR` (default
`~/.config/revdiff/history`), resolves the current Git/Jujutsu/Mercurial root,
and prints the newest history file. Process its `## Annotations` section using
the normal interpretation rules. Git history may also contain a commit and raw
diff; Mercurial/Jujutsu history omits the Git-only data. Signal termination
saves annotations to history even when the launcher's output file was not
written. See [usage.md](usage.md) for the full history layout and overrides.

## Persistent and pane-scoped terminals

Under tmux, prefix the launcher with `REVDIFF_TMUX_WINDOW=1` when the review
must survive client disconnection. This opens a server-owned tmux window instead
of a client-owned popup.

In a split agterm session, `REVDIFF_AGTERM_PANE=1` requests an overlay in the
agent's pane while leaving the sibling visible. It is ignored outside a split
and is a launcher environment variable, not a RevDiff flag.

An approved/escalated Codex command receives a fresh environment without
`AGTERM_*`. Before escalation, read `AGTERM_SESSION_ID` and `AGTERM_SOCKET` from
the normal environment and place their literal values in the approved command:

```bash
AGTERM_SESSION_ID='<captured-id>' \
AGTERM_SOCKET='<captured-socket>' \
$SCRIPT_DIR/launch-revdiff.sh --only=<file>
```

Do not reference the variables for expansion inside the approved command and do
not target agterm's `active` session; either can open the review in the wrong
session.

## Recover after launcher timeout or a manual flush

A launcher timeout leaves completion uncertain; the review may still be open.
Preserve its process handle, output path, and review identity. Do not retry or
open a duplicate review. Report only what existing evidence establishes; do not
claim annotations are safe or the review accepted merely because output is
missing or empty.

Recover from the retained process and exact output path first. If those are
unavailable, use output-file discovery or `$SCRIPT_DIR/read-latest-history.sh`
only after matching the result to the original review target and session.
The newest file or history entry can belong to another concurrent review.
Missing or empty sources do not prove a clean quit: keep completion unresolved
until the original process result or equivalent review-specific evidence
establishes it. Reuse existing authorization for read-only recovery.

Pressing `O` exports annotations without quitting. When the user asks to process
a flushed export, verify that it belongs to this review, interpret its comments,
and do not relaunch; they can reload with `R` after edits. An export does not
establish review completion or acceptance. Preserve preload authorship when
interpreting recovered or exported annotations.
