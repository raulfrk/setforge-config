---
name: cross-project-planning
description: Route and manage private Beads work when no single Git repository owns it, including personal or operational tasks, ownership decisions, and multi-repository initiatives. Do not use for work fully owned by one repository or merely because a repository lacks Beads.
---

# Cross-project planning

Use `/home/raul/planning` as the sole central private planning project. Keep
work in its owning repository whenever one repository owns execution.

## Choose the tracker

Decide ownership before creating or updating work:

- If exactly one repository owns execution, use that repository's tracker.
- If no repository owns the work, use the central planning project.
- If multiple repositories share one outcome, keep the shared outcome and
  coordination centrally and keep executable implementation and verification
  leaves in their owning repositories.
- If ownership is ambiguous, ask which outcome or repository owns it before
  tracking it.

Never duplicate the same executable work across trackers. The absence of a
repository-local Beads database is not a reason to route work centrally or
permission to initialize one.

## Use the central project explicitly

Never rely on current-directory or parent-directory discovery. Resolve and
verify the fixed project directly:

```sh
git -C /home/raul/planning rev-parse --show-toplevel
bd -C /home/raul/planning where --json
```

Canonicalize both returned paths and require the Beads path to equal
`/home/raul/planning/.beads`. Stop and report any mismatch.

Use the base `beads` skill for creation proposals and approval, claiming,
verification, closing, privacy, and configuration mechanics. A central issue
proposal must also state why no single repository owns it, its intended
outcome, and its acceptance criteria.

## Keep the boundary narrow

Use central epics only for genuinely shared outcomes and coordination. Do not
turn central planning into an agent controller, global routing mechanism,
implementation workspace, or artifact store. Do not configure `BEADS_DIR` or
add custom Beads policy keys for routing.
