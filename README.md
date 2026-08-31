# SetForge Codex profile

This repository defines Raul's main Codex profile.

The profile intentionally starts small:

- an empty global `AGENTS.md`;
- practical SetForge and Herdr usage skills;
- pinned `bd`, `revdiff`, and `wt` executables;
- a tracked `revdiff-herdr` Codex plugin that opens automatic Plan reviews and
  manual RevDiff sessions in a dedicated tab in the caller's Herdr workspace.

Repository-specific instructions and Beads configuration remain in their owning
repositories. OpenAI system skills and plugin-provided skills remain externally
owned except for the explicitly vendored `revdiff-herdr` bundle.

The RevDiff Plan hook runs only for a complete `<proposed_plan>` response while
Codex is in Plan Mode. The profile contains no workflow controller, audit
scheduler, recovery timer, build coordinator, automatic cleanup, or unrelated
background plugin activation. New components should be added only after their
behavior and value are reviewed.
