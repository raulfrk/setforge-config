#!/usr/bin/env python3
"""Prepare a plan projection, run RevDiff, and map annotations to source."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from plan_review_format import (
    read_mapping,
    remap_annotations,
    project_annotations,
    review_width,
    write_projection,
)


def terminal_columns() -> int:
    return shutil.get_terminal_size(fallback=(80, 24)).columns


def center_projection(path: Path, columns: int, width: int) -> None:
    """Center desktop projections without changing projected line numbers."""
    if columns < 90:
        return
    available = max(width, columns - 8)
    padding = max(0, (available - width) // 2)
    if padding == 0:
        return
    prefix = " " * padding
    lines = path.read_text(encoding="utf-8").splitlines()
    rendered = "\n".join(prefix + line if line else "" for line in lines)
    path.write_text(rendered + ("\n" if rendered else ""), encoding="utf-8")


def publish_generation(
    ready: Path, generation: int, columns: int, width: int
) -> None:
    temporary = ready.with_name(f"{ready.name}.tmp")
    temporary.write_text(
        json.dumps(
            {
                "generation": generation,
                "columns": columns,
                "content_width": width,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, ready)


def render_single(
    source: Path, view: Path, mapping: Path, columns: int, width: int
) -> None:
    write_projection(source, view, mapping, width)
    center_projection(view, columns, width)


def render_comparison(
    new: Path,
    old: Path,
    temp: Path,
    generation: int,
    new_mapping: Path,
    old_mapping: Path,
    columns: int,
    width: int,
) -> tuple[Path, Path]:
    """Represent responsive projections as a normal one-file Git diff."""
    repo = temp / f"comparison-{generation}"
    repo.mkdir()
    review_file = repo / "codex-plan.txt"
    render_single(old, review_file, old_mapping, columns, width)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "codex-plan.txt"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Plan Review",
            "-c",
            "user.email=plan-review.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-qm",
            "previous plan",
        ],
        cwd=repo,
        check=True,
    )
    render_single(new, review_file, new_mapping, columns, width)
    return repo, review_file


def run_revdiff(
    command: list[str],
    env: dict[str, str],
    cwd: Path | None,
    pane_id: str,
    initial_columns: int,
    handoff: Path,
) -> int:
    """Run RevDiff and request its lossless handoff after a stable resize."""
    process = subprocess.Popen(command, env=env, cwd=cwd)
    observed_columns = initial_columns
    changed_at: float | None = None
    while True:
        try:
            return process.wait(timeout=0.1)
        except subprocess.TimeoutExpired:
            current_columns = terminal_columns()
            if current_columns != observed_columns:
                observed_columns = current_columns
                changed_at = time.monotonic()
                continue
            if (
                current_columns != initial_columns
                and changed_at is not None
                and time.monotonic() - changed_at >= 0.25
            ):
                subprocess.run(
                    ["herdr", "pane", "send-keys", pane_id, "O"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                flush_deadline = time.monotonic() + 0.75
                while time.monotonic() < flush_deadline:
                    if handoff.exists():
                        return process.wait()
                    try:
                        return process.wait(timeout=0.05)
                    except subprocess.TimeoutExpired:
                        pass

                # RevDiff intentionally ignores O when there are no
                # annotations. Record that empty handoff and close only this
                # generation so the outer loop can reopen at the new width.
                handoff.touch()
                subprocess.run(
                    ["herdr", "pane", "send-keys", pane_id, "q"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                return process.wait()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--revdiff", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--old", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ready", type=Path, required=True)
    args = parser.parse_args()

    args.ready.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="plan-review-view-") as temp_value:
        temp = Path(temp_value)
        new_view = temp / "codex-plan.txt"
        new_map = temp / "codex-plan.map.json"
        old_map: Path | None = None
        if args.old is not None:
            old_map = temp / "previous-plan.map.json"
        handoff = temp / "handoff.md"
        preload = temp / "preload.md"
        generation = 0
        pending_flush: str | None = None
        env = os.environ.copy()
        env["REVDIFF_EXIT_CODE_ON_ANNOTATIONS"] = "true"
        pane_id = os.environ.get("HERDR_PANE_ID", "")
        if not pane_id:
            raise RuntimeError("HERDR_PANE_ID is required for annotation handoff")
        handoff_command = (
            f"cat > {shlex.quote(str(handoff))} && "
            f"herdr pane send-keys {shlex.quote(pane_id)} q"
        )
        result = 0
        try:
            while True:
                columns = terminal_columns()
                width = review_width(columns)
                try:
                    if args.old is None:
                        render_single(
                            args.new, new_view, new_map, columns, width
                        )
                        run_cwd = None
                        only_path = str(new_view)
                        projected_name = str(new_view)
                    else:
                        assert old_map is not None
                        run_cwd, new_view = render_comparison(
                            args.new,
                            args.old,
                            temp,
                            generation,
                            new_map,
                            old_map,
                            columns,
                            width,
                        )
                        only_path = "codex-plan.txt"
                        projected_name = only_path
                    if pending_flush is not None:
                        preload.write_text(
                            project_annotations(
                                pending_flush,
                                read_mapping(new_map),
                                read_mapping(old_map)
                                if old_map is not None
                                else None,
                                projected_name,
                            ),
                            encoding="utf-8",
                        )
                except (OSError, subprocess.SubprocessError, ValueError) as error:
                    if pending_flush is None:
                        raise
                    print(
                        f"error: annotation reflow failed; returning the last flush: {error}",
                        file=sys.stderr,
                    )
                    return 10
                if pending_flush is not None:
                    pending_flush = None
                    args.output.unlink(missing_ok=True)

                publish_generation(
                    args.ready, generation + 1, columns, width
                )
                command = [
                    str(args.revdiff),
                    f"--only={only_path}",
                    f"--output={args.output}",
                    f"--post-flush-command={handoff_command}",
                ]
                if preload.is_file() and preload.stat().st_size:
                    command.append(f"--annotations={preload}")
                result = run_revdiff(
                    command, env, run_cwd, pane_id, columns, handoff
                )
                if not handoff.is_file():
                    break

                raw = handoff.read_text(encoding="utf-8")
                canonical = remap_annotations(
                    raw,
                    read_mapping(new_map),
                    read_mapping(old_map) if old_map is not None else None,
                )
                # Preserve the flush before any operation required for the
                # replacement projection can fail.
                args.output.write_text(canonical, encoding="utf-8")
                generation += 1
                pending_flush = canonical
                handoff.unlink()
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
        return result


if __name__ == "__main__":
    raise SystemExit(main())
