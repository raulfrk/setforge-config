# SetForge agent profiles

This repository defines Raul's Codex, OpenCode, and Oh My Pi profiles.

## Oh My Pi

The `omp` profile targets OMP 18.1.18 and ports the same engineering policy,
private Beads workflow, risk-based review gate, Herdr controls, and RevDiff
workflow onto OMP's native agents, `task`/`hub`, Plan artifacts, and extension
lifecycle. Current limits shape the profile:

- OMP extensions cannot read or toggle native Plan directly. Conditional entry
  therefore requires a proven Herdr-owned interactive OMP pane; elsewhere the
  agent asks the user to type `/plan`.
- `plan.defaultOnStartup` can start every interactive session in Plan, but this
  profile keeps it `false` so routine work starts in Build. Print, RPC, and
  non-Herdr sessions do not receive conditional automatic entry.
- Automatic RevDiff gating applies to a root interactive native Plan proposal.
  Headless proposal review fails closed; ordinary prose uses `revdiff_plan` or
  `/revdiff-plan` manually.
- Plan and reviewer tool restrictions are policy and tool-list controls, not an
  operating-system read-only sandbox.
- OMP `task`/`hub` context, effort, wake, wait, and mail behavior is analogous
  to the Codex workflow but is not wire-compatible with Codex collaboration
  calls. Provider and tool effects cannot be exactly once across a process
  crash.
- Completed isolated workers retain patches because `apply: false`, but they
  cannot remain persistent correction owners. Persistent shared workers remain
  the owners for later corrections.
- OMP requires the terminal `yield` tool in every task child and suppresses
  `todo` in that session shape. The custom worker therefore uses `hub` for
  persistent coordination but has no child-local `todo` tool.
- Provider allowance and OAuth-visible models remain unverified until the user
  runs `/login openai-codex`. OMP can report local activity, but cannot
  reconstruct Codex rollout-tree credit estimates or topology.

The profile owns exactly its 36 listed resources below `~/.omp/agent/`, the
`~/.local/bin/omp` pin, and the shared `bd`, `revdiff`, `wt`, and `rtk` package
pins. It does not own `agent.db*`, models, settings, keybindings, `config.yaml`,
sessions, artifacts, memory, plugins, unlisted extensions, logs, native caches,
OpenCode paths, Codex paths, or Herdr's generated
`extensions/herdr-omp-agent-state.ts` integration. Because OMP gives
`config.yml` precedence over `config.yaml`, reconcile or remove an existing
live `~/.omp/agent/config.yaml` before installing this managed `config.yml`.

Review the exact locked install, install the profile, then install Herdr's OMP
integration with `PI_CODING_AGENT_DIR` unset:

```sh
manifest=/home/raul/projects/setforge-config/setforge.yaml
setforge install --profile=omp --config="$manifest" --locked --no-fetch --dry-run
setforge install --profile=omp --config="$manifest" --locked --no-fetch --yes
env -u PI_CODING_AGENT_DIR herdr integration install omp
setforge compare --profile=omp --config="$manifest" --check --strict
```

The install does not authenticate a provider. Later, inside OMP, run:

```text
/login openai-codex
```

Before replacing an existing OMP installation, list all snapshots and create a
uniquely labelled one with `--keep` set to the existing count plus one. Keep a
separate mode-restricted rollback bundle for package binaries, prior absence,
and the unowned Herdr integration because SetForge snapshots are additive:

```sh
setforge snapshot list
setforge snapshot create before-omp-profile-<UTC> --profile=omp --keep=<existing-count-plus-one>
```

For rollback, inspect and recover any active write-ahead operation, classify
each current path against its preflight and installed bytes, then restore the
recorded snapshot ID only where that cannot overwrite independent changes:

```sh
setforge recover --profile=omp
setforge snapshot restore <snapshot-id> --profile=omp
setforge compare --profile=omp
```

Restore package and Herdr integration bytes from the bound rollback bundle and
remove a newly created destination only while it still matches the failed
install candidate.

## Codex

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

## OpenCode

The OpenCode profile ports the same project principles and local workflow to
OpenCode 1.18.21. It installs pinned Build, Plan, worker, and reviewer agents;
the reusable SetForge, Herdr, Beads, review-gate, usage-check, and RevDiff
skills; and two local plugins. The coordinator plugin supplies persistent child
agent tools with pinned roles and bounded worktrees. The Plan workflow plugin
switches between the native Build and Plan agents and holds each completed Plan
response for an interactive RevDiff review before returning it to the user.

The profile owns only its 37 listed files below `~/.config/opencode/` and the
shared `bd`, `revdiff`, `wt`, and `rtk` package pins. It does not manage
`opencode.json`, `opencode.jsonc`, `tui.jsonc`, `package.json`, `node_modules`,
provider credentials, or any Codex path. Existing unlisted OpenCode files are
preserved. The Herdr-assisted review commands require a responsive Herdr
workspace. OpenCode exposes local token and cost statistics, but version 1.18.21
does not expose provider account allowance through a public command.

Install from a clean checkout after reviewing the dry run:

```sh
setforge install --profile=opencode --dry-run
setforge install --profile=opencode --yes
setforge compare --profile=opencode --check --strict
```

For a later update that has tracked-versus-live section drift, use `setforge
install --profile=opencode --auto=use-tracked --yes`.

The install does not authenticate OpenCode. When credentials are needed, run
the OpenCode-owned flow separately:

```sh
opencode auth login
```

Before changing an existing installation, create a snapshot with a unique UTC
label such as `before-opencode-profile-20260911T220000Z`. Choose `--keep` high
enough to retain all existing snapshots plus the new one, because the default
keeps only ten:

```sh
setforge snapshot list
setforge snapshot create before-opencode-profile-<UTC> --profile=opencode --keep=<count>
```

To roll back, first inspect any active write-ahead operation and recover it when
needed, then restore the recorded snapshot ID interactively:

```sh
setforge recover --profile=opencode
setforge recover --profile=opencode --apply --yes
setforge snapshot restore <snapshot-id> --profile=opencode
setforge compare --profile=opencode
```

Snapshot restore is additive: files created after the snapshot remain in place.
If the failed install created a managed destination that was absent beforehand,
remove it only after confirming that it still matches the failed install's
candidate bytes. Restore separately backed-up package binaries when package
installation changed them.
