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
- `--description`: **the FIRST line MUST be `Workdir: <exact absolute working/sub-project path>`** — the `handoff-discovery` SessionStart hook path-matches on this line to surface the handoff in the right directory, so use the actual working dir (e.g. a monorepo sub-project path like `/home/raul/mono/api`), not merely the repo root; then project dir path; active worktree + branch; **epic ID** (text reference — not a bd `--parent` link, since the handoff repo is a separate beads database); why session ended; original paused bd reference
- `--design`: active decisions / context next session needs
- `--acceptance`: specific next-step actions the next session should take
- `--notes`: outstanding research; open user Qs; any context that helps the next session resume quickly

## Discovery at next session

Discovery is automatic and owned by the `pickup` skill — not this one. At session start the `handoff-discovery` SessionStart hook scans `~/handoff/`, path-matches each open handoff's `Workdir:` path against the session's start dir, and injects any match as context pointing at `pickup`. The `pickup` skill then runs the resume gate: present the matched handoff(s) + each project's `bd ready`, the user picks one or several, `pickup` closes the consumed handoff(s), claims, and enters the flow. See the `pickup` skill and the `session-flow` "Auto-resume" section for the full lifecycle.

If `~/handoff/` does not exist there are no handoffs; the hook creates + inits it for next time. The directory is created on first handoff or first session-start scan, not at setup time.

## Closing

The consumed handoff bead is closed by `pickup` AFTER the user picks what to resume — never before the gate. It stays open until then, so an un-resumed handoff resurfaces next session. Ephemeral once consumed, not long-lived.
