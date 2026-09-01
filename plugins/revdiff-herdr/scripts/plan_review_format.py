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
BULLET_RE = re.compile(r"^(\s*)([-+*])\s+(.*)$")
ORDERED_RE = re.compile(r"^(\s*)(\d+[.)])\s+(.*)$")
QUOTE_RE = re.compile(r"^(\s*>\s?)(.*)$")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
LINK_DEFINITION_RE = re.compile(r"^\s{0,3}\[[^]]+\]:\s*\S+")
TABLE_DELIMITER_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
SETEXT_UNDERLINE_RE = re.compile(r"^\s{0,3}(?:=+|-+)\s*$")
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


def _is_plain_paragraph_line(lines: list[str], index: int) -> bool:
    line = lines[index]
    return bool(line.strip()) and not any(
        (
            FENCE_RE.match(line),
            ATX_HEADING_RE.match(line),
            line.startswith("    "),
            line.startswith("\t"),
            LINK_DEFINITION_RE.match(line),
            _is_table_line(lines, index),
            re.match(r"^\s{0,3}(?:---+|___+|\*\*\*+)\s*$", line),
            BULLET_RE.match(line),
            ORDERED_RE.match(line),
            QUOTE_RE.match(line),
        )
    )


def _has_hard_break(line: str) -> bool:
    return line.endswith("  ") or line.rstrip().endswith("\\")


def _starts_setext_heading(lines: list[str], index: int) -> bool:
    return (
        bool(lines[index].strip())
        and index + 1 < len(lines)
        and bool(SETEXT_UNDERLINE_RE.match(lines[index + 1]))
    )


def _coalesce_soft_wrapped_paragraphs(source_lines: list[str]) -> tuple[list[str], list[int]]:
    """Join ordinary Markdown soft wraps while retaining canonical line origins."""
    logical: list[str] = []
    origins: list[int] = []
    index = 0
    in_fence = False
    fence_marker = ""
    while index < len(source_lines):
        line = source_lines[index]
        fence = FENCE_RE.match(line)
        if in_fence:
            logical.append(line)
            origins.append(index + 1)
            if (
                fence
                and fence.group(1).startswith(fence_marker[0])
                and len(fence.group(1)) >= len(fence_marker)
            ):
                in_fence = False
                fence_marker = ""
            index += 1
            continue
        if fence:
            in_fence = True
            fence_marker = fence.group(1)
            logical.append(line)
            origins.append(index + 1)
            index += 1
            continue
        if _starts_setext_heading(source_lines, index):
            logical.extend((line, source_lines[index + 1]))
            origins.extend((index + 1, index + 2))
            index += 2
            continue
        if not _is_plain_paragraph_line(source_lines, index):
            logical.append(line)
            origins.append(index + 1)
            index += 1
            continue

        origin = index + 1
        parts = [line.strip()]
        hard_spaces = line.endswith("  ")
        while (
            not _has_hard_break(source_lines[index])
            and index + 1 < len(source_lines)
            and _is_plain_paragraph_line(source_lines, index + 1)
            and not _starts_setext_heading(source_lines, index + 1)
        ):
            index += 1
            parts.append(source_lines[index].strip())
            hard_spaces = source_lines[index].endswith("  ")
        paragraph = " ".join(parts)
        if hard_spaces:
            paragraph = paragraph.rstrip() + "  "
        logical.append(paragraph)
        origins.append(origin)
        index += 1
    return logical, origins


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
    source_lines, source_origins = _coalesce_soft_wrapped_paragraphs(
        source.splitlines()
    )
    output: list[str] = []
    line_map: list[int] = []
    in_fence = False
    fence_marker = ""

    def emit(value: str, source_line: int, *, preserve_trailing: bool = False) -> None:
        output.append(value if preserve_trailing else value.rstrip())
        line_map.append(source_line)

    def blank(source_line: int) -> None:
        if output and output[-1] != "":
            emit("", source_line)

    for index, line in enumerate(source_lines):
        source_line = source_origins[index]
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
            prefix = f"{heading.group(1)} "
            for rendered in _wrapped(
                heading.group(2), width, prefix, " " * len(prefix)
            ):
                emit(rendered, source_line)
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
            indent, marker, body = bullet.groups()
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

        hard_spaces = line.endswith("  ")
        body = line[:-2] if hard_spaces else line
        rendered_lines = _wrapped(body, width)
        if hard_spaces:
            rendered_lines[-1] += "  "
        for rendered in rendered_lines:
            emit(rendered, source_line, preserve_trailing=hard_spaces)

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
        str(new_mapping.get("projected", "codex-plan.md"))
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
        new_mapping.get("projected", "codex-plan.md")
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
