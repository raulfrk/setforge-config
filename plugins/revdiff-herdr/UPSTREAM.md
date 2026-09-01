# Upstream provenance

This plugin vendors selected Codex components from
[`umputun/revdiff`](https://github.com/umputun/revdiff) under the upstream MIT
license retained in [`LICENSE`](LICENSE).

- Upstream revision: `e3eb7328a49753d1c9c78c9c50a67339f9bb23f7`
- RevDiff release: `v1.12.0`
- Manual Codex plugin: `0.8.23`
- Planning plugin: `0.3.9`
- Local plugin: `0.1.3`
- Synchronized: `2026-08-31`

The `*.upstream.sh`, hook, extractor, reference, and manual-review skill files
originate from that revision. The `launch-*.sh` dispatchers, responsive
Markdown internals, formatter/runtime helpers, and plan-review skill are local.
`skills/revdiff/scripts/launch-revdiff.sh` is the single public entry point;
the plan-specific launch scripts are internal. Inside
Herdr they remove competing multiplexer selectors, open a dedicated tab, format
the plan for the live pane width, map annotations back to canonical Markdown,
and restore the caller's tab without changing the review result. The planning
hook detects complete `<proposed_plan>` blocks instead of assuming that Codex's
approval-oriented `permission_mode` identifies Plan mode.

Refresh with:

```bash
./scripts/sync-revdiff-upstream.sh <upstream-ref> <new-local-semver>
```

The command requires an explicit upstream revision and local version, imports
only the allowlisted upstream files, reapplies the Codex cache-path and
plan-trigger adaptations, and leaves the local responsive formatter, plan
skill, and Herdr launchers intact. Review the resulting diff and run the full
test suite before publishing the new marketplace version.
