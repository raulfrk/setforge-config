---
name: development-platform-use
description: Work on projects already on devbox or run requested builds and tests on the home workboxes through the existing Concourse-backed job interface. Route infrastructure configuration and recovery to the infrastructure repository.
---

# Development platform use

Use this workflow for projects already on devbox or explicitly selected home
workbox execution. Projects retained on Contabo stay there; do not redirect an
unrelated local task or migrate a project to make this skill applicable.
Work in the selected project or worktree on `devbox-1`. Read its `AGENTS.md`,
build definitions and optional `.infra/job.yml` to choose the actual command.
Resolve the checkout's canonical path: jobs require an existing directory
strictly below the ready `/srv/workspaces` mount. Migrated primary projects live
under `/srv/workspaces/projects`; worktrees have their own mapped directories.
Do not copy a Contabo checkout or start migration to make a path available.

## Run builds and tests

Prefer the installed `infra job` interface on devbox. It submits ordinary tasks
to Concourse and the persistent workboxes; everyday project work needs no new
pipeline or direct `fly execute` invocation.

```sh
infra job submit --project PROJECT --cwd /srv/workspaces/projects/PROJECT \
  --class quick -- COMMAND ARGUMENTS
infra job status JOB_ID
infra job logs JOB_ID
infra job artifacts JOB_ID
```

Replace the example's placeholders with the current project and its documented
argv. From another machine, use the existing strict devbox SSH alias and pass
the command with proper shell quoting; never weaken host-key checking.

Choose `quick` for small commands using the approved Git-capable image; `build`
for the project's approved Python/Rust/Go build image; `native-docker` when the
command needs a private rootless Docker daemon. Use `light`, `standard` or
`heavy` sizes, or explicit `--cpus` and `--memory`, according to demonstrated
requirements. The scheduler admits jobs by capacity; do not pick a worker or
alter infrastructure to bypass its limits. A project may select only images
already approved for its class.

## Shared files and completion

Jobs use the **same live shared files**, including staged changes, modifications
and untracked files. Submission does not snapshot or copy the checkout. Avoid
overlapping edits and jobs that write the same files; use a separate working
directory or serialize them when needed. A local build becoming safe is not
permission to silently discard or overwrite dirty work.

Retain the returned job ID. A submit timeout or lost acknowledgement is uncertain
execution: reconcile the existing job before another submission. Check terminal
status and logs, then retrieve declared artifacts. Report the actual build
result separately from infrastructure success.

`infra job patch JOB_ID` reports that edits already exist in the live directory;
it does not return a patch to apply. `infra job replay JOB_ID` creates a new job
with the retained command/settings against **current files**, not old bytes.
Replay only when deliberately requested or justified by the task. Cancel only
the intended job and confirm its terminal cleanup.

## Access, fallback and operations

Use only the project's authorized named secret values through the existing job
contract. Never put credentials in argv, logs, shared files or Fly variables;
never mount a host Docker socket. Image/secret allowlist changes are
infrastructure work, not a project-side workaround.

If the platform is unavailable, report that fact and use a local fallback only
when the task permits it and the local tools, resources, isolation and secrets
are suitable. Reconcile uncertain remote execution before running locally.

For setup, worker recovery, image changes or CI routing, read the infrastructure
repository's `AGENTS.md` and its Infrastructure Use skill. On devbox its selected
primary checkout is `/srv/workspaces/projects/infrastructure`; before migration,
the source checkout is `/home/raul/projects/infrastructure`. Use the current
`docs/runbooks/jobs.md` for job operations and `docs/runbooks/workbox-ci.md` for
the separate GitHub CI flow. Do not infer release or infrastructure-change
permission from a request to run tests. Home OpenCodex is retired; source
Contabo services are not a fallback to reconfigure.
