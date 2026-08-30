---
name: herdr
description: Inspect and control Herdr workspaces, tabs, panes, sessions, and coding agents. Use only when the user explicitly mentions Herdr or asks to use Herdr for terminal or agent control.
---

# Herdr

Herdr is a terminal workspace manager. Use its public CLI to inspect layout,
open terminals, run commands, and interact with coding agents.

Do not invoke this skill merely because parallel work might be useful. Herdr
control must be requested or clearly part of a Herdr-specific task.

## Resolve the calling pane

When these values are present, they identify the caller:

```bash
test "${HERDR_ENV:-}" = 1
printf '%s\n' \
  "$HERDR_WORKSPACE_ID" \
  "$HERDR_TAB_ID" \
  "$HERDR_PANE_ID"
```

If they are absent, use `CODEX_THREAD_ID` as the immutable identity:

1. Run `herdr session list --json`.
2. For each running session, run:

   ```bash
   herdr --session <session-name> pane list
   ```

3. Match only a Codex pane whose `agent_session.agent` is `codex` and whose
   `agent_session.value` exactly equals `CODEX_THREAD_ID`.
4. Continue only when exactly one live pane matches.
5. Use the returned session name and explicit workspace, tab, and pane IDs for
   every later command.

If zero or multiple panes match, report that caller identity cannot be resolved
safely and stop. Never match by terminal title, display name, pane order, or the
UI-focused pane.

Recheck the exact immutable match immediately before a mutating command because
pane IDs may change after moves.

After detached resolution, prefix every later command with
`herdr --session <resolved-session>` and target the resolved pane ID explicitly
instead of using `--current`.

## Inspect live state

Use opaque IDs returned by Herdr:

```bash
herdr workspace list
herdr tab list --workspace "$HERDR_WORKSPACE_ID"
herdr pane current --current
herdr pane list --workspace "$HERDR_WORKSPACE_ID"
herdr pane layout --current
herdr pane process-info --current
herdr agent list
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
herdr tab create \
  --workspace "$HERDR_WORKSPACE_ID" \
  --cwd "$PWD" \
  --label "<label>" \
  --no-focus
```

Inspect the caller's geometry before splitting:

```bash
herdr pane layout --current
```

Split a wide pane to the right or a tall/narrow pane downward:

```bash
herdr pane split \
  --current \
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
herdr pane run <pane-id> "<command>"
```

Wait for a known output condition:

```bash
herdr pane wait-output <pane-id> \
  --match "<literal text>" \
  --timeout 120000
```

Read recent output without terminal soft-wrap noise:

```bash
herdr pane read <pane-id> \
  --source recent-unwrapped \
  --lines 120
```

Use `--regex` instead of `--match` only when pattern matching is genuinely
needed. Use `--format ansi` only when terminal styling is evidence.

## Start and interact with an agent

An agent requires an existing available shell pane. Starting an agent does not
create layout:

```bash
herdr agent start <unique-name> \
  --kind codex \
  --pane <pane-id>
```

Pass native agent arguments only after `--`:

```bash
herdr agent start <unique-name> \
  --kind codex \
  --pane <pane-id> \
  -- <agent-arguments>
```

Prompt the agent and wait for a settled state:

```bash
herdr agent prompt <unique-name> \
  "<task>" \
  --wait \
  --timeout 120000
```

Inspect the agent:

```bash
herdr agent get <unique-name>
herdr agent read <unique-name> \
  --source recent-unwrapped \
  --lines 120
```

Wait for a specific state only when the workflow needs it:

```bash
herdr agent wait <unique-name> \
  --until blocked \
  --timeout 120000
```

Send logical keys for an interactive terminal UI:

```bash
herdr agent send-keys <unique-name> esc
herdr agent send-keys <unique-name> ctrl+c
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
