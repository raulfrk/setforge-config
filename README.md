# SetForge Codex and Claude Code configuration

This repository defines Raul's `codex` profile and its Claude Code counterpart,
the `claude` profile.

Codex and Claude Code are the supported coding agents. Herdr, RevDiff, Beads,
and the pinned command-line tools are shared integrations. Other coding-agent
profiles, skills, hooks, and compatibility fallbacks are outside this
repository's scope. References to other plugin formats in vendored provenance
and upstream import metadata describe where shared components came from; they
are not deployed agent integrations.

## Claude Code

The `claude` profile carries the same workflow as the Codex profile below,
expressed with Claude Code's native features:

| Codex | Claude Code |
| --- | --- |
| `tracked/codex/AGENTS.md` | `tracked/claude/CLAUDE.md` |
| `agents/review-*.toml` roles | `agents/review-*.md` subagents without file-editing tools |
| `config.toml` fragment | `settings.json` fragment: model, effort, permission mode, updates, status line |
| TUI `status_line` items | `statusline.sh` |
| Skills | The same skills under `tracked/claude/skills/`, with native tool names |
| `codex-tui` and `main-session` skills | Not ported yet: cross-session coordination is left out of the `claude` profile for now |
| `revdiff-herdr` Codex plugin, Stop hook | `revdiff-herdr` Claude plugin, ExitPlanMode hook |
| Herdr Plan Mode handoff | Not needed: Claude Code enters and leaves Plan Mode itself |

`tracked/claude/settings.json` holds only the profile's own keys. SetForge
merges it by key; the Herdr and Moshi `hooks` block and the plugin
registrations in the live file stay host-local. On a host whose
`~/.claude/settings.json` already exists, the first install keeps that file and
only records the fragment as the merge base: add the fragment's keys to the
live file once, then classify the remaining live-only keys as local with
`setforge stage claude_settings --profile=claude`.

The Claude plugin is `plugins/revdiff-herdr-claude/`, published through
`.claude-plugin/marketplace.json`. Its launchers are symlinks to the Codex
plugin's scripts, so both agents share one RevDiff and Herdr implementation;
only the hook, manifest, and skill text differ. Claude Code copies the linked
contents into its plugin cache on install.

Until the Claude plugin is pushed to GitHub, it is installed from this checkout
(`claude plugin marketplace add <checkout>`), and the `revdiff_herdr_claude`
package stays out of the `claude` profile: SetForge 1.3.9 cannot journal a
directory marketplace. After publishing, remove the local marketplace, add the
package to the profile, and run `setforge lock` and `setforge install`.

Two Codex settings have no Claude Code counterpart and are not reproduced: a
separate reasoning effort for Plan Mode, and the thread ID as terminal title.

## Codex

The profile intentionally starts small:

- a compact global `AGENTS.md` that favors proportional, evidence-backed
  project work, selective delegation, and disposable feasibility spikes over
  speculative architecture;
- practical SetForge, Herdr, and private Beads usage skills;
- a `development-platform-use` skill for everyday devbox project work and
  Concourse-backed builds through the existing `infra job` interface;
- pinned `bd`, `revdiff`, and `wt` executables;
- a tracked `revdiff-herdr` Codex plugin that opens automatic Plan reviews and
  manual RevDiff sessions in a dedicated tab in the caller's Herdr workspace,
  formats plans for the live pane width, compares each revision with the
  preceding one, maps annotations back to canonical Markdown, and then returns
  focus to the originating tab.

Codex preferences in `tracked/codex/config.toml` are a native config fragment:
SetForge manages only those keys. Codex keeps project trust, hook-trust hashes,
and onboarding records in its live configuration; they are not shared settings
or SetForge drift. Use native key reconciliation rather than whole-file capture.

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

When updating the local plugin, preserve paths used by running conversations.
Before `codex plugin add`, record the installed cache version and any older
version aliases. The CLI can remove that version while a running thread still
holds its hook command. After installation, verify the new payload against the
reviewed source, then restore each missing old version path as a symlink to the
compatible new version before ending the turn. Verify the complete alias chains
and invoke the old hook paths with a benign Stop event. A new plugin version
alone does not refresh commands already loaded by a running conversation.
