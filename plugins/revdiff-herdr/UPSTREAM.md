# Upstream provenance

These shared scripts and references back the `revdiff-herdr` Claude plugin in
`plugins/revdiff-herdr-claude/`, whose launchers are symlinks into this
directory. Some files are vendored from upstream's Codex plugin in
[`umputun/revdiff`](https://github.com/umputun/revdiff) under the upstream MIT
license retained in [`LICENSE`](LICENSE).

- Upstream revision: `e3eb7328a49753d1c9c78c9c50a67339f9bb23f7`
- RevDiff release: `v1.12.0`
- Upstream manual plugin: `0.8.23`
- Planning plugin: `0.3.9`
- Local plugin: `0.1.3` (the retired Codex plugin's version)
- Synchronized: `2026-08-31`

The `*.upstream.sh`, the `config.md` and `usage.md` references, and the
manual-review scripts originate from that revision. The launcher resolver,
`launch-*.sh` dispatchers, responsive plan launcher, and formatter/runtime
helpers are locally maintained. Inside Herdr they remove competing multiplexer
selectors, open a dedicated tab, format the plan for the live pane width, map
annotations back to canonical Markdown, and restore the caller's tab without
changing the review result.

Refresh with:

```bash
./scripts/sync-revdiff-upstream.sh <upstream-ref> <new-local-semver>
```

The command requires an explicit upstream revision and local version, imports
only the allowlisted upstream files, and leaves the locally maintained resolver,
responsive formatter, and Herdr launchers intact.
Review the resulting diff and run the full test suite before publishing the new
marketplace version.
