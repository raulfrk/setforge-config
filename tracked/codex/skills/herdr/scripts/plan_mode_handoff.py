#!/usr/bin/env python3
"""Fail-closed Herdr handoff between Codex Default and Plan modes."""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

PLACEHOLDER = "› Ask Codex to do anything"
POLL_SECONDS = 0.25
STABLE_SECONDS = 1.0
TIMEOUT_SECONDS = 120.0
PLAN_INDICATOR = re.compile(
    r"(?:^| · | {2,}|(?<=…) )"
    r"Plan mode(?: \(shift\+tab to cycle\))?(?=$| · | {2,})"
)


class HandoffError(RuntimeError):
    pass


def log(message):
    print(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {message}", file=sys.stderr, flush=True)


def run(command, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise HandoffError("handoff deadline exceeded")
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=min(5.0, remaining))
    except subprocess.TimeoutExpired as exc:
        raise HandoffError(f"Herdr command timed out: {command[3] if len(command) > 3 else command[-1]}") from exc
    if result.returncode:
        raise HandoffError(f"Herdr command failed ({result.returncode}): {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout


def marker_tail(text, marker):
    lines = text.splitlines()
    accepted = {marker, f"• {marker}"}
    matches = [index for index, line in enumerate(lines) if line.strip() in accepted]
    return None if not matches else lines[matches[-1] + 1 :]


def footer_mode(lines):
    footer = footer_evidence(lines)
    if footer is None:
        return None
    if re.search(r"Plan mode(?: \(shift\+tab to cycle\))?$", footer):
        return "plan"
    # A terminal ellipsis may clip the status line after a complete context percentage.
    return "default" if re.search(r"Context \d+% left(?: ·…)?$", footer) else None


def footer_evidence(lines):
    footer = next(
        (line.strip() for line in reversed(lines) if " · Contex" in line and " · " in line),
        None,
    )
    if not footer or not re.fullmatch(
        r"gpt-[^·]+ · ~?[/\w.-]+(?: · [^·]+)* · "
        r"Contex(?:t(?: \d+(?:% left|…)|…)|…)"
        r"(?:(?: +| · )Plan mode(?: \(shift\+tab to cycle\))?| ·…)?",
        footer,
    ):
        return None
    return footer


def completion(text, marker, allowed_prompts=()):
    tail = marker_tail(text, marker)
    if tail is None:
        return None, False
    prompts = [line.strip() for line in tail if line.lstrip().startswith("›")]
    permitted = {PLACEHOLDER, *allowed_prompts}
    if any(prompt not in permitted for prompt in prompts):
        raise HandoffError("new user input or a nonempty composer appeared after the marker")
    stripped = [line.strip() for line in tail]
    if any(
        line.startswith(("Do you trust", "Press enter to continue", "Allow command"))
        or line.lower() == "approval required"
        for line in stripped
    ):
        raise HandoffError("a dialog or approval prompt appeared after the marker")
    active = any(
        line.startswith(("• Working", "• Thinking"))
        for line in stripped
    )
    empty_composer = bool(prompts) and prompts[-1] == PLACEHOLDER
    return footer_mode(tail), empty_composer and not active


def native_footer_row(text, marker):
    tail = marker_tail(text, marker)
    if tail is None:
        return None
    composers = [index for index, line in enumerate(tail) if line.lstrip().startswith("›")]
    if not composers or tail[composers[-1]].strip() != PLACEHOLDER:
        return None
    return next(
        (line.strip() for line in tail[composers[-1] + 1 :] if line.strip()),
        None,
    )


def native_plan_visible(text, marker):
    footer = native_footer_row(text, marker)
    return footer is not None and PLAN_INDICATOR.search(footer) is not None


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-mode", choices=("plan", "default"), required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--marker", required=True)
    parser.add_argument("--continuation-file", required=True)
    parser.add_argument("--reason")
    args = parser.parse_args(argv)
    if args.target_mode == "default" and not args.reason:
        parser.error("--reason is required for --target-mode default")
    return args


def advance_stability(stable_since, previous, mode, complete, footer, target, now):
    acceptable = complete and (
        target == "plan" or (footer is not None and mode in ("plan", "default"))
    )
    signature = (complete,) if target == "plan" else (mode, complete, footer)
    if signature != previous or not acceptable:
        return (now if acceptable else None), signature
    return stable_since, signature


def log_observation(phase, text, marker, allowed_prompts=()):
    tail = marker_tail(text, marker)
    mode, complete = completion(text, marker, allowed_prompts)
    lines = tail or ()
    footer = footer_evidence(lines)
    candidate = next(
        (line.strip()[:240] for line in reversed(lines) if line.strip().startswith("gpt-")),
        None,
    )
    log(
        f"OBSERVE phase={phase} marker={tail is not None} complete={complete} "
        f"mode={mode or 'ambiguous'} footer_valid={footer is not None} "
        f"footer={candidate!r}"
    )


def main(argv=None):
    args = parse_args(argv)
    continuation_stat = os.stat(args.continuation_file)
    if continuation_stat.st_mode & 0o077:
        raise HandoffError("continuation file must not be accessible by group or others")
    with open(args.continuation_file, encoding="utf-8") as stream:
        continuation = stream.read()
    if not continuation.strip():
        raise HandoffError("continuation file is empty")
    deadline = time.monotonic() + TIMEOUT_SECONDS
    log(f"START pid={os.getpid()} target={args.target_mode}")
    prefix = ["herdr", "--session", args.session]
    pinned = None

    def identity():
        nonlocal pinned
        data = json.loads(run(prefix + ["pane", "list"], deadline))
        matches = [pane for pane in data["result"]["panes"] if pane.get("agent_session", {}).get("agent") == "codex" and pane.get("agent_session", {}).get("value") == args.thread_id]
        if len(matches) != 1:
            raise HandoffError(f"expected one immutable thread match, found {len(matches)}")
        location = (matches[0]["pane_id"], matches[0]["tab_id"], matches[0]["workspace_id"])
        if pinned is None:
            pinned = location
            log(f"READY pane={pinned[0]} tab={pinned[1]} target={args.target_mode}")
        elif location != pinned:
            raise HandoffError("the matched Codex pane moved during handoff")
        return matches[0]

    pane = identity()["pane_id"]

    def read():
        return run(prefix + ["agent", "read", pane, "--source", "recent-unwrapped", "--lines", "120"], deadline)

    stable_since = None
    previous = None
    while time.monotonic() < deadline:
        rendered = read()
        mode, complete = completion(rendered, args.marker)
        footer = footer_evidence(marker_tail(rendered, args.marker) or ())
        now = time.monotonic()
        stable_since, previous = advance_stability(
            stable_since, previous, mode, complete, footer, args.target_mode, now
        )
        if stable_since is not None and now - stable_since >= STABLE_SECONDS:
            break
        time.sleep(POLL_SECONDS)
    else:
        log_observation("initial-timeout", rendered, args.marker)
        raise HandoffError("timed out waiting for stable completed rendering")

    identity()
    rendered = read()
    current_mode, complete = completion(rendered, args.marker)
    footer = footer_evidence(marker_tail(rendered, args.marker) or ())
    if not complete or (
        args.target_mode == "default"
        and (footer is None or current_mode not in ("plan", "default"))
    ):
        raise HandoffError("completion state changed before mode action")
    if args.target_mode == "plan":
        action = prefix + ["agent", "prompt", pane, "/plan"]
        action_name = "/plan"
        log(f"ACTION {action_name}")
        run(action, deadline)
    elif current_mode != args.target_mode:
        action = prefix + ["pane", "send-text", pane, "\x1b[Z"]
        action_name = "Shift+Tab"
        log(f"ACTION {action_name}")
        run(action, deadline)

    allowed_prompts = ("› /plan",) if args.target_mode == "plan" else ()
    while time.monotonic() < deadline:
        rendered = read()
        mode, complete = completion(rendered, args.marker, allowed_prompts)
        target_visible = (
            native_plan_visible(rendered, args.marker)
            if args.target_mode == "plan"
            else mode == args.target_mode
        )
        if target_visible and complete:
            break
        time.sleep(POLL_SECONDS)
    else:
        log_observation("target-timeout", rendered, args.marker, allowed_prompts)
        raise HandoffError(f"target {args.target_mode} footer was not verified")

    identity()
    rendered = read()
    mode, complete = completion(rendered, args.marker, allowed_prompts)
    target_visible = (
        native_plan_visible(rendered, args.marker)
        if args.target_mode == "plan"
        else mode == args.target_mode
    )
    if not target_visible or not complete:
        raise HandoffError("verified state changed before continuation")
    response = json.loads(run(prefix + ["agent", "prompt", pane, continuation], deadline))
    agent = response["result"]["agent"]
    if agent.get("pane_id") != pane or agent.get("agent_session", {}).get("value") != args.thread_id:
        raise HandoffError("continuation response identity mismatch")
    log(f"SUCCESS target={args.target_mode} continuation=sent")


if __name__ == "__main__":
    try:
        main()
    except (HandoffError, OSError, ValueError, json.JSONDecodeError) as exc:
        log(f"FAILED {exc}")
        raise SystemExit(1)
