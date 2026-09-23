# SetForge agent profiles

This repository defines Raul's Codex profile.

## Codex

The profile intentionally starts small:

- a compact global `AGENTS.md` that favors proportional, evidence-backed
  project work, selective delegation, and disposable feasibility spikes over
  speculative architecture;
- practical SetForge, Herdr, and private Beads usage skills;
- pinned `bd`, `revdiff`, `rtk`, and `wt` executables;
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

Offline tests use pytest:

```sh
python3 -m pytest -q
```

Plugin tests live only in the repository's top-level `tests/` directory. They
are not a SetForge tracked resource and are not part of the installed plugin
payload.
