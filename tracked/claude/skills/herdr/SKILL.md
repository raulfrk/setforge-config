---
name: herdr
description: Inspect and control Herdr workspaces, tabs, panes, sessions, and coding agents. Use for explicit Herdr requests, Herdr-specific tasks, or running a command that needs an interactive terminal (never tmux).
---

# Herdr

Herdr is a terminal workspace manager. Use its public CLI to inspect layout,
open terminals, run commands, and interact with coding agents.

Do not invoke this skill merely because parallel work might be useful. Use it
when Herdr control is requested, the task is Herdr-specific, or a command needs
an interactive terminal.

Read [references/workspace-operations.md](references/workspace-operations.md)
for caller resolution, workspace, tab, pane, command, or coding-agent work.

Use opaque IDs returned by Herdr, preserve focus unless the user asks to switch,
and recheck immutable identity before mutations. Do not answer an approval or
user-decision prompt on the user's behalf. Never close a workspace, tab, pane,
or session without establishing its exact identity, inspecting its process and
agent state, and confirming its work is complete or preserved. Never stop the
Herdr server or kill its main process as ordinary cleanup.

## Quick reference (herdr 0.9.3)

- Syntax: `herdr <group>` (`pane`, `agent`, `tab`) lists every subcommand;
  `herdr <group> <cmd> --help` gives its options. Never run bare `herdr`: it
  launches or attaches the TUI.
- Put `--session <name>` before the group: `herdr --session default pane list`.
- In zsh, `H="herdr --session default"; $H pane list` fails (no word
  splitting); write the full command or define a function.
- Output: `pane read` and `agent read` print plain text; every other command
  prints JSON.
- Read before asking: `pane read <p> --source detection --lines 40` shows
  what Raul sees; do this before asking him for a screenshot. Poll with
  `--source detection` too.
- `pane send-text <p> "<text>"` types without Enter; `pane run <p> "<cmd>"`
  types and presses Enter. `pane send-keys <p> ctrl+u` clears a Claude input
  line.
- `agent prompt <t> "<text>" --wait` returns when the agent settles (idle,
  done or blocked) and waits forever without `--timeout`; `--timeout MS`
  requires `--wait`.
- `agent start <name> --kind claude --pane <p>` needs an idle shell prompt in
  that pane.
- Pane to Claude session: `pane process-info --pane <p>` shows argv with
  `--resume <id>`; with `--fork-session` the live session has a new id
  (`pane list` shows the current one under `agent_session.value`).

Restart a Claude session in pane `<p>`:

1. Save any unsent draft from `pane read`; `pane send-keys <p> ctrl+u`.
2. `pane run <p> /exit`; wait until the old pid from `process-info` exits.
3. `pane run <p> "claude -n <name> --resume <id>"`.
4. `pane wait-output <p> --match "bypass permissions" --timeout 60000`.
5. Re-type the saved draft with `pane send-text`.
