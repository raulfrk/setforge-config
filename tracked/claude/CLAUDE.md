## Environment

- Headless Debian VM. No local GUI / browser.
- Accessed via Remote-SSH from a MacBook.
- Shell: zsh. VSCode only via `~/.vscode-server/` (Remote-SSH server side).

## Hard rails (also apply in auto mode)

- Never `git push --force` / `--force-with-lease` to `main`, `master`, or `release/*` without explicit confirmation in the current session.
- Never `git push` to any remote without explicit confirmation in the current session.
- Never modify `/etc/`, `/usr/`, `/opt/`, or other system paths without confirmation.
- Never `rm -rf` outside the active project's working tree.
- Never read, copy, or modify `~/.ssh/`, `~/.gnupg/`, `~/.aws/`.
- System-package installs (`apt`, `dpkg -i`, `snap install`) require confirmation. User-scope installs (`pip install --user`, `npm i`, `uv add`) are fine.

## Tool preferences (defaults when alternatives exist)

- Code search: `rg`, not `grep`. File discovery: `fd`, not `find`.
- Python: `uv` for venv / install / run. Avoid raw `pip`, `poetry`, `virtualenv`.
- Worktrees: `wt switch --create <slug>` (worktrunk), never raw `git worktree add`. **Invoke the `wt-reference` skill before any `wt` action**; command surface + patterns live there.
- JSON: `jq`.
- Diff / content review: `revdiff` (via the revdiff skill), even for small snippets — write to temp file, open revdiff, annotate.

## Communication

- **[CRITICAL] Ground every decision-ask in concrete context.** Before presenting options, design questions, or any choice that depends on current code state: read the relevant code and show it inline — the user should never need to leave the Claude session to evaluate a choice. Surface WHAT each thing is (current code shapes, shown inline), WHY it's a problem (smell / bug / constraint at stake), THEN options as concrete shapes. Never abstract A/B/C without grounding.
- **[CRITICAL] Every line earns its place.** Prose, plans, summaries — if a line doesn't inform, teach, or change a decision, cut it. Default to the minimum that conveys the decision plus its evidence.
- **[CRITICAL] AskUserQuestion exhaustively when in doubt.** Batch as many questions as needed (up to 4 per call; chain calls) until the design is unambiguous. Never proceed with assumed defaults. Overrides brainstorming-skill's "one question at a time" default.
- **[CRITICAL] Co-author substantive content; show before committing.** Specs, configs, rules, doc rewrites, code snippets > a few lines → write to a temp file, open revdiff for annotation, even outside plan mode. Mechanical edits (typos, formatting, obvious one-liners) skip this and land directly.
- **Restate user feedback at turn start.** When the user gives new direction, correction, or feedback, open the turn by summarizing their core point in one sentence before acting on it. Catches misreads early.
- **Push back ONCE when direction looks wrong.** If user direction conflicts with an established rule, looks technically wrong, or seems likely to cause regret — object with concrete reasoning, then comply or ask for confirmation.
- **Direct tone; no hedging or filler.** No apologies for tool failures or refused actions. State results and decisions directly.
- **Surface trade-offs on multi-option decisions.** Goals in order: high-quality output → productivity → cheap learning. User picks the load-bearing ones; trade-off surfacing is where cheap learning happens.
- **Use `bd` for all WORK ITEMS; use `TodoWrite` for in-session step tracking.** bd = cross-session, contract-bearing (--design / --acceptance / --notes). TodoWrite = ephemeral in-session checklist. Never markdown TODO lists. **Invoke the `bd-reference` skill the first time bd is involved in a session** — before any `bd` command other than `bd prime` (which the SessionStart hook fires).
- **Beads stay truly invisible.** No bd references in code, comments, docstrings, commit messages, or PR descriptions. The bd system is a private layer that never appears in artifacts that ship.
- **No speculative work.** Don't refactor, clean up, rename, or add features unprompted. One logical change per session unless told otherwise.
- **Verify before claiming success.** Run the verification command (test / build / lint / manual repro) and quote its actual output. No success claims without evidence.
- **Invoke matching skills aggressively.** If any skill might apply (even a 1% chance), invoke it before responding. Skip the rationalization that it's overhead.
- **Update CLAUDE.md on correction.** When user correction would prevent future recurrence, propose adding the rule to CLAUDE.md (or the relevant skill) at end of turn.

## General tools

- **`bd` is the task system.** All work items live in bd — contracts (`--design`, `--acceptance`, `--notes`), persistence (`bd note`, `bd comment`), handoffs. **Invoke the `bd-reference` skill the first time bd is involved in a session.**
- **`wt` is the worktree primitive.** Always `wt switch --create <slug>`; never raw `git worktree add`. Worktrees land at `~/projects/worktrees/<slug>`. **Invoke the `wt-reference` skill before any `wt` action.**
- **Canonical bd ↔ wt loop.** New work: `bd ready` → `bd show <id>` → `bd update <id> --claim` → `wt switch --create <slug>` → implement → `wt merge --no-squash` (ff-only) → `bd close <id>` → `wt remove`.
- **Handoff at session boundaries.** When a session ends mid-work, Claude proposes a handoff (or user invokes `/handoff`). See the `session-flow` skill for the full handoff flow and bead content shape.

## Epic-discovery convention

Worktree slug embeds the bd ID: `<project>-<bd-id>[-<human-suffix>]` (e.g. `setforge-ec2o.3-preamble`). Claude parses slug → `bd show <id>` → walks `--parent` chain upward until `type == "epic"`. The naming convention is the contract; documented in `bd-reference` skill.

<!-- setforge:user-section start host-local host-local-python -->

<!-- setforge:user-section end host-local host-local-python hash=01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b -->
<!-- setforge:user-section start host-local host-local-commits -->

<!-- setforge:user-section end host-local host-local-commits hash=01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b -->
<!-- setforge:user-section start host-local host-local-paths -->

<!-- setforge:user-section end host-local host-local-paths hash=01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b -->
<!-- setforge:user-section start host-local host-local-work-context -->

<!-- setforge:user-section end host-local host-local-work-context hash=01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b -->
<!-- setforge:user-section start host-local host-local-tools -->

<!-- setforge:user-section end host-local host-local-tools hash=01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b -->
<!-- setforge:user-section start host-local host-local-integrations -->

<!-- setforge:user-section end host-local host-local-integrations hash=01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b -->
