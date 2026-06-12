---
name: reviewing-rust-code
description: 3-aspect parallel review fan for Rust code changes (Rust source / Cargo manifests / toolchain + lint configs / Rust CI). Runs `cargo clippy` + `cargo fmt --check` once, then dispatches `rust-spec-reviewer`, `rust-substance-reviewer`, and `rust-specifics-reviewer` in parallel via a single message of Agent tool calls. Consolidates verdicts worst-of-three. Use after Rust implementation (Phase 5), and again post-merge (Phase 7).
---

# Reviewing Rust Code

This skill orchestrates a 3-aspect parallel review fan for Rust code changes. Each aspect is a dedicated specialized agent under `~/.claude/agents/`; this skill's job is to run a one-time machine pre-pass (clippy + fmt), then dispatch all three agents in parallel via the `Agent` tool **in a single message**, then consolidate the three reports.

There is no separate prose/doc agent: Rust doc-comment (`///`) accuracy is folded into `rust-specifics-reviewer`.

## When to invoke

- **Phase 5** (review fan) after Phase 4 (Implement) completes and before Phase 6 (Address findings + merge), per the 7-phase flow in the `session-flow` skill.
- **Phase 7** (post-merge cross-cutting review) against the merged HEAD on the target branch.

Artifacts in scope:
- Rust source (`*.rs`).
- `Cargo.toml`, `Cargo.lock`.
- `rust-toolchain.toml`, `rustfmt.toml`, `clippy.toml`.
- `build.rs`.
- `.github/workflows/*.yml` that build/test Rust.

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

## Machine pre-pass (run ONCE, before dispatch)

Run from the crate/workspace root and **capture stdout+stderr without failing the skill on non-zero exit** — compile errors, lint hits, and formatting drift are *findings*, not skill failures:

```
cargo clippy --all-targets --message-format=short -- -W clippy::pedantic -W clippy::nursery
cargo fmt --check
```

The `-W clippy::pedantic -W clippy::nursery` flags are load-bearing: both groups are **allow-by-default**, so a bare `cargo clippy` emits only the warn-by-default lints and the `rust-specifics-reviewer` would have no pedantic/nursery lines to triage. Enabling them as warnings (`-W`, not `-D`) surfaces the full signal the specifics agent is told to interpret, without failing the build.

Toolchain caveat (this VM): invoke so the rustup shim resolves the pinned toolchain — ensure `~/.cargo/bin` is on `PATH` (`PATH="$HOME/.cargo/bin:$PATH" cargo ...`). A stale system `cargo` mis-resolves `rustc` and fails to parse a v4 `Cargo.lock`.

Concatenate the two outputs into a single `clippy_fmt_output` block injected into **every** agent prompt. If `cargo` is absent, or the crate does not build enough to lint, set `clippy_fmt_output: (unavailable: <reason>)` so the agents fall back to manual review instead of assuming a clean machine pass.

## Parallel dispatch

Send **a single message** containing 3 `Agent` tool calls, one per reviewer:

1. `subagent_type: rust-spec-reviewer` — spec/contract conformance.
2. `subagent_type: rust-substance-reviewer` — design, error model, security, `unsafe`, concurrency.
3. `subagent_type: rust-specifics-reviewer` — idiomatic-Rust conventions + clippy/fmt interpretation + tests + doc-comment accuracy.

Use the same prompt template across all three:

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
clippy_fmt_output:
<captured clippy + fmt text, or "(unavailable: <reason>)">

Apply your aspect-specific checklist (see your system prompt body).
Return structured findings + DoD checklist + verdict line.
```

## Consolidation

Compress the consolidated report: keep the verdict table (one line per
aspect) and reproduce every CONCERNS or BLOCK finding verbatim; include an
aspect's full sub-report verbatim ONLY when its verdict is not PASS — PASS
aspects compress to their verdict line plus a one-line DoD state.

After all 3 agents return, produce a single report:

```
# Rust review fan report (BASE_SHA..HEAD_SHA)

## rust-spec-reviewer (red)
<sub-report verbatim — or verdict line only if PASS>

## rust-substance-reviewer (green)
<sub-report verbatim — or verdict line only if PASS>

## rust-specifics-reviewer (purple)
<sub-report verbatim — or verdict line only if PASS>

## Overall
- rust-spec: <verdict>
- rust-substance: <verdict>
- rust-specifics: <verdict>

Overall verdict: <worst-of-three — BLOCK > CONCERNS > PASS>
```

## After the report

- CRITICAL findings → fix immediately.
- IMPORTANT findings → fix before merge. Per the commit conventions in CLAUDE.md, review-fix changes commit as their OWN commits — never squashed into the implementation commit.
- MINOR findings → fix inline as separate commits unless the fix is large or out-of-scope (file new bd with dep link in that case).

## Definition of done for the orchestrator

- [ ] Ran the clippy + fmt machine pre-pass once (or recorded `(unavailable: ...)` with a reason).
- [ ] All 3 reviewer dispatches issued in a single message (true parallel), each carrying `clippy_fmt_output`.
- [ ] All 3 agents returned a `Verdict: ...` line.
- [ ] Consolidated report produced — every non-PASS sub-report verbatim; PASS aspects compressed to verdict + DoD state.
- [ ] Worst-of-three overall verdict computed and stated explicitly.

## Self-improvement

While using this skill, stay alert for any *generic* way it could be better — clearer wording, a missing case, a smoother step, a recurring friction it should prevent. Not only failures; any worthwhile improvement, noticed anytime.

- **Don't edit mid-task.** Capture the observation; keep working.
- **At a completion checkpoint** (a finished unit of work before the next, or session end), pause and, if anything surfaced, propose it as a diff to THIS file via revdiff — one edit per idea, citing what prompted it.
- **Generic only.** Global config used across every project; never bake in project-specific detail (paths, repo/profile names, bead IDs) unless this artifact is itself project-scoped.
- **Never auto-apply.** Propose via revdiff; the user approves every edit. Never write it yourself.
- **Off-limits — never propose edits to:** hard rails, the safety/environment sections, system paths, `setforge:user-section` marker lines or their `hash=`, and *this self-improvement protocol itself* (the mechanism may not rewrite its own leash).
- **Substantive, not noise.** Rare and load-bearing; not cosmetic rewording; never re-propose a declined idea.
