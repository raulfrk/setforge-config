---
name: reviewing-bd-leaks
description: Always-on 1-agent scan for leaked Beads / bd task-tracker references in shipping artifacts (code, docstrings, comments, shipped docs, commit messages, PR descriptions). Dispatches `bd-leak-reviewer` via a single Agent tool call. Run in EVERY review process regardless of artifact type — Phase 5 and again post-merge in Phase 7.
---

# Reviewing bd Leaks

This skill orchestrates a 1-agent scan that enforces the "Beads stay truly invisible" rule. It is **language-agnostic** and runs on ANY diff: while the per-language fans (`reviewing-python-code`, `reviewing-rust-code`, etc.) are picked by artifact type, this one ALWAYS runs in parallel with whatever fans apply, because a tracker reference can leak into any file type, a commit message, or a PR body. The agent under `~/.claude/agents/` is dispatched via the `Agent` tool **in a single message**.

## When to invoke

- **Phase 5** (review fan) after Phase 4 (Implement) completes and before Phase 6 (Address findings + merge), per the 7-phase flow in the `session-flow` skill. Always — not gated on artifact type.
- **Phase 7** (post-merge cross-cutting review) against the merged HEAD on the target branch.

Artifacts in scope: code, tests, comments, docstrings, shipped docs (README, CHANGELOG, docs/, COMPATIBILITY.md), commit messages, and PR descriptions.

Exempt (the private orchestration layer legitimately references bd): `**/CLAUDE.md`, `**/.claude/skills/**`, `**/.claude/agents/**`, `tracked/claude/**`, fixtures mirroring that layer, and the leak-detector's own files. The agent enforces these exemptions itself.

This skill runs ALONGSIDE the artifact-specific fans; invoke it via its own Skill invocation in the same review batch. The per-language fans do NOT need to scan for tracker leaks — that is this skill's job.

## Dispatch inputs

Compute (or accept as input):

| Input | Default |
|---|---|
| `BASE_SHA` | `git merge-base HEAD origin/main` |
| `HEAD_SHA` | `git rev-parse HEAD` |
| `changed_files` | `git diff --name-only $BASE_SHA..$HEAD_SHA` |
| `pr_number` | the PR under review, or `(none)` |

## Dispatch

Send **a single message** containing 1 `Agent` tool call:

1. `subagent_type: bd-leak-reviewer` — detects leaked Beads / bd task-tracker references in shipping artifacts.

Prompt template:

```
You are scanning the diff in BASE_SHA..HEAD_SHA for leaked Beads / bd references.
BASE_SHA: <sha>
HEAD_SHA: <sha>
changed_files:
- <file>
- <file>
...
pr_number: <number or "(none)">

Apply your aspect-specific checklist (see your system prompt body).
Return structured findings + DoD checklist + verdict line.
```

## Consolidation

After the agent returns, produce a single report:

```
# bd-leak review report (BASE_SHA..HEAD_SHA)

## bd-leak-reviewer (orange)
<sub-report verbatim — or verdict line only if PASS>

## Overall
- bd-leak: <verdict>

Overall verdict: <verdict>
```

## After the report

- Any `[BLOCK]` finding → remove the leaked reference before merge (reword the docstring/comment, amend the commit message, edit the PR body). Per the commit conventions in CLAUDE.md, leak-removal changes commit as their OWN commits.
- A leak is a ship-invariant violation: there is no "MINOR" tier here — confirmed leaks block merge until removed.

## Definition of done for the orchestrator

- [ ] Single dispatch issued via a single message.
- [ ] Agent returned a `Verdict: ...` line.
- [ ] Consolidated report produced — sub-report verbatim when BLOCK; compressed to verdict when PASS.
- [ ] Verdict stated explicitly.

## Self-improvement

While using this skill, stay alert for any *generic* way it could be better — clearer wording, a missing case, a smoother step, a recurring friction it should prevent. Not only failures; any worthwhile improvement, noticed anytime.

- **Don't edit mid-task.** Capture the observation; keep working.
- **At a completion checkpoint** (a finished unit of work before the next, or session end), pause and, if anything surfaced, propose it as a diff to THIS file via revdiff — one edit per idea, citing what prompted it.
- **Generic only.** Global config used across every project; never bake in project-specific detail (paths, repo/profile names, bead IDs) unless this artifact is itself project-scoped.
- **Never auto-apply.** Propose via revdiff; the user approves every edit. Never write it yourself.
- **Off-limits — never propose edits to:** hard rails, the safety/environment sections, system paths, `setforge:user-section` marker lines or their `hash=`, and *this self-improvement protocol itself* (the mechanism may not rewrite its own leash).
- **Substantive, not noise.** Rare and load-bearing; not cosmetic rewording; never re-propose a declined idea.
