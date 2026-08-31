# Upstream provenance

This plugin vendors selected Codex components from
[`umputun/revdiff`](https://github.com/umputun/revdiff) under the upstream MIT
license retained in [`LICENSE`](LICENSE).

- Upstream revision: `e3eb7328a49753d1c9c78c9c50a67339f9bb23f7`
- RevDiff release: `v1.12.0`
- Manual Codex plugin: `0.8.23`
- Planning plugin: `0.3.9`
- Local plugin: `0.1.0`
- Synchronized: `2026-08-31`

The `*.upstream.sh`, hook, helper, reference, and skill files originate from
that revision. The two `launch-*.sh` dispatchers are local: inside Herdr they
remove competing multiplexer selectors and then execute the preserved upstream
launcher. The skill path-resolution paragraphs are adapted for Codex's
versioned plugin cache.

Refresh with:

```bash
./scripts/sync-revdiff-upstream.sh <upstream-ref> <new-local-semver>
```

The command requires an explicit upstream revision and local version, imports
only the allowlisted files, reapplies the cache-path adaptations, and leaves the
Herdr dispatchers intact. Review the resulting diff and run the full test suite
before publishing the new marketplace version.
