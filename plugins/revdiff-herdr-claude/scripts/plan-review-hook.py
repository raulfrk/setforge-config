#!/usr/bin/env python3
"""Review completed Claude Code plans through the ExitPlanMode PreToolUse hook."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

MARKER_RE = re.compile(r"^\s*<!--\s*previous revision:\s*(.+?)\s*-->\s*$")
SNAPSHOT_PREFIX = "plan-rev-"
SUCCESS_CODES = {0, 10}


def ask(reason: str = "") -> None:
    """Continue to Claude Code's own plan approval prompt."""
    output: dict[str, Any] = {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
    }
    if reason:
        output["permissionDecisionReason"] = reason
    print(json.dumps({"hookSpecificOutput": output}, separators=(",", ":")))


def review_failed(message: str) -> None:
    # The native approval prompt still follows, so a failed review must be
    # visible there instead of looking like an annotation-free review.
    ask(
        f"RevDiff plan review failed: {message}. "
        "The plan was NOT reviewed in RevDiff; "
        "this is not an annotation-free review."
    )


def deny(reason: str) -> None:
    """Block ExitPlanMode and return the reason to Claude."""
    print(reason, file=sys.stderr)
    sys.exit(2)


def read_event() -> dict[str, Any] | None:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return None
    return event if isinstance(event, dict) else None


def trusted_snapshot(path: Path) -> Path | None:
    """Return a canonical snapshot path confined to this hook's temp files."""
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not resolved.is_file() or not resolved.name.startswith(SNAPSHOT_PREFIX):
        return None
    try:
        resolved.relative_to(Path(tempfile.gettempdir()).resolve())
    except ValueError:
        return None
    return resolved


def resolve_launcher(plugin_root: Path, data_dir: str, cwd: object, name: str) -> Path | None:
    resolver = plugin_root / "scripts" / "resolve-launcher.sh"
    if not resolver.is_file():
        return None
    working_dir = cwd if isinstance(cwd, str) and Path(cwd).is_dir() else None
    try:
        result = subprocess.run(
            [str(resolver), name, data_dir],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=working_dir,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    path = Path(result.stdout.strip())
    return path if path.is_file() and os.access(path, os.X_OK) else None


def main() -> None:
    event = read_event()
    if event is None:
        review_failed("invalid PreToolUse hook JSON payload")
        return
    if event.get("hook_event_name") != "PreToolUse" or event.get("tool_name") != "ExitPlanMode":
        return

    tool_input = event.get("tool_input")
    plan = tool_input.get("plan") if isinstance(tool_input, dict) else None
    if not isinstance(plan, str) or not plan.strip():
        review_failed("the hook event contained no plan text")
        return

    first_line, separator, rest = plan.partition("\n")
    marker = MARKER_RE.match(first_line)
    if marker:
        plan = rest if separator else ""

    plugin_root_value = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not plugin_root_value:
        review_failed("CLAUDE_PLUGIN_ROOT is not set")
        return
    if not shutil.which("revdiff"):
        review_failed("revdiff binary is not available on PATH")
        return

    cwd = event.get("cwd")
    launcher = resolve_launcher(
        Path(plugin_root_value), os.environ.get("CLAUDE_PLUGIN_DATA", ""), cwd, "launch-revdiff.sh"
    )
    if launcher is None:
        review_failed("no executable launch-revdiff.sh was found")
        return

    old_snapshot = None
    if marker:
        old_snapshot = trusted_snapshot(Path(marker.group(1)))
        if old_snapshot is None:
            review_failed("the previous revision snapshot is unavailable")
            return

    new_snapshot: Path | None = None
    operation = "snapshot"
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", prefix=SNAPSHOT_PREFIX, delete=False
        ) as tmp:
            new_snapshot = Path(tmp.name)
            tmp.write(plan)
        operation = "launcher"
        args = [str(launcher), f"--only={new_snapshot}"]
        if old_snapshot is not None:
            args = [
                str(launcher),
                f"--compare-old={old_snapshot}",
                f"--compare-new={new_snapshot}",
            ]
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=345600,
            cwd=cwd if isinstance(cwd, str) and Path(cwd).is_dir() else None,
            check=False,
        )
    except KeyboardInterrupt:
        if new_snapshot is not None:
            new_snapshot.unlink(missing_ok=True)
        review_failed("launcher was interrupted")
        return
    except subprocess.TimeoutExpired:
        if new_snapshot is not None:
            new_snapshot.unlink(missing_ok=True)
        review_failed("launcher timed out")
        return
    except OSError:
        if new_snapshot is not None:
            new_snapshot.unlink(missing_ok=True)
        review_failed(
            "plan snapshot could not be written"
            if operation == "snapshot"
            else "launcher could not be started"
        )
        return

    assert new_snapshot is not None
    if result.returncode not in SUCCESS_CODES:
        new_snapshot.unlink(missing_ok=True)
        detail = result.stderr.strip()[-2000:]
        review_failed(
            f"launcher exited with status {result.returncode}" + (f": {detail}" if detail else "")
        )
        return

    annotations = result.stdout.strip()
    if result.returncode == 10 and not annotations:
        new_snapshot.unlink(missing_ok=True)
        review_failed("launcher reported annotations but returned no annotation text")
        return

    if old_snapshot is not None:
        old_snapshot.unlink(missing_ok=True)

    if not annotations:
        new_snapshot.unlink(missing_ok=True)
        ask("Plan reviewed in RevDiff with no annotations.")
        return

    deny(
        "The user reviewed the plan in RevDiff and added annotations. "
        "Revise the plan to address every annotation, then call ExitPlanMode again "
        "with the complete revised plan for another review.\n\n"
        f"{annotations}\n\n"
        "IMPORTANT: put this marker on the very first line of the revised plan. "
        "Do NOT substitute any other plan-rev-*.md path you may have seen earlier in "
        "this conversation; older markers belong to unrelated planning tasks and "
        "would compare against the wrong baseline:\n"
        f"<!-- previous revision: {new_snapshot} -->"
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # main() has already lost track of the reviewer here, so stay neutral.
        ask(
            "Plan review failed: the review was interrupted. "
            "The plan was NOT reviewed; this is not an annotation-free review."
        )
