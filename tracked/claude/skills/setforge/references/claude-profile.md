# Raul's Claude Code profile

The known source for Raul's personal Claude Code configuration is the `claude`
profile in `/home/raul/projects/setforge-config/setforge.yaml`. Its tracked
files live under `/home/raul/projects/setforge-config/tracked/claude/`. Use
this location first when asked to change Claude Code settings, global
`CLAUDE.md`, skills, agents, the status line, or plugins; verify the current
manifest and mapping before editing in case the ownership has changed. The
`codex` profile in the same manifest is a separate agent's configuration; do
not change it as a side effect. The `claude` profile also deploys
`tracked/herdr/config.toml`, which the `codex` profile shares, and
`claude-policy` is a subset of the same files; deploy only the intended profile.

`tracked/claude/settings.json` is a fragment of intended preferences, not the
whole live file. SetForge reconciles JSON at key granularity: it manages only
the keys in the fragment and leaves other live keys host-local. The `hooks`
block is installed by Herdr and Moshi, plugin and marketplace registrations are
written by the `claude` CLI, and permission-prompt acknowledgements are written
by Claude Code itself; none of these are shared settings or SetForge drift. Do
not copy the complete live file into the fragment or classify those keys as
`SHARED`. Instructions, agents, skills, and the status-line script use ordinary
tracked-file reconciliation.

`setforge stage claude_settings` offers one whole-document unit for this JSON
file: choose Keep local once, and re-run it when `stage --list` shows a pending
unit again. A fragment edit next to host-only keys can still end in `merge
conflict kept live, base not advanced`, which applies nothing even though the
dry-run says `noop`. Resolve it with `install --file=claude_settings
--reconcile-user-sections` and the Edit choice, back up the live file first, and
return only the conflicting region from the editor (SetForge keeps the lines
around it; a whole document breaks the JSON). Then confirm `jq empty` passes and
the `hooks` block is unchanged. Never use `--auto=use-tracked` on this file: on
a conflict it replaces the whole live file with the fragment.

Inspect the source checkout for existing changes, then compare the relevant
tracked file with its live destination and SetForge's reconciliation state.
Preserve unrelated edits and host-local intent. Make the requested change in
the tracked source and update the manifest only when resource declarations or
profile selections need to change. Preview the `claude` profile deployment and
check all proposed actions before applying it through SetForge. If unrelated
drift blocks deployment, leave it unresolved and report the source change and
deployment blocker.

Verify the resulting live file and profile after deployment. Do not directly
overwrite a SetForge-managed live file to bypass reconciliation.

## Scope and verify deployment

Use repeated `setforge install --file=<declared-id>` selectors for an approved
subset of ordinary tracked files. Preview those exact selectors and verify no
unrelated package, plugin, or ownership action is planned. Plugin operations
need their own verified scope; file selectors do not select them. Preserve
host-local model or effort choices during unrelated changes instead of broad
profile replacement.

Settings, `CLAUDE.md`, agents, and plugin hooks are read when a session starts.
A running session keeps what it loaded; verify a change in a new session, or
after `/reload-plugins` for plugin content. Do not restart or close another
live session merely to refresh its configuration.

The `revdiff-herdr` plugin is published from this repository's
`.claude-plugin/marketplace.json` and `plugins/revdiff-herdr-claude/`. Its
launcher scripts are symlinks to the Codex plugin's files in
`plugins/revdiff-herdr/`; Claude Code copies their contents into its versioned
cache on install. A change to a shared launcher therefore affects both agents:
run the whole test suite, and bump the Claude plugin version so the cache is
refreshed. An enabled plugin ID or a SetForge comparison alone does not
establish installed version/byte equality; compare the cached payload under
`~/.claude/plugins/cache/` with the reviewed source, excluding generated
bytecode. Follow the plugin's `skills/revdiff/references/install.md` when the
local checkout is ahead of the published marketplace.
