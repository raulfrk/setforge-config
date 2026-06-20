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
   over the whole set of this session's pages (or one per page — see *Multiple sessions* for the per-tab
   shape); the hub answers it the *instant* any listed page is submitted
   (a condition variable wakes it — no timer), then your turn resumes. End the turn with:
   ```bash
   curl -s --max-time 300 "http://<ip>:8730/wait?ids=page-a,page-b,page-c"   # -> {"id":"page-a"} on Submit
   ```
   On Submit it returns **`{"id":"<which>", "closed":<bool>, "annotations":[...]}`** and **consumes them
   atomically** — the notes are returned, then cleared + the flag reset server-side, so you never call a
   separate `/annotations` or `/clear`. (`closed:true` = the user hit Submit & Close.) With `timeout=0` it
   blocks indefinitely; otherwise `{"id":null}` after the timeout (re-issue). Watch only YOUR session's
   page ids. **Keep one `/wait` armed whenever a page is open — but branch on `closed` before re-arming:**
   a plain Submit (`closed:false`) means the page is still open, so address the notes and **re-arm**; a
   **Submit & Close** (`closed:true`) is the user's **APPROVAL — the review is concluded**: archive is
   done server-side, so read any final notes, `/clear` its state, and do **NOT** re-arm that id (the review
   is over; a fresh `/wait` on a closed page just blocks forever or instant-fires on a stale flag).
   Likewise, once a review is otherwise concluded (the user signals alignment / an empty plain-Submit that
   ends the loop), treat it like a close: stop watching, do not re-arm. Finish a turn without a wait armed
   on a still-*open*, still-*active* page and a Submit lands inert. (Do NOT nest it in `nohup … &` inside the bg task — run the `curl` as the
   background task itself so it blocks and notifies on return. Never `pkill -f` a pattern that matches your
   own shell.)
7. **Read the notes straight from the `/wait` response** (`annotations[]` — already consumed/cleared
   server-side; no `/annotations` or `/clear` call needed). Work each; treat `??`/"explain"/"what is" as
   questions (answer, optionally as a new explainer page). `GET /annotations?id=` still exists for a
   non-consuming peek.
8. **Iterate:** regenerate the page file (hub serves it live — it auto-reloads), then re-open the gate.
   **Once you've ADDRESSED the notes, use `/clear?id=<id>` (wipes them + resets the flag)** — `/rearm`
   only resets the submit flag and *keeps* the notes, so they linger and reappear on the next round (use
   `/rearm` only when you deliberately want to keep unaddressed notes). Bake the clear into the wait task
   (it `/clear`s the fired id after reading) so handled notes never pile up. Re-launch one `/wait`.

## Multiple sessions on the shared hub

The hub is one server for ALL Claude sessions, so its `pages/` holds everyone's reviews at once. Each
session must scope itself to what *it* created:

1. **Namespace your page ids.** Prefix with the bead id or a session slug (e.g. `deoq.3.1-review`,
   `jkbt-graph`) so your page files + state never collide with another session's.
2. **Subscribe to exactly the ids you created.** Pass only your own ids to `/wait?ids=…`. State is
   per-page (`annotations-<id>.json`, `submit-<id>.json`), so you never see another session's notes or
   submits (INV-5/INV-6). `/submit` does `notify_all`, which briefly wakes every waiter — but each
   re-checks only its own `ids` and returns nothing unless one of *those* flipped. No false pickup.
3. **Keep one `/wait` armed per id set — shared OR per-tab.** Two shapes both work:
   - **Shared:** one `/wait?ids=a,b,c` over your whole set, one background task. It returns the *first*
     page to flip and consumes only that one; re-arm to drain the next. Simplest; submits are serialized.
   - **Per-tab:** one `/wait?ids=<single>` per page (disjoint id sets), each its own background task. A
     multi-tab submit wakes each waiter independently — no serial drain. More concurrency-robust, more
     tasks to track; re-arm only the tab that fired — and only if it came back `closed:false` (a
     `closed:true` Submit & Close retires that tab; don't re-arm it).

   The hazard is **two waiters on the *same* ids** — both return the same hit and you process it twice.
   Disjoint per-tab waiters never overlap, so they're safe to run side by side. Before re-arming, reset the
   fired page's flag (`/rearm?id=…`, or the task clears the fired id) so a stale `submitted:true` can't
   re-fire instantly.

## Endpoints (all keyed by page id)

- `GET /` → 302 to the most-recent page · `GET /p/<id>` → the page (tab bar + annotation runtime injected) · `GET /pages` → tab list `[{id,title,mtime}]`.
- `GET /annotations?id=<id>` · `GET /submitted?id=<id>` · `GET /wait?ids=a,b,c[&timeout=<secs>]` (long-poll; blocks until a listed page is submitted, returns **`{"id","closed","annotations","markdown"}` and consumes (clears) the notes + resets the flag atomically**, or `{"id":null}` after `timeout` — default 300s, no upper cap, **`timeout=0` blocks indefinitely** until a submit. Arm with `timeout=0` (and a `curl` with no `--max-time`) for one forever-open wait, zero churn). The **`markdown`** field is the same batch rendered in revdiff's `## file:line (type)` format (see *Unified annotation format*) · `GET /archived` → closed pages `[{id,title,mtime}]`.
- `GET /reviewed?id=<id>` → `{secid: sechash}` of currently-reviewed sections (pruned to live sections).
- `POST /annotate {id,section,text[,file]}` · `POST /submit?id=<id>` · `POST /review {id,secid,hash,reviewed}` (toggle a section's reviewed-tick; locked RMW, orphan-pruned) · `POST /close?id=<id>` (**Submit & Close** — archive the page out of the tab bar; annotations kept for a final read) · `POST /reopen?id=<id>` (restore an archived page to the tabs) · `POST /resolve {id,section,text,ts}` (drop one handled note — each has a ✕) · `POST /clear?id=<id>` (wipe annotations + disarm; reviewed-ticks survive) · `POST /rearm?id=<id>` (disarm only).

**Empty state:** when no pages are open, `GET /` serves an "All caught up" page listing the **archived** reviews with **Reopen** buttons, and it auto-redirects to any new review that appears. So closing the last tab lands somewhere useful, not a dead end.

After addressing a batch, `/clear` the page (or the user ✕'s each) so it shows a clean slate next round. If a page comes back from `/wait` but is no longer in `/pages`, the user hit **Submit & Close** — read its final notes, then `/clear` its state; it won't be a tab again.

## Content modes (parity with revdiff)

Beyond the default `diff` block, a block may set an explicit `mode` (gen_webdiff.py):

- **`context`** — `{mode:"context", file}` reads a repo file and renders it context-only (no +/−). Explicit marker required; never inferred from a missing `range`.
- **`plan`** — `{mode:"plan", file}` renders a markdown file with a generated TOC.
- **`text`** — `{mode:"text", content}` renders synthetic/stdin content.
- **`all-files`** — `{mode:"all-files"}` lists `git ls-files` (capped).
- **`compare`** — `{mode:"compare", old, new}` renders a two-file diff (difflib).

**Security:** every disk path is resolved under the repo root and rejected on `..`/absolute/symlink escape (single shared helper); ALL file/stdin content is `html.escape`d (authored `why`/callouts stay raw); reads are size-capped with a truncation marker; binary files (NUL-sniffed) become a placeholder. A rejected/missing path renders a visible escaped error block, never unconfined content. `range` is optional for content-only pages.

## Visuals

A sticky **section overview map** (status dot per section + jump links + an N/total reviewed counter); per-file **diff-stat charts**; an authored **`diagram`** field on a group/block (inline `{type:"svg"}`, `{type:"img",src}`, or a labelled source fallback for mermaid/excalidraw — pre-export to SVG for an inline render; no CDN); collapsible **`<details>` groups** with badges. Per-section annotate stays on every section.

## Reviewed-tick & close-gating

Every section carries a stable `data-secid` and a `data-sechash` = sha256(content). A per-section **Reviewed** toggle persists in `reviewed-<id>.json` (independent of annotations/submit, so it survives reload/Submit/clear) and shows **green** when reviewed, **amber "↻ changed since reviewed"** when the content hash no longer matches, plain otherwise. **Submit & Close** is disabled (showing "N left") until every section is reviewed; **plain Submit is never gated**, and neither gates the actual bead merge.

## Unified annotation format

`annotation_format.py` is a faithful port of revdiff's annotation grammar (`## path (file-level)`, `## path:N (T)`, `## path:N-M (T)`, T ∈ {+,−,space}) with `## `-line body escaping, so annotations interchange losslessly between webdiff and revdiff through ONE parser. The `/wait` response's `markdown` field is this format (section notes → file-level; explicit hunk coords → line-level). `ts`/section metadata is webdiff-only and not carried across the handoff.

## Plan-review hook

`plan-review-webdiff-hook.py` is a custom `PreToolUse(ExitPlanMode)` hook (registered in tracked `settings.json`) that owns review-surface dispatch: with `review-surface=webdiff` (default) and the hub reachable/startable it serves the plan as a webdiff page (plan render + a two-file compare for the previous-revision rollover), blocks on `/wait?timeout=0`, and maps annotations to the ask/deny contract; with `revdiff`/no-browser it delegates to revdiff-planning's own hook unmodified. **Going live requires disabling revdiff-planning's own ExitPlanMode hook** (toggle that plugin off) so only one fires.

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
- **Test suite** (run with `/home/raul/setforge/.venv/bin/python` — it has Playwright + Hypothesis; system `python3` lacks them):
  - `test_webdiff_invariants.py <hub-url>` (Hypothesis + Playwright) — the hub's render/404/annotate/resolve/clear/isolation/submit/tab/zoom/no-overflow invariants, against an isolated test hub (`WEBDIFF_DIR=<tmp> python serve_webdiff.py <port> 127.0.0.1`).
  - `test_tristate.py` — submit tri-state (self-spinning). `test_reviewed.py` — reviewed-tick backend. `test_content_modes.py` — content modes + path security. `test_annotation_format.py` — revdiff⇄webdiff round-trip (Hypothesis). `test_plan_hook.py` — the ExitPlanMode hook (ask/deny/rollover/fallback). All self-spin an isolated hub and exit 0.
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
