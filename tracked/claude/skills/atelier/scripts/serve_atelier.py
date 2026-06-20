#!/usr/bin/env python3
"""atelier hub — ONE persistent server for ALL sessions. Each page is a subpath
(/p/<id>); a sticky tab bar switches between pages; each page has its own
annotations + Submit flag (so the agent polls /submitted?id=<id> and auto-resumes).

Pages live as <id>.html in $ATELIER_DIR/pages (default ~/.local/share/atelier).
State (annotations-<id>.json, submit-<id>.json) lives in $ATELIER_DIR/state.
($WEBDIFF_DIR / $WEB_MOCKUP_HOST are still read as back-compat aliases for one cycle.)
Drop a new page file in pages/ and it appears as a tab automatically.

Usage: python3 serve_atelier.py [port] [host]   (defaults: 8730, tailscale ip)
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from annotation_format import from_atelier as _to_revdiff_md  # unified revdiff '## file:line (type)' format
except Exception:
    _to_revdiff_md = None

_CV = threading.Condition()  # notified on every /submit — powers the /wait long-poll
_STATE_LOCK = threading.Lock()  # guards read-modify-write of per-page state files

ROOT = (os.environ.get("ATELIER_DIR") or os.environ.get("WEBDIFF_DIR")  # WEBDIFF_DIR: back-compat alias
        or os.path.expanduser("~/.local/share/atelier"))
PAGES = os.path.join(ROOT, "pages")
STATE = os.path.join(ROOT, "state")
ARCHIVE = os.path.join(ROOT, "archive")
os.makedirs(PAGES, exist_ok=True)
os.makedirs(STATE, exist_ok=True)
os.makedirs(ARCHIVE, exist_ok=True)
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


HOST = sys.argv[2] if len(sys.argv) > 2 else (
    os.environ.get("ATELIER_HOST") or os.environ.get("WEB_MOCKUP_HOST")  # WEB_MOCKUP_HOST: back-compat
    or _tailscale_ip())


def _list(dirpath: str) -> list[dict]:
    items = []
    for fn in os.listdir(dirpath):
        if not fn.endswith(".html"):
            continue
        pid = fn[:-5]
        path = os.path.join(dirpath, fn)
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


def _pages() -> list[dict]:
    return _list(PAGES)


def _archived() -> list[dict]:
    return list(reversed(_list(ARCHIVE)))  # most-recently-closed first


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


def _rev(pid: str) -> str:
    return os.path.join(STATE, f"reviewed-{pid}.json")


_SECID_RE = re.compile(r'data-secid="([^"]+)"')


def _live_secids(pid: str) -> set[str]:
    """The data-secid set actually present in the page right now. Used to prune reviewed
    entries for sections that a regeneration removed (so reviewed-<id>.json never accrues
    orphans, and close-gating counts only live sections)."""
    try:
        with open(os.path.join(PAGES, pid + ".html"), encoding="utf-8") as f:
            return {html_unescape(m) for m in _SECID_RE.findall(f.read())}
    except OSError:
        return set()


def html_unescape(s: str) -> str:
    return s.replace("&quot;", '"').replace("&#x27;", "'").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def _state(pid: str) -> str:
    """Normalized submit state: idle | submitted | working.

    Back-compat: legacy files held {submitted: bool}; map true->submitted, else idle.
    """
    d = _load(_sub(pid), {})
    if isinstance(d, dict):
        s = d.get("state")
        if s in ("idle", "submitted", "working"):
            return s
        if d.get("submitted"):
            return "submitted"
    return "idle"


def _set_state(pid: str, st: str) -> None:
    _save(_sub(pid), {"state": st, "ts": datetime.datetime.now().isoformat(timespec="seconds")})


def runtime(pid: str, mtime: float) -> str:
    return """
<style>
body{padding-top:54px}
#wd-tabs{position:fixed;top:0;left:0;right:0;z-index:10000;background:#1a1b26;border-bottom:1px solid #3b4261;display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:7px 10px}
#wd-tablist{flex:1 1 220px;min-width:0;display:flex;gap:6px;overflow-x:auto;white-space:nowrap}
#wd-tabs .tab{flex:0 0 auto;max-width:160px;overflow:hidden;text-overflow:ellipsis;color:#9aa5ce;text-decoration:none;font:13px sans-serif;padding:7px 11px;border-radius:8px;border:1px solid transparent}
#wd-tabs .tab:hover{background:#24283b}
#wd-tabs .tab.active{background:#24283b;color:#7aa2f7;border-color:#3b4261;font-weight:700}
#wd-tabs #wd-submit{flex:0 0 auto;background:#9ece6a;color:#16161e;border:0;border-radius:8px;padding:8px 14px;font:13px sans-serif;font-weight:700;cursor:pointer;min-height:38px}
#wd-tabs #wd-submit:disabled{background:#2c3a2a;color:#9ece6a}
#wd-tabs #wd-close{flex:0 0 auto;background:#7aa2f7;color:#16161e;border:0;border-radius:8px;padding:8px 12px;font:13px sans-serif;font-weight:700;cursor:pointer;min-height:38px}
#wd-tabs #wd-close:disabled{background:#26304a;color:#7aa2f7}
#wd-tabs .ct{flex:0 0 auto;color:#9aa5ce;font:12px sans-serif;padding:0 4px}
#wd-tabs #wd-master{flex:0 0 auto;background:#24283b;color:#7aa2f7;border:1px solid #3b4261;border-radius:8px;padding:8px 12px;font:13px sans-serif;font-weight:700;cursor:pointer;min-height:38px}
#wd-tabs #wd-hide{flex:0 0 auto;background:#24283b;color:#9aa5ce;border:1px solid #3b4261;border-radius:8px;padding:8px 12px;font:13px sans-serif;font-weight:700;cursor:pointer;min-height:38px}
/* hide-annotation-chrome toggle (persisted): pristine design view — content only, no review UI */
body.atelier-hide-anno .annobar,body.atelier-hide-anno #wd-map,body.atelier-hide-anno #wd-master,body.atelier-hide-anno #wd-mbox{display:none!important}
#wd-mbox{display:none;position:fixed;top:53px;left:0;right:0;z-index:9999;background:#1c2333;border-bottom:1px solid #3b4261;padding:10px 12px;box-shadow:0 6px 16px #0007}
#wd-mbox textarea{width:100%;min-height:64px;background:#16161e;color:#c0caf5;border:1px solid #3b4261;border-radius:8px;padding:10px;font:16px sans-serif}
#wd-mbox .b{margin-top:8px;display:flex;gap:8px}
#wd-mbox button{background:#7aa2f7;color:#16161e;border:0;border-radius:8px;padding:9px 16px;font:14px sans-serif;font-weight:600;cursor:pointer;min-height:40px}
#wd-mbox button.cancel{background:#24283b;color:#9aa5ce}
.annobar{margin-top:14px;padding-top:12px;border-top:1px dashed #3b4261;display:flex;flex-wrap:wrap;gap:8px;align-items:flex-start}
.annobar .annobox,.annobar>div:last-child{flex-basis:100%}
.annobar button.add{background:#24283b;color:#7aa2f7;border:1px solid #3b4261;border-radius:8px;padding:9px 14px;cursor:pointer;font:14px sans-serif;min-height:40px}
.annobar button.rvw{background:#24283b;color:#9aa5ce;border:1px solid #3b4261;border-radius:8px;padding:9px 14px;cursor:pointer;font:14px sans-serif;font-weight:700;min-height:40px}
.annobar button.rvw.on{background:#1e3a23;color:#9ece6a;border-color:#9ece6a}
.annobar button.rvw.stale{background:#3a2f1a;color:#e0af68;border-color:#e0af68}
.seam:has(.annobar .rvw.on){border-color:#9ece6a55}
.seam:has(.annobar .rvw.stale){border-color:#e0af6855}
#wd-map{position:sticky;z-index:50;background:#1a1b26;border:1px solid #3b4261;border-radius:10px;padding:8px 10px;margin:0 0 14px}
#wd-map .wd-map-h{color:#9aa5ce;font:12px sans-serif;font-weight:700;margin-bottom:6px}
#wd-map .wd-map-row{display:flex;flex-wrap:wrap;gap:6px}
#wd-map a.wd-dot{display:inline-flex;align-items:center;gap:5px;max-width:230px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#9aa5ce;text-decoration:none;font:12px sans-serif;background:#24283b;border:1px solid #3b4261;border-radius:20px;padding:4px 10px;min-height:30px}
#wd-map a.wd-dot i{flex:0 0 auto;width:9px;height:9px;border-radius:50%;background:#565f89}
#wd-map a.wd-dot.done i{background:#9ece6a} #wd-map a.wd-dot.stale i{background:#e0af68}
#wd-map a.wd-dot:hover{border-color:#7aa2f7;color:#c0caf5}
.annobox{display:none;margin-top:10px}
.annobox textarea{width:100%;min-height:72px;background:#16161e;color:#c0caf5;border:1px solid #3b4261;border-radius:8px;padding:11px;font:16px sans-serif}
.annobox .b{margin-top:8px;display:flex;gap:8px;flex-wrap:wrap}
.annobox button{background:#7aa2f7;color:#16161e;border:0;border-radius:8px;padding:10px 18px;cursor:pointer;font:14px sans-serif;font-weight:600;min-height:40px}
.annobox button.cancel{background:#24283b;color:#9aa5ce}
.anno{background:#1c2333;border:1px solid #3b4261;border-left:3px solid #e0af68;border-radius:7px;padding:9px 12px;font:14px sans-serif;color:#c0caf5;margin-top:6px}
.anno .meta{color:#565f89;font-size:11px;margin-top:3px}
.anno button.dismiss{float:right;background:none;border:0;color:#f7768e;font-size:18px;line-height:1;cursor:pointer;padding:0 2px;margin-left:8px}
#wd-working{position:fixed;inset:0;z-index:9990;background:rgba(22,22,30,.95);display:none;flex-direction:column;align-items:center;justify-content:center;gap:14px;text-align:center;padding:24px}
/* z-index 9990 keeps the working overlay BELOW the tab bar (10000) so you can switch tabs while a page works */
#wd-working.on{display:flex}
#wd-working .bn{font-size:50px;animation:wdbnc 1s infinite ease-in-out}
@keyframes wdbnc{0%,100%{transform:translateY(0)}50%{transform:translateY(-18px)}}
#wd-working .dots{display:flex;gap:8px}#wd-working .dots i{width:11px;height:11px;border-radius:50%;background:#7aa2f7;animation:wdbnc 1.2s infinite ease-in-out}
#wd-working .dots i:nth-child(2){animation-delay:.15s}#wd-working .dots i:nth-child(3){animation-delay:.3s}
#wd-working .t{color:#fff;font:18px sans-serif;font-weight:700}#wd-working .s{color:#9aa5ce;font:13px sans-serif;max-width:340px;line-height:1.5}
#wd-working .dz{margin-top:6px;background:#24283b;color:#9aa5ce;border:1px solid #3b4261;border-radius:7px;padding:6px 12px;font:12px sans-serif;cursor:pointer}
</style>
<div id="wd-tabs"></div>
<div id="wd-mbox"><div id="wd-mlist"></div><textarea placeholder="Note for this whole page"></textarea><div class="b"><button class="msave">Save note</button><button class="cancel">Cancel</button></div></div>
<div id="wd-working"><div class="bn">&#x1F916;</div><div class="dots"><i></i><i></i><i></i></div><div class="t">Claude is working&hellip;</div><div class="s">Your submit was received. This page holds until Claude finishes and re-arms, then refreshes to the updated review &mdash; no stale content.</div><button class="dz" id="wd-dismiss">Dismiss</button></div>
<script>
window.__PID__=%PID%;
window.__MTIME__=%MTIME%;
// apply the persisted hide-annotations preference before the runtime populates any chrome (no flash)
(function(){try{if(localStorage.getItem('atelier-hide-anno')==='1')document.body.classList.add('atelier-hide-anno');}catch(e){}})();
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
  const hb=document.createElement('button');hb.id='wd-hide';
  const _hl=()=>{hb.textContent=document.body.classList.contains('atelier-hide-anno')?'\\u270e Show annotations':'\\u{1F441} Hide annotations';};
  hb.onclick=()=>{const on=document.body.classList.toggle('atelier-hide-anno');try{localStorage.setItem('atelier-hide-anno',on?'1':'0');}catch(e){}_hl();};
  _hl();bar.appendChild(hb);
  const sb=document.createElement('button');sb.id='wd-submit';sb.textContent='\\u2713 Submit';
  sb.onclick=async()=>{sb.disabled=true;sb.textContent='\\u23f3 Submitting\\u2026';await fetch('/submit?id='+encodeURIComponent(__PID__),{method:'POST'});wdPoll();};
  bar.appendChild(sb);
  const cb=document.createElement('button');cb.id='wd-close';cb.textContent='Submit & Close';
  cb.onclick=async()=>{cb.disabled=true;cb.textContent='\\u23f3\\u2026';await fetch('/submit?id='+encodeURIComponent(__PID__),{method:'POST'});await fetch('/close?id='+encodeURIComponent(__PID__),{method:'POST'});location.href='/';};
  bar.appendChild(cb);
  var _h=bar.offsetHeight;
  document.body.style.paddingTop=(_h+4)+'px';  // bar may wrap to 2 rows on narrow screens
  var _mb=document.getElementById('wd-mbox'); if(_mb)_mb.style.top=_h+'px';  // note box sits below the (possibly 2-row) bar
  wdGate();  // reflect review state on the freshly-(re)built Submit & Close button
}
async function wdLoad(){
  let data=[]; try{data=await(await fetch('/annotations?id='+encodeURIComponent(__PID__))).json();}catch(e){}
  window.__NCOUNT__=data.length;
  let reviewed={}; try{reviewed=await(await fetch('/reviewed?id='+encodeURIComponent(__PID__))).json();}catch(e){}
  window.__REVIEWED__=reviewed;
  document.querySelectorAll('.annobar').forEach(bar=>{
    const sec=bar.dataset.section||'unlabelled'; bar.innerHTML='';
    const secid=bar.dataset.secid, sechash=bar.dataset.sechash;
    if(secid){
      const stored=reviewed[secid];
      const on=stored!==undefined&&stored===sechash;
      const stale=stored!==undefined&&stored!==sechash;
      const rv=document.createElement('button');rv.className='rvw'+(on?' on':'')+(stale?' stale':'');
      rv.textContent=on?'\\u2713 Reviewed':(stale?'\\u21bb changed since reviewed':'Mark reviewed');
      rv.onclick=async()=>{rv.disabled=true;
        await fetch('/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:__PID__,secid:secid,hash:sechash,reviewed:!on})});
        await wdLoad(); if(window.wdGate)wdGate();};
      bar.appendChild(rv);
    }
    const btn=document.createElement('button');btn.className='add';btn.textContent='\\u{1F4AC} Annotate';
    const box=document.createElement('div');box.className='annobox';
    box.innerHTML='<textarea placeholder="Your annotation\\u2026"></textarea><div class="b"><button class="save">Save</button><button class="cancel">Cancel</button></div>';
    const list=document.createElement('div');bar.append(btn,box,list);
    btn.onclick=()=>{box.style.display=box.style.display==='block'?'none':'block';const t=box.querySelector('textarea');if(box.style.display==='block')t.focus();};
    box.querySelector('.cancel').onclick=()=>{box.style.display='none';};
    box.querySelector('.save').onclick=async()=>{const ta=box.querySelector('textarea');const text=ta.value.trim();if(!text)return;
      const file=bar.dataset.file||'';
      await fetch('/annotate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:__PID__,section:sec,text,file})});
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
  wdMap();wdGate();
}
function wdMap(){
  // sticky section overview map: a status dot per section (green=reviewed, amber=changed
  // since reviewed, grey=todo) + a jump link. Built from the annobars + the reviewed map.
  var reviewed=window.__REVIEWED__||{};
  var anchor=document.querySelector('.wrap'); if(!anchor)return;          // only on generated pages
  var bars=document.querySelectorAll('.annobar');
  var done=0,total=0,items=[];
  bars.forEach(function(bar){
    var secid=bar.dataset.secid,sechash=bar.dataset.sechash,sec=bar.dataset.section||'';
    if(!secid)return; total++;
    var stored=reviewed[secid];
    var st=(stored!==undefined&&stored===sechash)?'done':((stored!==undefined)?'stale':'todo');
    if(st==='done')done++;
    items.push({secid:secid,sec:sec,st:st});
  });
  window.__REVCOUNT__={done:done,total:total};
  var box=document.getElementById('wd-map');
  if(total===0){if(box)box.remove();return;}   // no reviewable sections (e.g. a mockup) -> no map, no 0/0 count
  if(!box){box=document.createElement('div');box.id='wd-map';anchor.insertBefore(box,anchor.firstChild);}
  box.innerHTML='';
  var head=document.createElement('div');head.className='wd-map-h';
  head.textContent='Sections \\u2014 '+done+'/'+total+' reviewed';
  box.appendChild(head);
  var row=document.createElement('div');row.className='wd-map-row';
  items.forEach(function(it){
    var a=document.createElement('a');a.className='wd-dot '+it.st;a.href='#sec-'+it.secid;
    var i=document.createElement('i');var s=document.createElement('span');s.textContent=it.sec;
    a.append(i,s);
    a.onclick=function(e){e.preventDefault();
      var t=document.getElementById('sec-'+it.secid)||document.querySelector('[data-secid="'+it.secid+'"]');
      if(t){var d=t.closest('details');if(d)d.open=true;t.scrollIntoView({behavior:'smooth',block:'start'});}};
    row.appendChild(a);
  });
  box.appendChild(row);
  var bar=document.getElementById('wd-tabs'); if(bar)box.style.top=(bar.offsetHeight+2)+'px';
}
function wdGate(){
  // close-gating: Submit & Close stays disabled until EVERY section is reviewed (count
  // shown). Plain Submit is never gated. This gates only the page Close, never a bead merge.
  var cb=document.getElementById('wd-close'); if(!cb)return;
  var reviewed=window.__REVIEWED__||{};
  var total=0,done=0;
  document.querySelectorAll('.annobar').forEach(function(bar){
    var secid=bar.dataset.secid,sechash=bar.dataset.sechash; if(!secid)return;
    total++; if(reviewed[secid]===sechash)done++;
  });
  if(total===0){cb.disabled=false;cb.textContent='Submit & Close';cb.title='';return;}
  var left=total-done;
  cb.disabled=left>0;
  cb.textContent=left>0?('Submit & Close ('+left+' left)'):'Submit & Close';
  cb.title=left>0?(left+' section'+(left===1?'':'s')+' still need review'):'all sections reviewed';
}
(function(){var dz=document.getElementById('wd-dismiss');if(dz)dz.onclick=function(){window.__wddismissed=true;var ov=document.getElementById('wd-working');if(ov)ov.classList.remove('on');};})();
(function(){var box=document.getElementById('wd-mbox');if(!box)return;
  box.querySelector('.cancel').onclick=function(){box.style.display='none';};
  box.querySelector('.msave').onclick=async function(){var ta=box.querySelector('textarea');var text=ta.value.trim();if(!text)return;
    await fetch('/annotate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:__PID__,section:'\\u2605 page note',text:text})});
    ta.value='';box.style.display='none';wdLoad();wdTabs();};})();
function wdPoll(){
  // tri-state drives everything: submitted/working -> hold the overlay; idle -> reload to fresh content.
  fetch('/submitted?id='+encodeURIComponent(__PID__)).then(r=>r.json()).then(function(s){
    var st=s.state||(s.submitted?'submitted':'idle');
    var working=(st==='submitted'||st==='working');
    if(!working)window.__wddismissed=false;                                   // re-arm the overlay for next round
    var ov=document.getElementById('wd-working'); if(ov)ov.classList.toggle('on',working&&!window.__wddismissed);
    var sb=document.getElementById('wd-submit');
    if(sb){if(working){sb.disabled=true;sb.textContent='\\u23f3 Claude working\\u2026';}
      else if(sb.textContent.indexOf('Submitting')<0){sb.disabled=false;sb.textContent='\\u2713 Submit';}}
    if(working)return;                                                        // never reload mid-work (no stale-content flash)
    fetch('/pages').then(r=>r.json()).then(function(ps){var me=ps.find(p=>p.id===__PID__); if(me && me.mtime>__MTIME__+0.001){location.reload();}}).catch(function(){});
    fetch('/annotations?id='+encodeURIComponent(__PID__)).then(r=>r.json()).then(function(data){
      var ae=document.activeElement; if(ae&&ae.tagName==='TEXTAREA')return;   // don't disrupt typing
      if(data.length!==window.__NCOUNT__){wdLoad();wdTabs();}                 // live-refresh on clear/add/resolve
    }).catch(function(){});
  }).catch(function(){});
}
wdTabs();wdLoad();wdPoll();setInterval(wdPoll,3000);  // wdPoll() on load re-shows the overlay immediately when returning to a still-working page
</script>
""".replace("%PID%", json.dumps(pid)).replace("%MTIME%", json.dumps(mtime))


INDEX = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>atelier &mdash; all caught up</title>
<style>
body{background:#16161e;color:#c0caf5;font:15px/1.5 -apple-system,BlinkMacSystemFont,sans-serif;margin:0 auto;padding:30px 20px;max-width:760px}
h1{color:#9ece6a;font-size:24px;margin:0 0 6px} .sub{color:#9aa5ce;margin:0 0 22px}
.h{color:#565f89;font-size:13px;margin:18px 0 8px;text-transform:uppercase;letter-spacing:.06em}
.arow{display:flex;align-items:center;gap:10px;background:#1a1b26;border:1px solid #3b4261;border-radius:10px;padding:11px 13px;margin:8px 0}
.arow .t{flex:1 1 auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.arow button{flex:0 0 auto;background:#7aa2f7;color:#16161e;border:0;border-radius:8px;padding:8px 14px;font:13px sans-serif;font-weight:700;cursor:pointer;min-height:38px}
#none{color:#565f89}
</style></head>
<body>
<h1>&#10003; All caught up</h1>
<p class="sub">No open reviews. Reopen a closed one below to revisit it &mdash; and this page jumps to any new review automatically.</p>
<div class="h">Closed reviews</div>
<div id="arch"><span id="none">(nothing archived yet)</span></div>
<script>
async function load(){
  try{const pages=await(await fetch('/pages')).json(); if(pages.length){location.href='/p/'+encodeURIComponent(pages[pages.length-1].id);return;}}catch(e){}
  let arch=[]; try{arch=await(await fetch('/archived')).json();}catch(e){}
  const c=document.getElementById('arch');
  if(!arch.length){c.innerHTML='<span id="none">(nothing archived yet)</span>';return;}
  c.innerHTML='';
  arch.forEach(a=>{const r=document.createElement('div');r.className='arow';
    const t=document.createElement('span');t.className='t';t.textContent=a.title;
    const b=document.createElement('button');b.textContent='Reopen';
    b.onclick=async()=>{await fetch('/reopen?id='+encodeURIComponent(a.id),{method:'POST'});location.href='/p/'+encodeURIComponent(a.id);};
    r.append(t,b);c.appendChild(r);});
}
load();setInterval(load,4000);
</script></body></html>"""


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
        elif u.path == "/archived":
            self._send(200, json.dumps(_archived()))
        elif u.path.startswith("/p/"):
            pid = u.path[3:]
            if not _ID_RE.match(pid) or not os.path.exists(os.path.join(PAGES, pid + ".html")):
                # archived/unknown page → send to the index (All caught up + Reopen), not a dead 404
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
                return
            ppath = os.path.join(PAGES, pid + ".html")
            html = open(ppath, encoding="utf-8").read()
            rt = runtime(pid, os.path.getmtime(ppath))
            html = html.replace("</body>", rt + "</body>") if "</body>" in html else html + rt
            self._send(200, html, "text/html; charset=utf-8")
        elif u.path in ("/annotations", "/submitted", "/reviewed"):
            # these build state file paths from the id, so validate it like the POST
            # handlers do — an unvalidated id is a traversal-shaped read over the tailnet.
            pid = self._qs_id(u)
            if not pid or not _ID_RE.match(pid):
                self._send(400, json.dumps({"error": "bad id"}))
                return
            if u.path == "/annotations":
                self._send(200, json.dumps(_load(_anno(pid), [])))
            elif u.path == "/submitted":
                _st = _state(pid)
                self._send(200, json.dumps({"state": _st, "submitted": _st == "submitted"}))
            else:  # /reviewed
                live = _live_secids(pid)
                rev = {k: v for k, v in _load(_rev(pid), {}).items() if not live or k in live}
                self._send(200, json.dumps(rev))
        elif u.path == "/wait":
            # long-poll: block until any listed page is submitted (or ~5min timeout), return its id
            q = parse_qs(u.query)
            ids = [i for i in q.get("ids", [""])[0].split(",") if i and _ID_RE.match(i)]
            try:
                to = int(q.get("timeout", ["300"])[0])
            except ValueError:
                to = 300
            to = max(to, 0)  # 0 = block indefinitely until a submit; no upper cap
            deadline = None if to == 0 else time.monotonic() + to
            with _CV:
                while True:
                    hit = next((i for i in ids if _state(i) == "submitted"), None)
                    if hit is not None:
                        # consume atomically: return the notes AND clear them, and move the
                        # submit state to `working` (NOT idle) so the page holds the "Claude
                        # working" overlay until the agent finishes + re-arms (no flicker).
                        ann = _load(_anno(hit), [])
                        with _STATE_LOCK:
                            _save(_anno(hit), [])
                            _set_state(hit, "working")
                        closed = not os.path.exists(os.path.join(PAGES, hit + ".html"))
                        resp = {"id": hit, "closed": closed, "annotations": ann}
                        if _to_revdiff_md is not None:  # unified revdiff-format view of this batch
                            resp["markdown"] = _to_revdiff_md(ann)
                        self._send(200, json.dumps(resp))
                        return
                    if deadline is None:
                        _CV.wait(timeout=30)
                        continue
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self._send(200, json.dumps({"id": None}))
                        return
                    _CV.wait(timeout=min(remaining, 30))
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
            with _STATE_LOCK:
                items = _load(_anno(pid), [])
                item = {"section": str(d.get("section", ""))[:200], "text": str(d.get("text", ""))[:5000],
                        "ts": datetime.datetime.now().isoformat(timespec="seconds")}
                if d.get("file"):                       # carries the section's file for revdiff-format emit
                    item["file"] = str(d.get("file"))[:400]
                items.append(item)
                _save(_anno(pid), items)
            self._send(200, json.dumps({"ok": True, "count": len(items)}))
        elif u.path == "/review":
            secid = d.get("secid")
            shash = d.get("hash")
            reviewed = d.get("reviewed")
            if not isinstance(secid, str) or not secid or not isinstance(reviewed, bool) or (
                    reviewed and not isinstance(shash, str)):
                self._send(400, json.dumps({"error": "bad review payload"}))
                return
            live = _live_secids(pid)
            with _STATE_LOCK:
                rev = _load(_rev(pid), {})
                if not isinstance(rev, dict):
                    rev = {}
                if reviewed:
                    rev[secid] = shash
                else:
                    rev.pop(secid, None)
                # prune orphans for sections a regeneration removed
                rev = {k: v for k, v in rev.items() if not live or k in live}
                _save(_rev(pid), rev)
            self._send(200, json.dumps({"ok": True, "reviewed": len(rev)}))
        elif u.path == "/submit":
            with _STATE_LOCK:
                _set_state(pid, "submitted")
            with _CV:
                _CV.notify_all()  # wake any /wait long-poll instantly
            self._send(200, json.dumps({"ok": True}))
        elif u.path == "/resolve":
            with _STATE_LOCK:
                items = [a for a in _load(_anno(pid), []) if not (
                    a.get("ts") == d.get("ts") and a.get("section") == d.get("section") and a.get("text") == d.get("text"))]
                _save(_anno(pid), items)
            self._send(200, json.dumps({"ok": True, "count": len(items)}))
        elif u.path == "/close":
            # archive the page out of pages/ (drops it from the tab bar); keep annotations
            # in state/ so the agent can still read this final batch.
            src = os.path.join(PAGES, pid + ".html")
            if os.path.exists(src):
                os.replace(src, os.path.join(ARCHIVE, pid + ".html"))
            with _CV:
                _CV.notify_all()
            self._send(200, json.dumps({"ok": True}))
        elif u.path == "/reopen":
            src = os.path.join(ARCHIVE, pid + ".html")
            if os.path.exists(src):
                os.replace(src, os.path.join(PAGES, pid + ".html"))
            self._send(200, json.dumps({"ok": True}))
        elif u.path == "/clear":
            with _STATE_LOCK:
                _save(_anno(pid), [])
                _set_state(pid, "idle")
            self._send(200, json.dumps({"ok": True}))
        elif u.path == "/rearm":
            # reset to idle, but never clobber a submit that landed while working
            # (else the auto-rearm loop would silently drop an overlapping submit)
            with _STATE_LOCK:
                if _state(pid) != "submitted":
                    _set_state(pid, "idle")
            self._send(200, json.dumps({"ok": True}))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def log_message(self, *a):
        return


if __name__ == "__main__":
    print(f"atelier hub at http://{HOST}:{PORT}  (pages: {PAGES})")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
