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
- `--description`: project dir path; active worktree + branch; **epic ID** (text reference — not a bd `--parent` link, since the handoff repo is a separate beads database); why session ended; original paused bd reference
- `--design`: active decisions / context next session needs
- `--acceptance`: specific next-step actions the next session should take
- `--notes`: outstanding research; open user Qs; any context that helps the next session resume quickly

## Discovery at next session

SessionStart → `bd prime` → check `~/handoff/` for open beads → read content (project path, epic, context, suggested next-steps) → close the handoff bead (consumed) → `cd <project-dir>` → `bd show <epic-id>` + `bd ready` → present handoff context to user → **interactive gate**: `AskUserQuestion` with ready beads as options (handoff's suggested task marked Recommended) → user picks → claim and begin.

If `~/handoff/` does not exist, there are no handoffs — skip to normal `bd ready` flow. The directory is created on first handoff, not at setup time.

## Closing

Handoff bead is closed immediately after reading — before presenting the interactive gate. Ephemeral, not long-lived.
