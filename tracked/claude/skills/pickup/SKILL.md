---
name: pickup
description: Resume a paused session from a handoff bead. Invoke when the user says "pick up", "resume", "resume from handoff", or "continue where I left off", or when `session-flow` routes here at session start after finding a matching handoff. Owns the resume gate — discovers matching handoff(s) in ~/handoff, presents context + ready beads, lets the user pick one or several, closes the consumed handoff, claims, and enters the session-flow 7-phase flow.
---

# Pickup — resume from handoff

This skill discovers handoff beads in `~/handoff` that match the session's start directory and runs the resume gate. Resume is opt-in: invoke it directly ("pick up", "resume from handoff"), or let `session-flow` route here at session start. There is no SessionStart hook — discovery happens when this skill runs, not automatically.

The `~/handoff` repo is a SEPARATE beads database from any project. Operate on it with `cd ~/handoff` (or `bd` run from there); a handoff bead is consumed (closed) once read.

## The resume gate

1. **Discover matched handoff(s).** Run `cd ~/handoff && bd list --status open` and path-match each open handoff against the session's start dir yourself. The matching algorithm is load-bearing and now lives only here (no script backs it), so apply it faithfully:
   - Collect EVERY `Workdir:` line from the handoff's `--description` (in order). If a handoff has no `Workdir:` line, fall back to the path in its title format `Handoff: <name> (<path>)`.
   - Normalize both a tagged path and the start dir with realpath + `~` expansion (resolve symlinks; expand `~`).
   - Treat the handoff as a match when ANY tagged path is **at or below** the start dir — i.e. the normalized tagged path equals the start dir, OR begins with `start-dir + os.sep`. This is a true path-boundary test, never a bare substring match (so `/foo` must not match `/foobar`).
   - A start dir that is a parent therefore surfaces every handoff tagged beneath it (a monorepo root); a sub-project dir surfaces only its own.
   - Zero matches → tell the user there's no handoff for this directory; fall back to the normal `session-flow` "Session start" path (select work via `bd ready`).
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

A monorepo is several projects in one git repo sharing ONE bead DB, with one epic per project. Handoffs are tagged with the EXACT sub-project working path(s) — one `Workdir:` line per dir the work touches — so a root-level session surfaces every sub-project's handoff and the user disambiguates by picking. A single-repo project is one project (one DB, possibly many epics); the same gate applies, usually with a single match.

## Relationship to other skills

- `session-flow` owns the full 7-phase flow this skill hands off to; its "Session start" and "Session end + handoff" sections describe how this skill is invoked and the handoff lifecycle.
- `handoff` owns CREATING handoff beads (including the `Workdir:` path tag(s) this skill matches on).
- Invoke `bd-reference` before any `bd` command if not already loaded this session.

## Self-improvement

While using this skill, stay alert for any *generic* way it could be better — clearer wording, a missing case, a smoother step, a recurring friction it should prevent. Not only failures; any worthwhile improvement, noticed anytime.

- **Don't edit mid-task.** Capture the observation; keep working.
- **At a completion checkpoint** (a finished unit of work before the next, or session end), pause and, if anything surfaced, propose it as a diff to THIS file via revdiff — one edit per idea, citing what prompted it.
- **Generic only.** Global config used across every project; never bake in project-specific detail (paths, repo/profile names, bead IDs) unless this artifact is itself project-scoped.
- **Never auto-apply.** Propose via revdiff; the user approves every edit. Never write it yourself.
- **Off-limits — never propose edits to:** hard rails, the safety/environment sections, system paths, `setforge:user-section` marker lines or their `hash=`, and *this self-improvement protocol itself* (the mechanism may not rewrite its own leash).
- **Substantive, not noise.** Rare and load-bearing; not cosmetic rewording; never re-propose a declined idea.
