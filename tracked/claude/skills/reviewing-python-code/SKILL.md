---
name: reviewing-python-code
description: 4-aspect parallel review fan for Python code changes (Python source / pyproject / pre-commit / CI workflow edits). Dispatches `python-spec-reviewer`, `python-substance-reviewer`, `python-specifics-reviewer`, and `python-prose-reviewer` in parallel via a single message of Agent tool calls. Consolidates verdicts worst-of-four. Use after Python implementation (Phase 5), and again post-merge (Phase 7).
---

# Reviewing Python Code

This skill orchestrates a 4-aspect parallel review fan for Python code changes. Each aspect is a dedicated specialized agent under `~/.claude/agents/`; this skill's job is to dispatch all four in parallel via the `Agent` tool **in a single message**, then consolidate the four reports.

## When to invoke

- **Phase 5** (review fan) after Phase 4 (Implement) completes and before Phase 6 (Address findings + merge), per the 7-phase flow in the `session-flow` skill.
- **Phase 7** (post-merge cross-cutting review) against the merged HEAD on the target branch.

Artifacts in scope:
- Python source (`*.py`).
- `pyproject.toml`, `uv.lock`.
- `.pre-commit-config.yaml`.
- `.github/workflows/*.yml`.

For mixed-artifact PRs, invoke every applicable skill in parallel via separate Skill invocations: `reviewing-claude-md` when the diff also touches `.md` files under `tracked/claude/`, and `reviewing-markdown` when it touches generic `.md` files outside `tracked/claude/` (READMEs, project-level CLAUDE.md, docs/, CHANGELOG.md, ADRs).

## Dispatch inputs

Compute (or accept as input):

| Input | Default |
|---|---|
| `BASE_SHA` | `git merge-base HEAD origin/main` |
| `HEAD_SHA` | `git rev-parse HEAD` |
| `spec_path` | `~/.claude/projects/{cwd-slug}/specs/<YYYY-MM-DD>-<topic>.md` or `(none)` |
| `bd_id` | derive from current branch / worktree slug, or explicit user input |
| `changed_files` | `git diff --name-only $BASE_SHA..$HEAD_SHA` |

## Parallel dispatch

Send **a single message** containing 4 `Agent` tool calls, one per reviewer:

1. `subagent_type: python-spec-reviewer` — spec/contract conformance.
2. `subagent_type: python-substance-reviewer` — design, error model, security.
3. `subagent_type: python-specifics-reviewer` — CLAUDE.md Python conventions + type-hint completeness.
4. `subagent_type: python-prose-reviewer` — docstring prose quality + factual correctness vs. function body.

Use the same prompt template across all four:

```
You are reviewing the diff in BASE_SHA..HEAD_SHA.
BASE_SHA: <sha>
HEAD_SHA: <sha>
spec_path: <path or "(none)">
bd_id: <bd-id>
changed_files:
- <file>
- <file>
...

Apply your aspect-specific checklist (see your system prompt body).
Return structured findings + DoD checklist + verdict line.
```

## Consolidation

Compress the consolidated report: keep the verdict table (one line per
aspect) and reproduce every CONCERNS or BLOCK finding verbatim; include an
aspect's full sub-report verbatim ONLY when its verdict is not PASS — PASS
aspects compress to their verdict line plus a one-line DoD state.

After all 4 agents return, produce a single report:

```
# Python review fan report (BASE_SHA..HEAD_SHA)

## python-spec-reviewer (red)
<sub-report verbatim>

## python-substance-reviewer (green)
<sub-report verbatim>

## python-specifics-reviewer (purple)
<sub-report verbatim>

## python-prose-reviewer (yellow)
<sub-report verbatim>

## Overall
- python-spec: <verdict>
- python-substance: <verdict>
- python-specifics: <verdict>
- python-prose: <verdict>

Overall verdict: <worst-of-four — BLOCK > CONCERNS > PASS>
```

## After the report

- CRITICAL findings → fix immediately.
- IMPORTANT findings → fix before merge. Per the commit conventions in CLAUDE.md, review-fix changes commit as their OWN commits — never squashed into the implementation commit.
- MINOR findings → fix inline as separate commits unless the fix is large or out-of-scope (file new bd with dep link in that case).

## Definition of done for the orchestrator

- [ ] All 4 reviewer dispatches issued in a single message (true parallel).
- [ ] All 4 agents returned a `Verdict: ...` line.
- [ ] Consolidated report produced — every non-PASS sub-report verbatim; PASS aspects compressed to verdict + DoD state.
- [ ] Worst-of-four overall verdict computed and stated explicitly.

## Self-improvement

While using this skill, stay alert for any *generic* way it could be better — clearer wording, a missing case, a smoother step, a recurring friction it should prevent. Not only failures; any worthwhile improvement, noticed anytime.

- **Don't edit mid-task.** Capture the observation; keep working.
- **At a completion checkpoint** (a finished unit of work before the next, or session end), pause and, if anything surfaced, propose it as a diff to THIS file via revdiff — one edit per idea, citing what prompted it.
- **Generic only.** Global config used across every project; never bake in project-specific detail (paths, repo/profile names, bead IDs) unless this artifact is itself project-scoped.
- **Never auto-apply.** Propose via revdiff; the user approves every edit. Never write it yourself.
- **Off-limits — never propose edits to:** hard rails, the safety/environment sections, system paths, `setforge:user-section` marker lines or their `hash=`, and *this self-improvement protocol itself* (the mechanism may not rewrite its own leash).
- **Substantive, not noise.** Rare and load-bearing; not cosmetic rewording; never re-propose a declined idea.
