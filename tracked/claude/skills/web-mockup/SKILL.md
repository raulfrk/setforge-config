---
name: web-mockup
description: Serve a graphical mockup/design/RFC as a web page over the tailnet with persistent inline annotations, for visual back-and-forth review. Use when the user wants to SEE and ANNOTATE something in a browser rather than the terminal — "serve a mockup", "web mockup", "annotate on the web", "show me this as a web page I can annotate", "make it visible on the web with annotations", or any review where colour/diagrams/layout matter and revdiff's text view is not enough. Renders content as a self-contained graphical HTML page, serves it bound to the Tailscale IP, persists annotations to JSON, and reads them back so each can be addressed.
---

# web-mockup — served, annotatable web mockups

A reusable review surface: turn a design / RFC / option-comparison into a **graphical web page**
served over the tailnet, where the user adds **inline annotations per section** that persist
server-side so you can read and address them. The browser complement to revdiff — use it when
**colour, diagrams, swatches, or layout** carry the meaning and a text diff cannot.

## When to use

- The user asks to review a design/mockup/RFC **on the web** or **with annotations** that persist.
- The content is **visual** — colour palettes, UI/flow diagrams, side-by-side option cards, build-order
  graphics — where seeing beats reading.
- You want a **stable, reload-friendly** review loop across turns (vs a one-shot revdiff pass).

Prefer **revdiff** for code diffs and plain prose review; prefer **web-mockup** for graphical artifacts.

## Workflow

1. **Build the mockup HTML** (see "HTML contract" below): self-contained, graphical, no tables. End
   every annotatable section with `<div class="annobar" data-section="UNIQUE · LABEL"></div>`. Do NOT
   add annotation CSS/JS yourself — the server injects it.
2. **Write the server** (the script below, verbatim) and the HTML into a temp dir (e.g. the job tmp dir,
   never `/tmp` directly in a shared/bg session).
3. **Start the server detached** so it survives across turns:
   ```bash
   cd <dir> && setsid nohup python3 serve_mockup.py <page.html> > server.log 2>&1 < /dev/null &
   ```
   It auto-binds to the Tailscale IP. NEVER `pkill -f <pattern>` where the pattern also matches your own
   shell command — it kills the running shell (exit 144). Stop a prior instance by pid from `ss -ltnp`.
4. **Give the user the URL** it prints: `http://<tailscale-ip>:<port>` — reachable from any tailnet
   device (Mac, iPad). If it fell back to `127.0.0.1`, tell them to port-forward (`ssh -N -L`).
5. **Block on Submit, not on the user typing.** The page has a **Submit** button (top bar) that flips a
   server flag. Launch a background poller and end the turn — the click auto-resumes you:
   ```bash
   until curl -s http://<ip>:<port>/submitted | grep -q '"submitted": true'; do sleep 20; done; echo SUBMITTED
   ```
   (OR-in more `curl ... || curl ...` checks to watch several pages.) The user no longer has to say "annotated".
6. **Read annotations**: `curl -s http://<ip>:<port>/annotations` (or `cat annotations.json`) →
   `[{section, text, ts}]`. Work through each section by section; restate + resolve.
7. **Iterate**: edit the HTML file in place (the server serves it live — user just reloads). After
   addressing a batch, **re-arm** the gate: `curl -X POST http://<ip>:<port>/rearm` (resets the submit flag,
   keeps annotations) or `/clear` (also wipes annotations). Re-launch the poller. Tell the user it's refreshed.

## HTML contract

- **Self-contained**: inline `<style>`, no external assets (the VM has no internet/browser).
- **Graphical over prose**: diagrams, cards, flows, colour swatches, funnels, timelines — minimise text.
- **No tables** (hard to scan) — use cards / definition rows / flow boxes instead.
- **Mobile-friendly (required)** — the user reviews on phone/iPad too. Include
  `<meta name="viewport" content="width=device-width, initial-scale=1">`; make every multi-column grid
  and side-by-side layout **collapse to one column under ~760px** (`@media(max-width:760px){…}`); avoid
  fixed pixel widths that force horizontal scroll; keep any interactive control ≥40px tall; use `16px`
  inputs to stop iOS focus-zoom. A sticky sidebar nav must become a top/static bar (or horizontal scroll
  strip) on narrow screens; add `body{overflow-x:hidden}` as a guard. The injected annotation widget is
  already touch-sized. **Put ALL `@media` rules at the END of the stylesheet** (after the base rules) —
  media queries don't raise specificity, so an `@media` rule placed *before* a same-selector base rule
  silently loses the cascade and won't apply. This is the #1 reason a "responsive" page isn't.
- **Number sections** so the user can reference them.
- Each annotatable section ends with exactly: `<div class="annobar" data-section="N · Short Title"></div>`
  (unique `data-section` per section; the server wires a 💬 button + saved-note list onto each).

## The server — write verbatim to `serve_mockup.py`

```python
#!/usr/bin/env python3
"""Serve a graphical HTML mockup over the tailnet with persistent inline annotations.

Usage: python3 serve_mockup.py [page.html] [port] [host]
- page.html : the mockup file (default: index.html beside this script)
- port      : default 8722
- host      : default = `tailscale ip -4` (tailnet-only), else 127.0.0.1
Annotations persist to annotations.json beside this script. The annotation runtime
(CSS + JS) is INJECTED into the served page, so the mockup HTML stays pure content.
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(BASE, sys.argv[1] if len(sys.argv) > 1 else "index.html")
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8722
STORE = os.path.join(BASE, "annotations.json")
SUBMIT = os.path.join(BASE, "submit.json")


def _tailscale_ip() -> str:
    try:
        out = subprocess.run(
            ["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5
        ).stdout.strip().splitlines()
        if out and out[0].strip():
            return out[0].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "127.0.0.1"


def _choose_host() -> str:
    """Pick the bind address. Explicit override wins (3rd CLI arg or WEB_MOCKUP_HOST env);
    else the Tailscale IP if tailscale is up (tailnet-only, safe); else 127.0.0.1 (loopback —
    open directly on the same machine, or SSH-forward from a remote). Pass 0.0.0.0 to expose
    on all interfaces (LAN-reachable — opt-in, trusted networks only)."""
    if len(sys.argv) > 3:
        return sys.argv[3]
    if os.environ.get("WEB_MOCKUP_HOST"):
        return os.environ["WEB_MOCKUP_HOST"]
    return _tailscale_ip()


HOST = _choose_host()

RUNTIME = """
<style>
.annobar{margin-top:14px;padding-top:12px;border-top:1px dashed #3b4261}
.annobar button.add{background:#24283b;color:#7aa2f7;border:1px solid #3b4261;border-radius:8px;padding:9px 14px;cursor:pointer;font:14px sans-serif;min-height:40px}
.annobar button.add:hover{background:#7aa2f7;color:#16161e}
.annobox{display:none;margin-top:10px}
.annobox textarea{width:100%;min-height:72px;background:#16161e;color:#c0caf5;border:1px solid #3b4261;border-radius:8px;padding:11px;font:16px sans-serif}
.annobox .b{margin-top:8px;display:flex;gap:8px;flex-wrap:wrap}
.annobox button{background:#7aa2f7;color:#16161e;border:0;border-radius:8px;padding:10px 18px;cursor:pointer;font:14px sans-serif;font-weight:600;min-height:40px}
.annobox button.cancel{background:#24283b;color:#9aa5ce}
.anno{background:#1c2333;border:1px solid #3b4261;border-left:3px solid #e0af68;border-radius:7px;padding:9px 12px;font:14px sans-serif;color:#c0caf5;margin-top:6px}
.anno .meta{color:#565f89;font-size:11px;margin-top:3px}
.anno button.dismiss{float:right;background:none;border:0;color:#f7768e;font-size:18px;line-height:1;cursor:pointer;padding:0 2px;margin-left:8px}
#wm-counter{position:fixed;bottom:14px;right:14px;background:#7aa2f7;color:#16161e;font-weight:700;border-radius:999px;padding:9px 15px;box-shadow:0 4px 16px #0008;font:13px sans-serif;z-index:9999}
@media(max-width:600px){#wm-counter{bottom:10px;right:10px;padding:8px 12px;font-size:12px}}
#wm-bar{position:fixed;top:0;left:0;right:0;z-index:9999;background:#1a1b26;border-bottom:1px solid #3b4261;display:flex;gap:10px;align-items:center;padding:8px 14px}
#wm-bar button{background:#9ece6a;color:#16161e;border:0;border-radius:8px;padding:9px 16px;font:14px sans-serif;font-weight:700;cursor:pointer;min-height:40px}
#wm-bar button:disabled{background:#2c3a2a;color:#9ece6a;cursor:default}
</style>
<div id="wm-bar"><button id="wm-submit">&#10003; Submit &mdash; done annotating</button></div>
<div id="wm-counter">0 annotations</div>
<script>
async function wmLoad(){
  let data=[]; try{data=await(await fetch('/annotations')).json();}catch(e){}
  document.querySelectorAll('.annobar').forEach(bar=>{
    const sec=bar.dataset.section||bar.getAttribute('data-section')||'unlabelled';
    bar.innerHTML='';
    const btn=document.createElement('button');btn.className='add';btn.textContent='\\u{1F4AC} Annotate this section';
    const box=document.createElement('div');box.className='annobox';
    box.innerHTML='<textarea placeholder="Your annotation\\u2026"></textarea><div class="b"><button class="save">Save</button><button class="cancel">Cancel</button></div>';
    const list=document.createElement('div');bar.append(btn,box,list);
    btn.onclick=()=>{box.style.display=box.style.display==='block'?'none':'block';const t=box.querySelector('textarea');if(box.style.display==='block')t.focus();};
    box.querySelector('.cancel').onclick=()=>{box.style.display='none';};
    box.querySelector('.save').onclick=async()=>{const ta=box.querySelector('textarea');const text=ta.value.trim();if(!text)return;
      await fetch('/annotate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({section:sec,text})});
      ta.value='';box.style.display='none';wmLoad();};
    data.filter(a=>a.section===sec).forEach(a=>{const d=document.createElement('div');d.className='anno';
      const x=document.createElement('button');x.className='dismiss';x.title='Clear handled';x.textContent='\\u00d7';
      x.onclick=async()=>{await fetch('/resolve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ts:a.ts,section:a.section,text:a.text})});wmLoad();};
      const t=document.createElement('div');t.textContent=a.text;const m=document.createElement('div');m.className='meta';m.textContent=a.ts||'';
      d.append(x,t,m);list.append(d);});
  });
  const c=document.getElementById('wm-counter');if(c)c.textContent=data.length+' annotation'+(data.length===1?'':'s');
  document.body.style.paddingTop='52px';
}
const _sb=document.getElementById('wm-submit');
if(_sb)_sb.onclick=async()=>{await fetch('/submit',{method:'POST'});_sb.disabled=true;_sb.textContent='\\u2713 Submitted \\u2014 Claude is resuming\\u2026';};
wmLoad();
</script>
"""


def load() -> list[dict]:
    try:
        with open(STORE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save(items: list[dict]) -> None:
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)
    os.replace(tmp, STORE)


def load_submit() -> dict:
    try:
        with open(SUBMIT, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"submitted": False}


def save_submit(obj: dict) -> None:
    tmp = SUBMIT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    os.replace(tmp, SUBMIT)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body, ctype: str = "application/json") -> None:
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            try:
                with open(PAGE, encoding="utf-8") as f:
                    html = f.read()
            except FileNotFoundError:
                self._send(500, json.dumps({"error": "page missing"}))
                return
            html = html.replace("</body>", RUNTIME + "</body>") if "</body>" in html else html + RUNTIME
            self._send(200, html, "text/html; charset=utf-8")
        elif self.path == "/annotations":
            self._send(200, json.dumps(load()))
        elif self.path == "/submitted":
            self._send(200, json.dumps(load_submit()))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self) -> None:  # noqa: N802
        n = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(n) if n else b"{}"
        if self.path == "/annotate":
            try:
                d = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                self._send(400, json.dumps({"error": "bad json"}))
                return
            items = load()
            items.append(
                {
                    "section": str(d.get("section", ""))[:200],
                    "text": str(d.get("text", ""))[:5000],
                    "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                }
            )
            save(items)
            self._send(200, json.dumps({"ok": True, "count": len(items)}))
        elif self.path == "/submit":
            save_submit({"submitted": True, "ts": datetime.datetime.now().isoformat(timespec="seconds")})
            self._send(200, json.dumps({"ok": True}))
        elif self.path == "/resolve":
            try:
                d = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                self._send(400, json.dumps({"error": "bad json"}))
                return
            items = [a for a in load() if not (
                a.get("ts") == d.get("ts") and a.get("section") == d.get("section") and a.get("text") == d.get("text"))]
            save(items)
            self._send(200, json.dumps({"ok": True, "count": len(items)}))
        elif self.path in ("/clear", "/rearm"):
            if self.path == "/clear":
                save([])
            save_submit({"submitted": False})
            self._send(200, json.dumps({"ok": True}))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def log_message(self, *args) -> None:
        return


if __name__ == "__main__":
    if HOST == "127.0.0.1":
        how = f"open http://127.0.0.1:{PORT} directly (same machine), or SSH-forward the port"
    elif HOST == "0.0.0.0":
        how = f"reachable on the LAN at http://<this-host-ip>:{PORT} from any device"
    else:
        how = f"open http://{HOST}:{PORT}"
    print(f"web-mockup serving (page: {os.path.basename(PAGE)}) — {how}")
    print(f"annotations persist to: {STORE}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
```

## Notes

- **Choosing the bind (how the user reaches it).** The server prints the right access line for whatever
  it bound. Three cases:
  - **Same machine with a browser** (e.g. running on a laptop): no override needed — with no Tailscale it
    binds `127.0.0.1`; just open `http://127.0.0.1:<port>` **directly**, no forwarding.
  - **Remote + Tailscale** (headless VM): auto-binds the Tailscale IP — open from any tailnet device
    (Mac, iPad). Tailnet-only; no public exposure, no forwarding.
  - **Remote, no Tailscale:** either SSH-forward (`ssh -N -L <port>:127.0.0.1:<port> <host>`), **or** run
    with `0.0.0.0` to expose on the LAN — opt-in, trusted networks only.
  - **Override always wins:** `python3 serve_mockup.py page.html 8722 0.0.0.0`, or `WEB_MOCKUP_HOST=<ip>`.
- **Persistence.** `annotations.json` survives reloads and server restarts; safe to stop/restart the
  server while iterating on the HTML.
- **Detached run.** Always `setsid nohup … &` so the server outlives the turn. Health-check with
  `curl -s -o /dev/null -w '%{http_code}' http://<ip>:<port>/`.
- **One page per server** (per port). To review several artifacts at once, run on different ports.
- **Touch / mobile caveat.** The annotation widget is touch-friendly. Native HTML5 drag-and-drop does
  **not** work on touch (iPad/phone) — if a page needs reordering, add tap controls (▲/▼ buttons) as a
  touch fallback, or tell the user that drag-drop needs a desktop browser.
- **Self-improvement.** If this skill ever needs more (multi-page, auth, export annotations to a file),
  capture the observation and propose a diff at a checkpoint — never expand it mid-task.
