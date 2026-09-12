# OMP native Plan handoff

Use the profile's `plan_enter` tool only for a substantial request that warrants
OMP's native Plan mode. It is available only to a root interactive session.

Call `plan_enter` as the sole tool in the response with a short reason and the
complete private continuation. After it returns `status: armed`, emit only the
returned marker. The detached helper waits for that exact completed assistant
message, verifies the Herdr pane and OMP session identity, requires an unchanged
empty Build composer for one second, sends `/plan` once, verifies native Plan,
and submits the continuation once.

Do not call it for routine work. Do not retry an armed or failed handoff. If it
reports that Herdr metadata or an interactive TUI is unavailable, ask the user
to type `/plan` and continue the request there. OMP's native approval overlay is
the only normal exit from Plan; never answer it on the user's behalf.
