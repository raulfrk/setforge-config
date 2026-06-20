#!/usr/bin/env python3
"""Shared annotation format — atelier ⇄ revdiff interchange.

A faithful Python port of revdiff's annotation grammar (app/annotation/parse.go
+ store.go), so annotation bodies cross between the two review surfaces
byte-faithfully and ONE parser governs both. The header grammar (emitted by FormatOutput):

    ## path (file-level)
    ## path:N (T)
    ## path:N-M (T)

with T ∈ {"+", "-", " "}. Bodies may themselves contain "## " lines; those are
escaped on output (one leading space) and un-escaped on parse, so the body text
round-trips byte-for-byte — including embedded headers, multiline, and
path-with-colon. (ts / section metadata is atelier-only and is NOT carried in
this format — a documented loss across the surface boundary.)

CLI:
    python3 annotation_format.py format < anns.json   # [{file,line,end_line,type,comment}] -> markdown
    python3 annotation_format.py parse  < anns.md      # markdown -> JSON list
    python3 annotation_format.py from-atelier < wd.json  # atelier [{section,text,file?,line?,...}] -> markdown
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field

# Verbatim from revdiff app/annotation/parse.go:
#   ^## (.+?)(?::(\d+)(?:-(\d+))?)? \((file-level|\+|-| )\)$
HEADER_RE = re.compile(r"^## (.+?)(?::(\d+)(?:-(\d+))?)? \((file-level|\+|-| )\)$")


@dataclass
class Annotation:
    file: str
    line: int = 0          # 0 ⇒ file-level
    end_line: int = 0      # 0 ⇒ single line (or file-level)
    type: str = ""         # "+" | "-" | " "  (empty for file-level)
    comment: str = ""

    def as_dict(self) -> dict:
        return {"file": self.file, "line": self.line, "end_line": self.end_line,
                "type": self.type, "comment": self.comment}


def escape_header_lines(body: str) -> str:
    """Prefix any body line whose first non-space content is '## ' with one space,
    so a comment line cannot be mistaken for a record header. Port of store.go."""
    if "## " not in body:
        return body
    return "\n".join((" " + ln) if ln.lstrip(" ").startswith("## ") else ln
                     for ln in body.split("\n"))


def format_output(anns: list) -> str:
    """Render annotations as revdiff markdown. Preserves the given order (revdiff
    sorts cosmetically; both parse identically). Returns '' for an empty list."""
    out, first = [], True
    for a in anns:
        a = a if isinstance(a, Annotation) else Annotation(**a)
        if not first:
            out.append("\n")
        first = False
        body = escape_header_lines(a.comment)
        if a.line == 0:
            out.append(f"## {a.file} (file-level)\n{body}\n")
        elif a.end_line > 0:
            out.append(f"## {a.file}:{a.line}-{a.end_line} ({a.type})\n{body}\n")
        else:
            out.append(f"## {a.file}:{a.line} ({a.type})\n{body}\n")
    return "".join(out)


def _parse_header(line: str) -> Annotation | None:
    m = HEADER_RE.match(line)
    if m is None:
        return None
    f, n, end, t = m.group(1), m.group(2), m.group(3), m.group(4)
    if t == "file-level":
        # restore a numeric tail the regex peeled off a path that ends in :N / :N-M
        if n:
            f += ":" + n + ("-" + end if end else "")
        return Annotation(file=f)
    a = Annotation(file=f, type=t, line=int(n))
    if end:
        a.end_line = int(end)
    return a


def parse(text: str) -> list:
    """Parse revdiff markdown into annotations, in source order. A '## ' line that
    is not a valid header is folded into the current body (un-escaped). Any non-blank
    content before the first header — a malformed '## ' line OR plain text — raises
    ValueError. Port of parse.go."""
    out: list = []
    current: Annotation | None = None
    body: list = []
    seen_header = False
    nonblank = False

    def flush():
        nonlocal current, body
        if current is None:
            return
        if body and body[-1] == "":   # strip the single trailing empty line FormatOutput adds
            body = body[:-1]
        current.comment = "\n".join(body)
        out.append(current)
        current = None
        body = []

    for line in text.split("\n"):
        if line.startswith("## "):
            ann = _parse_header(line)
            if ann is None:
                if not seen_header:
                    raise ValueError(f"annotation header malformed before any record: {line!r}")
                # non-grammar '## ' inside a record → body content (strip one escape space)
                body.append(line[1:] if line.startswith(" ") and line.lstrip(" ").startswith("## ") else line)
                continue
            flush()
            seen_header = True
            current = ann
            continue
        if not seen_header:
            if line.strip() == "":
                continue
            nonblank = True
            break
        body.append(line[1:] if line.startswith(" ") and line.lstrip(" ").startswith("## ") else line)

    if not seen_header and nonblank:
        raise ValueError("annotation input has content before any header")
    flush()
    return out


def from_atelier(items: list) -> str:
    """Map atelier annotations to revdiff markdown. An atelier note is section-level,
    so it emits file-level (no :N) unless it carries explicit line/type from the real
    hunk model. `file` falls back to the section label for non-file sections."""
    anns = []
    for it in items:
        f = it.get("file") or it.get("section") or "(note)"
        line = int(it.get("line") or 0)
        end = int(it.get("end_line") or 0)
        typ = it.get("type") or (" " if line else "")
        anns.append(Annotation(file=f, line=line, end_line=end, type=typ,
                               comment=str(it.get("text", it.get("comment", "")))))
    return format_output(anns)


def _main(argv: list) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    data = sys.stdin.read()
    if cmd == "format":
        print(format_output(json.loads(data or "[]")), end="")
    elif cmd == "from-atelier":
        print(from_atelier(json.loads(data or "[]")), end="")
    elif cmd == "parse":
        print(json.dumps([a.as_dict() for a in parse(data)], ensure_ascii=False, indent=2))
    else:
        sys.stderr.write(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
