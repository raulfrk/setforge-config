#!/usr/bin/env python3
"""webdiff hub — ONE persistent server for ALL sessions. Each page is a subpath
(/p/<id>); a sticky tab bar switches between pages; each page has its own
annotations + Submit flag (so the agent polls /submitted?id=<id> and auto-resumes).

Pages live as <id>.html in $WEBDIFF_DIR/pages (default ~/.local/share/webdiff).
State (annotations-<id>.json, submit-<id>.json) lives in $WEBDIFF_DIR/state.
Drop a new page file in pages/ and it appears as a tab automatically.

Usage: python3 serve_webdiff.py [port] [host]   (defaults: 8730, tailscale ip)
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.environ.get("WEBDIFF_DIR") or os.path.expanduser("~/.local/share/webdiff")
PAGES = os.path.join(ROOT, "pages")
STATE = os.path.join(ROOT, "state")
os.makedirs(PAGES, exist_ok=True)
os.makedirs(STATE, exist_ok=True)
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8730
_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _tailscale_ip() -> str:
    try:
        out = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5).stdout.strip().splitlines()
        if out and out[0].strip():
            return out[0].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "127.0.0.1"


HOST = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("WEB_MOCKUP_HOST") or _tailscale_ip()


def _pages() -> list[dict]:
    items = []
    for fn in os.listdir(PAGES):
        if not fn.endswith(".html"):
            continue
        pid = fn[:-5]
        path = os.path.join(PAGES, fn)
        title = pid
        try:
            head = open(path, encoding="utf-8").read(4000)
            m = re.search(r"<title>(.*?)</title>", head, re.S)
            if m:
                title = re.sub(r"\s+", " ", m.group(1)).strip()
        except OSError:
            pass
        items.append({"id": pid, "title": title, "mtime": os.path.getmtime(path)})
    items.sort(key=lambda x: x["mtime"])
    return items


def _load(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save(path: str, obj) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _anno(pid: str) -> str:
    return os.path.join(STATE, f"annotations-{pid}.json")


def _sub(pid: str) -> str:
    return os.path.join(STATE, f"submit-{pid}.json")


def runtime(pid: str, mtime: float) -> str:
    return """
<style>
body{padding-top:54px}
#wd-tabs{position:fixed;top:0;left:0;right:0;z-index:10000;background:#1a1b26;border-bottom:1px solid #3b4261;display:flex;align-items:center;gap:8px;padding:7px 10px}
#wd-tablist{flex:1 1 auto;display:flex;gap:6px;overflow-x:auto;white-space:nowrap}
#wd-tabs .tab{flex:0 0 auto;max-width:160px;overflow:hidden;text-overflow:ellipsis;color:#9aa5ce;text-decoration:none;font:13px sans-serif;padding:7px 11px;border-radius:8px;border:1px solid transparent}
#wd-tabs .tab:hover{background:#24283b}
#wd-tabs .tab.active{background:#24283b;color:#7aa2f7;border-color:#3b4261;font-weight:700}
#wd-tabs #wd-submit{flex:0 0 auto;background:#9ece6a;color:#16161e;border:0;border-radius:8px;padding:8px 14px;font:13px sans-serif;font-weight:700;cursor:pointer;min-height:38px}
#wd-tabs #wd-submit:disabled{background:#2c3a2a;color:#9ece6a}
#wd-tabs .ct{flex:0 0 auto;color:#9aa5ce;font:12px sans-serif;padding:0 4px}
#wd-tabs #wd-master{flex:0 0 auto;background:#24283b;color:#7aa2f7;border:1px solid #3b4261;border-radius:8px;padding:8px 12px;font:13px sans-serif;font-weight:700;cursor:pointer;min-height:38px}
#wd-mbox{display:none;position:fixed;top:53px;left:0;right:0;z-index:9999;background:#1c2333;border-bottom:1px solid #3b4261;padding:10px 12px;box-shadow:0 6px 16px #0007}
#wd-mbox textarea{width:100%;min-height:64px;background:#16161e;color:#c0caf5;border:1px solid #3b4261;border-radius:8px;padding:10px;font:16px sans-serif}
#wd-mbox .b{margin-top:8px;display:flex;gap:8px}
#wd-mbox button{background:#7aa2f7;color:#16161e;border:0;border-radius:8px;padding:9px 16px;font:14px sans-serif;font-weight:600;cursor:pointer;min-height:40px}
#wd-mbox button.cancel{background:#24283b;color:#9aa5ce}
.annobar{margin-top:14px;padding-top:12px;border-top:1px dashed #3b4261}
.annobar button.add{background:#24283b;color:#7aa2f7;border:1px solid #3b4261;border-radius:8px;padding:9px 14px;cursor:pointer;font:14px sans-serif;min-height:40px}
.annobox{display:none;margin-top:10px}
.annobox textarea{width:100%;min-height:72px;background:#16161e;color:#c0caf5;border:1px solid #3b4261;border-radius:8px;padding:11px;font:16px sans-serif}
.annobox .b{margin-top:8px;display:flex;gap:8px;flex-wrap:wrap}
.annobox button{background:#7aa2f7;color:#16161e;border:0;border-radius:8px;padding:10px 18px;cursor:pointer;font:14px sans-serif;font-weight:600;min-height:40px}
.annobox button.cancel{background:#24283b;color:#9aa5ce}
.anno{background:#1c2333;border:1px solid #3b4261;border-left:3px solid #e0af68;border-radius:7px;padding:9px 12px;font:14px sans-serif;color:#c0caf5;margin-top:6px}
.anno .meta{color:#565f89;font-size:11px;margin-top:3px}
.anno button.dismiss{float:right;background:none;border:0;color:#f7768e;font-size:18px;line-height:1;cursor:pointer;padding:0 2px;margin-left:8px}
</style>
<div id="wd-tabs"></div>
<div id="wd-mbox"><div id="wd-mlist"></div><textarea placeholder="Note for this whole page"></textarea><div class="b"><button class="msave">Save note</button><button class="cancel">Cancel</button></div></div>
<script>
window.__PID__=%PID%;
window.__MTIME__=%MTIME%;
async function wdTabs(){
  let pages=[]; try{pages=await(await fetch('/pages')).json();}catch(e){}
  let cnt=0; try{cnt=(await(await fetch('/annotations?id='+encodeURIComponent(__PID__))).json()).length;}catch(e){}
  const bar=document.getElementById('wd-tabs'); if(!bar)return; bar.innerHTML='';
  const list=document.createElement('div');list.id='wd-tablist';
  pages.forEach(p=>{const a=document.createElement('a');a.className='tab'+(p.id===__PID__?' active':'');a.href='/p/'+encodeURIComponent(p.id);a.textContent=p.title;a.title=p.title;list.appendChild(a);});
  bar.appendChild(list);
  const ct=document.createElement('span');ct.className='ct';ct.textContent=cnt+' note'+(cnt===1?'':'s');bar.appendChild(ct);
  const mb=document.createElement('button');mb.id='wd-master';mb.textContent='\\u{1F4AC} Note';
  mb.onclick=()=>{const x=document.getElementById('wd-mbox');x.style.display=x.style.display==='block'?'none':'block';if(x.style.display==='block')x.querySelector('textarea').focus();};
  bar.appendChild(mb);
  const sb=document.createElement('button');sb.id='wd-submit';sb.textContent='\\u2713 Submit';
  sb.onclick=async()=>{sb.disabled=true;sb.textContent='\\u23f3 Submitting\\u2026';await fetch('/submit?id='+encodeURIComponent(__PID__),{method:'POST'});wdPoll();};
  bar.appendChild(sb);
}
async function wdLoad(){
  let data=[]; try{data=await(await fetch('/annotations?id='+encodeURIComponent(__PID__))).json();}catch(e){}
  document.querySelectorAll('.annobar').forEach(bar=>{
    const sec=bar.dataset.section||'unlabelled'; bar.innerHTML='';
    const btn=document.createElement('button');btn.className='add';btn.textContent='\\u{1F4AC} Annotate';
    const box=document.createElement('div');box.className='annobox';
    box.innerHTML='<textarea placeholder="Your annotation\\u2026"></textarea><div class="b"><button class="save">Save</button><button class="cancel">Cancel</button></div>';
    const list=document.createElement('div');bar.append(btn,box,list);
    btn.onclick=()=>{box.style.display=box.style.display==='block'?'none':'block';const t=box.querySelector('textarea');if(box.style.display==='block')t.focus();};
    box.querySelector('.cancel').onclick=()=>{box.style.display='none';};
    box.querySelector('.save').onclick=async()=>{const ta=box.querySelector('textarea');const text=ta.value.trim();if(!text)return;
      await fetch('/annotate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:__PID__,section:sec,text})});
      ta.value='';box.style.display='none';wdLoad();wdTabs();};
    data.filter(a=>a.section===sec).forEach(a=>{const d=document.createElement('div');d.className='anno';
      const x=document.createElement('button');x.className='dismiss';x.title='Clear handled';x.textContent='\\u00d7';
      x.onclick=async()=>{await fetch('/resolve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:__PID__,ts:a.ts,section:a.section,text:a.text})});wdLoad();wdTabs();};
      const t=document.createElement('div');t.textContent=a.text;const m=document.createElement('div');m.className='meta';m.textContent=a.ts||'';
      d.append(x,t,m);list.append(d);});
  });
  var ml=document.getElementById('wd-mlist');
  if(ml){ml.innerHTML=''; data.filter(a=>a.section==='\\u2605 page note').forEach(a=>{var d=document.createElement('div');d.className='anno';
    var x=document.createElement('button');x.className='dismiss';x.textContent='\\u00d7';
    x.onclick=async()=>{await fetch('/resolve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:__PID__,ts:a.ts,section:a.section,text:a.text})});wdLoad();wdTabs();};
    var t=document.createElement('div');t.textContent=a.text;d.append(x,t);ml.append(d);});}
}
(function(){var box=document.getElementById('wd-mbox');if(!box)return;
  box.querySelector('.cancel').onclick=function(){box.style.display='none';};
  box.querySelector('.msave').onclick=async function(){var ta=box.querySelector('textarea');var text=ta.value.trim();if(!text)return;
    await fetch('/annotate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:__PID__,section:'\\u2605 page note',text:text})});
    ta.value='';box.style.display='none';wdLoad();wdTabs();};})();
function wdPoll(){
  fetch('/pages').then(r=>r.json()).then(ps=>{var me=ps.find(p=>p.id===__PID__); if(me && me.mtime>__MTIME__+0.001){location.reload();}}).catch(function(){});
  fetch('/submitted?id='+encodeURIComponent(__PID__)).then(r=>r.json()).then(s=>{var sb=document.getElementById('wd-submit'); if(!sb)return;
    if(s.submitted){sb.disabled=true;sb.textContent='\\u23f3 Claude working\\u2026';} else if(sb.textContent.indexOf('Submitting')<0){sb.disabled=false;sb.textContent='\\u2713 Submit';}}).catch(function(){});
}
wdTabs();wdLoad();setInterval(wdPoll,3000);
</script>
""".replace("%PID%", json.dumps(pid)).replace("%MTIME%", json.dumps(mtime))


INDEX = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>webdiff hub</title>
<style>body{background:#16161e;color:#c0caf5;font:15px sans-serif;margin:0;padding:30px}code{color:#7aa2f7}</style></head>
<body><h1>webdiff hub</h1><p>No pages yet. Drop an <code>&lt;id&gt;.html</code> into <code>%PAGES%</code>.</p></body></html>""".replace("%PAGES%", PAGES)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _qs_id(self, u):
        return parse_qs(u.query).get("id", [""])[0]

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        if u.path == "/":
            pages = _pages()
            if pages:
                self.send_response(302)
                self.send_header("Location", "/p/" + pages[-1]["id"])
                self.end_headers()
                return
            self._send(200, INDEX, "text/html; charset=utf-8")
        elif u.path == "/pages":
            self._send(200, json.dumps(_pages()))
        elif u.path.startswith("/p/"):
            pid = u.path[3:]
            if not _ID_RE.match(pid) or not os.path.exists(os.path.join(PAGES, pid + ".html")):
                self._send(404, "no such page", "text/plain")
                return
            ppath = os.path.join(PAGES, pid + ".html")
            html = open(ppath, encoding="utf-8").read()
            rt = runtime(pid, os.path.getmtime(ppath))
            html = html.replace("</body>", rt + "</body>") if "</body>" in html else html + rt
            self._send(200, html, "text/html; charset=utf-8")
        elif u.path == "/annotations":
            self._send(200, json.dumps(_load(_anno(self._qs_id(u)), [])))
        elif u.path == "/submitted":
            self._send(200, json.dumps(_load(_sub(self._qs_id(u)), {"submitted": False})))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):  # noqa: N802
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            d = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            d = {}
        pid = d.get("id") or self._qs_id(u)
        if not pid or not _ID_RE.match(pid):
            self._send(400, json.dumps({"error": "bad id"}))
            return
        if u.path == "/annotate":
            items = _load(_anno(pid), [])
            items.append({"section": str(d.get("section", ""))[:200], "text": str(d.get("text", ""))[:5000],
                          "ts": datetime.datetime.now().isoformat(timespec="seconds")})
            _save(_anno(pid), items)
            self._send(200, json.dumps({"ok": True, "count": len(items)}))
        elif u.path == "/submit":
            _save(_sub(pid), {"submitted": True, "ts": datetime.datetime.now().isoformat(timespec="seconds")})
            self._send(200, json.dumps({"ok": True}))
        elif u.path == "/resolve":
            items = [a for a in _load(_anno(pid), []) if not (
                a.get("ts") == d.get("ts") and a.get("section") == d.get("section") and a.get("text") == d.get("text"))]
            _save(_anno(pid), items)
            self._send(200, json.dumps({"ok": True, "count": len(items)}))
        elif u.path in ("/clear", "/rearm"):
            if u.path == "/clear":
                _save(_anno(pid), [])
            _save(_sub(pid), {"submitted": False})
            self._send(200, json.dumps({"ok": True}))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def log_message(self, *a):
        return


if __name__ == "__main__":
    print(f"webdiff hub at http://{HOST}:{PORT}  (pages: {PAGES})")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
