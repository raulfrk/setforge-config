# Workspace operations

## Resolve the calling pane

When present, `HERDR_SOCKET_PATH`, `HERDR_WORKSPACE_ID`, `HERDR_TAB_ID`, and
`HERDR_PANE_ID` locate the caller's Herdr context. Resolve the socket to exactly
one running entry in `herdr session list --json`, then use that session name and
explicit IDs for later commands. Do not silently fall back to the default session.
These environment values locate a pane; they do not prove which Claude Code session
is currently loaded there.

When the caller context is absent, enumerate running sessions and their panes:

```bash
herdr session list --json
herdr --session <session-name> pane list
```

Use `CLAUDE_CODE_SESSION_ID` as the expected immutable conversation identity. A
matching `agent_session.agent` / `agent_session.value` is only a candidate: a
pane keeps the identity its last SessionStart hook reported, which can be stale
after `/clear`, `/resume`, or a relaunch. Cached metadata alone never authorizes
sending input or other conversation-specific mutations, even when exactly one
pane matches.

Use the user's explicit session/pane target or current authoritative runtime
identity. If the intended
caller cannot be confirmed without disrupting another conversation, report the
ambiguity and request the target instead of guessing. Never select by terminal
title, display name, pane order, or UI focus, or send a slash command into a working
agent merely to probe its identity.

Before mutation, recheck that the resolved session and pane still identify the
intended target; use new IDs returned after moves. Prefix subsequent commands
with `herdr --session <resolved-session>` and pass explicit target IDs instead
of `--current`. The examples below assume that session has already been resolved.

## Inspect live state

Use opaque IDs returned by Herdr:

```bash
herdr --session <resolved-session> workspace list
herdr --session <resolved-session> tab list --workspace <resolved-workspace-id>
herdr --session <resolved-session> pane list --workspace <resolved-workspace-id>
herdr --session <resolved-session> pane layout --pane <pane-id>
herdr --session <resolved-session> pane process-info --pane <pane-id>
herdr --session <resolved-session> agent list
herdr session list --json
```

Typical IDs are:

- Workspace: `w1`
- Tab: `w1:t1`
- Pane: `w1:p1`

Treat them as opaque handles. Parse IDs from command responses; never derive
them from sidebar position or a display label.

After moving a pane, use the returned new pane ID. Closed pane and tab IDs are
not reusable targets.

## Create layout

Default to the caller's current workspace, tab, and working directory. Keep
focus unchanged unless the user asks to switch.

Create a tab:

```bash
herdr --session <resolved-session> tab create \
  --workspace <resolved-workspace-id> \
  --cwd "$PWD" \
  --label "<label>" \
  --no-focus
```

Inspect the caller's geometry before splitting:

```bash
herdr --session <resolved-session> pane layout --pane <pane-id>
```

Split a wide pane to the right or a tall/narrow pane downward:

```bash
herdr --session <resolved-session> pane split \
  --pane <pane-id> \
  --direction right \
  --cwd "$PWD" \
  --no-focus
```

The response contains the new pane at `.result.pane.pane_id`.

Do not create a new workspace, worktree, or different working directory unless
the user requests that topology or it is necessary for the stated task.

## Run an ordinary command

Run a command in an available shell pane:

```bash
herdr --session <resolved-session> pane run <pane-id> "<command>"
```

Wait for a known output condition:

```bash
herdr --session <resolved-session> pane wait-output <pane-id> \
  --match "<literal text>" \
  --timeout 60000
```

Inspect current output without scrolling the agent's conversation:

```bash
herdr --session <resolved-session> pane read <pane-id> --source detection --lines 120
```

Use passive `detection` reads for polling. Explicit history reads can scroll an
idle alternate-screen agent up and back down to collect older output. Use the
following only when that history traversal is intended:

```bash
herdr --session <resolved-session> pane read <pane-id> \
  --source recent-unwrapped \
  --lines 120
```

Use `--regex` instead of `--match` only when pattern matching is genuinely
needed. Use `--format ansi` only when terminal styling is evidence.

## Start and interact with an agent

An agent requires an existing available shell pane. Starting an agent does not
create layout:

```bash
herdr --session <resolved-session> agent start <unique-name> \
  --kind claude \
  --pane <pane-id>
```

Pass native agent arguments only after `--`:

```bash
herdr --session <resolved-session> agent start <unique-name> \
  --kind claude \
  --pane <pane-id> \
  -- <agent-arguments>
```

Prompt the agent and wait for a settled state:

```bash
herdr --session <resolved-session> agent prompt <unique-name> \
  "<task>" \
  --wait \
  --timeout 60000
```

Inspect the agent:

```bash
herdr --session <resolved-session> agent get <unique-name>
herdr --session <resolved-session> agent read <unique-name> \
  --source detection \
  --lines 120
```

Wait for a specific state only when the workflow needs it:

```bash
herdr --session <resolved-session> agent wait <unique-name> \
  --until blocked \
  --timeout 60000
```

Send logical keys for an interactive terminal UI:

```bash
herdr --session <resolved-session> agent send-keys <unique-name> esc
herdr --session <resolved-session> agent send-keys <unique-name> ctrl+c
```

Do not answer an approval or user-decision prompt on the user's behalf. Inspect
the blocked output and ask the user.

## Understand agent state

- `working`: the agent is actively processing.
- `idle`: the agent is ready for input and its completed work has been seen.
- `done`: the agent is ready for input after unseen background work completed.
- `blocked`: Herdr recognized a question or approval UI.
- `unknown`: an agent exists but Herdr cannot classify it confidently.

`unknown` does not mean finished. A quiet pane or shell prompt is not sufficient
completion evidence when an agent is expected.

## Focus and destructive actions

Use `--no-focus` for background actions. Focus a tab, pane, workspace, or agent
only when the user asks to switch attention.

Do not close a workspace, tab, pane, or session unless:

1. its exact identity is established;
2. its process and agent state have been inspected;
3. its work is complete or safely preserved; and
4. the user authorized the closure when it is not clearly owned by this task.

Never stop the Herdr server or kill its main process as ordinary cleanup.

## Less-common operations

Routine work should use the commands above without CLI discovery. If a
Herdr-specific operation is not covered, load the installed version-matched
agent guidance:

```bash
herdr --skill
```

Use that guidance instead of guessing syntax. Do not run bare `herdr` for
discovery because it launches or attaches the TUI.
