#!/usr/bin/env python3
"""Prepare a plan projection, run RevDiff, and map annotations to source."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
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


def projection_geometry(columns: int) -> tuple[int, int]:
    """Return every terminal dimension that changes projected bytes."""
    width = review_width(columns)
    if columns < 90:
        return width, 0
    available = max(width, columns - 8)
    return width, max(0, (available - width) // 2)


def center_projection(path: Path, padding: int) -> None:
    """Center desktop projections without changing projected line numbers."""
    if padding == 0:
        return
    prefix = " " * padding
    lines = path.read_text(encoding="utf-8").splitlines()
    rendered = "\n".join(prefix + line if line else "" for line in lines)
    path.write_text(rendered + ("\n" if rendered else ""), encoding="utf-8")


def render_single(
    source: Path, view: Path, mapping: Path, width: int, padding: int
) -> None:
    write_projection(source, view, mapping, width)
    center_projection(view, padding)


def create_baseline_repo(
    repo: Path,
    source: Path,
    mapping: Path,
    width: int,
    padding: int,
    message: str,
) -> Path:
    """Create the clean tracked Markdown file required by RevDiff context mode."""
    repo.mkdir()
    review_file = repo / "codex-plan.md"
    render_single(source, review_file, mapping, width, padding)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "codex-plan.md"], cwd=repo, check=True)
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
            message,
        ],
        cwd=repo,
        check=True,
    )
    return review_file


def render_comparison(
    new: Path,
    old: Path,
    temp: Path,
    generation: int,
    new_mapping: Path,
    old_mapping: Path,
    width: int,
    padding: int,
) -> tuple[Path, Path]:
    """Represent responsive projections as a normal one-file Git diff."""
    repo = temp / f"comparison-{generation}"
    review_file = create_baseline_repo(
        repo, old, old_mapping, width, padding, "previous plan"
    )
    render_single(new, review_file, new_mapping, width, padding)
    return repo, review_file


def render_context(
    source: Path,
    temp: Path,
    generation: int,
    mapping: Path,
    width: int,
    padding: int,
) -> tuple[Path, Path]:
    """Represent a clean Markdown document as repository-backed context."""
    repo = temp / f"context-{generation}"
    review_file = create_baseline_repo(
        repo, source, mapping, width, padding, "plan context"
    )
    return repo, review_file


def annotation_input_active(screen: str) -> bool:
    """Recognize RevDiff annotation mode even when its status line wraps."""
    return "[enter] save" in screen and "[esc] cancel" in screen


def pane_ready_for_reflow(pane_id: str, child_pid: int) -> bool:
    """Fail closed unless the exact RevDiff child is foreground and non-modal."""
    try:
        info = subprocess.run(
            ["herdr", "pane", "process-info", "--pane", pane_id],
            text=True,
            capture_output=True,
            timeout=1,
            check=False,
        )
        if info.returncode != 0:
            return False
        payload = json.loads(info.stdout)
        processes = payload["result"]["process_info"]["foreground_processes"]
        if not any(
            process.get("name") == "revdiff" and process.get("pid") == child_pid
            for process in processes
        ):
            return False

        screen = subprocess.run(
            [
                "herdr",
                "pane",
                "read",
                pane_id,
                "--source",
                "visible",
                "--lines",
                "6",
                "--format",
                "text",
            ],
            text=True,
            capture_output=True,
            timeout=1,
            check=False,
        )
        return screen.returncode == 0 and not annotation_input_active(screen.stdout)
    except (KeyError, OSError, TypeError, ValueError, subprocess.TimeoutExpired):
        return False


def extract_history_annotations(history: str) -> str:
    """Extract Store.FormatOutput content from a RevDiff history record."""
    marker = "\n## Annotations\n\n"
    if marker not in history:
        raise ValueError("RevDiff history record has no annotations section")
    annotations = history.split(marker, 1)[1]
    diff_marker = "\n---\n\n## Diff\n\n"
    if diff_marker in annotations:
        annotations = annotations.rsplit(diff_marker, 1)[0]
    return annotations.rstrip("\n")


def read_generation_history(history_dir: Path) -> str:
    records = list(history_dir.glob("*/*.md"))
    if len(records) > 1:
        raise ValueError("RevDiff wrote multiple history records for one generation")
    if not records:
        return ""
    return extract_history_annotations(records[0].read_text(encoding="utf-8"))


def write_checkpoint(path: Path, content: str) -> None:
    """Atomically replace the canonical annotation checkpoint."""
    if not content:
        path.unlink(missing_ok=True)
        return
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


@dataclass(frozen=True)
class RevDiffResult:
    code: int
    reflow: bool
    geometry: tuple[int, int]


def run_revdiff(
    command: list[str],
    env: dict[str, str],
    cwd: Path | None,
    pane_id: str,
    initial_geometry: tuple[int, int],
) -> RevDiffResult:
    """Run RevDiff and terminate it once the latest safe geometry settles."""
    process = subprocess.Popen(command, env=env, cwd=cwd)
    observed_geometry = initial_geometry
    changed_at: float | None = None
    while True:
        try:
            return RevDiffResult(process.wait(timeout=0.1), False, initial_geometry)
        except subprocess.TimeoutExpired:
            current_geometry = projection_geometry(terminal_columns())
            if current_geometry != observed_geometry:
                observed_geometry = current_geometry
                changed_at = (
                    time.monotonic()
                    if current_geometry != initial_geometry
                    else None
                )
                continue
            if (
                current_geometry != initial_geometry
                and changed_at is not None
                and time.monotonic() - changed_at >= 0.75
            ):
                if not pane_ready_for_reflow(pane_id, process.pid):
                    continue
                # Inspection can take long enough for another resize. Never
                # terminate a generation for geometry that is already stale.
                latest_geometry = projection_geometry(terminal_columns())
                if latest_geometry != current_geometry:
                    observed_geometry = latest_geometry
                    changed_at = (
                        time.monotonic()
                        if latest_geometry != initial_geometry
                        else None
                    )
                    continue
                if process.poll() is not None:
                    return RevDiffResult(process.returncode, False, initial_geometry)
                try:
                    process.terminate()
                except ProcessLookupError:
                    return RevDiffResult(process.wait(), False, initial_geometry)
                return RevDiffResult(process.wait(), True, current_geometry)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--revdiff", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--old", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    descriptions = parser.add_mutually_exclusive_group()
    descriptions.add_argument("--description")
    descriptions.add_argument("--description-file", type=Path)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="plan-review-view-") as temp_value:
        temp = Path(temp_value)
        new_view = temp / "codex-plan.md"
        new_map = temp / "codex-plan.map.json"
        old_map: Path | None = None
        if args.old is not None:
            old_map = temp / "previous-plan.map.json"
        preload = temp / "preload.md"
        generation = 0
        pending_annotations: str | None = None
        next_geometry: tuple[int, int] | None = None
        env = os.environ.copy()
        env["REVDIFF_EXIT_CODE_ON_ANNOTATIONS"] = "true"
        pane_id = os.environ.get("HERDR_PANE_ID", "")
        if not pane_id:
            raise RuntimeError("HERDR_PANE_ID is required for annotation handoff")
        result = 0
        try:
            while True:
                geometry = next_geometry or projection_geometry(terminal_columns())
                next_geometry = None
                width, padding = geometry
                try:
                    if args.old is None:
                        run_cwd, new_view = render_context(
                            args.new,
                            temp,
                            generation,
                            new_map,
                            width,
                            padding,
                        )
                        only_path = "codex-plan.md"
                        projected_name = only_path
                    else:
                        assert old_map is not None
                        run_cwd, new_view = render_comparison(
                            args.new,
                            args.old,
                            temp,
                            generation,
                            new_map,
                            old_map,
                            width,
                            padding,
                        )
                        only_path = "codex-plan.md"
                        projected_name = only_path
                    if pending_annotations is not None:
                        projected = project_annotations(
                            pending_annotations,
                            read_mapping(new_map),
                            read_mapping(old_map)
                            if old_map is not None
                            else None,
                            projected_name,
                        )
                        if projected:
                            preload.write_text(
                                projected,
                                encoding="utf-8",
                            )
                        else:
                            preload.unlink(missing_ok=True)
                except (OSError, subprocess.SubprocessError, ValueError) as error:
                    if pending_annotations is None:
                        raise
                    print(
                        f"error: annotation reflow failed; returning the last flush: {error}",
                        file=sys.stderr,
                    )
                    return 10
                pending_annotations = None
                generation_output = temp / f"output-{generation}.md"
                history_dir = temp / f"history-{generation}"
                command = [
                    str(args.revdiff),
                    f"--only={only_path}",
                    f"--output={generation_output}",
                    f"--history-dir={history_dir}",
                ]
                if args.description is not None:
                    command.append(f"--description={args.description}")
                elif args.description_file is not None:
                    command.append(f"--description-file={args.description_file}")
                if preload.is_file() and preload.stat().st_size:
                    command.append(f"--annotations={preload}")
                run_result = run_revdiff(command, env, run_cwd, pane_id, geometry)
                result = run_result.code
                if not run_result.reflow:
                    if result in (0, 10):
                        raw = (
                            generation_output.read_text(encoding="utf-8")
                            if generation_output.is_file()
                            else ""
                        )
                        canonical = remap_annotations(
                            raw,
                            read_mapping(new_map),
                            read_mapping(old_map) if old_map is not None else None,
                        )
                        write_checkpoint(args.output, canonical)
                    break

                raw = read_generation_history(history_dir)
                canonical = remap_annotations(
                    raw,
                    read_mapping(new_map),
                    read_mapping(old_map) if old_map is not None else None,
                )
                # Preserve the flush before any operation required for the
                # replacement projection can fail.
                write_checkpoint(args.output, canonical)
                generation += 1
                pending_annotations = canonical
                next_geometry = run_result.geometry
        except KeyboardInterrupt:
            return 130
        return result


if __name__ == "__main__":
    raise SystemExit(main())
