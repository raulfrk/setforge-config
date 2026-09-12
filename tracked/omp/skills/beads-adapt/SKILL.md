---
name: beads-adapt
description: Adapt an existing Git repository to the canonical private Beads configuration while preserving issues, metadata, Git bytes, and recovery state. Use for legacy, drifted, tracked, remotely configured, or hook-enabled Beads repositories; use beads-bootstrap when no database exists.
---

# Adapt an existing Beads repository

Read the base `beads` skill and
[the canonical project configuration](../beads/references/project-config.md).
Run adaptation only from the primary Git checkout. If invoked from a linked
worktree, stop and move the procedure to the primary checkout before inspection
or mutation. Operate only on the database whose canonical path is the primary
checkout's `<git-root>/.beads`. Require `BEADS_DIR` to be unset and require that
directory to be a real directory rather than a symlink, with no `redirect`
file. Never reinitialize it or turn this procedure into a migration framework.

## Inspect and preview

Inspect `metadata.json`, `bd config show`, installed Beads hooks, Dolt remotes,
`sync.remote`, Git ignore provenance, tracked `.beads` paths, staged changes,
and the exhaustive issue graph from the base skill. Show the exact detected
state and proposed delta, then obtain explicit approval before mutation.

If the database already has embedded/in-process mode, the canonical seven
values and provenance, no `sync.remote`, no hooks or remotes, no tracked
`.beads` paths, and `.git/info/exclude` as its ignore source, return without
creating a backup or changing anything.

For a conversion, require embedded/in-process mode. Stop on staged divergence
affecting tracked `.beads` paths or the proposed removal of exact Beads-only
`.gitignore` lines. Inventory those lines and preserve every unrelated byte.

## Prove there are no holders

Require installed `lsfd` and `jq`. Use literal canonical paths, not a regular
expression, and fail closed:

```sh
set -o pipefail
beads_dir=$(realpath -- "$git_root/.beads") || exit 1
holders=$(
  lsfd -J -o PID,NAME |
    jq -ce --arg root "$beads_dir" \
      '[.lsfd[] | select(((.name // "") == $root) or ((.name // "") | startswith($root + "/")))]'
) || {
  echo "holder inspection failed" >&2
  exit 1
}
test "$holders" = '[]' || {
  printf 'database holders found: %s\n' "$holders" >&2
  exit 1
}
```

Any holder, missing tool, command failure, or parse failure stops before backup
or mutation.

## Preserve before mutation

Create a unique directory with `mktemp` below
`${XDG_STATE_HOME:-$HOME/.local/state}/beads/adaptation-backups`. Resolve it and
prove it is outside the Git worktree, copy `.beads` with `cp -a`, and report the
recovery path.

Compare source and archive by literal relative path, type, mode, size, and
SHA-256. Compare exact `metadata.json` bytes and normalized exhaustive issue and
dependency snapshots. Do not mutate anything if a comparison fails.

## Apply the approved conversion

Only after preservation verifies, perform this fixed sequence:

1. If the exact `.beads/` line is absent from `<git-root>/.git/info/exclude`,
   append it while preserving all existing content. Re-read the file and
   require exactly one such line before continuing.
2. Remove only the approved exact Beads-only `.gitignore` lines, then
   immediately require `git check-ignore --no-index -v .beads` to resolve to
   `.git/info/exclude`; `--no-index` is required while database paths remain
   tracked. If it does not, restore the exact original `.gitignore` bytes and
   stop before any other mutation.
3. With native `bd --sandbox`, uninstall only positively identified Beads
   hooks.
4. With `bd --sandbox`, remove only approved Beads remotes.
5. With `bd --sandbox`, unset `sync.remote`, then verify the key is absent.
   Pinned Beads 1.1.2 can report success without persisting this removal; if
   the key remains, use `apply_patch` to remove only the detected `remote:`
   entry nested under `sync:` in `<git-root>/.beads/config.yaml`. Preserve every
   other line and verify absence with `bd config show` before continuing.
6. Assert `bd dolt remote list --json` returns `[]`.
7. Execute the canonical configuration command exactly as shown in the
   reference.
8. Enumerate tracked database paths literally with
   `git ls-files -z -- .beads`, and hash every corresponding live path.
9. Only when that enumeration is nonempty, run non-forced
   `git rm -r --cached -- <enumerated-literal-paths>`, then rehash the same
   paths.
10. Prove every live byte hash is unchanged and `.beads` remains private.

Every `bd` mutation uses `--sandbox`. Recheck configuration and provenance,
that `sync.remote` is absent, hooks, remotes, the normalized issue graph, Git
visibility, and that `git check-ignore -v .beads` resolves to
`.git/info/exclude`. If a postcondition fails, preserve the recovery archive,
report the exact state, and do not claim success.
