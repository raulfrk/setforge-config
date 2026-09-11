---
name: herdr
description: Inspect and control Herdr workspaces, tabs, panes, sessions, and coding agents, including an authorized Codex collaboration-mode handoff. Use for explicit Herdr requests or when global instructions direct the narrow mode-handoff workflow.
---

# Herdr

Herdr is a terminal workspace manager. Use its public CLI to inspect layout,
open terminals, run commands, and interact with coding agents.

Do not invoke this skill merely because parallel work might be useful. Herdr
control must be requested or clearly part of a Herdr-specific task.

Choose the narrow reference for the requested operation:

- Read [references/mode-handoff.md](references/mode-handoff.md) only for an
  authorized Codex collaboration-mode handoff.
- Read [references/workspace-operations.md](references/workspace-operations.md)
  for caller resolution, workspace, tab, pane, command, or coding-agent work.

Use opaque IDs returned by Herdr, preserve focus unless the user asks to switch,
and recheck immutable identity before mutations. Do not answer an approval or
user-decision prompt on the user's behalf. Never close a workspace, tab, pane,
or session without establishing its exact identity, inspecting its process and
agent state, and confirming its work is complete or preserved. Never stop the
Herdr server or kill its main process as ordinary cleanup.
