#!/usr/bin/env python3
"""Security + content-parity invariants for gen_atelier.py content modes.

Builds an isolated temp git repo, runs gen_atelier.py with crafted specs, and inspects
the generated HTML. Dependency-light. Run: python3 test_content_modes.py (exit 0 = pass).
"""
import json, os, subprocess, sys, tempfile

GEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gen_atelier.py")


def gen(repo, blocks, **extra):
    spec = {"title": "t", "repo": repo, "groups": [{"heading": "G", "blocks": blocks}], **extra}
    sf = os.path.join(repo, "_spec.json"); of = os.path.join(repo, "_out.html")
    open(sf, "w").write(json.dumps(spec))
    subprocess.run([sys.executable, GEN, sf, of], check=True, capture_output=True, text=True)
    return open(of, encoding="utf-8").read()


def main() -> int:
    fails = []

    def check(name, cond):
        print(("PASS" if cond else "FAIL"), name)
        if not cond:
            fails.append(name)

    repo = tempfile.mkdtemp()
    subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.name", "t"], check=True)

    # a normal text file with an HTML-injection payload + a sentinel line
    open(os.path.join(repo, "evil.txt"), "w").write("<script>alert(1)</script>\nSENTINEL_LINE_XYZ\n")
    # an oversize file (> 256 KiB)
    open(os.path.join(repo, "big.txt"), "w").write("A" * (300 * 1024))
    # a binary file (NUL bytes)
    open(os.path.join(repo, "bin.dat"), "wb").write(b"PK\x00\x00\x01\x02binary")
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
    subprocess.run(["git", "-C", repo, "commit", "-qm", "init"], check=True)

    # X1: path traversal in context mode is REJECTED (content never read/rendered)
    h = gen(repo, [{"mode": "context", "file": "../../../../etc/passwd", "label": "trav", "why": "x"}])
    check("traversal rejected (error block shown)", "cannot render" in h and "escapes repo root" in h)
    check("traversal: no file content table rendered", '<div class="dt">' not in h)

    # X1: file content is html-escaped (no raw <script>), escaped form present
    h = gen(repo, [{"mode": "context", "file": "evil.txt", "label": "evil", "why": "x"}])
    check("file content escaped (no raw <script>)", "<script>alert(1)</script>" not in h)
    check("file content escaped (entity present)", "&lt;script&gt;" in h)

    # X1: oversize truncated
    h = gen(repo, [{"mode": "context", "file": "big.txt", "label": "big", "why": "x"}])
    check("oversize file truncated marker", "truncated" in h)

    # X1: binary placeholdered (NUL-sniff), raw bytes not dumped
    h = gen(repo, [{"mode": "context", "file": "bin.dat", "label": "bin", "why": "x"}])
    check("binary placeholdered", "binary file" in h)

    # context mode requires the EXPLICIT marker: a default (diff) block with no mode must NOT
    # read the whole file — the sentinel only present in evil.txt's body must be absent when
    # there is no diff for it (range empty => no diff => no content).
    h = gen(repo, [{"file": "evil.txt", "label": "nomode", "why": "x"}], range="HEAD")
    check("no-mode block does not auto-read file (context needs explicit marker)",
          "SENTINEL_LINE_XYZ" not in h)
    # and the explicit context marker DOES surface it
    h = gen(repo, [{"mode": "context", "file": "evil.txt", "label": "ctx", "why": "x"}])
    check("explicit context mode reads the file", "SENTINEL_LINE_XYZ" in h)

    # stdin/synthetic text mode escapes its content too (no escape-helper bypass)
    h = gen(repo, [{"mode": "text", "content": "<b>raw</b>", "label": "syn", "why": "x"}])
    check("synthetic text escaped", "<b>raw</b>" not in h and "&lt;b&gt;raw&lt;/b&gt;" in h)

    # compare mode: two files, content escaped, diff rendered
    open(os.path.join(repo, "a.txt"), "w").write("one\ntwo\n")
    open(os.path.join(repo, "b.txt"), "w").write("one\nTWO<script>\n")
    h = gen(repo, [{"mode": "compare", "old": "a.txt", "new": "b.txt", "label": "cmp", "why": "x"}])
    check("compare renders + escapes", "TWO&lt;script&gt;" in h)
    check("compare traversal rejected", "cannot render" in gen(
        repo, [{"mode": "compare", "old": "a.txt", "new": "../../etc/passwd", "label": "c", "why": "x"}]))

    # plan mode: markdown headings -> TOC, content escaped, inline (bold/code) + tables rendered
    open(os.path.join(repo, "plan.md"), "w").write(
        "# Title\n\nsome <b>text</b> with **bold** and `code`\n\n## Sub\n- item\n\n"
        "| A | B |\n|---|---|\n| **x** | `y` |\n\nrisky **<script>** done\n")
    h = gen(repo, [{"mode": "plan", "file": "plan.md", "label": "plan", "why": "x"}])
    check("plan builds TOC", 'class="toc"' in h)
    check("plan escapes body", "<b>text</b>" not in h and "&lt;b&gt;text&lt;/b&gt;" in h)
    check("plan renders bold", "<strong>bold</strong>" in h)
    check("plan renders inline code", "<code>code</code>" in h)
    check("plan renders tables", '<table class="md-tbl">' in h and "<th>A</th>" in h and "<td><strong>x</strong></td>" in h)
    check("plan inline stays injection-safe", "<strong><script></strong>" not in h and "<strong>&lt;script&gt;</strong>" in h)

    # all-files mode: lists tracked files, no traversal
    h = gen(repo, [{"mode": "all-files", "label": "files", "why": "x"}])
    check("all-files lists tracked files", "evil.txt" in h and "big.txt" in h)

    print("\nRESULT:", "ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
