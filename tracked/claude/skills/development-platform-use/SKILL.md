---
name: development-platform-use
description: Develop on devbox and run builds, test suites and Docker-based or long commands on the home workboxes through the existing Concourse-backed job interface. Route infrastructure configuration and recovery to the infrastructure repository.
---

# Development platform use

Projects live on `devbox-1`. Work in the selected project or worktree: primary
checkouts are under `/srv/workspaces/projects`, worktrees under
`/srv/workspaces/worktrees`. Read its `CLAUDE.md` or `AGENTS.md`, build
definitions and optional `.infra/job.yml` to choose the actual command.

devbox is the editing host. It has language toolchains for short local checks
and no Docker. Send test suites, builds, parallel or long runs and anything
that needs Docker to the workboxes. Do not install Docker, build services or
other heavy tooling on devbox to avoid a job.

Resolve the checkout's canonical path: jobs require an existing directory
strictly below the ready `/srv/workspaces` mount.

## Run builds and tests

Use the installed `infra job` interface on devbox. It submits ordinary tasks
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
command needs a private rootless Docker daemon. A project may select only
images already approved for its class. The scheduler admits jobs by capacity;
do not pick a worker or alter infrastructure to bypass its limits.

## Size, time and priority

Sizes are `light` (1 CPU, 2 GiB), `standard` (2 CPUs, 4 GiB) and `heavy`
(5 CPUs, 10 GiB); `--cpus` and `--memory` set them explicitly. `quick` and
`build` default to standard, `native-docker` to heavy. Size a repeated job from
the `usage` that `infra job status` shows for its last run, plus headroom, not
from a preset by habit: a smaller reservation starts sooner.

- `--timeout` sets the time limit, up to `12h`. Defaults: 30 minutes for
  `quick`, 2 hours for `build` and `native-docker`. A job stopped at its limit
  ends `failed` with reason `time_limit`. Ask for a long limit only when the
  work needs it; a hung job holds its slot until the limit.
- `--max-wait` sets the longest wait for capacity, up to the default `24h`. A
  job that waits longer ends `failed` with reason `wait_timeout`; it never ran
  and can be submitted again.
- `--priority high|normal|low` orders waiting jobs. Use `high` only when a
  person or an agent is blocked on the result, `low` for bulk work that can
  wait, such as mutation shards and benchmarks.

A job killed for memory ends with reason `out-of-memory`: request more memory
or lower its parallelism instead of repeating it unchanged. A `quick` or
`build` job may hold at most 1024 processes and threads; `can't start new
thread` means too many parallel workers.

## Shared files and completion

Jobs use the **same live shared files**, including staged changes, modifications
and untracked files. Submission does not snapshot or copy the checkout. Avoid
overlapping edits and jobs that write the same files; use a separate working
directory or serialize them when needed. A local build becoming safe is not
permission to silently discard or overwrite dirty work. Do not delete or
replace a job's `--cwd` directory while the job runs; remove it only after
`infra job status` shows a final state.

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
when the task permits it and devbox's tools, resources, isolation and secrets
are suitable. Reconcile uncertain remote execution before running locally.

For setup, worker recovery, image changes or CI routing, read the infrastructure
repository's `CLAUDE.md` or `AGENTS.md` and its Infrastructure Use skill. Its
primary checkout is `/srv/workspaces/projects/infrastructure`. Use the current
`docs/runbooks/jobs.md` for job operations and `docs/runbooks/workbox-ci.md` for
the separate GitHub CI flow. Do not infer release or infrastructure-change
permission from a request to run tests. Contabo is no longer a development
host; neither it nor its retired services are a fallback to reconfigure.
