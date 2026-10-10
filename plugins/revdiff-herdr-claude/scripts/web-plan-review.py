#!/usr/bin/env python3
"""Serve one HTML plan as a local web page and print the review comments it collects.

Exit 0: reviewed, no comments. Exit 10: reviewed, comments on stdout. Anything
else: the review failed (reason on stderr).
"""

from __future__ import annotations

import argparse
import errno
import hmac
import html
import json
import os
import re
import secrets
import socketserver
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import urlsplit

BLOCK_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "tr", "figure", "pre", "blockquote", "aside"})
DEFAULT_PORT = 47821  # fixed, so the phone app keeps one tunnel across reviews
QUOTE_LIMIT = 80
MAX_BODY = 1 << 20
CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-{nonce}'; "
    "connect-src 'self'; img-src data:"
)
# The only Host headers we answer, so a web page cannot read the plan through DNS rebinding.
HOST_RE = re.compile(r"(?:127\.0\.0\.1|localhost|\[::1\])(?::[0-9]+)?", re.IGNORECASE)

Comment = tuple["int | None", str]


class Plan(NamedTuple):
    html: str  # the plan with a data-line stamp on each commentable block
    title: str
    quotes: dict[int, str]  # stamped line -> block text, cut for quoting


def collapse(text: str) -> str:
    return " ".join(text.split())


def cut(text: str) -> str:
    return text if len(text) <= QUOTE_LIMIT else text[: QUOTE_LIMIT - 1].rstrip() + "…"


class PlanParser(HTMLParser):
    """Find commentable blocks and the offsets where their start tags take a stamp."""

    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        # html.parser counts lines by "\n" only; use the same rule for offsets.
        self.line_starts = [0] + [m.end() for m in re.finditer("\n", source)]
        self.stamps: list[tuple[int, int]] = []  # (offset after the tag name, line)
        self.quotes: dict[int, str] = {}
        self.title = ""
        self.open: list[tuple[str, int | None, list[str]]] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag not in BLOCK_TAGS:
            return
        row, col = self.getpos()
        # Comments are keyed by line, so only the outermost block starting on a
        # line is commentable; the page and the server then agree on it.
        line = row if not self.stamps or self.stamps[-1][1] != row else None
        if line is not None:
            name = re.match(r"<[^\s/>]+", self.get_starttag_text() or "")
            self.stamps.append((self.line_starts[row - 1] + col + (name.end() if name else 1), row))
        self.open.append((tag, line, []))

    def handle_data(self, data: str) -> None:
        for _, _, parts in self.open:
            parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag not in BLOCK_TAGS:
            return
        for index in range(len(self.open) - 1, -1, -1):
            if self.open[index][0] == tag:
                self.close_blocks(index)
                return

    def close_blocks(self, index: int) -> None:
        """Finish the block at `index` and anything left open inside it."""
        for tag, line, parts in self.open[index:]:
            text = collapse("".join(parts))
            if line is not None:
                self.quotes[line] = cut(text)
            if tag == "h1" and text and not self.title:
                self.title = text
        del self.open[index:]


def parse_plan(source: str) -> Plan:
    parser = PlanParser(source)
    parser.feed(source)
    parser.close()
    parser.close_blocks(0)
    pieces: list[str] = []
    previous = 0
    for offset, line in parser.stamps:
        pieces += [source[previous:offset], f' data-line="{line}"']
        previous = offset
    pieces.append(source[previous:])
    return Plan("".join(pieces), parser.title or "Plan review", parser.quotes)


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{{TITLE}}</title>
<style>
:root{color-scheme:light dark;--sans:-apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,sans-serif;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;--bg:#f5f6f8;--surface:#fff;--fg:#11132a;--body:#2c2f48;--muted:#6d7190;--line:#ebecf5;--accent:#3f55d6;--on-accent:#fff;--tonal:#eceffb;--on-tonal:#3346b8;--ok-bg:#e2f8ec;--ok-fg:#0b7a3d;--err:#b3261e;--panel:#f6f7fa;--node:#fff;--field:#f6f7fa;--note:#f1f2f6;--bar:rgba(255,255,255,.78);--bar-line:rgba(17,19,42,.08);--bubble:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20'%3E%3Cpath fill='%233f55d6' d='M4 3h12a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H9l-4 3.5V14H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z'/%3E%3C/svg%3E")}
@media (prefers-color-scheme:dark){:root{--bg:#0b0c10;--surface:#15161c;--fg:#f1f2ff;--body:#c9cce4;--muted:#8d91ad;--line:#25272f;--accent:#8f9eff;--on-accent:#0b0c10;--tonal:#1d2140;--on-tonal:#b9c2ff;--ok-bg:#0f3323;--ok-fg:#6fe3a2;--err:#ff8a80;--panel:#101116;--node:#1c1e26;--field:#101116;--note:#1b1d25;--bar:rgba(21,23,38,.78);--bar-line:rgba(255,255,255,.09);--bubble:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 20 20'%3E%3Cpath fill='%238f9eff' d='M4 3h12a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H9l-4 3.5V14H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z'/%3E%3C/svg%3E")}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-padding-bottom:96px}
body{margin:0;padding-bottom:calc(84px + env(safe-area-inset-bottom));background:var(--bg);color:var(--body);font:15px/1.5 var(--sans);-webkit-font-smoothing:antialiased;overflow-wrap:anywhere}
body:has(#status:not(:empty)){padding-bottom:calc(148px + env(safe-area-inset-bottom))}
main,#end{max-width:44rem;margin:0 auto;padding:0 max(12px,env(safe-area-inset-right)) 0 max(12px,env(safe-area-inset-left))}
main::before{content:"Plan review";display:block;margin:calc(16px + env(safe-area-inset-top)) 6px 0;color:var(--accent);font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase}
h1,h2,h3,h4,h5,h6{margin:14px 0 4px;color:var(--fg);font-weight:650;line-height:1.25}
h1{font-size:22px;line-height:1.2;letter-spacing:-.018em}
main>h1{margin:5px 6px 12px}
main>h1+p,main>h1+.cbox+p{margin:-7px 6px 12px;color:var(--muted);font-size:14px}
main>h1+.cbox{margin:6px 6px 10px}
main>h1+.cbox+p{margin-top:0}
h2{margin:18px 0 8px;color:var(--muted);font-size:12px;letter-spacing:.07em;text-transform:uppercase}
h3{font-size:15px}
h4{font-size:14px}
h5{color:var(--muted);font-size:13px}
h6{color:var(--muted);font-size:12px;letter-spacing:.02em}
p{margin:6px 0}
strong{color:var(--fg);font-weight:600}
a{color:var(--accent)}
hr{margin:12px 0;border:0;border-top:1px solid var(--line)}
code,pre{font-family:var(--mono)}
code{padding:1px 5px;border-radius:4px;background:color-mix(in srgb,var(--muted) 14%,transparent);color:var(--fg);font-size:.88em}
pre{margin:8px 0;padding:10px 12px;overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--fg);font-size:12.5px;line-height:1.5}
pre code{padding:0;background:none;font-size:inherit}
blockquote{margin:8px 0;padding:2px 0 2px 12px;border-left:2px solid color-mix(in srgb,var(--accent) 45%,transparent);color:var(--muted)}
section{margin:0 0 10px;padding:14px 15px;border:1px solid var(--line);border-radius:12px;background:var(--surface)}
section>:first-child,aside>:first-child,blockquote>:first-child,li>:first-child{margin-top:0}
section>:last-child,aside>:last-child,blockquote>:last-child,li>:last-child{margin-bottom:0}
mark{display:inline-flex;align-items:center;gap:6px;max-width:100%;padding:1px 8px 1px 7px;border-radius:999px;background:var(--ok-bg);color:var(--ok-fg);font-size:11.5px;font-weight:600;line-height:1.5;vertical-align:1px;white-space:nowrap}
mark::before{content:"";flex:none;width:6px;height:6px;border-radius:50%;background:currentColor}
aside{position:relative;margin:10px 0 2px;padding:9px 12px 9px 36px;border-radius:8px;background:var(--note);color:var(--fg);font-size:14px;line-height:1.42}
aside::before{content:"?";position:absolute;left:10px;top:10px;display:grid;place-items:center;width:18px;height:18px;border-radius:50%;background:var(--accent);color:var(--on-accent);font-size:11px;font-weight:800;line-height:1}
ol,ul{margin:6px 0;padding:0;list-style:none}
li>ol,li>ul{margin:4px 0 0}
ol{counter-reset:step}
ol>li:not(.cbox),ul>li:not(.cbox){position:relative}
ol>li:not(.cbox){counter-increment:step;min-height:24px;padding:1px 0 12px 32px}
ol>li:not(.cbox)::before{content:counter(step);position:absolute;left:0;top:0;display:grid;place-items:center;width:22px;height:22px;border-radius:50%;background:var(--tonal);color:var(--on-tonal);font-size:11.5px;font-weight:650;line-height:1}
ol>li:not(.cbox)::after,ol>li.cbox::after{content:"";position:absolute;left:10px;top:26px;bottom:2px;width:1.5px;border-radius:2px;background:var(--line)}
ol>li:not(.cbox):last-child{padding-bottom:2px}
ol>li:last-child::after,ol>li.open::after{display:none}
ol>li.open{padding-bottom:1px;margin-bottom:11px}
ol>li.open::before{background:var(--accent);color:var(--on-accent)}
ul>li:not(.cbox){padding:3px 0 3px 20px}
ul>li:not(.cbox)::before{content:"";position:absolute;left:3px;top:.72em;width:7px;height:7px;border-radius:50%;background:var(--accent)}
table{width:100%;margin:2px 0 0;border-collapse:separate;border-spacing:0}
th,tr:not(.cbox)>td{padding:8px 12px 8px 0;text-align:left;vertical-align:top}
th{padding-top:2px;padding-bottom:6px;color:var(--muted);font-size:10.5px;font-weight:650;letter-spacing:.07em;text-transform:uppercase}
tr:not(.cbox)>td{border-top:1px solid var(--line);font-size:14px}
tr:not(.cbox)>td:first-child{color:var(--fg);font:500 12.5px/1.45 var(--mono);overflow-wrap:break-word}
tr:not(.cbox)>td:last-child:not(:first-child){color:var(--muted)}
th:last-child,tr:not(.cbox)>td:last-child{padding-right:0}
figure{margin:6px 0 2px;padding:10px 8px 8px;border-radius:8px;background:var(--panel)}
figcaption{margin-top:6px;color:var(--muted);font-size:12px;text-align:center}
svg{max-width:100%;height:auto;fill:currentColor}
figure svg{display:block;width:100%}
svg .node{fill:var(--node);stroke:var(--line);stroke-width:1}
svg .dot{fill:var(--tonal)}
svg .ic{fill:none;stroke:var(--accent);stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}
svg .lbl{fill:var(--fg);font:600 12px var(--sans)}
svg .sub{fill:var(--muted);font:500 10.5px var(--sans)}
svg .wire{fill:none;stroke:var(--accent);stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
svg .loop{stroke-dasharray:1 6;opacity:.75}
svg .pill{fill:var(--tonal);stroke:var(--panel);stroke-width:4}
svg .pilltxt{fill:var(--on-tonal);font:700 10.5px var(--sans)}
[data-line]{cursor:pointer;-webkit-tap-highlight-color:transparent}
[data-line].open:not(tr){padding-right:24px;border-radius:8px;background-color:var(--tonal);background-image:var(--bubble);background-repeat:no-repeat;background-position:right 4px top 5px;background-size:16px;box-shadow:-4px 0 0 3px var(--tonal),4px 0 0 3px var(--tonal);color:var(--fg)}
figure[data-line].open{padding-right:8px}
blockquote[data-line].open{border-radius:0 8px 8px 0}
pre[data-line].open{border-color:transparent}
tr.open>td,tr.open>th{border-top-color:transparent;background-color:var(--tonal)}
tr.open>td:first-child,tr.open>th:first-child{border-radius:8px 0 0 8px;box-shadow:-7px 0 0 var(--tonal)}
tr.open>td:last-child,tr.open>th:last-child{padding-right:24px;border-radius:0 8px 8px 0;background-image:var(--bubble);background-repeat:no-repeat;background-position:right 4px top 8px;background-size:16px;box-shadow:7px 0 0 var(--tonal)}
.cbox{margin:6px 0 10px}
.cbox:not(tr)::before,.cbox>td::before{content:"Your comment";display:block;margin:0 0 5px 2px;color:var(--accent);font-size:10.5px;font-weight:650;letter-spacing:.06em;text-transform:uppercase}
ol>li.cbox{position:relative;margin:0;padding:0 0 12px 32px}
ol>li.cbox::after{top:0}
ul>li.cbox{margin:0;padding:5px 0 8px 20px}
tr.cbox>td{padding:6px 0 10px}
textarea{display:block;width:100%;resize:vertical;padding:8px 10px;border:1px solid color-mix(in srgb,var(--muted) 40%,transparent);border-radius:8px;background:var(--field);color:var(--fg);font:inherit;font-size:16px;line-height:1.4;outline:0}
textarea::placeholder{color:var(--muted);opacity:.8}
textarea:focus,.cbox textarea{border-color:var(--accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 14%,transparent)}
#end label{display:block;margin:0 0 8px;color:var(--muted);font-size:12px;font-weight:650;letter-spacing:.07em;text-transform:uppercase}
#bar{position:fixed;left:0;right:0;bottom:0;z-index:4;display:grid;grid-template-columns:1fr 1.3fr;column-gap:8px;padding:8px max(12px,env(safe-area-inset-right),calc(50% - 22rem + 12px)) calc(8px + env(safe-area-inset-bottom)) max(12px,env(safe-area-inset-left),calc(50% - 22rem + 12px));border-top:1px solid var(--bar-line);background:var(--bar);-webkit-backdrop-filter:blur(20px) saturate(170%);backdrop-filter:blur(20px) saturate(170%)}
#status{grid-column:1/-1;margin:0 0 8px;color:var(--muted);font-size:13px;font-weight:500;line-height:1.35;text-align:center}
#status:empty{margin:0}
#status.ok{color:var(--ok-fg);font-size:15px;font-weight:650}
#status.err{color:var(--err)}
button{display:flex;align-items:center;justify-content:center;gap:8px;min-height:42px;padding:0 12px;border:0;border-radius:9px;font:600 14.5px/1.2 var(--sans);letter-spacing:-.01em;white-space:nowrap;cursor:pointer;touch-action:manipulation}
button:disabled{opacity:.45;cursor:default}
#none{border:1px solid var(--line);background:var(--surface);color:var(--fg)}
#send{background:var(--accent);color:var(--on-accent)}
#send b{display:grid;place-items:center;min-width:19px;height:19px;padding:0 5px;border-radius:10px;background:color-mix(in srgb,var(--on-accent) 22%,transparent);font-size:12px;font-weight:600}
</style>
</head>
<body>
<main>
{{PLAN}}
</main>
<div id="end"><section>
<label for="general">General comment</label>
<textarea id="general" rows="3" placeholder="About the plan as a whole"></textarea>
</section></div>
<div id="bar">
<p id="status" role="status"></p>
<button id="none">No comments</button>
<button id="send" disabled>Send <b id="count">0</b> <span id="noun">comments</span></button>
</div>
<script nonce="{{NONCE}}">
(() => {
  const TOKEN = "{{TOKEN}}";
  const $ = (id) => document.getElementById(id);
  const general = $("general"), send = $("send"), none = $("none"), status = $("status");
  const count = $("count"), noun = $("noun");
  const notes = new Map(); // line -> {el, box, ta}
  let sent = false;

  const filled = () => [...notes.values()].map((n) => n.ta).concat(general).filter((t) => t.value.trim());
  function update() {
    const n = filled().length;
    count.textContent = n;
    noun.textContent = n === 1 ? "comment" : "comments";
    send.disabled = n === 0;
    none.disabled = n > 0; // "No comments" must not throw typed text away
  }
  general.addEventListener("input", update);

  function makeBox(el, ta) {
    let box;
    if (el.tagName === "TR") {
      box = document.createElement("tr");
      box.appendChild(document.createElement("td")).colSpan = Math.max(el.cells.length, 1);
      box.firstChild.appendChild(ta);
    } else {
      box = document.createElement(el.tagName === "LI" ? "li" : "div");
      box.appendChild(ta);
    }
    box.className = "cbox";
    el.after(box);
    return box;
  }
  function toggle(el) {
    const line = Number(el.dataset.line), old = notes.get(line);
    if (old && old.ta.value.trim()) return old.ta.focus();
    if (old) {
      old.box.remove();
      el.classList.remove("open");
      notes.delete(line);
      return update();
    }
    const ta = document.createElement("textarea");
    ta.rows = 3;
    ta.placeholder = "Comment on this block";
    ta.addEventListener("input", update);
    notes.set(line, {el, ta, box: makeBox(el, ta)});
    el.classList.add("open");
    ta.focus();
  }
  document.addEventListener("click", (e) => {
    if (sent || e.target.closest(".cbox")) return;
    const el = e.target.closest("[data-line]");
    if (el) toggle(el);
  });

  function busy(on) {
    const n = filled().length;
    send.disabled = on || n === 0;
    none.disabled = on || n > 0;
  }
  async function submit(withComments) {
    const comments = [];
    if (withComments) {
      for (const [line, n] of notes) comments.push({line, text: n.ta.value});
      comments.push({line: null, text: general.value});
    }
    busy(true);
    status.className = "";
    status.textContent = "Sending…";
    try {
      const r = await fetch("/submit", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({token: TOKEN, comments}),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw Object.assign(new Error(j.error || "HTTP " + r.status), {status: r.status});
      sent = true;
      document.querySelectorAll("textarea").forEach((t) => (t.disabled = true));
      send.disabled = none.disabled = true;
      status.className = "ok";
      status.textContent = "Received ✓";
    } catch (e) {
      busy(false);
      status.className = "err";
      // A refused (403) page is stale, so retrying cannot work and the server's text says what to do.
      const retry = e.status === 403 ? "" : ". Your text is still here; try again.";
      status.textContent = "Not sent: " + e.message + retry;
    }
  }
  send.addEventListener("click", () => submit(true));
  none.addEventListener("click", () => submit(false));
})();
</script>
</body>
</html>
"""


class Review:
    """State of the one review: the page, the secrets guarding it, and its single outcome."""

    def __init__(self, plan: Plan, parent: int) -> None:
        self.plan = plan
        self.parent = parent
        self.token = secrets.token_hex(16)
        self.nonce = secrets.token_hex(16)
        values = {
            "TITLE": html.escape(plan.title),
            "PLAN": plan.html,
            "NONCE": self.nonce,
            "TOKEN": self.token,
        }
        # One pass, so nothing inside the plan text is ever treated as a placeholder.
        self.page = re.sub(r"\{\{(\w+)\}\}", lambda m: values[m[1]], PAGE).encode()
        self.csp = CSP.format(nonce=self.nonce)
        self.lock = threading.Lock()
        self.done = threading.Event()
        self.comments: list[Comment] | None = None

    def accept(self, comments: list[Comment]) -> bool:
        with self.lock:
            # An abandoned review must never take an answer nobody will read.
            if self.comments is not None or os.getppid() != self.parent:
                return False
            self.comments = comments
            return True


def check_submission(raw: bytes, token: str, lines: set[int]) -> tuple[int, str, list[Comment]]:
    """Validate a browser submission; the status is 200 when the comments are usable."""
    try:
        body = json.loads(raw)
    except (ValueError, RecursionError):
        return 400, "the request body is not JSON", []
    if not isinstance(body, dict):
        return 400, "the request body must be an object", []
    sent = body.get("token")
    if not isinstance(sent, str) or not hmac.compare_digest(sent.encode(), token.encode()):
        return 403, "this page is from an earlier review; reload it to see the current plan", []
    items = body.get("comments")
    if not isinstance(items, list):
        return 400, "comments must be a list", []
    comments: list[Comment] = []
    for item in items:
        line = item.get("line") if isinstance(item, dict) else 0
        text = item.get("text") if isinstance(item, dict) else None
        if not isinstance(text, str) or not (line is None or (type(line) is int and line in lines)):
            return 400, "a comment has no text or points at an unknown line", []
        if text.strip():
            comments.append((line, text.strip()))
    return 200, "", comments


def render(name: str, plan: Plan, comments: list[Comment]) -> str:
    blocks: list[str] = []
    for line, text in sorted(comments, key=lambda c: (c[0] is None, c[0] or 0)):
        if line is None:
            blocks.append(f"## {name} (file-level)\n{text}")
        else:
            quote = f"> {plan.quotes[line]}".rstrip()
            blocks.append(f"## {name}:{line} ( )\n{quote}\n{text}")
    return "\n\n".join(blocks)


class Handler(BaseHTTPRequestHandler):
    server: ReviewServer
    timeout = 10  # drop connections that stall mid-request

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def reply(self, status: int, body: bytes, content_type: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def reply_json(self, status: int, payload: dict[str, Any]) -> None:
        self.reply(status, json.dumps(payload).encode(), "application/json")

    def host_refused(self) -> bool:
        """Answer 403 and return True unless the Host header names this machine."""
        host = (self.headers.get("Host") or "").strip()
        if HOST_RE.fullmatch(host):
            return False
        shown = repr(host[:80])[1:-1]
        message = f'refused: this page only answers on 127.0.0.1 or localhost (got host "{shown}")'
        self.reply(403, message.encode(), "text/plain; charset=utf-8")
        return True

    def do_GET(self) -> None:
        if self.host_refused():
            return
        review = self.server.review
        if urlsplit(self.path).path != "/":
            self.reply_json(404, {"error": "not found"})
            return
        self.reply(200, review.page, "text/html; charset=utf-8", {"Content-Security-Policy": review.csp})

    def do_POST(self) -> None:
        if self.host_refused():
            return
        review = self.server.review
        if urlsplit(self.path).path != "/submit":
            self.reply_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY:
            self.reply_json(400, {"error": "missing or oversized request body"})
            return
        status, message, comments = check_submission(self.rfile.read(length), review.token, set(review.plan.quotes))
        if status == 200 and not review.accept(comments):
            status, message = 409, "this review is closed"
        if status != 200:
            self.reply_json(status, {"error": message})
            return
        try:
            self.reply_json(200, {"ok": True})
        finally:
            # Finish only after the reply is out, so the page can show "Received".
            review.done.set()


class ReviewServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    # Reviews follow each other on one port; do not wait out the last one's TIME_WAIT.
    # A port that something is still listening on stays busy.
    allow_reuse_address = True

    def __init__(self, review: Review, port: int) -> None:
        super().__init__(("127.0.0.1", port), Handler)
        self.review = review


def configured_port(environ: Mapping[str, str]) -> int:
    """The port to serve on: WEB_PLAN_PORT, else the fixed default; 0 means any free port."""
    raw = environ.get("WEB_PLAN_PORT")
    if raw is None:
        return DEFAULT_PORT
    if not re.fullmatch(r"[0-9]{1,5}", raw) or int(raw) > 65535:
        raise ValueError(f"WEB_PLAN_PORT must be a whole number from 0 to 65535, not {raw!r}")
    return int(raw)


def listed_ports(raw: bytes) -> set[int]:
    try:
        servers = json.loads(raw)["servers"]
        return {s["port"] for s in servers if isinstance(s, dict) and isinstance(s.get("port"), int)}
    except (ValueError, KeyError, TypeError):
        return set()


def moshi_problem(port: int) -> str | None:
    """Return why Moshi's Browser Preview cannot list this server, or None when it can."""
    try:
        result = subprocess.run(
            ["moshi-hook", "servers"],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=20,
            check=False,
        )
    except FileNotFoundError:
        return "moshi-hook is not on PATH, so the review page would not show up in Moshi"
    except (OSError, subprocess.SubprocessError) as exc:
        return f"moshi-hook servers could not run: {exc}"
    if result.returncode != 0:
        return f"moshi-hook servers exited with status {result.returncode}"
    if port not in listed_ports(result.stdout):
        return f"moshi-hook servers did not list port {port}"
    return None


def abandon_when_orphaned(parent: int) -> None:
    # The hook that started us can be killed without cleanup; nobody would
    # ever read this review, so leave instead of serving forever.
    while os.getppid() == parent:
        time.sleep(1)
    print("web-plan-review: the parent process is gone; review abandoned", file=sys.stderr, flush=True)
    os._exit(1)


def parse_args(argv: list[str]) -> Path:
    parser = argparse.ArgumentParser(
        prog="web-plan-review.py",
        usage="web-plan-review.py --only=FILE | --compare-old=OLD --compare-new=NEW",
        add_help=False,  # a help text on stdout with exit 0 would read as "no comments"
        allow_abbrev=False,
    )
    parser.add_argument("--only")
    parser.add_argument("--compare-old")
    parser.add_argument("--compare-new")
    args = parser.parse_args(argv)
    if args.only is not None and args.compare_old is None and args.compare_new is None:
        return Path(args.only)
    if args.only is None and args.compare_old is not None and args.compare_new is not None:
        return Path(args.compare_new)  # marking changes against OLD is deferred
    parser.error("use --only=FILE or --compare-old=OLD --compare-new=NEW")


def fail(message: str) -> int:
    print(f"web-plan-review: {message}", file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    path = parse_args(argv)
    try:
        wanted_port = configured_port(os.environ)
    except ValueError as exc:
        return fail(str(exc))
    parent = os.getppid()
    threading.Thread(target=abandon_when_orphaned, args=(parent,), daemon=True).start()
    try:
        source = path.read_bytes().decode("utf-8", "replace")
    except OSError as exc:
        return fail(f"cannot read {path}: {exc.strerror or exc}")
    if not source.strip():
        return fail(f"{path} is empty")
    plan = parse_plan(source)
    review = Review(plan, parent)
    try:
        server = ReviewServer(review, wanted_port)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            return fail(f"port {wanted_port} is in use; another plan review may be open")
        return fail(f"cannot bind a local port: {exc.strerror or exc}")
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
    print(f"web-plan-review: serving http://127.0.0.1:{port}/", file=sys.stderr, flush=True)

    # Moshi probes the page while listing, so the server must already be answering.
    problem = moshi_problem(port)
    if problem:
        return fail(problem)
    review.done.wait()
    server.shutdown()
    server.server_close()
    if not review.comments:
        return 0
    sys.stdout.buffer.write(render(path.name, plan, review.comments).encode("utf-8", "replace") + b"\n")
    sys.stdout.buffer.flush()
    return 10


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
