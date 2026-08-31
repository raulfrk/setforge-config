#!/usr/bin/env python3
"""Prepare a plan projection, run RevDiff, and map annotations to source."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from plan_review_format import (
    read_mapping,
    remap_annotations,
    review_width,
    write_projection,
)


def terminal_columns() -> int:
    return shutil.get_terminal_size(fallback=(80, 24)).columns


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--revdiff", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--old", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ready", type=Path, required=True)
    args = parser.parse_args()

    columns = terminal_columns()
    width = review_width(columns)
    args.ready.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="plan-review-view-") as temp_value:
        temp = Path(temp_value)
        new_view = temp / "codex-plan.md"
        new_map = temp / "codex-plan.map.json"
        write_projection(args.new, new_view, new_map, width)

        old_view: Path | None = None
        old_map: Path | None = None
        if args.old is not None:
            old_view = temp / "previous-plan.md"
            old_map = temp / "previous-plan.map.json"
            write_projection(args.old, old_view, old_map, width)

        args.ready.write_text(
            json.dumps({"columns": columns, "content_width": width}) + "\n",
            encoding="utf-8",
        )

        command = [str(args.revdiff)]
        if old_view is None:
            command.extend(["--stdin", "--stdin-name=codex-plan.md"])
        else:
            command.extend(
                [
                    f"--compare-old={old_view}",
                    f"--compare-new={new_view}",
                    "--collapsed",
                ]
            )
        command.append(f"--output={args.output}")

        env = os.environ.copy()
        env["REVDIFF_EXIT_CODE_ON_ANNOTATIONS"] = "true"
        try:
            if old_view is None:
                with new_view.open("r", encoding="utf-8") as stream:
                    result = subprocess.run(command, stdin=stream, env=env, check=False)
            else:
                result = subprocess.run(command, env=env, check=False)
        except KeyboardInterrupt:
            return 130

        if args.output.is_file() and args.output.stat().st_size:
            annotations = args.output.read_text(encoding="utf-8")
            mapped = remap_annotations(
                annotations,
                read_mapping(new_map),
                read_mapping(old_map) if old_map is not None else None,
            )
            args.output.write_text(mapped, encoding="utf-8")
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
