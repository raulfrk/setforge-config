#!/usr/bin/env python3
"""Generate a webdiff page: per-section authored "why" + a GitHub-style diff rendered
with a self-contained FLEXBOX renderer (line-number gutter + code), so it wraps cleanly
on mobile (flex min-width:0 doesn't collapse like a <table>). No CDN.

- DEFAULT no-wrap: each line one row, horizontal scroll for long lines.
- WRAP toggle: code column wraps to fit width; gutter stays fixed.
- A-/A+ zoom sets the diff font-size inline (reliable). Python syntax highlighting inline.

Usage: python3 gen_webdiff.py <spec.json> <out.html>   (schema in repo SKILL.md)
"""
import html
import re
import json
import subprocess
import sys
from pathlib import Path

spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
OUT = Path(sys.argv[2])
REPO = spec["repo"]
RANGE = spec["range"]

_KW = ("def class return if elif else for while in not and or import from as with try except finally "
       "raise yield lambda pass break continue None True False self cls async await global nonlocal "
       "assert del is").split()
_TOKEN = re.compile(r"(?P<comment>\#[^\n]*)"
                    r"|(?P<string>(?:[rbfRBF]{0,2})(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'))"
                    r"|(?P<number>\b\d[\d_]*\.?\d*\b)|(?P<decorator>@\w[\w.]*)|(?P<name>[A-Za-z_]\w*)")
_CLS = {"comment": "hc", "string": "hs", "number": "hn", "decorator": "hd"}
_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def diff_for(path: str) -> str:
    return subprocess.run(["git", "-C", REPO, "diff", RANGE, "--", path],
                          capture_output=True, text=True, check=True).stdout


def hl_py(code: str) -> str:
    out, pos = [], 0
    for m in _TOKEN.finditer(code):
        if m.start() > pos:
            out.append(html.escape(code[pos:m.start()]))
        kind, text = m.lastgroup, html.escape(m.group())
        out.append(f'<span class="hk">{text}</span>' if (kind == "name" and m.group() in _KW)
                   else (text if kind == "name" else f'<span class="{_CLS[kind]}">{text}</span>'))
        pos = m.end()
    if pos < len(code):
        out.append(html.escape(code[pos:]))
    return "".join(out) or "&nbsp;"


def _row(cls: str, o: str, n: str, pfx: str, code: str, lang: str) -> str:
    inner = hl_py(code) if lang == "py" else (html.escape(code) or "&nbsp;")
    return (f'<div class="dl {cls}"><span class="no">{o}</span><span class="no">{n}</span>'
            f'<span class="co"><span class="pf">{html.escape(pfx)}</span>{inner}</span></div>')


def render_diff(raw: str, lang: str) -> str:
    rows, oldn, newn = [], 0, 0
    for line in raw.splitlines():
        if line.startswith(("diff --git", "index ", "+++", "---", "new file", "deleted file", "rename ", "similarity ")):
            rows.append(f'<div class="dl meta"><span class="no"></span><span class="no"></span><span class="co">{html.escape(line)}</span></div>')
            continue
        m = _HUNK.match(line)
        if m:
            oldn, newn = int(m.group(1)), int(m.group(2))
            rows.append(f'<div class="dl hunk"><span class="no"></span><span class="no"></span><span class="co">{html.escape(line)}</span></div>')
            continue
        if line.startswith("+"):
            rows.append(_row("add", "", str(newn), "+", line[1:], lang)); newn += 1
        elif line.startswith("-"):
            rows.append(_row("del", str(oldn), "", "-", line[1:], lang)); oldn += 1
        else:
            body = line[1:] if line.startswith(" ") else line
            rows.append(_row("ctx", str(oldn), str(newn), " ", body, lang)); oldn += 1; newn += 1
    return '<div class="dt">' + "".join(rows) + "</div>"


parts = []
for c in spec.get("callouts", []):
    parts.append(f'<div class="callout {c.get("cls","")}">{c["html"]}</div>')
parts.append('<div class="annobar" data-section="0 · Overview"></div>')

for gi, g in enumerate(spec["groups"], 1):
    badge = f' <span class="badge {g.get("badge_cls","b1")}">{html.escape(g["badge"])}</span>' if g.get("badge") else ""
    parts.append(f'<h2>{html.escape(g["heading"])}{badge}</h2>')
    if g.get("note"):
        parts.append(f'<p class="note">{g["note"]}</p>')
    for blk in g["blocks"]:
        path = blk["file"]
        lang = "py" if path.endswith(".py") else ""
        raw = diff_for(path)
        if "split" in blk or "hunks" in blk:
            subs = blk.get("split") or blk.get("hunks")
            why = "<ul class='why-list'>" + "".join(
                f"<li><b>{html.escape(s['label'])}</b> — {s['why']}</li>" for s in subs) + "</ul>"
            label = path.split("/")[-1]
        else:
            why, label = blk["why"], blk["label"]
        parts.append(
            f'<div class="seam"><div class="lbl">{html.escape(label)}</div>'
            f'<div class="why">{why}</div>{render_diff(raw, lang)}'
            f'<div class="annobar" data-section="{html.escape(f"{gi} · {label}")}"></div></div>')

BODY = "\n".join(parts)
sub = spec.get("sub", f"Diff <code>{html.escape(RANGE)}</code> — each change with its why; annotate either.")

PAGE = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(spec.get("title","webdiff"))}</title>
<style>
:root{{--bg:#16161e;--bg2:#1a1b26;--panel:#1c2333;--panel2:#24283b;--line:#3b4261;--text:#c0caf5;--muted:#9aa5ce;--dim:#565f89;--F:#7aa2f7;--E:#9ece6a;--ok:#9ece6a;--warn:#e0af68;--why:#89ddff;}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;overflow-x:hidden}}
.wrap{{max-width:1100px;margin:0 auto;padding:22px 18px 90px}} h1{{font-size:23px;margin:0 0 4px;color:#fff}} .sub{{color:var(--muted);margin:0 0 18px;font-size:14px}}
h2{{font-size:17px;margin:30px 0 4px;border-bottom:1px solid var(--line);padding-bottom:6px}}
h2 .badge{{font-size:11px;font-weight:700;border-radius:6px;padding:2px 8px;margin-left:8px;vertical-align:middle}}
.b1{{background:#7aa2f733;color:var(--F);border:1px solid var(--F)}} .b2{{background:#9ece6a33;color:var(--E);border:1px solid var(--E)}}
.note{{color:var(--muted);font-size:13.5px;margin:6px 0 12px}}
.seam{{background:var(--bg2);border:1px solid var(--line);border-radius:11px;padding:12px 14px 8px;margin:0 0 12px}}
.seam .lbl{{font-weight:700;font-size:13px;color:#fff;margin-bottom:3px}} .seam .why{{font-size:13px;line-height:1.5;color:var(--why)}}
.seam .why b{{color:#cfeeff}} .seam .why code{{color:#9ece6a}} .why-list{{margin:4px 0;padding-left:18px}} .why-list li{{margin:3px 0}}
code{{background:var(--panel2);padding:1px 6px;border-radius:5px;font:12.5px ui-monospace,Menlo,monospace;color:#7dcfff}}
/* GitHub-style flexbox diff */
.dt{{margin:9px 0 4px;background:var(--panel);border:1px solid var(--line);border-radius:8px;overflow-y:auto;overflow-x:hidden;max-height:75vh;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:10px;line-height:1.5}}
.dl{{display:flex;min-width:0}}
.dl .no{{flex:0 0 auto;width:3.2ch;padding:0 6px;text-align:right;color:var(--dim);user-select:none;white-space:nowrap}}
.dl .co{{flex:1 1 auto;min-width:0;padding:0 8px 0 4px;white-space:pre-wrap;overflow-wrap:anywhere;color:#a9b1d6}}
.dl .pf{{display:inline-block;width:1ch;color:var(--dim)}}
.dl.add{{background:#9ece6a14}} .dl.add .pf{{color:#9ece6a}}
.dl.del{{background:#f7768e14}} .dl.del .pf{{color:#f7768e}}
.dl.hunk .co{{color:#7dcfff;background:#7dcfff10}} .dl.meta .co{{color:var(--dim)}}
.hk{{color:#bb9af7}}.hs{{color:#e0af68}}.hc{{color:#565f89;font-style:italic}}.hn{{color:#ff9e64}}.hd{{color:#7dcfff}}
.callout{{background:#7aa2f714;border:1px solid var(--F);border-radius:9px;padding:11px 13px;margin:10px 0;font-size:13.5px}}
.callout.ok{{background:#9ece6a14;border-color:var(--ok)}} .callout.warn{{background:#e0af6814;border-color:var(--warn)}}
#dctl{{position:fixed;bottom:14px;right:14px;z-index:9998;display:flex;gap:6px;align-items:center;background:#1a1b26ee;border:1px solid var(--line);border-radius:10px;padding:6px}}
#dctl button{{background:#24283b;color:#7aa2f7;border:1px solid var(--line);border-radius:7px;padding:7px 11px;font:13px sans-serif;font-weight:700;cursor:pointer;min-height:36px}}
#dctl .v{{color:#9aa5ce;font:12px sans-serif;min-width:34px;text-align:center}}
b{{color:#fff}} @media(max-width:760px){{.wrap{{padding:16px 12px 90px}}}}
</style></head><body><div class="wrap">
<h1>{html.escape(spec.get("title","webdiff"))}</h1><p class="sub">{sub}</p>
{BODY}
</div>
<div id="dctl"><span style="color:#9aa5ce;font:12px sans-serif">text</span><button onclick="dz(-1)">A&minus;</button><span class="v" id="zval">10px</span><button onclick="dz(1)">A+</button></div>
<script>
var _fs=10;
function dz(n){{_fs=Math.max(9,Math.min(30,_fs+n));document.querySelectorAll('.dt').forEach(function(d){{d.style.fontSize=_fs+'px';}});var v=document.getElementById('zval');if(v)v.textContent=_fs+'px';}}
dz(0);
</script>
</body></html>"""
OUT.write_text(PAGE, encoding="utf-8")
print(f"wrote {OUT} — {BODY.count('class=\"dt\"')} diffs (flexbox github-style)")
