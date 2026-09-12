#!/usr/bin/env python3
"""One-shot Herdr handoff from an OMP Build turn into native Plan."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time
from typing import Any


class UnsafeSurface(RuntimeError):
    """A terminal or identity condition that must fail without input."""


class UnsettledSurface(RuntimeError):
    """A safe condition that may settle before the bounded deadline."""


def secure_write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)


def fail(root: Path, message: str) -> None:
    secure_write(root / "FAILURE", message.rstrip() + "\n")
    raise SystemExit(1)


def request(socket_path: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "id": f"omp-plan-handoff:{os.getpid()}:{time.time_ns()}",
        "method": method,
        "params": params,
    }
    received = bytearray()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3)
        client.connect(socket_path)
        client.sendall(json.dumps(payload, separators=(",", ":")).encode() + b"\n")
        while b"\n" not in received:
            chunk = client.recv(65536)
            if not chunk:
                break
            received.extend(chunk)
    if b"\n" not in received:
        raise RuntimeError("Herdr returned an incomplete response")
    response = json.loads(bytes(received).split(b"\n", 1)[0])
    if response.get("error"):
        raise RuntimeError(json.dumps(response["error"], sort_keys=True))
    return response


def verified_agent(state: dict[str, Any]) -> dict[str, Any]:
    response = request(state["socket"], "agent.get", {"target": state["pane"]})
    agent = response.get("result", {}).get("agent", {})
    required = {
        "workspace_id": state["workspace"],
        "tab_id": state["tab"],
        "pane_id": state["pane"],
        "agent": "omp",
        "agent_session": {
            "agent": "omp",
            "kind": "path",
            "source": "herdr:omp",
            "value": state["session"],
        },
    }
    for field, expected in required.items():
        if agent.get(field) != expected:
            raise UnsafeSurface(f"Herdr identity changed for {field}")
    return agent


def read_screen(state: dict[str, Any]) -> str:
    response = request(
        state["socket"],
        "agent.read",
        {
            "target": state["pane"],
            "source": "recent_unwrapped",
            "format": "text",
            "lines": 160,
            "strip_ansi": True,
        },
    )
    read = response.get("result", {}).get("read", {})
    if read.get("truncated"):
        raise UnsafeSurface("Herdr recent output is truncated")
    text = read.get("text")
    if not isinstance(text, str):
        raise UnsafeSurface("Herdr recent output is unavailable")
    return text


def branch_state(session: Path, marker: str) -> tuple[str, str | None, str | None, str | None, int]:
    mode = "build"
    plan_path = None
    latest_role = None
    latest_text = None
    marker_count = 0
    for raw in session.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if entry.get("type") == "mode_change" and entry.get("mode") in {"build", "plan", "none"}:
            mode = "plan" if entry["mode"] == "plan" else "build"
            data = entry.get("data") or {}
            plan_path = data.get("planFilePath") if mode == "plan" else None
        message = entry.get("message") if entry.get("type") == "message" else None
        if not isinstance(message, dict) or message.get("role") not in {"assistant", "user"}:
            continue
        parts = message.get("content")
        if not isinstance(parts, list):
            continue
        text = "".join(
            part.get("text", "")
            for part in parts
            if isinstance(part, dict) and part.get("type") == "text"
        )
        latest_role, latest_text = message["role"], text
        if message["role"] == "assistant" and text.strip() == marker:
            marker_count += 1
    return mode, plan_path, latest_role, latest_text, marker_count


def inspect_surface(state: dict[str, Any], require_plan: bool) -> tuple[str, str | None, str]:
    marker = state["marker"]
    agent = verified_agent(state)
    if agent.get("agent_status") not in {"idle", "done"}:
        raise UnsettledSurface("OMP has not settled")
    screen = read_screen(state)
    mode, plan_path, role, text, count = branch_state(Path(state["session"]), marker)
    if marker not in screen or role != "assistant" or text is None or text.strip() != marker or count != 1:
        raise UnsafeSurface("the exact assistant marker is absent or ambiguous")
    if not screen.rstrip().endswith("╰─"):
        raise UnsafeSurface("the OMP composer is not positively empty")
    lowered = screen.lower()
    if any(
        token in lowered
        for token in ("approval required", "waiting for user input", "select an option", "confirm?")
    ):
        raise UnsafeSurface("an approval or question dialog is visible")
    has_plan_status = "🗺 Plan" in screen
    if require_plan and (mode != "plan" or not plan_path or not has_plan_status):
        raise UnsettledSurface("native Plan is not yet positively verified")
    if not require_plan and mode == "plan" and not has_plan_status:
        raise UnsafeSurface("the OMP journal and terminal disagree about Plan mode")
    return mode, plan_path, screen


def wait_for_stable_surface(
    state: dict[str, Any], require_plan: bool, deadline: float
) -> tuple[str, str | None]:
    last_reason = "the OMP surface did not settle"
    while time.time() < deadline:
        try:
            mode, plan_path, first = inspect_surface(state, require_plan)
            digest = hashlib.sha256(first.encode()).digest()
            time.sleep(1)
            mode2, plan_path2, second = inspect_surface(state, require_plan)
            if hashlib.sha256(second.encode()).digest() == digest and (mode2, plan_path2) == (mode, plan_path):
                return mode, plan_path
            last_reason = "the OMP surface changed during the settle interval"
        except UnsettledSurface as error:
            last_reason = str(error)
        except UnsafeSurface:
            raise
        time.sleep(0.1)
    raise UnsafeSurface(last_reason)


def send_prompt(state: dict[str, Any], text: str) -> None:
    verified_agent(state)
    response = request(state["socket"], "agent.prompt", {"target": state["pane"], "text": text})
    if response.get("result", {}).get("type") != "agent_prompted":
        raise UnsafeSurface("Herdr did not accept the prompt")


def cleanup_success(root: Path) -> None:
    for child in root.iterdir():
        if child.is_file():
            child.unlink()
    root.rmdir()


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(2)
    root = Path(sys.argv[1])
    state_path = root / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    deadline = float(state["deadline"])
    if (root / "SENT_PLAN").exists() or (root / "SENT_CONTINUATION").exists():
        raise UnsafeSurface("the one-shot handoff already crossed an input boundary")
    verified_agent(state)
    secure_write(root / "READY", f"{os.getpid()}\n")

    marker = state["marker"]
    while time.time() < deadline:
        agent = verified_agent(state)
        if agent.get("agent_status") in {"idle", "done"}:
            screen = read_screen(state)
            _, _, role, text, count = branch_state(Path(state["session"]), marker)
            if marker in screen and role == "assistant" and text is not None and text.strip() == marker and count == 1:
                mode, _ = wait_for_stable_surface(state, False, min(deadline, time.time() + 8))
                if mode != "plan":
                    secure_write(root / "SENT_PLAN", "1\n")
                    send_prompt(state, "/plan")
                    wait_for_stable_surface(state, True, min(deadline, time.time() + 10))
                else:
                    wait_for_stable_surface(state, True, min(deadline, time.time() + 8))
                continuation = Path(state["continuation_file"]).read_text(encoding="utf-8")
                secure_write(root / "SENT_CONTINUATION", "1\n")
                send_prompt(state, continuation)
                cleanup_success(root)
                return
        time.sleep(0.1)
    raise UnsafeSurface("the 120-second handoff deadline expired")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as error:
        evidence = Path(sys.argv[1]) if len(sys.argv) == 2 else Path("/tmp")
        fail(evidence, f"{type(error).__name__}: {error}")
