---
name: revdiff
description: Open explicitly requested interactive RevDiff reviews of diffs, files, and documents, collect inline annotations, and address them in context. Also answer questions about RevDiff usage, configuration, themes, and keybindings. Use for requests such as "revdiff", "annotate diff", "interactive diff review", "revdiff FILE", or "open this review in revdiff"; a generic request for a written review does not itself request the TUI.
---

# revdiff - TUI Diff Review

Review diffs with inline annotations using revdiff TUI in a terminal overlay. Works in git, hg, and jj repos (auto-detected).

## Script Path Resolution

OpenCode reports the absolute base directory when this skill is loaded.
Resolve the directory containing that exact file, then use its `scripts/`
directory:

```bash
SKILL_DIR="<absolute directory containing this loaded SKILL.md>"
SCRIPT_DIR="$SKILL_DIR/scripts"
```

Do not guess a config-repository path. Use the base directory reported by the
loaded skill and `$SCRIPT_DIR` for script paths throughout this skill.

## Activation

Open the TUI for explicit interactive annotation intent, such as "revdiff",
"annotate this file", "interactive diff review", or "open this review in revdiff".
Use context to distinguish a request for written analysis from a request to open
the review UI; phrases such as "review changes" alone do not require a TUI.
The profile's completed-plan plugin remains the automatic plan-review flow;
do not launch a duplicate manual review when it is handling that plan.

## Answering Questions

If the user asks a question about revdiff (configuration, themes, keybindings, installation, usage) rather than requesting a review session, consult the reference files in `references/` and answer directly. Do NOT launch the TUI for informational questions.

- `references/install.md` — installation methods and plugin setup
- `references/config.md` — config file, options, colors, chroma themes
- `references/usage.md` — examples, key bindings, output format

## Using Existing Review History

If the user says things like "locate my review", "use my latest revdiff annotations", "pull up the review I just did in another terminal", or "what did I annotate earlier" — the user ran revdiff outside this plugin flow and wants OpenCode to process the stored annotations. Read the most recent file from the persistent history directory via the helper script, then process the annotations through Step 3.5 classification as if they had come from a fresh launcher call:

```bash
$SCRIPT_DIR/read-latest-history.sh
```

The script resolves the history dir from `$REVDIFF_HISTORY_DIR` (default `~/.config/revdiff/history`), finds the repo subdir via VCS root basename (jj/git/hg), and prints the newest `.md` file found. Each history file contains a header (path, refs, and — when available — a git commit hash), the annotations in `## file:line (type)` format, and the raw git diff for annotated files. The `commit:` line and diff block are captured from git only; in hg/jj repos the diff block will be empty and no commit hash is recorded. See `references/usage.md` "Review History" section for directory layout, stdin/only handling, and override options.

The history file is also the recovery path when a review is cut short by a lost connection: on signal termination (a SIGHUP from a dropped SSH/tmux client, or a SIGTERM) revdiff saves the current annotations to history — never the `-o` output — so `read-latest-history.sh` still recovers them.

## Opening an In-Session Review

When the user asks to open an in-session review in revdiff (the conversation already contains review comments produced earlier in the session), write those comments to a temp file (e.g. `/tmp/revdiff-review-XXXXXX.md`) using the format documented in `references/usage.md` ("Output Format" section), then run the normal launcher flow (Step 1 ref detection, Step 2 invocation) with `--annotations=<temp-path>` appended. Retain that exact preload baseline and its known authorship until the review
finishes. Compare returned annotations with it before Step 3.5: unchanged
assistant suggestions are not user instructions and do not authorize edits.
Interpret user additions or changes in context; reordering alone is not approval.
Existing explicit user directions remain valid, but do not repeat completed work.
If authorship or intent cannot be established for a consequential edit, clarify
that edit rather than treating the whole returned file as new authorization.

## Reviewing a Diff That Lives Outside the Working Tree

Some review targets are not the current repo state: a GitHub PR diff, a patch file on disk, or `git format-patch -1 --stdout` output. Pipe the unified diff into `revdiff --stdin` and the input is parsed as a real multi-file diff (one tree entry per file, hunk navigation, per-file annotations) instead of a context-only buffer. revdiff auto-detects the unified-diff signature; on a malformed patch the input falls back silently to raw-text mode.

After establishing that an interactive RevDiff review was requested, use this
instead of the normal launcher flow when:
- the user asks to "review PR #N", "review this patch", "review `gh pr diff` output", or supplies a patch URL/path
- the diff describes commits that are not checked out locally (e.g. someone else's branch on a remote-only PR)
- the user pastes a unified diff and asks for a review of *that diff*, not the working tree

Example invocations (route through the same launcher as the normal flow):

```bash
gh pr diff 123 | $SCRIPT_DIR/launch-revdiff.sh --stdin
git format-patch -1 --stdout | $SCRIPT_DIR/launch-revdiff.sh --stdin
cat /tmp/feature.patch | $SCRIPT_DIR/launch-revdiff.sh --stdin
```

`--stdin` is mutually exclusive with refs, `--staged`, `--only`, `--all-files`, `--include`, `--exclude`, and `--annotations`, so do not combine with the Step 1 ref detection — go directly to Step 3 once the launcher returns. Annotations come back keyed by the real file paths from the diff (not by `--stdin-name`).

## How It Works

1. Launch revdiff in a Herdr tab when `HERDR_ENV=1`, otherwise use the upstream terminal backend selection
2. User navigates the diff, adds annotations on specific lines
3. On quit, annotations are captured from stdout
4. OpenCode reads annotations and addresses each one
5. Loop: re-launch revdiff to verify fixes, user can add more annotations
6. Done when user quits without annotations

## Workflow

### Step 1: Determine Review Mode

**All-files mode**: If `$ARGUMENTS` matches "all files", "all-files", or "browse all files" (with optional "exclude <prefix>" parts), use **all-files mode**:
- Pass `--all-files` to the launcher
- If user mentions exclude patterns (e.g., "exclude vendor", "exclude vendor and mocks"), pass each as `--exclude=<prefix>`
- Skip ref detection entirely, go directly to Step 2
- Example: "all files exclude vendor" → `--all-files --exclude=vendor`

**File review mode**: If `$ARGUMENTS` is a single token that points at a file on disk (e.g., `docs/plans/feature.md`, `/tmp/notes.txt`, `README.md`, `main.go`, `file.blah`), treat it as file review:
- Decide with `test -f "$ARGUMENTS"` — if the file exists, it's file review mode
- Also treat as file review if the token starts with `/` or `./`, or contains `/` and has a file extension (e.g., `src/app.go`), even when the file is not yet reachable from the current directory
- Skip ref detection entirely
- Go directly to Step 2 with `--only=<filepath>` (no ref argument)
- Works both inside and outside a VCS repo — revdiff reads the file from disk as context-only
- Ambiguous token (e.g., `main` — both a branch name and a potential filename without extension) → prefer ref mode; ask the user only if neither `test -f` nor `git rev-parse --verify` resolves

**Ref mode**: If `$ARGUMENTS` contains explicit ref(s) (e.g., `HEAD~1`, `main`, or `main feature` for two-ref diff), use as-is.

**Auto-detect**: If no ref provided, run the smart detection script:

```bash
$SCRIPT_DIR/detect-ref.sh
```

The script outputs structured fields:
- `branch`, `main_branch`, `is_main`, `has_uncommitted`, `has_staged_only`
- `suggested_ref` — the ref to pass to revdiff (empty = uncommitted changes)
- `use_staged` — if `true`, pass `--staged` to the launcher (staged-only changes detected)
- `needs_ask` — if `true`, ask the user before proceeding

**When `use_staged: true`**, pass `--staged` to the launcher. This means all changes are in the index (staged) with nothing unstaged — without `--staged`, revdiff would show an empty diff.

**When `needs_ask: true`** (on a feature branch with uncommitted changes), present the user with options as a numbered list and wait for their response:

1. **Uncommitted only** — pass no ref (review just working changes)
2. **Branch vs {main_branch}** — pass main_branch as ref (full branch diff including uncommitted)

**When `needs_ask: false`**, use `suggested_ref` directly:
- On main + uncommitted → no ref (uncommitted changes)
- On main + staged only → no ref + `--staged` (staged changes)
- On main + clean → `HEAD~1` (last commit)
- On feature branch + clean → main branch name (full branch diff)

### Step 2: Launch Review

When you are launching revdiff for the user (e.g., right after a refactor or analysis), pass `--description="..."` so the info popup (`i` key) explains what the change is and what to look at — markdown is supported. For longer prose, write the markdown to a temp file and pass `--description-file=/tmp/revdiff-desc-XXXXXX.md`. The two flags are mutually exclusive; both are optional. Skip when there's no useful context to add.

**When the recent change likely created new untracked files** (new packages, new test files, new docs, new scripts that haven't been `git add`-ed yet), pass `--untracked` so those files appear in the tree. Use this in working-tree mode (no ref, no `--staged`); skip it for ref-to-ref reviews where untracked files are not part of the historical diff.

Pass `--start-at-change` only when the user explicitly asks for that cursor preference; never infer it automatically.

Run the launcher script:

```bash
$SCRIPT_DIR/launch-revdiff.sh [base] [against] [--staged] [--untracked] [--only=file1] [--all-files] [--exclude=prefix] [--description=text|--description-file=path]
```

**Long-running command:** the launcher stays pending until the user finishes
reviewing. Give it an overall runtime sufficient for human review, while keeping
each tool wait within the harness limit. Do not background it or end the turn
while its required result is pending. If the command yields, retain its session
handle and collect output and exit status. A legitimate human review wait is
not a stalled implementation. If the overall timeout is reached, use Step 3's
recovery path rather than opening a duplicate review.

**Disconnect-resilient tmux window mode**: when running under tmux, prefix the launcher with `REVDIFF_TMUX_WINDOW=1` to open revdiff in a persistent, server-owned tmux window instead of a client-owned `display-popup`. The review then survives a dropped SSH or tmux client — reattach and it is still there. This is a launcher environment variable, not a revdiff flag.

**Pane-scoped overlay (agterm)**: when running in an agterm split, `REVDIFF_AGTERM_PANE=1` opens revdiff in the agent's own pane instead of over the whole session, leaving the sibling pane live and visible. The user sets it in the environment; it is ignored outside a split. This is a launcher environment variable, not a revdiff flag.

The script:
- Selects Herdr first when `HERDR_ENV=1`; otherwise preserves the upstream backend order
- Launches revdiff in an overlay
- Captures annotation output to a temp file
- Prints captured annotations to stdout

The bundled launcher sets `REVDIFF_EXIT_CODE_ON_ANNOTATIONS`; exit `10` means annotations were captured and is not a launcher failure. Treat other nonzero statuses as failures. On those failures the launcher relays revdiff's own stderr — report that text verbatim instead of guessing which argument was at fault.

#### Agterm sessions and approval escalation

When OpenCode runs inside an agterm session, the launcher opens revdiff in agterm's native full-pane overlay — its first-choice backend, checked ahead of tmux. That branch needs `AGTERM_SESSION_ID` and `AGTERM_SOCKET` in the launcher's environment.

Commands that run after an approval boundary run in a fresh environment that **strips every `AGTERM_*` variable** (along with `TERM_PROGRAM` and `GHOSTTY_*`), keeping only `PATH`. Launched from there without those variables, the launcher skips the agterm branch and fails with `no overlay terminal available`.

Before escalating, read the values in the normal (unescalated) environment and inline them as **literal** values in the approved command:

```bash
AGTERM_SESSION_ID='<captured-id>' \
AGTERM_SOCKET='<captured-socket>' \
$SCRIPT_DIR/launch-revdiff.sh --only=<file>
```

- Do NOT reference `$AGTERM_SESSION_ID` / `$AGTERM_SOCKET` inside the approved command — they are already unset there, so the expansion is empty. Read them first in the normal environment, then paste the literal strings.
- Do NOT work around the missing session id by targeting the `active` session (agterm's default): that can open revdiff in an unrelated agterm window or session. The captured session id keeps the overlay on the reviewing session.

### Step 3: Process Annotations

**Collecting launcher output**: In the normal case the launcher returns synchronously with annotations on stdout — process them as described below. If the bash tool reports exit `10`, read stdout and process it as annotations; do not call it a failure. If the bash tool instead reports a timeout, only the launcher process died, but revdiff itself is still open in the overlay and no annotations are lost: revdiff writes them to disk the moment the user quits, and `O` flushes them any time. Do NOT retry the launcher. Use the fallback:

1. Reassure the user and offer both paths, making clear nothing is lost — keep it short and do NOT explain the save mechanics (disk writes, `O` flush, quit-to-save); the user does not need them. Say something like: "The process waiting on your revdiff review timed out and exited — that's harmless, and any annotations you made are safe. Whenever you're done, message me and tell me to either load your annotations and continue, or that you're done and want to stop." Do NOT assume they want to load; quitting with no annotations, or choosing to stop, is a valid outcome.
2. Wait for the user to reply. They cannot respond while the overlay has focus, so their reply means they are back at the session (they quit, or flushed with `O` and switched back).
3. On their reply you MUST act; do not stop at step 1. If they chose to stop, acknowledge and end. Otherwise read the persisted annotations, most recent output file first (the launcher writes to `$TMPDIR` when set, falling back to `/tmp`):
   ```bash
   output_file="$(ls -t "${TMPDIR:-/tmp}"/revdiff-output-* 2>/dev/null | head -1)"
   if [ -n "$output_file" ] && [ -f "$output_file" ]; then
     cat "$output_file"
   fi
   ```
4. If the output file has content, process it as annotations below. If it is empty or missing, fall back to the durable review history, which survives even when the launcher's cleanup removed the temp file: run `$SCRIPT_DIR/read-latest-history.sh` and process the annotations from its `## Annotations` section (see "Using Existing Review History"). Only if both are empty did the user quit without annotating.

Both reads return complete content: revdiff writes the output file atomically on exit, and the history entry is complete before the process exits. That guarantees no partial read, not that the file belongs to this review: with two reviews live under one `$TMPDIR`, the newest match may belong to the other one.

A reviewer may also keep revdiff open on purpose and press `O` to flush the current annotations to the same output file mid-session, without quitting. The flush uses the same atomic write, so the fallback read above still returns a complete file. When the user says something like "I flushed my notes, go ahead" while the overlay is still open, read the most recent output file exactly as in the timeout fallback and process the annotations; do NOT relaunch revdiff. After you finish the code changes, the reviewer reloads with `R` and continues in the same session. No launcher flags change for this — the launcher already passes an output file, and `O` reuses it.

If the script produces output, it contains the returned annotation store, which
may include unchanged preloaded comments. Establish user-authored additions or
changes against the retained preload baseline before treating them as edit
instructions. The output format is:

```
## file.go:43 (+)
use errors.Is() instead of direct comparison

## store.go:18 (-)
don't remove this validation
```

Each annotation block has:
- `## filename:line (type)` — which file and line, `(+)` = added, `(-)` = removed, `(file-level)` = file note
- Comment text below — what the user wants changed

### Step 3.5: Interpret Annotations

Interpret the comment and referenced context together:

- Answer questions directly in chat, including "why is this needed?". Special
  punctuation or opening keywords are not required.
- Apply concrete requested changes within the authorized scope, such as
  "rename this function".
- Clarify material ambiguity, such as "maybe split this" when the intended
  behavior or scope is unclear. Do not treat every other comment as an edit.

Mixed batches may contain questions and edits. Answer the questions and carry
out the clear, authorized edits without an automatic explanation-review loop.
Open an explanation in RevDiff only when the user requests interactive review
of that explanation. Returned questions do not automatically approve edits.

### Step 4: Determine the Scoped Changes

State the intended change proportionally. Existing concrete edit instructions
supply authorization; do not ask "Proceed?" for each annotation. Ask only for
material ambiguity, a necessary missing decision, or an action outside the
existing authorization. Use normal planning and risk checkpoints when required.

### Step 5: Address Annotations

Update the actual source for authorized edits, verify the affected behavior, and
apply the relevant review requirements before presenting the next revision.
Keep questions as questions and preserve the original review target.

### Step 6: Loop

After fixing, continue the explicitly requested interactive review with the same
ref. If only a question was answered, do not automatically open another TUI;
resume it when the user asks to continue the interactive review. The user can:
- Add more annotations → go back to Step 3
- Quit without annotations → review complete (no output)

### Step 7: Done

When the script produces no output, the review is complete. Inform the user.

## Example Sessions

```text
User: "revdiff HEAD~1"
→ launch the HEAD~1 diff
→ user annotates: "handler.go:43 - use errors.Is()"
→ collect completed annotations
→ apply the scoped edit and verify it
→ re-launch the same diff for the requested review loop
→ user quits without annotations: review complete
```

```text
User annotates: "why is this mutex needed?"
→ inspect the referenced code and answer in chat
→ do not change code or open an explanation TUI without a request
```

```text
User: "revdiff all files exclude vendor"
→ launch with --all-files --exclude=vendor
→ collect and interpret returned annotations in context
```

```text
User: "revdiff docs/plans/feature.md"
→ test -f succeeds: use --only=docs/plans/feature.md
→ user annotates: "drop the resolved open question"
→ edit the document within scope and continue the interactive review
```
