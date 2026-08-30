---
name: setforge
description: Inspect, author, deploy, verify, snapshot, and roll back SetForge profiles. Use when the user mentions SetForge, setforge.yaml, profile deployment, tracked-file drift, or SetForge-managed packages and plugins.
---

# SetForge

SetForge deploys a versioned profile from `setforge.yaml` into the user's live
environment. Treat the profile source, live files, and SetForge transition state
as three distinct sources of evidence.

## Establish the target

Use an explicit manifest and profile whenever they are known:

```bash
manifest=/absolute/path/to/setforge.yaml
profile=codex
```

Do not silently use a different checkout, profile, or discovered configuration.
Before changing a shared executable or live configuration, identify active
consumers and explain the continuity effect.

## Inspect without changing state

Validate the manifest:

```bash
setforge validate --profile="$profile" --config="$manifest"
```

Inspect the resolved profile and current drift:

```bash
setforge status --profile="$profile" --config="$manifest"
setforge compare --profile="$profile" --config="$manifest"
```

Use a strict drift gate when exact equality is required:

```bash
setforge compare \
  --profile="$profile" \
  --config="$manifest" \
  --check \
  --strict
```

`status` is informational and normally exits successfully even when it reports
missing capabilities or drift. Read its contents rather than treating exit zero
as proof that the profile is ready.

## Preview deployment

Run a dry installation before changing the live environment:

```bash
setforge install \
  --profile="$profile" \
  --config="$manifest" \
  --locked \
  --no-fetch \
  --dry-run
```

Inspect every planned write, package change, plugin change, and reconciliation
decision. Preserve unrelated live files and user-owned sections.

Do not use `--auto=use-tracked` unless replacing the corresponding live content
is already approved. Do not use `--no-secrets-scan` merely for convenience.

## Create a rollback point

Before a broad or consequential deployment:

```bash
setforge snapshot create before-change \
  --profile="$profile" \
  --config="$manifest"
```

List available snapshots with:

```bash
setforge snapshot list
```

A snapshot restore is additive: it overlays captured files but does not remove
live-only files created afterward.

## Apply an approved deployment

After the dry run is understood and the user has authorized the live change:

```bash
setforge install \
  --profile="$profile" \
  --config="$manifest" \
  --locked \
  --no-fetch
```

Keep interactive reconciliation enabled when a live-versus-tracked choice is
unsettled. Use `--auto=use-tracked --yes` only when all such replacements were
explicitly decided in advance.

## Verify the result

After installation:

```bash
setforge validate --profile="$profile" --config="$manifest"
setforge compare --profile="$profile" --config="$manifest" --check --strict
setforge status --profile="$profile" --config="$manifest"
setforge transitions list --profile="$profile"
```

Verify important executables independently with `command -v`, `type -a`, their
version, and their digest when the profile pins them. A correctly installed
binary can still be shadowed by an older executable earlier on `PATH`.

Run a second identical dry installation when idempotence matters. It should
report no planned work. Dry runs never create transitions, so transition
absence is state-safety evidence rather than proof of idempotence.

## Recover or roll back

Inspect a recorded transition:

```bash
setforge transitions show <transition-id-or-unique-prefix>
```

Revert the latest profile transition interactively:

```bash
setforge revert --profile="$profile" --config="$manifest"
```

Restore a named snapshot interactively:

```bash
setforge snapshot restore <snapshot-id-or-label> \
  --profile="$profile" \
  --config="$manifest"
```

If SetForge reports an interrupted write-ahead operation, inspect it first:

```bash
setforge recover --profile="$profile"
```

Do not apply recovery, revert, or restore without confirming the exact affected
profile and obtaining authority for the live mutation.

SetForge snapshots and transition reverts do not guarantee restoration of
provisioned package bytes or removal of live-only files. Before a consequential
package replacement or exact deletion, preserve a separate byte-for-byte backup
and an explicit restoration procedure for those resources.

## Cleanup safety

Treat `cleanup` and `cleanup-orphans` as destructive review surfaces, not routine
maintenance. Preview and inspect every candidate. Never remove a protected,
active, user-owned, or merely unfamiliar item. Prefer an explicit retained item
over broad cleanup when ownership is uncertain.
