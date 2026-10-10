---
name: revdiff
description: Open explicitly requested interactive RevDiff reviews of diffs, files, and documents, collect inline annotations, and address them in context. Also answer questions about RevDiff usage, configuration, themes, and keybindings. Use for requests such as "revdiff", "annotate diff", "interactive diff review", "revdiff FILE", or "open this review in revdiff"; a generic request for a written review does not itself request the TUI.
allowed-tools: [Bash, Read, Edit, Write, Grep, Glob]
---

# RevDiff interactive review

Open RevDiff for explicit interactive annotation requests. It supports Git,
Mercurial, and Jujutsu repositories, plus individual files outside a repository.

## Resolve the bundled scripts

The scripts live beside this loaded `SKILL.md`:

```bash
SCRIPT_DIR="${CLAUDE_SKILL_DIR}/scripts"
```

Do not guess a config-repository path or fall back to `~/.claude/skills`:
marketplace plugins load from a versioned plugin cache. Use `$SCRIPT_DIR` for
every script path below and in linked references.

## Activate narrowly

Open the TUI for requests such as "revdiff", "annotate this file", or
"interactive diff review". A generic request to review changes asks for written
analysis, not the TUI. Do not duplicate the automatic completed-plan review
handled by the bundled ExitPlanMode hook.

For informational questions, answer directly from the relevant reference:

- Read [references/install.md](references/install.md) for installation or plugin setup.
- Read [references/config.md](references/config.md) for configuration, colors, or themes.
- Read [references/usage.md](references/usage.md) for keys, navigation, and output format.
- Read [references/advanced-workflows.md](references/advanced-workflows.md) only
  for external patch/stdin review, preloaded comments, stored-history or timeout
  recovery, persistent tmux windows, or agterm-specific launching.

## Common workflow

### 1. Select the review target

- For "all files", pass `--all-files`; translate each requested exclusion to
  `--exclude=<prefix>` and skip ref detection.
- For a single file, confirm with `test -f` when possible and pass
  `--only=<filepath>` without a ref. Treat absolute paths, `./` paths, and paths
  containing both `/` and an extension as files even if temporarily unreachable.
- For one or two explicit refs, pass them as supplied. Prefer ref mode for an
  ambiguous bare token unless file and ref checks both fail.
- With no explicit target, run `$SCRIPT_DIR/detect-ref.sh`. Honor its
  `suggested_ref` and `use_staged` fields. When `needs_ask` is true, ask the user
  to choose between uncommitted changes and the full branch diff against the
  reported main branch.

For a PR diff, patch, or pasted unified diff that is not the working tree, read
the advanced-workflows reference and use its stdin flow instead of ref detection.

When the user asks for suggested changes with agent annotations, prepare actual
file edits within the authorized scope and review their diff with preloaded
rationale. Use a document-only proposal only when requested. Preserve existing
edits as the baseline, isolate overlapping work when needed, and read the
advanced-workflows reference for the preload procedure. This request does not
expand which files or systems the user authorized you to change.

### 2. Launch RevDiff

Use the single public launcher:

```bash
$SCRIPT_DIR/launch-revdiff.sh [base] [against] [--staged] [--untracked] [--only=file1] [--all-files] [--exclude=prefix] [--description=text|--description-file=path]
```

Add a useful Markdown `--description` when launching after analysis or changes;
use a temporary `--description-file` for longer prose. The flags are mutually
exclusive. Add `--untracked` only for working-tree reviews that should include
new files. Pass `--start-at-change` only when the user explicitly requests it.

The launcher selects Herdr first when `HERDR_ENV=1`; otherwise it preserves the
upstream terminal backend order. It remains pending until the human finishes,
which can exceed the Bash tool's foreground limit. Run it with
`run_in_background`, keep the task handle, and collect its final output and exit
status from the completion notification. Do not end the turn or continue
dependent work while its result is required.

The launcher sets `REVDIFF_EXIT_CODE_ON_ANNOTATIONS`: exit `10` means annotations
were captured successfully. Other nonzero exits are failures; report the
launcher/revdiff stderr rather than guessing. For a timeout, do not launch a
duplicate review—read the advanced-workflows recovery procedure.

### 3. Interpret returned annotations

Annotation records use the form:

```text
## file.go:43 (+)
use errors.Is() instead of direct comparison
```

Interpret each comment with its referenced context:

- Answer questions directly in chat; punctuation or special keywords are not required.
- Apply concrete edits within the already authorized scope.
- Clarify ambiguity that materially changes behavior or scope.

A returned question does not authorize an edit or an explanation-review loop.
For preloaded annotations, use the authorship rules in the advanced-workflows
reference before treating returned text as a new user instruction.

### 4. Address and continue

State the intended scoped change, update the actual source for authorized edits,
and verify affected behavior. Reopen the same explicitly requested interactive
review after edits. If only a question was answered, wait for the user to ask to
resume the TUI. The review is complete when the user quits without annotations.

When the user asks to locate annotations from an earlier external RevDiff
session, read the stored-history workflow rather than opening a new review.
