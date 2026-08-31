# SetForge Codex profile

This repository defines Raul's main Codex profile.

The profile intentionally starts small:

- an empty global `AGENTS.md`;
- practical SetForge and Herdr usage skills;
- pinned `bd`, `revdiff`, and `wt` executables;
- a tracked `revdiff-herdr` Codex plugin that opens automatic Plan reviews and
  manual RevDiff sessions in a dedicated tab in the caller's Herdr workspace,
  then returns focus to the originating tab.

Repository-specific instructions and Beads configuration remain in their owning
repositories. OpenAI system skills and plugin-provided skills remain externally
owned except for the explicitly vendored `revdiff-herdr` bundle.

The RevDiff Plan hook runs only for a complete `<proposed_plan>` response while
Codex is in Plan Mode. The profile contains no workflow controller, audit
scheduler, recovery timer, build coordinator, automatic cleanup, or unrelated
background plugin activation. New components should be added only after their
behavior and value are reviewed.

Plugin tests live only in the repository's top-level `tests/` directory. They
are not a SetForge tracked resource and are not part of the installed plugin
payload.

On a new host, SetForge 1.2.0 can falsely report the first Codex 0.151
marketplace/plugin mutation as unsuccessful after Codex has installed it. Check
`codex plugin marketplace list --json` and `codex plugin list --json`; when the
requested state is present, rerun the same SetForge install and it should be a
no-op. The tracked SetForge skill records the exact compatibility check.
