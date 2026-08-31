---
name: setforge
description: Inspect, author, reconcile, deploy, verify, snapshot, and roll back SetForge profiles and project injections. Use when the user mentions SetForge, setforge.yaml, profile deployment, tracked-file drift, host-local changes, durable ownership, or SetForge-managed resources.
---

# SetForge

SetForge manages versioned profile sources, live resources, and private
reconciliation state. Establish which source, profile, and host are in scope
before interpreting drift or changing anything.

## Establish the target

Use the installed CLI as the command authority and explicit paths when known:

```bash
manifest=/absolute/path/to/setforge.yaml
profile=codex
setforge --version
setforge migrate --check --config="$manifest"
setforge validate --profile="$profile" --config="$manifest"
setforge profile show "$profile" --config="$manifest"
```

Use `setforge config show --tracked`, `--local`, or `--effective` to distinguish
tracked configuration, host intent, and the resolved profile. `status` is
informational and normally exits successfully even when it reports drift or
missing capabilities; read its contents.

Do not silently switch checkout, source, profile, or host. Before changing a
shared executable or live configuration, identify active consumers and explain
the continuity effect.

## Understand host-local reconciliation

For an ordinary tracked file, treat these as distinct evidence:

- the tracked source;
- the live destination;
- private base, local, absence, and index state below
  `~/.local/state/setforge/`.

`~/.config/setforge/local.yaml` stores host selection, intent, source, and path
overrides. It does not store host-local file bodies. Do not introduce legacy
host-local markers or overlay sections into tracked files or `local.yaml`.

Inspect a drifted file before resolving it:

```bash
setforge inspect <file-or-live-path> \
  --profile="$profile" \
  --config="$manifest"
```

Classify each live change interactively:

```bash
setforge stage <file-or-live-path> \
  --profile="$profile" \
  --config="$manifest"
setforge stage --list --profile="$profile" --config="$manifest"
```

`LOCAL` retains a hunk only on that host. `SHARED` makes it eligible for
promotion to the tracked source by capture or sync. Do not proceed while
relevant hunks remain `PENDING`. YAML/YML and JSON/JSONC may stage structured
units; TOML and other plain files use line hunks.

Avoid blanket `sync --auto=use-live` when a file may contain host-only changes.
Inspect and stage it first, then confirm that only intended `SHARED` content
will be promoted. Back up `~/.local/state/setforge/` when durable local
classifications must survive host recovery.

## Inspect and preview

```bash
setforge status --profile="$profile" --config="$manifest"
setforge compare --profile="$profile" --config="$manifest"
setforge ownership list
setforge install \
  --profile="$profile" \
  --config="$manifest" \
  --locked \
  --no-fetch \
  --dry-run
```

Inspect every planned write, package/plugin change, ownership action, and
reconciliation decision. Use `compare --check --strict` only when exact live
equality is required. Use `--no-fetch` only when the checked-out source is the
intended authority.

Do not use `--auto=use-tracked` unless replacing the corresponding live content
is approved. Do not use `--no-secrets-scan` merely for convenience; if the user
explicitly excludes the scanner, inspect the source for secrets and record why
the bypass is necessary.

## Snapshot and deploy

Before a broad or consequential deployment:

```bash
setforge snapshot create before-change \
  --profile="$profile" \
  --config="$manifest"
```

After reviewing the dry run, deploy with the same manifest, profile, lock, and
fetch choices but without `--dry-run`. Keep reconciliation interactive when a
live-versus-tracked choice is unsettled. Use `--auto=use-tracked --yes` only
when every replacement was explicitly decided in advance.

After deployment:

```bash
setforge validate --profile="$profile" --config="$manifest"
setforge compare --profile="$profile" --config="$manifest" --check --strict
setforge stage --list --profile="$profile" --config="$manifest"
setforge status --profile="$profile" --config="$manifest"
setforge transitions list --profile="$profile"
```

Verify pinned executables independently with `command -v`, `type -a`, version,
and digest where applicable. Run a second identical dry install when
idempotence matters; it should report no planned work.

### Codex 0.151 plugin mutation compatibility

SetForge 1.2.0 expects Codex plugin mutation JSON to contain
`"success": true`, while Codex CLI 0.151 returns an operation-specific success
object instead. A first marketplace or plugin reconciliation can therefore
report failure after the mutation actually succeeded. Do not immediately undo
the operation. Inspect both native states:

```bash
codex plugin marketplace list --json
codex plugin list --json
```

If the requested marketplace and plugin are installed and enabled, rerun the
same SetForge install; the converged second pass should be a no-op. Treat any
different state as a real failure. Recheck this note against the installed
versions and remove it once SetForge accepts Codex's current mutation payloads.

## Ownership and project profiles

Ownership claims are durable and exist independently of whether a manifest can
currently be loaded. Inspect them with `setforge ownership list` and use
`ownership history` for the current checkout. Release, revert, or recover an
ownership transition only after resolving the exact claim or transition and
confirming that the authority change is intended; releasing a claim does not
alter the resource itself.

For reusable files injected into a project:

```bash
setforge project list
setforge project inject <project-profile> /path/to/project --dry-run
setforge project sync /path/to/project --dry-run
setforge project remove <project-profile> /path/to/project --dry-run
```

Choose `--git-hidden` for host-private injected files and `--git-tracked` for
normal project content. Preview collision resolution and removal before apply;
removal restores the state recorded immediately before that injection.

## Recover, roll back, and migrate

Inspect an interrupted write-ahead operation before applying recovery:

```bash
setforge recover --profile="$profile"
setforge ownership recover --config="$manifest"
```

Use `transitions show`, `revert`, and `snapshot restore` only after confirming
the exact profile and affected resources. Snapshot restore is additive and does
not delete live-only files. Transition reverts and snapshots do not guarantee
restoration of provisioned package bytes; preserve a separate byte-for-byte
backup for consequential package replacement.

Run `migrate --check` before changing schema versions. Review backups and the
full chain before `migrate --apply`, downgrade, or `--finalize`; finalization
permanently strips retired host-local markers.

## Cleanup safety

Treat `cleanup` and `cleanup-orphans` as destructive review surfaces. Preview
and inspect every candidate. Never remove a protected, active, user-owned, or
merely unfamiliar resource, and prefer explicit retention when ownership is
uncertain.
