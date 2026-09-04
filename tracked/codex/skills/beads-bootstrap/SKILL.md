---
name: beads-bootstrap
description: Bootstrap a new Git repository with an approved private, stealth Beads database and the canonical reviewer-friendly project configuration. Use for new-repository Beads setup; use beads-adapt when a database already exists.
---

# Bootstrap Beads privately

Initialize only a repository the user selected. Read the base `beads` skill and
[the canonical project configuration](../beads/references/project-config.md)
before proposing any mutation.

## Inspect and propose

Run initialization only from the primary Git checkout. If invoked from a linked
worktree, resolve the primary checkout with `git worktree list --porcelain` and
move the procedure there before proposing or running any mutation. Never create
a worktree-local Beads database. Require `BEADS_DIR` to be unset and reject a
primary `.beads` symlink or `redirect` file before initialization.

1. Resolve `git rev-parse --show-toplevel` and run `bd where --json` from the
   primary checkout root.
2. Treat `no beads project found` as absence. If a database exists, do not
   initialize: report whether its seven values conform and route drift to the
   `beads-adapt` skill.
3. Propose the exact repository prefix, this initialization command, and the
   canonical configuration command from the reference:

   ```sh
   bd init --stealth --non-interactive --skip-agents --skip-hooks \
     --prefix <approved-prefix>
   ```

4. Obtain explicit user approval immediately before running either command.

## Initialize and verify

Run the approved initialization from the Git root, then execute the canonical
configuration command exactly as shown in the reference. Do not reproduce or
extend its settings.

Verify all of these observable results:

```sh
git check-ignore -v .beads
git ls-files .beads
git status --short --untracked-files=all
bd hooks list
bd dolt remote list --json
bd config show
```

The ignore source must be the repository's `.git/info/exclude`; the tracked-file
and status checks must not expose `.beads`; the remote list must be empty; no
Beads hook may be installed; and every canonical value and provenance must
match the reference. On any failure, keep the database private, report the
actual state, and do not claim success or silently reinitialize.
