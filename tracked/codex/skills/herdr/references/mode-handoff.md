# Codex collaboration-mode handoff


When global instructions authorize an autonomous mode handoff, use
`../scripts/plan_mode_handoff.py`. Announce the handoff, start the helper in the
foreground with an early-yield execution, confirm its process is running, then
end the turn with the exact marker on its own line. The helper waits for one
full second of stable completed rendering before acting; it never uses Herdr's
agent lifecycle status as evidence that the turn ended.

Pass the resolved Herdr session and immutable Codex thread ID, a fresh marker,
and a private file containing the already-authorized continuation. Launch with
a private umask and redirect stderr to a private runtime log. Run this as the
foreground command through the execution tool with an early yield:

```bash
umask 077
python3 <absolute-reference-dir>/../scripts/plan_mode_handoff.py \
  --target-mode plan \
  --session <session> \
  --thread-id <thread-id> \
  --marker <fresh-marker> \
  --continuation-file <private-file> \
  2> <private-runtime-log>
```

After the execution tool yields a live session, use a separate bounded,
read-only check to confirm its OS process is running and its private log
contains `READY`. Only then end the turn with the marker. Keep the yielded
execution session so its final status can be collected.

Use `--target-mode default --reason '<why planning no longer applies>'` only as
the fallback allowed by the global policy. Normal plan approval and
implementation do not use this fallback. On Herdr 0.8.2, logical
`shift+tab` is ineffective; the helper sends the standard Shift+Tab terminal
sequence through Herdr's raw pane interface. It does not answer dialogs, clear
input, retry a mode action, or infer success from transcript prose. Continue
only after the resumed turn receives the corresponding developer-level mode
instruction; the footer check is transport evidence, not that instruction.
Plan entry works with any native status-line selection or order, including a
disabled status line. After stable completion it sends the idempotent `/plan`
setter exactly once, then requires the explicit visible native `Plan mode`
indicator and an empty composer before sending the continuation. Default-mode
exit remains restricted to a positively identified legacy footer mode; a
terminal `·…` marker is accepted when the full context percentage remains visible.
