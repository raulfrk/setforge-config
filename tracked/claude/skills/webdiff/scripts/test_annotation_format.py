#!/usr/bin/env python3
"""Round-trip + grammar tests for the shared annotation format (bead 3.13.4).

Property: parse(format_output(anns)) == anns for arbitrary annotation lists,
including bodies with embedded '## ' headers, multiline text, path-with-colon,
and file-level records. Run: python3 test_annotation_format.py (exit 0 = pass).
"""
import sys
from hypothesis import given, settings, strategies as st

from annotation_format import Annotation, parse, format_output, from_webdiff

fails = []


def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL"), name, detail if not cond else "")
    if not cond:
        fails.append(name)


# ---- explicit cases the acceptance criteria name ----
def explicit():
    # file-level (no :N)
    a = [Annotation(file="src/foo.py", comment="overall note")]
    check("file-level round-trip", [x.as_dict() for x in parse(format_output(a))] == [x.as_dict() for x in a])
    check("file-level header shape", format_output(a).splitlines()[0] == "## src/foo.py (file-level)")

    # single line + range, each type
    a = [Annotation(file="a.py", line=5, type="+", comment="added line"),
         Annotation(file="a.py", line=10, end_line=14, type="-", comment="removed block"),
         Annotation(file="a.py", line=3, type=" ", comment="context line")]
    check("line/range/types round-trip", [x.as_dict() for x in parse(format_output(a))] == [x.as_dict() for x in a])

    # body that itself contains a '## ' header-like line (must escape + recover)
    body = "see this:\n## fake.py:9 (+)\nand more"
    a = [Annotation(file="x.py", line=1, type="+", comment=body)]
    out = format_output(a)
    check("embedded ## escaped on output", "\n ## fake.py:9 (+)" in out)
    check("embedded ## body recovered", parse(out)[0].comment == body)

    # path-with-colon round-trips (header grammar is colon-aware)
    a = [Annotation(file="weird:name.py", line=7, type="+", comment="c")]
    check("path-with-colon round-trip", parse(format_output(a))[0].file == "weird:name.py")

    # a path that itself ends in :N at file-level (numeric-tail restore)
    a = [Annotation(file="file:10", comment="c")]
    check("numeric-tail file-level restore", parse(format_output(a))[0].file == "file:10")

    # multiline body with blank lines
    a = [Annotation(file="m.py", line=2, type="+", comment="l1\n\nl3\n")]
    check("multiline+blank round-trip", parse(format_output(a))[0].comment == "l1\n\nl3\n")

    # empty list -> empty string
    check("empty -> ''", format_output([]) == "")

    # from_webdiff: section-level note -> file-level using section label as path
    md = from_webdiff([{"section": "1 · gen.py", "text": "looks good"}])
    check("webdiff section -> file-level", "## 1 · gen.py (file-level)" in md and "looks good" in md)
    # webdiff note carrying real hunk coords -> line-level
    md = from_webdiff([{"file": "gen.py", "line": 5, "type": "+", "text": "here"}])
    check("webdiff hunk coords -> line-level", md.splitlines()[0] == "## gen.py:5 (+)")


# ---- property: parse∘format is identity ----
_files = st.text(min_size=1, max_size=40).filter(lambda s: "\n" not in s)
_bodies = st.text(max_size=200)


@st.composite
def _ann(draw):
    f = draw(_files)
    file_level = draw(st.booleans())
    if file_level:
        return Annotation(file=f, comment=draw(_bodies))
    line = draw(st.integers(min_value=1, max_value=99999))
    has_end = draw(st.booleans())
    end = draw(st.integers(min_value=line, max_value=line + 500)) if has_end else 0
    typ = draw(st.sampled_from(["+", "-", " "]))
    return Annotation(file=f, line=line, end_line=end, type=typ, comment=draw(_bodies))


@settings(max_examples=400, deadline=None)
@given(st.lists(_ann(), max_size=8))
def test_roundtrip(anns):
    recovered = parse(format_output(anns))
    check("PROP roundtrip",
          [a.as_dict() for a in recovered] == [a.as_dict() for a in anns],
          detail=f"{[a.as_dict() for a in anns]} -> {[a.as_dict() for a in recovered]}")


if __name__ == "__main__":
    explicit()
    test_roundtrip()
    print("\nRESULT:", "ALL PASS" if not fails else f"{len(set(fails))} FAILED: {sorted(set(fails))}")
    sys.exit(1 if fails else 0)
