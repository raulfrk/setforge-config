---
name: webdiff
description: Serve a code/doc diff as a graphical web page over the tailnet — each change split into labeled sections with an authored "why", syntax-highlighted and mobile-wrapped, with persistent inline annotations and a Submit button that auto-resumes the agent. The browser-native complement to revdiff. Use when reviewing a diff where colour, rationale-next-to-code, or phone/iPad review matters, or when the user says "webdiff", "web diff", "review this diff on the web", "annotated web review".
---

# webdiff — served, annotated diff review

A review surface that turns a diff into a **graphical web page**: every change sits in its own
section with an **authored rationale** directly above the **syntax-highlighted hunk**, the user
adds **inline annotations per section** that persist server-side, and a **Submit** button flips a
server flag so the agent auto-resumes — no "annotated" typing needed.

It is the browser-native sibling of **revdiff** (terminal TUI). Both review the same diffs; offer
both at the Phase-6 gate (see `session-flow`). Prefer **webdiff** when rationale-beside-code, colour,
or phone/iPad review carries the meaning; prefer **revdiff** for a fast in-terminal pass.

## When to use

- The user asks to review a diff **on the web** / **with rationale beside each change** / on a phone or iPad.
- A change is worth explaining as you review it (design rewrites, multi-file features, teaching a newcomer).
- You want a **reload-friendly, submit-to-unblock** review loop across turns.

## The hub model — ONE server, many pages

`serve_webdiff.py` is a **single persistent hub** shared by ALL sessions (default port **8730**). Each
review is a **page** (`<id>.html`) under `$WEBDIFF_DIR/pages` (default `~/.local/share/webdiff/pages`),
reached at `/p/<id>`. A sticky **tab bar** lists every page (tab label = the page's `<title>`), highlights
the active one, shows the note count, and keeps a **Submit** button pinned right. Each page has its own
annotations + Submit flag (state in `$WEBDIFF_DIR/state`). Drop a new `<id>.html` in `pages/` → it appears
as a tab automatically. Don't spawn a per-page server.

## Workflow

1. **Compute the range.** `BASE..HEAD` for a merged/branch diff, or `HEAD` for uncommitted working-tree
   changes (run `git add -N <new-files>` first so untracked files appear in the diff).
2. **Author the spec.** Write a `spec.json` (schema in `scripts/gen_webdiff.py`'s docstring): `groups` →
   `blocks`. A block is one file as a `whole`-file diff, a `split` (one file → labeled sub-sections sliced
   at marker substrings like `class Foo` / `def bar(`), or per-`hunks` notes. **You author every `label` +
   `why`.** Set a clear page `title` (it becomes the tab label) — keep it short.
3. **Generate into the hub's pages dir:** `python3 scripts/gen_webdiff.py spec.json "$HOME/.local/share/webdiff/pages/<id>.html"`.
4. **Ensure the hub is up** (start once; reuse forever):
   ```bash
   curl -sf http://<ip>:8730/pages >/dev/null || setsid nohup python3 scripts/serve_webdiff.py 8730 > /tmp/webdiff-hub.log 2>&1 < /dev/null &
   ```
5. **Give the user the URL** `http://<tailscale-ip>:8730/p/<id>` — tabs switch between all pages.
6. **Wait via the `/wait` long-poll — event-driven, NOT a poll loop.** Run ONE blocking background request
   over the whole set of this session's pages; the hub answers it the *instant* any listed page is submitted
   (a condition variable wakes it — no timer), then your turn resumes. End the turn with:
   ```bash
   curl -s --max-time 300 "http://<ip>:8730/wait?ids=page-a,page-b,page-c"   # -> {"id":"page-a"} on Submit
   ```
   It returns `{"id":"<which>"}` immediately on Submit, or `{"id":null}` after ~5 min idle (just re-issue —
   one request per idle window, not a busy loop). Watch only YOUR session's page ids (the shared hub also
   holds other sessions' pages). **Keep one `/wait` armed whenever a page is open** — finish a turn without
   one and a Submit lands inert. (Do NOT nest it in `nohup … &` inside the bg task — run the `curl` as the
   background task itself so it blocks and notifies on return. Never `pkill -f` a pattern that matches your
   own shell.)
7. **Read annotations** of the submitted page: `curl -s "http://<ip>:8730/annotations?id=$HIT"` → `[{section,text,ts}]`.
   Work each; restate + resolve. Treat `??`/"explain"/"what is" as questions (answer, optionally as a new explainer page).
8. **Iterate:** regenerate the page file (hub serves it live — user reloads), then **re-arm** that page:
   `curl -X POST "http://<ip>:8730/rearm?id=<id>"` (resets submit, keeps annotations) or `/clear?id=<id>`
   (also wipes them). Re-launch the poller.

## Endpoints (all keyed by page id)

- `GET /` → 302 to the most-recent page · `GET /p/<id>` → the page (tab bar + annotation runtime injected) · `GET /pages` → tab list `[{id,title,mtime}]`.
- `GET /annotations?id=<id>` · `GET /submitted?id=<id>` · `GET /wait?ids=a,b,c` (long-poll; blocks until a listed page is submitted, returns `{"id":...}` or `{"id":null}` after ~5min).
- `POST /annotate {id,section,text}` · `POST /submit?id=<id>` · `POST /close?id=<id>` (**Submit & Close** — archive the page out of the tab bar; annotations kept for a final read) · `POST /resolve {id,section,text,ts}` (drop one handled note — each has a ✕) · `POST /clear?id=<id>` (wipe + disarm) · `POST /rearm?id=<id>` (disarm only).

After addressing a batch, `/clear` the page (or the user ✕'s each) so it shows a clean slate next round. If a page comes back from `/wait` but is no longer in `/pages`, the user hit **Submit & Close** — read its final notes, then `/clear` its state; it won't be a tab again.

## Binding / reachability

With Tailscale up the hub binds the tailnet IP (tailnet-only, no public exposure). Override the bind with a
2nd arg or `WEB_MOCKUP_HOST=<ip>` (`0.0.0.0` = LAN, trusted networks only; `127.0.0.1` needs SSH forward).
`WEBDIFF_DIR` relocates the pages/state root.

## Notes

- **Rendering:** a **self-contained, GitHub-style flexbox diff** (line-number gutter + colorized,
  Python-syntax-highlighted code) — **no CDN**. It is mobile-friendly: long lines always wrap to fit
  the width with the gutter fixed (flex `min-width:0`, not a `<table>` — a table collapses the code
  column to one char per line). One view, no wrap/unwrap toggle. Bottom-right **A−/A+** sets the diff
  font size (inline style — reliable). Validated with Playwright/Chromium screenshots (both wide + phone
  widths).
- **Verify it yourself:** screenshot + assert with Playwright/Chromium (`playwright install chromium` +
  system deps) or test DOM logic with jsdom — both are how this skill's zoom/render were validated.
- **Invariant suite:** `scripts/test_webdiff_invariants.py <hub-url>` (Hypothesis + Playwright) asserts the
  hub's 9 invariants (render/404/annotate-roundtrip/resolve/clear/per-page-isolation/submit-isolation/
  tab-completeness/zoom-clamp/no-mobile-overflow). Run it against an isolated test hub
  (`WEBDIFF_DIR=<tmp> python serve_webdiff.py <port> 127.0.0.1`) so it never touches live state.
- **bg sessions:** this is the sanctioned web review surface for background jobs — never downgrade to an
  inline-only proposal because the session is backgrounded.
- **Don't `pkill -f` the server** by a pattern that also matches your shell — kill by pid from `ss -ltnp`.

## Self-improvement

While using this skill, stay alert for any *generic* way it could be better — clearer wording, a missing
case, a smoother step, a recurring friction it should prevent.

- **Don't edit mid-task.** Capture the observation; keep working.
- **At a completion checkpoint**, propose it as a diff to THIS file via revdiff/webdiff — one edit per idea.
- **Generic only.** Never bake in project-specific detail unless this artifact is itself project-scoped.
- **Never auto-apply.** Propose; the user approves every edit.
- **Off-limits:** hard rails, safety/environment sections, system paths, `setforge:user-section` markers, and
  this self-improvement protocol itself.
- **Substantive, not noise.** Rare and load-bearing; never re-propose a declined idea.
