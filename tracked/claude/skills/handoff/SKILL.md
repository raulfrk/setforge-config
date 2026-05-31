---
name: handoff
description: >-
  Create a handoff bead when pausing work mid-session. Stores project path,
  epic ID, worktree state, and next-steps in ~/handoff/ for the next session
  to discover and resume from.
when_to_use: >-
  When the user says '/handoff', 'hand off', 'save state', or 'I'm stopping'.
  Also invoked proactively by Claude at session end when work is paused.
---

# Handoff

Create a handoff bead to preserve session state for the next session.

## When to handoff

- User invokes `/handoff` explicitly.
- Claude proposes a handoff proactively when work is paused mid-session.
- Session is ending with a bd issue still in_progress.

## Create the handoff bead

**Always in `~/handoff/`** — never in the current project's beads database. Auto-inits `~/handoff/` as a git repo + beads on first use.

- `--title`: `Handoff: <project-name> (<project-path>)` — routing only, no next-action detail (that goes in description/acceptance)
- `--description`: **emit one `Workdir: <exact absolute working/sub-project path>` line per directory the work touches** — e.g. both the engine repo AND the config repo when work spans both (list the primary working dir first by convention; at least one line is mandatory). Use the actual working dirs (e.g. a monorepo sub-project path like `/home/raul/mono/api`), not merely the repo root — the discovery hook surfaces the handoff in each (see "Discovery at next session" below). Then: project dir path; active worktree + branch; **epic ID** (text reference — not a bd `--parent` link, since the handoff repo is a separate beads database); why session ended; original paused bd reference
- `--design`: active decisions / context next session needs
- `--acceptance`: specific next-step actions the next session should take
- `--notes`: outstanding research; open user Qs; any context that helps the next session resume quickly

## Discovery at next session

Discovery and the resume gate are owned by the `pickup` skill and the `handoff-discovery` SessionStart hook — not this skill. At session start the hook scans `~/handoff/` (creating + initializing it if absent), path-matches open handoffs' `Workdir:` paths against the session's start dir, and points `pickup` at any match. See the `pickup` skill and the `session-flow` "Auto-resume" section for the full lifecycle — including that the consumed handoff is closed only after the user picks.

## Closing

The consumed handoff bead is closed by `pickup` AFTER the user picks what to resume — never before the gate. It stays open until then, so an un-resumed handoff resurfaces next session. Ephemeral once consumed, not long-lived.
