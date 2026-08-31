#!/usr/bin/env python3
"""Build and map a readable, width-aware projection of a Markdown plan."""

from __future__ import annotations

import argparse
import json
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path


ATX_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
BULLET_RE = re.compile(r"^(\s*)[-+*]\s+(.*)$")
ORDERED_RE = re.compile(r"^(\s*)(\d+[.)])\s+(.*)$")
QUOTE_RE = re.compile(r"^(\s*>\s?)(.*)$")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
LINK_DEFINITION_RE = re.compile(r"^\s{0,3}\[[^]]+\]:\s*\S+")
TABLE_DELIMITER_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
ANNOTATION_RE = re.compile(r"^(##\s+)(.+?)(?::(\d+)(?:-(\d+))?)?\s+\(([^)]*)\)\s*$")


@dataclass(frozen=True)
class Projection:
    text: str
    line_map: list[int]


def review_width(columns: int) -> int:
    """Reserve RevDiff chrome while keeping narrow screens usable."""
    if columns < 90:
        return max(32, columns - 13)
    return max(48, min(80, columns - 8))


def _is_table_line(lines: list[str], index: int) -> bool:
    line = lines[index]
    if TABLE_DELIMITER_RE.match(line):
        return True
    if "|" not in line:
        return False
    previous_is_delimiter = index > 0 and bool(
        TABLE_DELIMITER_RE.match(lines[index - 1])
    )
    next_is_delimiter = index + 1 < len(lines) and bool(
        TABLE_DELIMITER_RE.match(lines[index + 1])
    )
    return previous_is_delimiter or next_is_delimiter or line.lstrip().startswith("|")


def _wrapped(text: str, width: int, first: str = "", rest: str = "") -> list[str]:
    available = max(1, width - len(first))
    continuation = max(1, width - len(rest))
    # textwrap has one width for all lines. The narrower of the first and
    # continuation rows guarantees neither prefix pushes content past width.
    content_width = min(available, continuation)
    pieces = textwrap.wrap(
        text.strip(),
        width=content_width,
        break_long_words=False,
        break_on_hyphens=False,
        replace_whitespace=False,
        drop_whitespace=True,
    )
    if not pieces:
        return [first.rstrip()]
    return [first + pieces[0], *[rest + piece for piece in pieces[1:]]]


def render_markdown(source: str, width: int) -> Projection:
    """Return a spacious review projection and its projected-to-source map."""
    source_lines = source.splitlines()
    output: list[str] = []
    line_map: list[int] = []
    in_fence = False
    fence_marker = ""

    def emit(value: str, source_line: int) -> None:
        output.append(value.rstrip())
        line_map.append(source_line)

    def blank(source_line: int) -> None:
        if output and output[-1] != "":
            emit("", source_line)

    for index, line in enumerate(source_lines):
        source_line = index + 1
        fence = FENCE_RE.match(line)
        if in_fence:
            emit(line, source_line)
            if (
                fence
                and fence.group(1).startswith(fence_marker[0])
                and len(fence.group(1)) >= len(fence_marker)
            ):
                in_fence = False
                fence_marker = ""
                blank(source_line)
            continue
        if fence:
            blank(source_line)
            fence_marker = fence.group(1)
            in_fence = True
            emit(line, source_line)
            continue

        if not line.strip():
            blank(source_line)
            continue

        heading = ATX_HEADING_RE.match(line)
        if heading:
            blank(source_line)
            title = heading.group(2)
            title_lines = _wrapped(title, width)
            for rendered in title_lines:
                emit(rendered, source_line)
            depth = len(heading.group(1))
            underline = "=" if depth == 1 else "-" if depth == 2 else "·"
            emit(
                underline * min(width, max(3, max(map(len, title_lines)))), source_line
            )
            blank(source_line)
            continue

        # Preserve structures whose columns, indentation, or exact tokens are
        # semantically significant. Long unbreakable tokens are left intact by
        # _wrapped() as well.
        if (
            line.startswith("    ")
            or line.startswith("\t")
            or LINK_DEFINITION_RE.match(line)
            or _is_table_line(source_lines, index)
            or re.match(r"^\s{0,3}(?:---+|___+|\*\*\*+)\s*$", line)
        ):
            emit(line, source_line)
            continue

        bullet = BULLET_RE.match(line)
        if bullet:
            indent, body = bullet.groups()
            level = max(0, len(indent.expandtabs(2)) // 2)
            marker = "•" if level == 0 else "◦"
            checkbox = re.match(r"^\[([ xX])\]\s+(.*)$", body)
            if checkbox:
                marker = "☑" if checkbox.group(1).lower() == "x" else "☐"
                body = checkbox.group(2)
            prefix = f"{indent}{marker} "
            for rendered in _wrapped(body, width, prefix, " " * len(prefix)):
                emit(rendered, source_line)
            blank(source_line)
            continue

        ordered = ORDERED_RE.match(line)
        if ordered:
            indent, marker, body = ordered.groups()
            prefix = f"{indent}{marker} "
            for rendered in _wrapped(body, width, prefix, " " * len(prefix)):
                emit(rendered, source_line)
            blank(source_line)
            continue

        quote = QUOTE_RE.match(line)
        if quote:
            prefix, body = quote.groups()
            for rendered in _wrapped(body, width, prefix, " " * len(prefix)):
                emit(rendered, source_line)
            blank(source_line)
            continue

        for rendered in _wrapped(line, width):
            emit(rendered, source_line)

    while output and output[-1] == "":
        output.pop()
        line_map.pop()

    rendered_text = "\n".join(output)
    if rendered_text:
        rendered_text += "\n"
    return Projection(rendered_text, line_map)


def write_projection(source: Path, output: Path, mapping: Path, width: int) -> None:
    projection = render_markdown(source.read_text(encoding="utf-8"), width)
    output.write_text(projection.text, encoding="utf-8")
    mapping.write_text(
        json.dumps(
            {
                "source": str(source),
                "projected": str(output),
                "line_map": projection.line_map,
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


def _mapped_line(mapping: dict[str, object], projected_line: int) -> int:
    values = mapping.get("line_map")
    if not isinstance(values, list) or not values:
        return projected_line
    position = max(1, min(projected_line, len(values))) - 1
    value = values[position]
    return value if isinstance(value, int) and value > 0 else projected_line


def remap_annotations(
    annotations: str,
    new_mapping: dict[str, object],
    old_mapping: dict[str, object] | None = None,
) -> str:
    """Translate projection line references back to canonical Markdown."""
    new_source = Path(str(new_mapping.get("source", "plan.md"))).name
    new_projected = Path(
        str(new_mapping.get("projected", "codex-plan.txt"))
    ).name
    old_projected = (
        Path(str(old_mapping.get("projected", "previous-plan.md"))).name
        if old_mapping
        else ""
    )
    old_source = (
        Path(str(old_mapping.get("source", "previous-plan.md"))).name
        if old_mapping
        else ""
    )
    result: list[str] = []
    for line in annotations.splitlines():
        match = ANNOTATION_RE.match(line)
        if not match:
            result.append(line)
            continue
        prefix, filename, start, end, kind = match.groups()
        use_old = old_mapping is not None and (
            kind.strip() == "-"
            or (
                old_projected != new_projected
                and Path(filename).name == old_projected
            )
        )
        mapping = old_mapping if use_old and old_mapping is not None else new_mapping
        canonical_name = old_source if use_old else new_source
        if start is None:
            result.append(f"{prefix}{canonical_name} ({kind})")
            continue
        mapped_start = _mapped_line(mapping, int(start))
        suffix = ""
        if end is not None:
            mapped_end = _mapped_line(mapping, int(end))
            if mapped_end != mapped_start:
                suffix = f"-{mapped_end}"
        result.append(f"{prefix}{canonical_name}:{mapped_start}{suffix} ({kind})")
    trailing = "\n" if annotations.endswith("\n") else ""
    return "\n".join(result) + trailing


def _projected_line(
    mapping: dict[str, object], source_line: int, *, last: bool = False
) -> int:
    values = mapping.get("line_map")
    if not isinstance(values, list) or not values:
        return source_line
    matches = [
        index + 1 for index, value in enumerate(values) if value == source_line
    ]
    if matches:
        return matches[-1] if last else matches[0]
    return min(
        range(1, len(values) + 1),
        key=lambda projected: (
            abs(int(values[projected - 1]) - source_line)
            if isinstance(values[projected - 1], int)
            else len(values)
        ),
    )


def project_annotations(
    annotations: str,
    new_mapping: dict[str, object],
    old_mapping: dict[str, object] | None = None,
    projected_name: str | None = None,
) -> str:
    """Translate canonical line references into the current projection."""
    target_name = projected_name or str(
        new_mapping.get("projected", "codex-plan.txt")
    )
    result: list[str] = []
    for line in annotations.splitlines():
        match = ANNOTATION_RE.match(line)
        if not match:
            result.append(line)
            continue
        prefix, _filename, start, end, kind = match.groups()
        mapping = (
            old_mapping
            if old_mapping is not None and kind.strip() == "-"
            else new_mapping
        )
        if start is None:
            result.append(f"{prefix}{target_name} ({kind})")
            continue
        projected_start = _projected_line(mapping, int(start))
        suffix = ""
        if end is not None:
            projected_end = _projected_line(mapping, int(end), last=True)
            if projected_end != projected_start:
                suffix = f"-{projected_end}"
        result.append(
            f"{prefix}{target_name}:{projected_start}{suffix} ({kind})"
        )
    trailing = "\n" if annotations.endswith("\n") else ""
    return "\n".join(result) + trailing


def read_mapping(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"invalid line map: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    render = subparsers.add_parser("render")
    render.add_argument("--source", type=Path, required=True)
    render.add_argument("--output", type=Path, required=True)
    render.add_argument("--map", dest="mapping", type=Path, required=True)
    render.add_argument("--width", type=int, required=True)

    remap = subparsers.add_parser("remap")
    remap.add_argument("--annotations", type=Path, required=True)
    remap.add_argument("--new-map", type=Path, required=True)
    remap.add_argument("--old-map", type=Path)

    args = parser.parse_args()
    if args.command == "render":
        write_projection(args.source, args.output, args.mapping, max(1, args.width))
        return

    annotations = args.annotations.read_text(encoding="utf-8")
    mapped = remap_annotations(
        annotations,
        read_mapping(args.new_map),
        read_mapping(args.old_map) if args.old_map else None,
    )
    args.annotations.write_text(mapped, encoding="utf-8")


if __name__ == "__main__":
    main()
