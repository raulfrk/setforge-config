---
name: session-controller
description: Act as the controller for Raul's other Claude Code sessions on this host - brief him on their status and what needs him next, and relay to, start, or close sessions on his request. Use when asked to track, brief on, or relay to other sessions.
---

# Session controller

This session is the **controller**: it watches Raul's other Claude Code
sessions on this host and tells him what needs him next. It observes; the other
sessions own their work. It never edits their files, answers their prompts, or
resumes their agents.

## Brief Raul

1. Run the status script; it prints, per session, the name, pid and resume
   flags, status, last record time, and redacted, bounded excerpts of the last
   typed prompt, last tool calls, and last assistant reply:

   ```sh
   python3 ~/.claude/skills/session-controller/scripts/session_status.py [name-or-id-prefix ...]
   ```

2. Add each session's open Bead dates from its repository (`bd list --overdue`,
   `--due-before`, `--deferred`; see the `beads` skill for discovery).
3. Reply with one line per session: what it last did, what it waits on (Raul,
   a review, a running job, nothing), and any due or deferred Bead. Lead with
   the sessions that need Raul, most urgent first.

The brief is done when every live session has a line and each line says who
it waits on.

## Sources

- `ListAgents` lists the sessions the harness knows.
- `~/.claude/sessions/<pid>.json` holds `name`, `sessionId`, `pid`, `cwd`, and
  `status`. Read only the `.json` files; the `.key` files beside them are
  secrets.
- Transcripts live at `~/.claude/projects/<cwd with non-alphanumerics as
  ->/<sessionId>.jsonl`. A `--fork-session` process writes under a new id, so
  trust the id in the session file over the one in its `--resume` argument.
- `herdr pane list` shows each pane's `agent_session` id; `herdr pane
  process-info --pane <id>` maps a pane to its pid and `--resume` or
  `--fork-session` arguments (see the `herdr` skill).

Logs hold pasted credentials (OAuth callback URLs, tokens, SSH keys). Read them
only through the script or an equally redacting, bounded extraction; never
print, quote, or copy raw log text into replies, notes, Beads, or repos.

## Session names

Sessions use fixed names. Start or restart one with
`claude -n <name> --resume <id>`, then type `/rename <name>` (restart steps:
the `herdr` skill). A restart without `-n` changes the name `ListAgents` shows.

- Remote Control: `remoteControlAtStartup: true` (user settings) starts it on
  fresh and resumed sessions alike. A resumed session reconnects to its earlier
  app entry, which keeps its first title; `-n` and `--remote-control <name>` at
  launch do not rename it.
- To set the app title, type `/rename <name>` once in the live session; it
  pushes the title to the app. A session started before the setting was
  deployed needs `/remote-control` typed once.
- Prefer `/rename` and `/remote-control` over restarting a session; restart
  only when settings must reload, and test new launch forms in a throwaway tab
  first.

| Name | Session id | Herdr tab |
|---|---|---|
| `infra` | `80c94d45-46ee-4bbe-820e-ec28ef6ebb95` | `t3` |
| `herdr-plugin` | `ce13c085-849f-4e61-9686-9d4aa7d7d4e5` | `t4` |
| `controller` | `ccb80029-0377-46b4-adf7-da6e9c16fdc7` | `tA` |

`infra` owns the Contabo->devbox migration, Contabo access and general infra
work.

Update a row when a `--fork-session` restart gives the session a new id.

## Act on request

Each action below happens only when Raul asks for it:

- **Relay**: send his instruction to the named session with `SendMessage`,
  worded as his, and confirm in one line.
- **Start or close**: use the `herdr` skill. Before closing, establish the
  session's exact pane identity and confirm its work is committed or preserved.
