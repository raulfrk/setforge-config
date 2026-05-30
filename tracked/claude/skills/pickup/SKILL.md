---
name: pickup
description: Resume a paused session from a handoff bead. Invoke when the handoff-discovery SessionStart hook injects "open handoff(s) match this directory" context, or when the user says "pick up", "resume", "resume from handoff", or "continue where I left off". Owns the resume gate — reads the matched handoff(s) from ~/handoff, presents context + ready beads, lets the user pick one or several, closes the consumed handoff, claims, and enters the session-flow 7-phase flow.
---

# Pickup — resume from handoff

The `handoff-discovery` SessionStart hook (see the `session-flow` skill, "Auto-resume") scans `~/handoff`, path-matches open handoff beads against the session's start directory, and injects any match as context. This skill consumes that signal and runs the resume gate. It can also be invoked directly ("pick up", "resume from handoff").

The `~/handoff` repo is a SEPARATE beads database from any project. Operate on it with `cd ~/handoff` (or `bd` run from there); a handoff bead is consumed (closed) once read.

## The resume gate

1. **Locate matched handoff(s).** Read the hook-injected context (which handoff bead IDs matched this directory). If invoked directly with no injected context, run `cd ~/handoff && bd ready` and path-match each open handoff's tagged sub-project path against the current directory yourself (a handoff matches when its tagged path is at or below the session's start dir — a true path-boundary test, not a substring match).
   - Zero matches → tell the user there's no handoff for this directory; fall back to normal `session-flow` Session-start (select work via `bd ready`).
   - One match → proceed with it.
   - Several matches (a monorepo root over multiple sub-projects) → present all of them; the user may pick one OR several.

2. **Read each matched handoff fully.** `cd ~/handoff && bd show <handoff-id>` — read `--description` (project dir, exact sub-project path, active worktree + branch, epic ID, why the session ended, the original paused bd), `--design` (active decisions/context), `--acceptance` (next-step actions), `--notes` (open questions, research).

3. **Present context.** Summarize for each matched handoff: last session state, active decisions, what was in-progress, and the suggested next steps. For each handoff's project, `cd <project-dir>` and run `bd show <epic-id>` + `bd ready` to surface that project's current ready queue.

4. **Interactive gate** (`AskUserQuestion`). Present the ready beads as options; the handoff's suggested task(s) appear first, marked `(Recommended)`. Other ready beads are additional options. The user picks which to work on — one, several (→ feeds the multi-bead flow), or a different direction via "Other". NEVER auto-claim; the user always chooses.

5. **Consume the handoff(s).** Once the user has chosen, close each consumed handoff bead: `cd ~/handoff && bd close <handoff-id> --reason "Resumed; user selected <choice>"`.

6. **Claim + enter the flow.** `cd <project-dir>`, `bd update <chosen-id> --claim` for the picked bead(s), and enter the `session-flow` 7-phase flow:
   - One bead → single-bead flow.
   - Several beads → the multi-bead pipeline (one combined brainstorm + spec, carve, per-bead plans, wave plan, parallel implement, etc.).

## Monorepo note

A monorepo is several projects in one git repo sharing ONE bead DB, with one epic per project. Handoffs are tagged with the EXACT sub-project working path so a root-level session surfaces every sub-project's handoff and the user disambiguates by picking. A single-repo project is one project (one DB, possibly many epics); the same gate applies, usually with a single match.

## Relationship to other skills

- `session-flow` owns the full 7-phase flow this skill hands off to; its "Auto-resume" and "Session end + handoff" sections describe the hook + handoff lifecycle.
- `handoff` owns CREATING handoff beads (including the exact-sub-project-path tag this skill matches on).
- Invoke `bd-reference` before any `bd` command if not already loaded this session.
