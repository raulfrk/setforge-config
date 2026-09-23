#!/usr/bin/env python3
"""Switch a completed Codex root between collaboration modes in place."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence


PLACEHOLDER = "› Ask Codex to do anything"
POLL_SECONDS = 0.25
STABLE_SECONDS = 1.0
INPUT_SETTLE_SECONDS = 0.1
TIMEOUT_SECONDS = 120.0
EFFORTS = frozenset(("low", "medium", "high", "xhigh", "max", "ultra"))
PLAN_INDICATOR = re.compile(
    r"(?:^| · | {2,}|(?<=…) )"
    r"Plan mode(?: \(shift\+tab to cycle\))?(?=$| · | {2,})"
)
STATUS_FIELD = re.compile(
    r"^(Session|Model|Reasoning(?: effort)?|Directory|Collaboration mode):"
    r"\s*(.*?)\s*$"
)


class HandoffError(RuntimeError):
    """A terminal, identity, or ordering condition made the handoff unsafe."""


@dataclass(frozen=True)
class PaneIdentity:
    pane_id: str
    tab_id: str
    workspace_id: str
    record: Mapping[str, Any]


@dataclass(frozen=True)
class Surface:
    model: str
    effort: str
    cwd: str
    mode: str | None
    footer: str


@dataclass(frozen=True)
class Status:
    thread_id: str
    model: str
    effort: str
    cwd: str
    mode: str


def log(message: str) -> None:
    print(
        f"{datetime.now().astimezone().isoformat(timespec='seconds')} {message}",
        file=sys.stderr,
        flush=True,
    )


def safe_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", value):
        raise HandoffError(f"{label} is not a safe identifier")
    return value


def run(command: Sequence[str], deadline: float) -> str:
    if not command or any(not isinstance(part, str) or "\x00" in part for part in command):
        raise HandoffError("Herdr command contains an invalid argument")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise HandoffError("handoff deadline exceeded")
    long_operation = "agent" in command and "prompt" in command and "--wait" in command
    try:
        result = subprocess.run(
            list(command),
            text=True,
            capture_output=True,
            timeout=remaining if long_operation else min(5.0, remaining),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HandoffError(f"Herdr command timed out: {command[0]}") from exc
    except OSError as exc:
        raise HandoffError(f"could not execute Herdr: {exc}") from exc
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise HandoffError(f"Herdr command failed ({result.returncode}): {detail}")
    return result.stdout


def prefix(session: str) -> list[str]:
    return ["herdr", "--session", safe_id(session, "session")]


def json_result(raw: str) -> Mapping[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HandoffError("Herdr response was not JSON") from exc
    if not isinstance(data, Mapping):
        raise HandoffError("Herdr response was not an object")
    result = data.get("result", data)
    if not isinstance(result, Mapping):
        raise HandoffError("Herdr result was not an object")
    return result


def list_panes(session: str, deadline: float) -> list[Mapping[str, Any]]:
    result = json_result(run(prefix(session) + ["pane", "list"], deadline))
    panes = result.get("panes")
    if not isinstance(panes, list) or any(not isinstance(item, Mapping) for item in panes):
        raise HandoffError("Herdr pane list was malformed")
    return list(panes)


def location(pane: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        safe_id(pane.get("pane_id"), "pane.pane_id"),
        safe_id(pane.get("tab_id"), "pane.tab_id"),
        safe_id(pane.get("workspace_id"), "pane.workspace_id"),
    )


def pinned_pane(
    session: str,
    pinned: tuple[str, str, str],
    deadline: float,
) -> PaneIdentity:
    matches = [pane for pane in list_panes(session, deadline) if location(pane) == pinned]
    if len(matches) != 1:
        raise HandoffError("pinned pane identity changed or disappeared")
    pane = matches[0]
    if pane.get("agent") != "codex":
        raise HandoffError("pinned pane is no longer running Codex")
    return PaneIdentity(*location(pane), pane)


def read_pane(session: str, pane_id: str, deadline: float, lines: int = 240) -> str:
    return run(
        prefix(session)
        + ["pane", "read", pane_id, "--source", "recent-unwrapped", "--lines", str(lines)],
        deadline,
    )


def extract_cwd(result: Mapping[str, Any]) -> str | None:
    process = result.get("process_info", result)
    if not isinstance(process, Mapping):
        return None
    foreground = process.get("foreground_processes")
    if not isinstance(foreground, list):
        return None
    values = [item.get("cwd") for item in foreground if isinstance(item, Mapping)]
    paths = [value for value in values if isinstance(value, str)]
    return paths[0] if paths and len(set(paths)) == 1 else None


def same_cwd(expected: Path, observed: str) -> bool:
    return expected.expanduser().resolve(strict=False) == Path(observed).expanduser().resolve(
        strict=False
    )


def observed_cwd(
    session: str,
    pane: PaneIdentity,
    expected: Path,
    deadline: float,
) -> str:
    candidate = pane.record.get("foreground_cwd") or pane.record.get("cwd")
    if isinstance(candidate, str) and same_cwd(expected, candidate):
        return candidate
    candidate = extract_cwd(
        json_result(
            run(
                prefix(session)
                + ["pane", "process-info", "--pane", pane.pane_id],
                deadline,
            )
        )
    )
    if not candidate or not same_cwd(expected, candidate):
        raise HandoffError("Herdr pane cwd does not match the expected cwd")
    return candidate


def marker_tail(text: str, marker: str) -> list[str] | None:
    lines = text.splitlines()
    accepted = {marker, f"• {marker}"}
    matches = [index for index, line in enumerate(lines) if line.strip() in accepted]
    return None if not matches else lines[matches[-1] + 1 :]


def completion(text: str, marker: str) -> bool:
    tail = marker_tail(text, marker)
    if tail is None:
        return False
    prompts = [line.strip() for line in tail if line.lstrip().startswith("›")]
    if any(prompt != PLACEHOLDER for prompt in prompts):
        raise HandoffError("new user input or a nonempty composer appeared after the marker")
    stripped = [line.strip() for line in tail]
    if any(
        line.startswith(("Do you trust", "Press enter to continue", "Allow command"))
        or line.lower() == "approval required"
        for line in stripped
    ):
        raise HandoffError("a dialog or approval prompt appeared after the marker")
    active = any(line.startswith(("• Working", "• Thinking")) for line in stripped)
    return bool(prompts) and prompts[-1] == PLACEHOLDER and not active


def surface(screen: str) -> Surface | None:
    lines = screen.splitlines()
    prompts = [index for index, line in enumerate(lines) if line.strip() == PLACEHOLDER]
    if not prompts:
        return None
    suffix = [line.strip() for line in lines[prompts[-1] + 1 :] if line.strip()]
    if any(
        line.startswith(("• Working", "• Thinking", "Do you trust", "Allow command", "›"))
        for line in suffix
    ):
        return None
    candidates: list[tuple[str, list[str]]] = []
    for line in suffix:
        pieces = [part.strip() for part in line.split("·")]
        route = pieces[0].split() if pieces else []
        if len(pieces) >= 2 and len(route) == 2 and route[1] in EFFORTS:
            candidates.append((line, pieces))
    if not candidates:
        return None
    footer, pieces = candidates[-1]
    model, effort = pieces[0].split()
    mode = None
    if PLAN_INDICATOR.search(footer):
        mode = "plan"
    elif re.search(r"(?:^| · )Main \[default\](?:$| · )", footer) or (
        "Plan mode" not in footer
        and re.search(
            r"(?:^| · )Context \d+% left(?: ·…)?(?: · ← for agents)?$",
            footer,
        )
    ):
        mode = "default"
    return Surface(model, effort, pieces[1], mode, footer)


def discover_marker_pane(
    session: str,
    marker: str,
    expected_cwd: Path,
    deadline: float,
) -> PaneIdentity:
    stable_since = None
    previous = None
    pinned = None
    while time.monotonic() < deadline:
        candidates: list[tuple[PaneIdentity, str]] = []
        for record in list_panes(session, deadline):
            if record.get("agent") != "codex":
                continue
            pane = PaneIdentity(*location(record), record)
            try:
                observed_cwd(session, pane, expected_cwd, deadline)
                screen = read_pane(session, pane.pane_id, deadline)
                if completion(screen, marker) and surface(screen) is not None:
                    candidates.append((pane, screen))
            except HandoffError:
                continue
        if len(candidates) > 1:
            raise HandoffError("completed handoff marker appears in multiple Codex panes")
        if len(candidates) == 1:
            pane, screen = candidates[0]
            candidate_pin = (pane.pane_id, pane.tab_id, pane.workspace_id)
            if pinned is not None and candidate_pin != pinned:
                raise HandoffError("handoff marker moved between panes")
            pinned = candidate_pin
            key = screen
            now = time.monotonic()
            status = pane.record.get("agent_status", pane.record.get("status"))
            idle = not isinstance(status, str) or status in ("idle", "done", "unknown")
            if idle and key == previous and stable_since is not None:
                if now - stable_since >= STABLE_SECONDS:
                    log(f"READY pane={pane.pane_id}")
                    return pane
            else:
                previous = key
                stable_since = now if idle else None
        else:
            previous = None
            stable_since = None
        time.sleep(POLL_SECONDS)
    raise HandoffError("timed out waiting for the stable completed Codex marker")


def status_field(line: str) -> re.Match[str] | None:
    candidate = line.strip()
    if candidate.startswith("│"):
        candidate = candidate[1:].strip()
    if candidate.endswith("│"):
        candidate = candidate[:-1].strip()
    return STATUS_FIELD.match(candidate)


def status_panel(screen: str) -> Status:
    lines = screen.splitlines()
    session_rows = [
        index
        for index, line in enumerate(lines)
        if (match := status_field(line)) is not None and match.group(1) == "Session"
    ]
    if not session_rows:
        raise HandoffError("Codex /status panel has no exact Session field")
    session_index = session_rows[-1]
    top = next(
        (index for index in range(session_index - 1, max(-1, session_index - 45), -1)
         if lines[index].strip().startswith(("╭", "┌"))),
        None,
    )
    bottom = next(
        (index for index in range(session_index + 1, min(len(lines), session_index + 45))
         if lines[index].strip().startswith(("╰", "└"))),
        None,
    )
    if top is None or bottom is None:
        raise HandoffError("Codex /status panel has incomplete borders")
    fields: dict[str, str] = {}
    for line in lines[top + 1 : bottom]:
        match = status_field(line)
        if match is None:
            continue
        key = "Reasoning" if match.group(1).startswith("Reasoning") else match.group(1)
        fields[key] = match.group(2)
    missing = [key for key in ("Session", "Model", "Directory", "Collaboration mode") if key not in fields]
    if missing:
        raise HandoffError("Codex /status panel is missing fields: " + ", ".join(missing))
    model_text = fields["Model"].strip()
    combined = re.match(r"^(\S+) \(reasoning (\w+)(?:,|\))", model_text)
    if combined:
        model, effort = combined.groups()
    elif "Reasoning" in fields:
        model, effort = model_text, fields["Reasoning"].split()[0]
    else:
        raise HandoffError("Codex /status panel has no exact reasoning effort")
    return Status(
        safe_id(fields["Session"], "status.Session"),
        model,
        effort,
        fields["Directory"],
        fields["Collaboration mode"].strip().lower(),
    )


def send_keys(
    session: str,
    pane_id: str,
    keys: Sequence[str],
    deadline: float,
) -> None:
    if not keys:
        return
    run(prefix(session) + ["agent", "send-keys", pane_id, *keys], deadline)


def submit_literal(session: str, pane_id: str, text: str, deadline: float) -> None:
    if not text.startswith("/") or any(char in text for char in "\r\n\x00"):
        raise HandoffError("only one literal slash command may be submitted")
    run(prefix(session) + ["pane", "send-text", pane_id, text], deadline)
    time.sleep(INPUT_SETTLE_SECONDS)
    send_keys(session, pane_id, ["enter"], deadline)


def wait_status(
    session: str,
    pinned: tuple[str, str, str],
    expected_thread: str,
    expected_cwd: Path,
    deadline: float,
    *,
    expected_model: str | None = None,
    expected_effort: str | None = None,
    expected_mode: str | None = None,
) -> Status:
    before = read_pane(session, pinned[0], deadline)
    submit_literal(session, pinned[0], "/status", deadline)
    last_error: HandoffError | None = None
    while time.monotonic() < deadline:
        pane = pinned_pane(session, pinned, deadline)
        observed_cwd(session, pane, expected_cwd, deadline)
        screen = read_pane(session, pane.pane_id, deadline)
        if screen == before or surface(screen) is None:
            time.sleep(POLL_SECONDS)
            continue
        try:
            status = status_panel(screen)
            if status.thread_id != expected_thread:
                raise HandoffError("Codex thread changed during the in-place handoff")
            if not same_cwd(expected_cwd, status.cwd):
                raise HandoffError("Codex /status cwd does not match the expected cwd")
            if expected_model is not None and status.model != expected_model:
                raise HandoffError("Codex /status model does not match the target")
            if expected_effort is not None and status.effort != expected_effort:
                raise HandoffError("Codex /status effort does not match the target")
            if expected_mode is not None and status.mode != expected_mode:
                raise HandoffError("Codex /status collaboration mode does not match the target")
            return status
        except HandoffError as exc:
            last_error = exc
        time.sleep(POLL_SECONDS)
    detail = f": {last_error}" if last_error else ""
    raise HandoffError(f"timed out waiting for verified Codex /status{detail}")


def wait_surface(
    session: str,
    pinned: tuple[str, str, str],
    expected_cwd: Path,
    model: str,
    effort: str,
    deadline: float,
    mode: str | None = None,
) -> PaneIdentity:
    while time.monotonic() < deadline:
        pane = pinned_pane(session, pinned, deadline)
        observed_cwd(session, pane, expected_cwd, deadline)
        observed = surface(read_pane(session, pane.pane_id, deadline))
        if (
            observed is not None
            and observed.model == model
            and observed.effort == effort
            and same_cwd(expected_cwd, observed.cwd)
            and (mode is None or observed.mode == mode)
        ):
            return pane
        time.sleep(POLL_SECONDS)
    label = f"{model}/{effort}" + (f"/{mode}" if mode else "")
    raise HandoffError(f"timed out waiting for verified Codex surface {label}")


def enter_plan_mode(
    session: str,
    pinned: tuple[str, str, str],
    expected_cwd: Path,
    model: str,
    deadline: float,
) -> None:
    before = read_pane(session, pinned[0], deadline)
    submit_literal(session, pinned[0], "/plan", deadline)
    while time.monotonic() < deadline:
        pane = pinned_pane(session, pinned, deadline)
        observed_cwd(session, pane, expected_cwd, deadline)
        screen = read_pane(session, pane.pane_id, deadline)
        observed = surface(screen)
        if (
            screen != before
            and observed is not None
            and observed.model == model
            and same_cwd(expected_cwd, observed.cwd)
            and observed.mode == "plan"
        ):
            return
        time.sleep(POLL_SECONDS)
    raise HandoffError("timed out waiting for /plan to settle")


def state_root() -> Path:
    if os.environ.get("XDG_STATE_HOME"):
        return Path(os.environ["XDG_STATE_HOME"]).expanduser() / "codex-mode-handoff"
    return Path.home() / ".local" / "state" / "codex-mode-handoff"


def unfinished_path(args: argparse.Namespace) -> Path:
    return state_root() / (
        f"{safe_id(args.session, 'session')}-{safe_id(args.thread_id, 'thread_id')}.json"
    )


def require_no_unfinished(args: argparse.Namespace) -> None:
    path = unfinished_path(args)
    if path.exists():
        raise HandoffError(f"unfinished handoff marker already exists: {path}")


def write_unfinished(args: argparse.Namespace, pane: PaneIdentity) -> Path:
    root = state_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    path = unfinished_path(args)
    payload = {
        "status": "in_progress",
        "session": args.session,
        "thread_id": args.thread_id,
        "pane_id": pane.pane_id,
        "tab_id": pane.tab_id,
        "workspace_id": pane.workspace_id,
        "cwd": str(args.cwd.expanduser().resolve(strict=False)),
        "target_mode": args.target_mode,
    }
    descriptor = None
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(descriptor, (json.dumps(payload, sort_keys=True) + "\n").encode())
        os.fsync(descriptor)
    except FileExistsError as exc:
        raise HandoffError(f"unfinished handoff marker already exists: {path}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return path


def remove_unfinished(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def read_continuation(path: Path) -> str:
    mode = path.stat().st_mode
    if mode & 0o077:
        raise HandoffError("continuation file must not be accessible by group or others")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise HandoffError("continuation file is empty")
    return text


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-mode", choices=("plan", "default"), required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--marker", required=True)
    parser.add_argument("--continuation-file", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.cwd.expanduser().is_dir():
        parser.error("--cwd must name an existing directory")
    return args


def prompt_continuation(
    session: str,
    pane_id: str,
    continuation: str,
    deadline: float,
) -> None:
    result = json_result(
        run(prefix(session) + ["agent", "prompt", pane_id, continuation], deadline)
    )
    agent = result.get("agent")
    if not isinstance(agent, Mapping) or agent.get("pane_id") != pane_id:
        raise HandoffError("continuation response pane identity mismatch")


def handoff(args: argparse.Namespace) -> PaneIdentity:
    continuation = read_continuation(args.continuation_file)
    require_no_unfinished(args)
    log(
        f"ARMED session={safe_id(args.session, 'session')} "
        f"thread={safe_id(args.thread_id, 'thread_id')} cwd={args.cwd}"
    )
    deadline = time.monotonic() + TIMEOUT_SECONDS
    pane = discover_marker_pane(args.session, args.marker, args.cwd, deadline)
    pinned = (pane.pane_id, pane.tab_id, pane.workspace_id)
    initial = wait_status(
        args.session,
        pinned,
        args.thread_id,
        args.cwd,
        deadline,
    )
    log(
        f"VERIFIED thread={initial.thread_id} pane={pane.pane_id} "
        f"route={initial.model}/{initial.effort}/{initial.mode}"
    )
    wait_surface(args.session, pinned, args.cwd, initial.model, initial.effort, deadline)
    model, effort = initial.model, initial.effort
    if args.target_mode == "default" and initial.mode != "default":
        raise HandoffError(
            "Default handoff requires the developer-level Default Mode instruction first"
        )
    marker_path = write_unfinished(args, pane)
    if args.target_mode == "plan":
        if initial.mode == "plan":
            log(f"NOOP /plan mode=plan already-active pane={pane.pane_id}")
        else:
            log(f"ACTION /plan pane={pane.pane_id}")
            enter_plan_mode(args.session, pinned, args.cwd, model, deadline)
    final_status = wait_status(
        args.session,
        pinned,
        args.thread_id,
        args.cwd,
        deadline,
        expected_model=model,
        expected_effort=effort if args.target_mode == "default" else None,
        expected_mode=args.target_mode,
    )
    if args.target_mode == "plan":
        wait_surface(
            args.session,
            pinned,
            args.cwd,
            model,
            final_status.effort,
            deadline,
            mode="plan",
        )
    log(f"ACTION continuation pane={pane.pane_id} thread={final_status.thread_id}")
    prompt_continuation(args.session, pane.pane_id, continuation, deadline)
    pane = pinned_pane(args.session, pinned, deadline)
    remove_unfinished(marker_path)
    return pane


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        pane = handoff(args)
        log(
            f"SUCCESS target={args.target_mode} thread={args.thread_id} "
            f"pane={pane.pane_id} continuation=sent"
        )
        return 0
    except (HandoffError, OSError, UnicodeError, ValueError) as exc:
        log(f"FAILED {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
