# Codex collaboration-mode handoff

Use `../scripts/plan_mode_handoff.py` only when global instructions authorize a
Codex collaboration-mode handoff. The helper keeps the completed Codex root,
process, thread, Herdr pane, and model intact while moving between Default and
Plan modes. Codex may apply its configured Plan-mode reasoning effort when
`/plan` is submitted.

Before arming it, use the native agent list and require that this root has no
running child work. Announce the handoff, create a private continuation file,
and start the helper in the foreground with an early-yield execution. Pass the
current immutable Codex thread ID, expected working directory, and a fresh
marker:

```bash
umask 077
python3 <absolute-reference-dir>/../scripts/plan_mode_handoff.py \
  --target-mode plan \
  --session <session> \
  --thread-id <thread-id> \
  --cwd <absolute-working-directory> \
  --marker <fresh-marker> \
  --continuation-file <private-file> \
  2> <private-runtime-log>
```

When the native app-server control socket is available, the helper reuses the
installed `main-session` native reader and requires this exact loaded thread to
be idle before commands or continuation. It only reads thread state; it never
resumes a thread or changes permissions/settings. For a different server, pass
`--app-server-socket <socket-path>`. A present socket with unavailable or blocked
thread state fails safely. Without that socket it uses the stable rendered
marker and passive pane checks. A final marker may appear before the native
turn finishes; `/status` can succeed during that interval.

After the execution yields a live session, use a separate bounded read-only
check to confirm its OS process is running and its private log contains
`ARMED`. Only then end the turn with the exact marker on its own line. `READY`
is logged after that completed marker is located and stabilized. Keep the
yielded execution session so its final status can be collected.

Before logging `ARMED`, the helper rejects an existing unfinished marker for
the same Herdr session and Codex thread. This makes interrupted-handoff state a
visible preflight failure while the current root can still report it; the
helper never deletes ambiguous recovery state automatically.

The helper locates exactly one completed Codex pane using that unguessable
rendered marker and the expected cwd. Before changing anything, it uses
`/status` to require the supplied immutable thread ID and pins the pane, tab,
workspace, and cwd. It never infers identity from a terminal title.
Herdr's cached `agent_session` is not authoritative: SessionStart hooks in a
shared Codex daemon can report another conversation's ID to an inherited pane.
The fresh rendered marker locates the candidate; `/status` verifies its thread
before `/plan` or continuation. Footer service labels such as `fast` are ignored;
model and reasoning effort are still checked against `/status`. An unknown
footer fails with a specific diagnostic instead of guessing a mode or sending
input. After CLI updates, run the repository's handoff regression tests and
check a captured live footer before relying on the helper.

The helper accepts complete bordered status panels and the unboxed native
Codex 0.159 layout. Unboxed status requires the native version header, all
identity/route fields, and the empty composer boundary; a clipped or incomplete
panel still refuses the handoff. Do not confuse missing box borders in the
recognized unboxed layout with clipping.

All polling uses `herdr pane read --source detection`, which takes a passive
snapshot without scrolling. Do not use `recent` or `recent-unwrapped` for this
workflow: Herdr may send mouse-wheel events to harvest an idle agent's
alternate-screen history, visibly replaying the conversation on every poll.
The marker and complete `/status` panel must fit in the live pane. If the panel
is clipped, enlarge the pane; never fall back to interactive history reads.

Slash commands use `herdr pane run` to submit text and Enter together. Do not
split them into `send-text`, a delay, and `send-keys`: that exposes Codex's
autocomplete menu and unnecessarily repaints conversation history during the
handoff. The fresh `/status` checks still run before and after the mode change.

If a newly submitted `/plan` explicitly reports that it is disabled while a
task is in progress, the helper waits for completion, rechecks the same marker,
empty input, pinned pane and fresh `/status`, and retries `/plan` once. Without
native readiness, it additionally requires a changed, stable idle screen after
the rejection. Changed user input, an approval, or changed identity stops
recovery. Timeouts and uncertain command/continuation delivery are never
replayed; the retained unfinished marker still requires inspection. A retry
does not extend the original deadline or resend the continuation.

Switching focus between Herdr tabs is supported; the target tab need not be
focused. Keep the original conversation loaded in its pane until the handoff
finishes. Replacing it inside the same TUI or closing its TUI can unload the
thread and hide the marker, so the helper times out without sending commands to
the replacement conversation. On return, inspect the retained runtime log and
collect the helper's exit status; `ARMED` alone is not success. Request a fresh
handoff after a discovery failure. If an unfinished marker exists, inspect it
first because a mode change or continuation may already have been attempted.

For a Plan target the helper sends `/plan` only when the verified mode is not
already Plan. For a Default target, the standard plan-approval flow and the
developer-level Default Mode instruction must already have restored Default
Mode. The helper accepts the handoff only after a final `/status` verifies the
same thread ID, pinned cwd, unchanged model, and target collaboration mode. For
Plan, it also verifies that the displayed reasoning effort matches `/status`,
allowing Codex's configured Plan-mode override. It then submits the
continuation exactly once.

The helper never opens `/model`, sets reasoning effort itself, sends `ctrl+c`,
exits Codex, starts an agent, forks or resumes a thread, edits configuration,
or uses a named profile. It retains a private unfinished marker when
continuation delivery fails after the handoff is armed.

Exit Plan Mode through the standard plan-approval flow. Use a fallback only when
planning no longer applies, such as a changed or abandoned task or accidental
entry, and explain why. Never bypass a pending approval or active collaboration
rules. The helper's Default handoff still requires the corresponding developer-
level Default Mode instruction; it does not replace that mode-change boundary.
