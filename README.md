# SetForge Codex profile

This repository defines Raul's main Codex profile.

The profile intentionally starts small:

- a compact global `AGENTS.md` that favors proportional, evidence-backed
  project work, selective delegation, and disposable feasibility spikes over
  speculative architecture;
- practical SetForge, Herdr, and private Beads usage skills;
- pinned `bd`, `revdiff`, and `wt` executables;
- a tracked `revdiff-herdr` Codex plugin that opens automatic Plan reviews and
  manual RevDiff sessions in a dedicated tab in the caller's Herdr workspace,
  formats plans for the live pane width, compares each revision with the
  preceding one, maps annotations back to canonical Markdown, and then returns
  focus to the originating tab.

Repository-specific instructions and Beads configuration remain in their owning
repositories. The profile's Beads skill requires user approval before database
initialization or issue creation, always initializes in stealth mode, favors
reviewer-friendly shallow decomposition, and keeps tracking details out of the
project artifacts and Git metadata it manages. OpenAI system skills and
plugin-provided skills remain externally owned except for the explicitly
vendored `revdiff-herdr` bundle.

The RevDiff Plan hook runs only for a complete `<proposed_plan>` response while
Codex is in Plan Mode. The profile contains no workflow controller, audit
scheduler, recovery timer, build coordinator, automatic cleanup, or unrelated
background plugin activation. New components should be added only after their
behavior and value are reviewed.

The global project principles are checked before deployment with a small,
single-sample behavioral smoke evaluation. It installs the candidate profile
into an isolated XDG home, runs representative Codex tasks, and combines
deterministic checks with a separate agent review. The evaluation code and
fixtures are not part of the installed profile. Offline and fixture tests use
pytest:

```sh
python3 -m pytest -q
python3 evals/project_principles.py
```

The second command makes Codex model calls and reports the retained artifact
path only when passed `--keep-artifacts`.

Plugin tests live only in the repository's top-level `tests/` directory. They
are not a SetForge tracked resource and are not part of the installed plugin
payload.

On a new host, SetForge 1.2.0 can falsely report the first Codex 0.151
marketplace/plugin mutation as unsuccessful after Codex has installed it. Check
`codex plugin marketplace list --json` and `codex plugin list --json`; when the
requested state is present, rerun the same SetForge install and it should be a
no-op. The tracked SetForge skill records the exact compatibility check.
