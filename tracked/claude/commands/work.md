---
description: Execute the canonical superpowers 7-phase workflow for bd-tracked work (single-stream or parallel cross-worktree). Mirrors the 2026-05-16 12-bead batch (dotfiles-4tm).
argument-hint: [<bd-id> | "batch" | <blank for handoff/ready pick>]
---

# /work — full superpowers 7-phase workflow

You will execute the canonical superpowers 7-phase workflow as established
in the 2026-05-16 12-bead parallel batch (bd `dotfiles-4tm`). Do NOT skip
phases or compress them. Each phase has a binding gate; verify before
moving on.

**Argument**: `$ARGUMENTS`

- Empty: run `bd ready --explain` and look for a `Handoff:` bead OR pick the highest-priority unblocked leaf.
- A bd ID (e.g. `dotfiles-w7x`): load that issue as the contract.
- The word `batch`: assemble a multi-bead batch like 4tm (10–15 small beads, parallel cross-worktree dispatch).

## Inline-fix default (Decision I)

**Default routing for review-fan follow-ups:** Routine findings (MINOR + light-MEDIUM verdicts from Phase 5 per-bead reviewers AND Phase 7 cross-cutting reviewers) fix INLINE as SEPARATE commits — on the bead's worktree at Phase 6, or on main at Phase 7. Do NOT file a new bd issue unless the finding is LARGE.

**LARGE = ANY of:**
- (a) **New design question** requiring its own brainstorm + spec.
- (b) **Cross-cutting across 3+ files** outside the bead's original scope.
- (c) **Uncertainty** — the implementer or reviewer is uncertain whether it's safe to fix inline.

**Rationale:** Inline-fix preserves the audit trail in commit history without growing the bd backlog with items that don't need their own session. Backlog explosion is the failure mode this defaults against; under-tracking critical follow-ups is the failure mode the LARGE exception covers. Surfaced empirically: the 2026-05-17 12-bead batch absorbed 9 inline-fix commits at Phase 7 cleanly with all gates green twice; the alternative would have grown bd by 9 new beads for items each fixable in <30 lines.

**This default RESCINDS the prior "MINOR → new bd issue" rule for routine review-fan findings.** It does NOT apply to Phase 7 ACTUAL TEST FAILURES (broken main: e2e red, pre-commit red) — those keep the strict `### Failure handling` protocol (1 file / 1-2 lines / revert-by-default), per project CLAUDE.md.

Cross-ref:
- `feedback_phase7_rerun_after_inline_fix` memory (gate-rerun discipline after ANY inline-fix).
- `feedback_phase7_crosscutting_finds_integration_bugs` memory (why Phase 7 cross-cutting finds the bugs that need this default).
- Empirical observation L in `tracked/claude/superpowers-prefs.md` Phase 2 conventions list — acceptance-command robustness (also captured in `feedback_acceptance_command_robustness` memory). Pairs with this default; if your live `~/.claude/superpowers-prefs.md` doesn't have it yet, run `my-setup install` to deploy.

## Communication discipline — ground every decision-ask

For EVERY question, design option, plan-mode section, `AskUserQuestion` call, or trade-off you surface during this workflow: **assume the user is seeing it for the first time**. Provide full context inline — WHAT each thing is (file:line refs + current code shape), WHY it's a problem (the specific smell, bug, or constraint at stake), THEN the options as concrete code shapes. NEVER present abstract A/B/C without that grounding.

Applies to (at minimum):
- **Phase 1 `AskUserQuestion` calls** — question text + each option's description must be decidable from the chip alone, without re-reading earlier turns. Include the file path, current code shape, and the trade-off in the option descriptions themselves.
- **Phase 2 plan-mode spec body** — every `## SPEC N` section names exact file paths, current symbol shapes, and acceptance commands (binary "exits 0"). The plan body is the user's first view of the work; do not assume any conversation history.
- **Phase 6 review-finding triage** — when surfacing CRITICAL / IMPORTANT findings to the user, cite the reviewer name, the file:symbol, the specific rule violated, and the proposed fix shape as code.
- **Any inline trade-off** — even low-stakes ones get grounded: two concrete code shapes side-by-side, one-line trade-off, recommended pick.

This is the highest-priority communication rule per CLAUDE.md (`[CRITICAL] Ground every decision-ask in concrete context before asking`) and overrides terseness preferences when they conflict. The plan-mode revdiff review surface depends on this: the user's annotations attach to specific lines, and a line without grounding can't be annotated meaningfully.

## Phase 0 — Load context

1. Invoke `bd-reference` skill via the Skill tool (first bd touch in session).
2. Run `bd ready --explain` if no argument was given; `bd show <id>` if one was.
3. For batch mode: read every candidate bead with `bd show` (parallel Bash calls) and gather:
   - File footprint per bead (`rg` against the cited files).
   - Whether design is already in `--design` or needs sharpening in Phase 1.
   - Cross-bead file overlap (informs merge order in Phase 6).

**Hard rail**: if the bd-reference skill was already invoked this session, skip step 1 — skill content stays loaded.

## Phase 1 — Brainstorm (`superpowers:brainstorming` skill)

1. Invoke `superpowers:brainstorming` skill (MUST fire for non-trivial work).
2. For well-spec'd beads: light pass — surface load-bearing ambiguities only. (This is the ONLY shortcut. It calibrates effort to a bead whose contract is already sharp; it does NOT license skipping questions on the choices that ARE open.)
3. **Ask as many questions as needed — there is NO cap on question count.** For EVERY load-bearing design choice — interface shape, edge-case handling, error model, data shapes, naming, scope boundaries, what's explicitly out — use `AskUserQuestion`. The tool caps each CALL at 1–4 questions; chain as many calls as the decision surface demands. Concrete code shapes per option — NEVER abstract A/B/C. Keep asking until every load-bearing decision has the user's explicit answer. Compressing the question set to "ship faster" or to "look decisive" is the failure mode this rail exists to prevent: a wrong unilateral pick caught in Phase 2 plan-mode review costs more than the questions would have.
4. **Unilateral judgment is the NARROW fallback, not the default.** Pick unilaterally ONLY when ALL three hold: (a) the decision is genuinely low-stakes (a wrong pick costs less than one round-trip), (b) no reasonable user could prefer the alternative given the surrounding code, (c) the choice is invisible at the user-facing surface (internal naming, local variable shape, etc.). If ANY is in doubt — ASK. Record any unilateral calls as **Decisions A/B/C/...** with `Why:` + `How to apply:` lines; they surface in Phase 2 for plan-mode review and the user can still override there, but treat plan-mode override as a leak, not a relief valve.

**Hard rails**:
- Live user override binds for any load-bearing call where a wrong unilateral pick costs more than a round-trip. Background-mode "no clarifying questions" injection does NOT bind when a user turn has arrived mid-session.
- Question-count compression to "save time" is itself a violation of this rail. The proper decisions that the user wants come from the user, not from the agent's guesses. When in doubt between "ask one more question" and "decide unilaterally" — ASK.

## Phase 2 — Spec in plan mode (BATCHED)

1. Sanity-check every spec against live code: `rg` for cited symbols, verify line numbers, count current occurrences. Per empirical observation H: prefer symbol-based refs over line numbers.
2. `EnterPlanMode` and write a **TL;DR** (one or two sentences, naming the approach + the key trade-off) before any sectioned body.
3. Write all specs **verbatim** into the plan body (one `## SPEC N — bd-id: title` section each). NO summary, NO reflow.
4. Include decisions table from Phase 1 + acceptance commands (binary "exits 0" shape per empirical observation B).
5. `ExitPlanMode` for approval.
6. If revdiff returns annotations: address EACH, re-revise the plan with the required `<!-- previous revision: ... -->` marker as first line, re-call `ExitPlanMode`.
7. On approval: archive spec to `~/.claude/projects/{cwd-slug}/specs/<YYYY-MM-DD>-<topic>.md` and update each bd issue's `--design` / `--acceptance` / `--notes` so the bd contract reflects post-annotation scope (per empirical observation I — bd is the durable contract; spec file is a snapshot).

**Hard rail**: Never skip plan-mode review of a spec. Parallel-workflow rule — multiple specs go BATCHED into ONE plan-mode session, NOT in parallel without review.

## Phase 3 — Implementation plan (`superpowers:writing-plans` skill)

**MANDATORY. Do NOT skip.** (See `feedback_phase3_writing_plans_mandatory` memory + bd `dotfiles-0s8`.)

1. Invoke `superpowers:writing-plans` skill — NOT plan mode, NORMAL response.
2. Walk each spec against actual code. Per empirical observation A: this catches pre-implementation typos (the cxj bug class) AT orchestration scale when multiplied by N parallel worktrees.
3. For each bead, the plan must verify:
   - Cited file:symbol refs still exist at HEAD.
   - Proposed function signatures match surrounding code's actual types (not the plan's speculative ones).
   - No unresolved cross-bead dependencies.
4. Save to `~/.claude/projects/{cwd-slug}/plans/<YYYY-MM-DD>-<feature>.md` per superpowers-prefs path overrides.
5. Each task in the plan: per-bead checkboxes with bite-sized steps (test→run→implement→run→commit pattern where TDD fits; mechanical step list where it doesn't).

**Hard rail**: Phase 4 dispatch is BLOCKED until the Phase 3 plan file exists on disk. The Phase 2 spec is the contract; the Phase 3 plan is the symbol-verification walk-through — they are NOT interchangeable.

## Phase 4 — Implement (single-stream OR parallel cross-worktree)

**Pre-dispatch baseline**: `uv run pytest tests/ -m 'not e2e_docker' -q` on main MUST exit 0. If red, abort and investigate — main is broken independent of this work.

### Single-stream (default)

Use `superpowers:executing-plans` skill. TDD via `superpowers:test-driven-development` where the contract isn't obvious. Implement in the current worktree.

### Parallel cross-worktree (when work is decomposable)

1. Invoke `wt-reference` skill (first wt touch in session).
2. **SEQUENTIAL** worktree creation (git index lock race otherwise):

```
wt switch --create dotfiles-<id>-<slug> --yes
```

Repeat for each bead. The wt config's `pre-start` hook will run `uv sync` per worktree.

3. **ONE PARALLEL MESSAGE** dispatching N Agents:
   - Each Agent uses `subagent_type: general-purpose` (or a domain-specific subagent if defined).
   - **DO NOT pass `isolation: worktree`** to the Agent tool (per empirical observation J: broken in this VM-headless build).
   - Each prompt MUST include:
     - `cd ~/projects/worktrees/<slug>` as first command.
     - `bd update dotfiles-<id> --claim` before any edit.
     - The anti-smell directive block (see "Anti-smell block" below) **VERBATIM**.
     - The bead's acceptance commands.
     - A word budget proportional to scope (100 / 200 / 300 word ceilings).

### Anti-smell block (VERBATIM in every Phase 4 agent prompt)

```
**Anti-smell discipline — non-negotiable, not preferences:**
- Drop unused parameters. NEVER take a param you'll discard via `del foo` or `# noqa: ARG001` or "reserved for future use" comments.
- Yield minimum-viable tuple shapes. NEVER include fields "for future callers" or "for symmetry".
- Hoist imports to module top. NO function-local imports for stdlib or same-package modules (except cycle-breaking, documented inline).
- Drop dead code paths. If a guard is unreachable from any caller, don't write it. Exception: `assert_never` exhaustiveness fall-through.
- Use the tightest type hints that hold. If a value is provably non-None after a fallback branch, return type should say so.
- No "for future" comments unless a bd issue ID is cited inline.
- Avoid loose typing. NO `Any` in production code. NO `# type: ignore[...]` without a tight specific code + a one-line preceding comment.
- Avoid shortcuts. If the spec calls for a refactor, do the actual refactor.
- F-strings only — no `.format()` or `%`-formatting (LOGGER `%`-style is the one exception).
- Function bodies under ~40 lines, nesting depth ≤3.

If you find yourself wanting to add a comment that says "reserved for", "TODO", "placeholder", or "for future" — STOP. Either implement the real thing, or remove the leftover scaffolding and file a bd issue.
```

## Phase 5 — Review fan (ALWAYS PARALLEL)

After all Phase 4 agents return, dispatch the matrix review fan in ONE message:

- For each Python bead: invoke `reviewing-python-code` skill → 4 aspect reviewers (spec / form / substance / specifics; prose skipped pending dotfiles-ya2).
- For each tracked/claude bead: invoke `reviewing-claude-md` skill → 4 aspect reviewers.
- For each generic markdown bead (READMEs, project CLAUDE.md, specs, docs/): invoke `reviewing-markdown` skill → 1 prose reviewer.

Total reviewer count: `4 × (python_beads + claude_md_beads) + 1 × markdown_beads`. ALL fire in a single parallel message.

**Per empirical observation D**: reviewers must verify cited evidence (e.g., "this rationale claims X already used Y — check Y").

## Phase 6 — Address findings + merge

Triage per reviewer verdicts:
- **CRITICAL** → fix immediately in the worktree before merge.
- **IMPORTANT** → fix as SEPARATE review-fix commit (never squash into impl commit; observation F).
- **MINOR + light-MEDIUM** → fix INLINE on the bead's worktree as a SEPARATE review-fix commit (per the **Decision-I default**, see "Inline-fix default" section above). Reserve `bd create` ONLY for LARGE: (a) new design question requiring its own brainstorm + spec, OR (b) cross-cutting across 3+ files outside the bead's scope, OR (c) implementer/reviewer is uncertain whether it's safe to fix inline.

### Merge sequence (DO NOT parallelize merges)

1. Identify file-overlap groups. Disjoint beads merge in any order (Wave 1).
2. For each overlap chain (e.g. deploy.py: a7u→kve→ka0), sequence by smallest-blast-radius first; subsequent beads rebase onto post-prior-merge main before their own `wt merge`.
3. Cross-cutting sweep beads (e.g. qzq's codebase-wide type:ignore audit) merge LAST — rebase onto final main, apply on top.

For each merge:
```
cd ~/projects/worktrees/<slug>
git rebase main
# smoke: uv run pytest <affected-files>
wt merge --no-squash --yes
```

`wt merge` already removes the worktree on success — `wt remove` afterward is redundant and will error.

## Phase 7 — Post-merge cross-cutting review (MANDATORY for multi-worktree)

On merged main in the project root:

```sh
pre-commit run --all-files                       # exit 0
uv run pytest tests/ -m 'not e2e_docker' -v       # exit 0
uv run pytest tests/docker/ -m e2e_docker -v      # exit 0
```

(The exact final-check commands come from the project's CLAUDE.md `## Final checks (post-merge)` section.)

Then re-dispatch the appropriate `reviewing-X` skills against merged HEAD to catch INTEGRATION-EMERGENT issues — e.g., bead A's commit added a function-local import in a NEW test that bead B's per-worktree review couldn't see because B wasn't merged with A yet at Phase 5 time.

**Per `feedback_phase7_rerun_after_inline_fix` memory**: ANY inline-fix on main following a Phase 7 finding MUST re-run BOTH gates (pre-commit + Docker e2e) before claiming complete.

Per project CLAUDE.md `### Failure handling`:

**Actual test failure on main** (e2e red, pre-commit red, mypy/ruff red):
- Inline-fix ONLY when both hold: one file, narrowly scoped (1–2 lines).
- Otherwise: `git revert <merge-commit>` → fix on feature branch → re-merge → re-run Phase 7.

**Routine Phase 7 review-fan findings** (all gates stayed green; reviewers surfaced quality nits):
- Default: fix INLINE on main as SEPARATE commits (one logical change per commit per the Commits rule).
- Escape hatch: file new bd for LARGE only (see "Inline-fix default" section above for the (a)/(b)/(c) criteria).

For inline-fixes (either path), the harness's worktree-isolation rule still applies when the change spans multiple files — use `wt switch --create <fix-slug>` + `EnterWorktree --path <new-worktree>`, edit there, `wt merge` back. Single-file edits to main can land directly. Either way, re-run BOTH Phase 7 gates after.

## Phase 8 — Close out

1. `bd close <id1> <id2> ...` for every completed bead (one call, multiple IDs).
2. `bd close <orchestration-id> --reason="..."` if a handoff/orchestration bead existed.
3. Save 1–3 cross-session memories via Write to `~/.claude/projects/{cwd-slug}/memory/<feedback|user|project|reference>_<topic>.md` ONLY for non-obvious, repeatable patterns (NOT for ephemeral session state). Update `MEMORY.md` index.
4. Per **Decision-I default**: MINOR + light-MEDIUM findings should already have been inline-fixed during Phase 6 (per-bead) or Phase 7 (post-merge). File new bd ONLY for LARGE out-of-scope discoveries — (a) new design question OR (b) cross-cutting 3+ files OR (c) implementer/reviewer uncertain.
5. Final summary to user: scope, outcomes, follow-up beads, memories saved.

## End-of-flow `result:` headline

Per the background-job conventions, when the workflow is genuinely
complete (all gates green, all beads closed, follow-ups filed), end your
final message with a single `result:` line on its own — self-contained,
readable by someone who never saw the ask.

## Hard rails (reminder)

- **Phase 3 is MANDATORY.** Skipping it is the cxj bug class at orchestration scale.
- **Plan-mode review of every spec is non-negotiable.** Batched form for related specs; sequential for independent ones.
- **Review fan fires per bead, not per session.** N beads = N × 4 (or N × 1 for markdown) reviewers in parallel.
- **Review-fix commits are SEPARATE commits.** Never squash. `wt merge --no-squash --yes`.
- **Phase 7 inline-fix → re-run BOTH gates.** Memory directive overrides any "it's fine" instinct.
- **Routine review-fan findings (MINOR + light-MEDIUM) → fix INLINE as separate commits.** Per the **Decision-I default**: reserve `bd create` for LARGE follow-ups only — (a) new design question, (b) cross-cutting 3+ files, (c) uncertainty. The qzq-pattern (2026-05-16) — explicit user scope expansion — is the strongest variant of this default. The OLD "MINOR → new bd, never inline-fix" rule is RESCINDED for routine findings; it survives only for Phase 7 ACTUAL TEST FAILURES (where revert-by-default applies, per project CLAUDE.md `### Failure handling`).

## Cross-refs

- `superpowers-prefs.md` (Phase flow + empirical observations A–L).
- `feedback_phase3_writing_plans_mandatory` (memory).
- `feedback_phase7_rerun_after_inline_fix` (memory).
- `feedback_newtype_for_contract_enforcement` (memory).
- `feedback_docker_e2e_coverage_preference` (memory).
- `feedback_reviewer_matrix_pattern` (memory).
- `bd-reference` skill (flag syntax, persistence layers, handoff patterns).
- `wt-reference` skill (worktree primitive + sibling-rebase pattern).
- bd `dotfiles-4tm` (the canonical 12-bead batch this command codifies).
- bd `dotfiles-0s8` (the Phase 3 enforcement bead — once landed, supersedes this command's Phase 3 hard-rail prose).
