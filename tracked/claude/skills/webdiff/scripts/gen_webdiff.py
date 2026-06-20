#!/usr/bin/env python3
"""Generate a webdiff page: per-section authored "why" + a GitHub-style diff rendered
with a self-contained FLEXBOX renderer (line-number gutter + code), so it wraps cleanly
on mobile (flex min-width:0 doesn't collapse like a <table>). No CDN.

- DEFAULT no-wrap: each line one row, horizontal scroll for long lines.
- WRAP toggle: code column wraps to fit width; gutter stays fixed.
- A-/A+ zoom sets the diff font-size inline (reliable). Python syntax highlighting inline.

Usage: python3 gen_webdiff.py <spec.json> <out.html>   (schema in repo SKILL.md)
"""
import hashlib
import html
import re
import json
import subprocess
import sys
from pathlib import Path

spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
OUT = Path(sys.argv[2])
REPO = spec["repo"]
RANGE = spec.get("range", "")  # optional: content-only pages (plan/all-files/text) need no range

_KW = ("def class return if elif else for while in not and or import from as with try except finally "
       "raise yield lambda pass break continue None True False self cls async await global nonlocal "
       "assert del is").split()
_TOKEN = re.compile(r"(?P<comment>\#[^\n]*)"
                    r"|(?P<string>(?:[rbfRBF]{0,2})(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'))"
                    r"|(?P<number>\b\d[\d_]*\.?\d*\b)|(?P<decorator>@\w[\w.]*)|(?P<name>[A-Za-z_]\w*)")
_CLS = {"comment": "hc", "string": "hs", "number": "hn", "decorator": "hd"}
_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def _sechash(*parts: str) -> str:
    """Content fingerprint of a section. Changes ⇒ a prior 'Reviewed' tick goes stale
    (the runtime flips it to amber '↻ changed since reviewed')."""
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


_seen_secids: dict[str, int] = {}


def _secid(*parts: str) -> str:
    """Stable, ORDINAL-FREE section id derived from section identity (heading/label/file),
    so inserting or reordering sections does not orphan an unrelated section's reviewed
    state. A genuine identity collision is disambiguated with a deterministic suffix so the
    DOM id stays unique (else two sections would share one reviewed entry)."""
    h = hashlib.sha1()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x00")
    base = "s" + h.hexdigest()[:11]
    n = _seen_secids.get(base, 0)
    _seen_secids[base] = n + 1
    return base if n == 0 else f"{base}-{n}"


def _annobar(section: str, secid: str, sechash: str) -> str:
    return (f'<div class="annobar" data-section="{html.escape(section)}" '
            f'data-secid="{html.escape(secid)}" data-sechash="{html.escape(sechash)}"></div>')


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


# ---------------------------------------------------------------------------
# Content-parity modes (context / plan / text / all-files / compare) + security
# ---------------------------------------------------------------------------
MAX_BYTES = 256 * 1024          # per-file read cap
MAX_FILES = 2000                # all-files listing cap
_ROOT = Path(REPO).resolve()


def _confined(p: str) -> Path:
    """Resolve p UNDER the repo root and reject any escape (.., absolute path, or a
    symlink whose target leaves the root). resolve() collapses .. and follows symlinks,
    so relative_to(root) is a true containment test, not a string-prefix guess."""
    full = (_ROOT / p).resolve()
    try:
        full.relative_to(_ROOT)
    except ValueError:
        raise ValueError(f"path escapes repo root: {p!r}")
    return full


def _read_confined(p: str) -> tuple[str, bool]:
    """Read a repo-confined file as display text. Returns (text, truncated).
    Binary (NUL-sniffed) → placeholder; non-utf8 → errors='replace'; size-capped."""
    full = _confined(p)
    raw = full.read_bytes()
    truncated = len(raw) > MAX_BYTES
    raw = raw[:MAX_BYTES]
    if b"\x00" in raw:
        return "⟨binary file — not shown⟩", truncated
    return raw.decode("utf-8", errors="replace"), truncated


def _lang_for(path: str) -> str:
    return "py" if path.endswith(".py") else ""


def _trunc_row() -> str:
    return ('<div class="dl meta"><span class="no"></span><span class="no"></span>'
            '<span class="co">⟨truncated — file exceeds display cap⟩</span></div>')


def render_file(text: str, lang: str, truncated: bool, start: int = 1) -> str:
    """Render plain file content as a context-only listing (line gutter, no +/- diff).
    `text` is the raw, UNESCAPED file body — _row/hl_py escape it (never join raw)."""
    rows = [_row("ctx", str(i), str(i), " ", line, lang)
            for i, line in enumerate(text.splitlines() or [""], start)]
    if truncated:
        rows.append(_trunc_row())
    return '<div class="dt">' + "".join(rows) + "</div>"


def render_compare(old_p: str, new_p: str, lang: str) -> str:
    """Unified diff between two repo-confined files (difflib, never git --no-index, so
    both paths stay confined). Content lines are escaped by render_diff."""
    import difflib
    o, ot = _read_confined(old_p)
    n, nt = _read_confined(new_p)
    raw = "\n".join(difflib.unified_diff(o.splitlines(), n.splitlines(),
                                         fromfile=old_p, tofile=new_p, lineterm="", n=3))
    body = render_diff(raw, lang) if raw.strip() else (
        '<div class="dt"><div class="dl meta"><span class="no"></span><span class="no"></span>'
        '<span class="co">⟨files identical⟩</span></div></div>')
    return body + (_trunc_row() if (ot or nt) else "")


_MD_H = re.compile(r"^(#{1,4})\s+(.*)$")
_MD_FENCE = re.compile(r"^```")


def render_markdown(text: str) -> tuple[str, str]:
    """Minimal, SAFE markdown → HTML (everything html.escaped first, then a small set of
    block constructs re-applied). Returns (toc_html, body_html). Used for plan-file mode."""
    out, toc, in_code, in_list = [], [], False, False
    for line in text.splitlines():
        if _MD_FENCE.match(line):
            if in_list:
                out.append("</ul>"); in_list = False
            out.append("</pre>" if in_code else '<pre class="md-pre">')
            in_code = not in_code
            continue
        if in_code:
            out.append(html.escape(line)); continue
        m = _MD_H.match(line)
        if m:
            if in_list:
                out.append("</ul>"); in_list = False
            lvl = len(m.group(1)); txt = html.escape(m.group(2))
            anchor = "h" + _sechash(line)[:8]
            toc.append(f'<li class="toc-l{lvl}"><a href="#{anchor}">{txt}</a></li>')
            out.append(f'<h{lvl+1} id="{anchor}" class="md-h">{txt}</h{lvl+1}>')
            continue
        if line.lstrip().startswith(("- ", "* ")):
            if not in_list:
                out.append('<ul class="md-ul">'); in_list = True
            out.append(f"<li>{html.escape(line.lstrip()[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>"); in_list = False
        out.append(f"<p>{html.escape(line)}</p>" if line.strip() else "")
    if in_list:
        out.append("</ul>")
    if in_code:
        out.append("</pre>")
    toc_html = ('<ul class="toc">' + "".join(toc) + "</ul>") if toc else ""
    return toc_html, "".join(out)


def render_allfiles() -> tuple[str, bool]:
    """List repo files (git ls-files), capped. Names only — no content read."""
    files = subprocess.run(["git", "-C", REPO, "ls-files"],
                           capture_output=True, text=True, check=True).stdout.splitlines()
    truncated = len(files) > MAX_FILES
    rows = "".join(f'<li>{html.escape(f)}</li>' for f in files[:MAX_FILES])
    return f'<ul class="md-ul allfiles">{rows}</ul>', truncated


# ---------------------------------------------------------------------------
# Visual upgrades: diff-stat charts, embedded diagrams (overview map = runtime)
# ---------------------------------------------------------------------------
def _diffstat(raw: str) -> tuple[int, int]:
    add = sum(1 for ln in raw.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
    dele = sum(1 for ln in raw.splitlines() if ln.startswith("-") and not ln.startswith("---"))
    return add, dele


def render_diffstat(add: int, dele: int) -> str:
    total = add + dele
    if total == 0:
        return ""
    aw = round(100 * add / total)
    return (f'<div class="dstat"><span class="dstat-n da">+{add}</span>'
            f'<span class="dstat-bar"><span class="da" style="width:{aw}%"></span>'
            f'<span class="dd" style="width:{100 - aw}%"></span></span>'
            f'<span class="dstat-n dd">&minus;{dele}</span></div>')


def render_diagram(d: dict) -> str:
    """Embed an AUTHORED diagram. SVG is inlined (Excalidraw/mermaid should be pre-exported
    to SVG for a real render); 'img' takes a data-URI/confined src; any other type falls back
    to a labelled source block (no CDN, so no client-side mermaid runtime)."""
    t = (d.get("type") or "svg").lower()
    content = d.get("content", "")
    if t == "svg":
        return f'<div class="diagram">{content}</div>'
    if t == "img":
        return f'<div class="diagram"><img alt="diagram" src="{html.escape(d.get("src", ""))}"></div>'
    return ('<div class="diagram"><div class="note">⟨'
            f'{html.escape(t)} source — pre-export to SVG to render inline⟩</div>'
            f'<pre class="md-pre">{html.escape(content)}</pre></div>')


parts = []
_ov_callouts = "".join(c.get("html", "") for c in spec.get("callouts", []))
for c in spec.get("callouts", []):
    parts.append(f'<div class="callout {c.get("cls","")}">{c["html"]}</div>')
parts.append(_annobar("0 · Overview", "overview", _sechash("overview", _ov_callouts)))

for gi, g in enumerate(spec["groups"], 1):
    badge = f' <span class="badge {g.get("badge_cls","b1")}">{html.escape(g["badge"])}</span>' if g.get("badge") else ""
    parts.append(f'<details class="grp" open><summary class="gsum">'
                 f'<span class="gh">{html.escape(g["heading"])}</span>{badge}</summary>')
    if g.get("note"):
        parts.append(f'<p class="note">{g["note"]}</p>')
    if g.get("diagram"):
        parts.append(render_diagram(g["diagram"]))
    for blk in g["blocks"]:
        mode = blk.get("mode", "diff")
        # Defaults; each mode fills body (rendered HTML), hash_src (content fingerprint
        # basis), ident (stable secid input), label, why. `why` is AUTHORED markup (raw,
        # like callouts) — only file/stdin CONTENT is escaped, inside the render_* helpers.
        why = blk.get("why", "")
        try:
            if mode == "context":
                path = blk["file"]
                text, trunc = _read_confined(path)
                label = blk.get("label", path.split("/")[-1])
                body, hash_src, ident = render_file(text, _lang_for(path), trunc), text, path
            elif mode == "compare":
                old_p, new_p = blk["old"], blk["new"]
                label = blk.get("label", f"{old_p} → {new_p}")
                body = render_compare(old_p, new_p, _lang_for(new_p))
                hash_src, ident = old_p + "\x00" + new_p, old_p + "\x00" + new_p
            elif mode == "text":
                content = str(blk.get("content", ""))
                trunc = len(content) > MAX_BYTES
                content = content[:MAX_BYTES]
                label = blk.get("label", "text")
                body, hash_src, ident = render_file(content, "", trunc), content, label
            elif mode == "plan":
                path = blk["file"]
                text, trunc = _read_confined(path)
                toc, md = render_markdown(text)
                label = blk.get("label", path.split("/")[-1])
                toc_block = f'<div class="toc-wrap">{toc}</div>' if toc else ""
                body = f'{toc_block}<div class="md-body">{md}</div>' + (_trunc_row() if trunc else "")
                hash_src, ident = text, path
            elif mode == "all-files":
                lst, trunc = render_allfiles()
                label = blk.get("label", "repository files")
                body = lst + (
                    '<p class="note">⟨listing truncated at the file cap⟩</p>' if trunc else "")
                hash_src, ident = "all-files", "all-files"
            else:  # diff (default)
                path = blk["file"]
                raw = diff_for(path)
                if "split" in blk or "hunks" in blk:
                    subs = blk.get("split") or blk.get("hunks")
                    why = "<ul class='why-list'>" + "".join(
                        f"<li><b>{html.escape(s['label'])}</b> — {s['why']}</li>" for s in subs) + "</ul>"
                    label = path.split("/")[-1]
                else:
                    label = blk["label"]
                body = render_diffstat(*_diffstat(raw)) + render_diff(raw, _lang_for(path))
                hash_src, ident = raw, path
        except (ValueError, OSError, KeyError) as e:
            # rejected traversal / missing file / bad spec → a VISIBLE, escaped error block
            # (never silently read or render unconfined content)
            label = blk.get("label", blk.get("file", mode))
            body = f'<div class="callout warn">cannot render ({mode}): {html.escape(str(e))}</div>'
            hash_src, ident = str(e), str(blk)
        if blk.get("diagram"):
            body = render_diagram(blk["diagram"]) + body
        secid = _secid(g["heading"], label, ident)
        sechash = _sechash(hash_src, label, str(why))
        parts.append(
            f'<div class="seam" id="sec-{secid}"><div class="lbl">{html.escape(label)}</div>'
            f'<div class="why">{why}</div>{body}'
            f'{_annobar(f"{gi} · {label}", secid, sechash)}</div>')
    parts.append('</details>')

BODY = "\n".join(parts)
sub = spec.get("sub") or (
    f"Diff <code>{html.escape(RANGE)}</code> — each change with its why; annotate either."
    if RANGE else "Review — each section with its why; annotate any.")

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
/* content-parity modes: plan-file markdown + TOC, all-files listing */
.toc-wrap{{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px 12px;margin:8px 0}}
.toc{{list-style:none;margin:0;padding:0;font-size:13px}} .toc li{{margin:2px 0}} .toc a{{color:var(--F);text-decoration:none}}
.toc .toc-l2{{padding-left:14px}} .toc .toc-l3{{padding-left:28px}} .toc .toc-l4{{padding-left:42px}}
.md-body{{font-size:14px;line-height:1.6;overflow-wrap:anywhere}} .md-body .md-h{{color:#fff;margin:14px 0 6px;border-bottom:1px solid var(--line);padding-bottom:3px}}
.md-body p{{margin:6px 0}} .md-ul{{margin:6px 0;padding-left:20px}} .md-ul li{{margin:3px 0}}
.md-pre{{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px;overflow-x:auto;white-space:pre-wrap;overflow-wrap:anywhere;font:12.5px ui-monospace,Menlo,monospace;color:#a9b1d6}}
.allfiles{{max-height:60vh;overflow-y:auto;font:12.5px ui-monospace,Menlo,monospace;color:#a9b1d6}}
/* diff-stat charts */
.dstat{{display:flex;align-items:center;gap:8px;margin:6px 0 2px;font:11px ui-monospace,Menlo,monospace}}
.dstat-n.da{{color:#9ece6a}} .dstat-n.dd{{color:#f7768e}}
.dstat-bar{{flex:0 0 120px;display:flex;height:9px;border-radius:4px;overflow:hidden;background:#3b4261}}
.dstat-bar .da{{background:#9ece6a}} .dstat-bar .dd{{background:#f7768e}}
/* embedded diagrams */
.diagram{{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px;margin:8px 0;overflow-x:auto}}
.diagram svg,.diagram img{{max-width:100%;height:auto}}
/* collapsible groups */
details.grp{{margin:18px 0 0}}
summary.gsum{{cursor:pointer;list-style:none;font-size:17px;font-weight:700;border-bottom:1px solid var(--line);padding:8px 0 6px;margin-bottom:6px}}
summary.gsum::-webkit-details-marker{{display:none}}
summary.gsum::before{{content:"\\25BE  ";color:var(--dim)}}
details.grp:not([open]) summary.gsum::before{{content:"\\25B8  "}}
summary.gsum .gh{{color:#fff}} summary.gsum .badge{{font-size:11px;font-weight:700;border-radius:6px;padding:2px 8px;margin-left:8px;vertical-align:middle}}
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
