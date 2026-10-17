# SetForge Claude Code configuration

This repository defines Raul's Claude Code configuration as the `claude`
profile, with `claude-policy` as a subset of the same files.

Claude Code is the supported coding agent. Herdr, RevDiff, Beads, and the
pinned command-line tools are shared integrations. Other coding-agent
profiles, skills, hooks, and compatibility fallbacks are outside this
repository's scope. References to other plugin formats in vendored provenance
and upstream import metadata describe where shared components came from; they
are not deployed agent integrations.

## Claude Code

The `claude` profile deploys:

- the global `tracked/claude/CLAUDE.md` and the `ponytail-adhd` output style;
- `agents/review-*.md` subagents without file-editing tools;
- a `settings.json` fragment: model, effort, permission mode, updates, status
  line, with `statusline.sh`;
- skills under `tracked/claude/skills/`, including SetForge, Herdr, private
  Beads, and `development-platform-use` for devbox and Concourse-backed builds;
- pinned `bd`, `revdiff`, and `wt` executables and the Herdr config;
- the `revdiff-herdr` Claude plugin, whose ExitPlanMode hook opens Plan
  reviews in a dedicated Herdr tab.

`tracked/claude/settings.json` holds only the profile's own keys. SetForge
merges it by key; the Herdr and Moshi `hooks` block and the plugin
registrations in the live file stay host-local. On a host whose
`~/.claude/settings.json` already exists, the first install keeps that file and
only records the fragment as the merge base: add the fragment's keys to the
live file once, then classify the remaining live-only keys as local with
`setforge stage claude_settings --profile=claude`.

The Claude plugin is `plugins/revdiff-herdr-claude/`, published through
`.claude-plugin/marketplace.json`. Its launchers are symlinks to the scripts
in `plugins/revdiff-herdr/`, the vendored RevDiff and Herdr implementation;
only the hook, manifest, and skill text differ. Claude Code copies the linked
contents into its plugin cache on install.

Repository-specific instructions and Beads configuration remain in their owning
repositories. The Beads skill requires user approval before database
initialization or issue creation, always initializes in stealth mode, favors
reviewer-friendly shallow decomposition, and keeps tracking details out of the
project artifacts and Git metadata it manages.

Offline tests use pytest:

```sh
python3 -m pytest -q
```

Plugin tests live only in the repository's top-level `tests/` directory. They
are not a SetForge tracked resource and are not part of the installed plugin
payload.
