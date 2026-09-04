# Project engineering principles

Inspect the project before designing. Distinguish current requirements from
imagined future needs, and define how the requested behavior will be
demonstrated through a test, command, fixture, or observable result before
writing production code.

Before fully implementing functionality whose success depends on a material
technical uncertainty, use the smallest cheap runnable experiment that could
disprove the approach. Before running it, state in a progress update the
question, expected result, and success threshold. Do not create or modify
production code until the experiment meets that threshold. If it fails or is
inconclusive, stop and report the blocker, or revise the approach and prove the
revised critical path before implementation. Keep spike code disposable and
separate from production; never silently promote it into the final design. Do
not spike routine work whose behavior is already established by the repository
and tests.

Implement the smallest coherent solution satisfying the request. Extend
established project patterns and capabilities before introducing competing
architecture or tooling.

Do not add frameworks, generalized subsystems, registries, factories, plugin
mechanisms, configuration layers, or extension points unless a current
requirement or established repository convention demonstrates a concrete need
and the addition reduces net complexity.

Prefer evolutionary design: write direct code for known cases and abstract only
after a stable repeated concept exists. Superficial duplication or hypothetical
reuse is insufficient evidence.

Add dependencies, services, generators, or build layers only when existing
capabilities cannot reasonably solve the current problem and their ongoing cost
is justified.

Keep adjacent cleanup out of scope unless required for the requested change;
report worthwhile broader improvements separately.

Use one primary agent to own each coherent change. Delegate only bounded,
independent workstreams or independent review; keep sequential work and shared
mutable state with the primary owner. Choose concurrency from the actual
decomposition, never from the number of available agent slots.

When producing an implementation plan, including in Plan Mode, include
representative snippets whenever they materially clarify the intended
result—for example exact policy text, interface signatures, schemas, critical
control flow, or test cases. Use snippets to resolve ambiguity, not to
pre-implement the entire change or invent details unsupported by the project.

Verify observable behavior and inspect the final diff for unused scaffolding,
speculative options, unnecessary indirection, and unrelated changes. Preserve
complexity demonstrably required for correctness, security, reliability,
performance, or compatibility.

Use pytest for new and modified Python tests. Do not add `unittest` imports,
`unittest.TestCase` suites, or `self.assert*` calls. When modifying an existing
unittest-based module, convert the affected tests to pytest; broaden the
conversion only when needed to keep that module coherent.

Before planning or implementing material tracked work in a Git checkout,
resolve its canonical Git root, resolve the primary worktree from the first
`worktree` entry returned by `git worktree list --porcelain`, and run
`bd where --json` from the current checkout root. Before accepting a discovered
project, require `BEADS_DIR` to be unset. The primary `.beads` directory itself
must not be a symlink or contain `redirect` when that path exists; its absence
is allowed so `bd where` can report no project. In a linked worktree, reject a
worktree-local `.beads` path before canonicalization. Then load the `beads`
skill only when the returned canonical `path` equals the primary worktree's
canonical `<git-root>/.beads`. Stop on any mismatch. If it reports no Beads
project, continue normally without initializing or proposing Beads.

Before presenting a decision-complete implementation plan, run the
`review-gate` skill in plan mode. After completing file-changing work and its
deterministic checks, run the skill in implementation mode before handoff,
commit, or push. If changes result from a completed RevDiff review, run the
corresponding gate again before presenting or offering another review.
