import importlib.util
import json
from pathlib import Path
import sys

import pytest


SCRIPT = Path(__file__).parents[1] / "tracked/codex/skills/herdr/scripts/plan_mode_handoff.py"
SPEC = importlib.util.spec_from_file_location("plan_mode_handoff", SCRIPT)
handoff = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = handoff
SPEC.loader.exec_module(handoff)

MARKER = "READY_TOKEN"
THREAD = "01same-thread"
PANE = "w1:p1"
TAB = "w1:t1"
WORKSPACE = "w1"
EFFORT_BY_MODEL = {"gpt-5.6-sol": "medium", "gpt-6-astra": "xhigh"}


def footer(model, cwd, mode="default", effort=None):
    effort = effort or EFFORT_BY_MODEL[model]
    suffix = (
        "Plan mode (shift+tab to cycle)"
        if mode == "plan"
        else "Main [default] · ← for agents"
    )
    return f"{model} {effort} · {cwd} · weekly 97% left · Context 95% left · {suffix}"


def status_panel(model, cwd, mode, thread=THREAD, serial=1, effort=None):
    effort = effort or EFFORT_BY_MODEL[model]
    return (
        f"/status {serial}\n"
        "╭────────────────────────────────────────────────────────────────╮\n"
        "│  >_ OpenAI Codex (v0.155.0)                                   │\n"
        "│                                                               │\n"
        f"│  Model:                {model} (reasoning {effort}, summaries detailed) │\n"
        "│  Model provider:       openai                                 │\n"
        f"│  Directory:            {cwd}                                  │\n"
        "│  Permissions:          Full Access                            │\n"
        f"│  Collaboration mode:   {mode.title()}                         │\n"
        f"│  Session:              {thread}                               │\n"
        "╰────────────────────────────────────────────────────────────────╯\n"
    )


def idle_screen(
    model,
    cwd,
    mode="default",
    *,
    effort=None,
    marker=True,
    status="",
    extra="",
):
    rendered_marker = f"• {MARKER}\n" if marker else ""
    return (
        f"assistant final\n{rendered_marker}{extra}\n{status}"
        f"› Ask Codex to do anything\n\n  {footer(model, cwd, mode, effort)}"
    )


def test_surface_parses_fixed_routes_and_modes(tmp_path):
    default = handoff.surface(idle_screen("gpt-5.6-sol", str(tmp_path)))
    plan = handoff.surface(idle_screen("gpt-6-astra", str(tmp_path), "plan"))
    assert (default.model, default.effort, default.mode) == (
        "gpt-5.6-sol",
        "medium",
        "default",
    )
    assert (plan.model, plan.effort, plan.mode) == (
        "gpt-6-astra",
        "xhigh",
        "plan",
    )


@pytest.mark.parametrize(
    "extra,match",
    [
        ("› a new user message", "new user input"),
        ("Do you trust this directory?", "dialog"),
        ("• Working (1s • esc to interrupt)", None),
    ],
)
def test_completion_rejects_unsafe_or_active_surfaces(tmp_path, extra, match):
    rendered = idle_screen("gpt-5.6-sol", str(tmp_path), extra=extra)
    if match:
        with pytest.raises(handoff.HandoffError, match=match):
            handoff.completion(rendered, MARKER)
    else:
        assert not handoff.completion(rendered, MARKER)


def test_marker_must_be_an_exact_rendered_line(tmp_path):
    rendered = idle_screen("gpt-5.6-sol", str(tmp_path)).replace(
        f"• {MARKER}", f"mentioned {MARKER} in prose"
    )
    assert not handoff.completion(rendered, MARKER)


def test_status_panel_accepts_real_bordered_layout_without_fork(tmp_path):
    parsed = handoff.status_panel(
        status_panel("gpt-6-astra", str(tmp_path), "plan")
    )
    assert parsed == handoff.Status(
        THREAD,
        "gpt-6-astra",
        "xhigh",
        str(tmp_path),
        "plan",
    )


def test_status_panel_accepts_wrapped_model_summary(tmp_path):
    rendered = status_panel("gpt-5.6-sol", str(tmp_path), "default").replace(
        "gpt-5.6-sol (reasoning medium, summaries detailed)",
        "gpt-5.6-sol (reasoning medium, summaries\n│                        detailed)",
    )
    parsed = handoff.status_panel(rendered)
    assert (parsed.model, parsed.effort, parsed.thread_id) == (
        "gpt-5.6-sol",
        "medium",
        THREAD,
    )


@pytest.mark.parametrize(
    "replacement,match",
    [
        ("01other-thread", "thread changed"),
        ("gpt-5.6-sol", "model does not match"),
        ("medium", "effort does not match"),
        ("default", "collaboration mode does not match"),
    ],
)
def test_wait_status_rejects_wrong_identity_or_route(monkeypatch, tmp_path, replacement, match):
    rendered = idle_screen(
        "gpt-6-astra",
        str(tmp_path),
        "plan",
        status=status_panel("gpt-6-astra", str(tmp_path), "plan"),
    )
    expected_thread = THREAD
    expected_model = "gpt-6-astra"
    expected_effort = "xhigh"
    expected_mode = "plan"
    if replacement.startswith("01"):
        rendered = rendered.replace(THREAD, replacement)
    elif replacement.startswith("gpt-"):
        rendered = rendered.replace(expected_model, replacement)
    elif replacement == "medium":
        rendered = rendered.replace("reasoning xhigh", "reasoning medium")
    else:
        rendered = rendered.replace("Plan", "Default")
    screens = iter(["before", rendered, rendered])
    monkeypatch.setattr(handoff, "read_pane", lambda *_args, **_kwargs: next(screens, rendered))
    monkeypatch.setattr(handoff, "submit_literal", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        handoff,
        "pinned_pane",
        lambda *_args, **_kwargs: handoff.PaneIdentity(
            PANE,
            TAB,
            WORKSPACE,
            {"cwd": str(tmp_path), "agent": "codex"},
        ),
    )
    monkeypatch.setattr(handoff, "POLL_SECONDS", 0)
    with pytest.raises(handoff.HandoffError, match=match):
        handoff.wait_status(
            "test",
            (PANE, TAB, WORKSPACE),
            expected_thread,
            tmp_path,
            handoff.time.monotonic() + 0.01,
            expected_model=expected_model,
            expected_effort=expected_effort,
            expected_mode=expected_mode,
        )


def test_wait_status_ignores_stale_panel_while_command_is_in_composer(monkeypatch, tmp_path):
    old = idle_screen(
        "gpt-5.6-sol",
        str(tmp_path),
        status=status_panel("gpt-5.6-sol", str(tmp_path), "default"),
    )
    pending = old + "\n› /status"
    fresh = idle_screen(
        "gpt-6-astra",
        str(tmp_path),
        "plan",
        status=status_panel("gpt-6-astra", str(tmp_path), "plan", serial=2),
    )
    screens = iter([old, pending, fresh])
    monkeypatch.setattr(handoff, "read_pane", lambda *_args, **_kwargs: next(screens, fresh))
    monkeypatch.setattr(handoff, "submit_literal", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        handoff,
        "pinned_pane",
        lambda *_args, **_kwargs: handoff.PaneIdentity(
            PANE,
            TAB,
            WORKSPACE,
            {"cwd": str(tmp_path), "agent": "codex"},
        ),
    )
    monkeypatch.setattr(handoff, "POLL_SECONDS", 0)
    observed = handoff.wait_status(
        "test",
        (PANE, TAB, WORKSPACE),
        THREAD,
        tmp_path,
        handoff.time.monotonic() + 1,
        expected_model="gpt-6-astra",
        expected_effort="xhigh",
        expected_mode="plan",
    )
    assert observed.model == "gpt-6-astra"


class Harness:
    def __init__(
        self,
        cwd,
        *,
        model="gpt-5.6-sol",
        mode="default",
        thread=THREAD,
        fail_continuation=False,
    ):
        self.cwd = str(cwd)
        self.model = model
        self.effort = EFFORT_BY_MODEL[model]
        self.mode = mode
        self.thread = thread
        self.fail_continuation = fail_continuation
        self.pending = None
        self.status_serial = 0
        self.status = ""
        self.calls = []
        self.continuations = []

    def pane(self):
        return {
            "agent": "codex",
            "agent_status": "idle",
            "cwd": self.cwd,
            "foreground_cwd": self.cwd,
            "pane_id": PANE,
            "tab_id": TAB,
            "workspace_id": WORKSPACE,
        }

    def screen(self):
        return idle_screen(
            self.model,
            self.cwd,
            self.mode,
            effort=self.effort,
            status=self.status,
        )

    def run(self, command, _deadline):
        self.calls.append(list(command))
        args = list(command[3:])
        if args[:2] == ["pane", "list"]:
            return json.dumps({"result": {"panes": [self.pane()]}})
        if args[:2] == ["pane", "read"]:
            return self.screen()
        if args[:2] == ["pane", "process-info"]:
            return json.dumps(
                {"result": {"process_info": {"foreground_processes": [{"cwd": self.cwd}]}}}
            )
        if args[:2] == ["pane", "send-text"]:
            self.pending = args[-1]
            return "{}"
        if args[:2] == ["agent", "send-keys"]:
            keys = args[3:]
            if "enter" in keys and self.pending:
                command_text = self.pending
                self.pending = None
                if command_text == "/status":
                    self.status_serial += 1
                    self.status = status_panel(
                        self.model,
                        self.cwd,
                        self.mode,
                        self.thread,
                        self.status_serial,
                        self.effort,
                    )
                elif command_text == "/plan":
                    self.mode = "plan"
                else:
                    raise AssertionError(f"unexpected slash command: {command_text}")
            return json.dumps({"result": {"type": "ok"}})
        if args[:2] == ["agent", "prompt"]:
            if self.fail_continuation:
                raise handoff.HandoffError("continuation failed")
            self.continuations.append(args[-1])
            return json.dumps({"result": {"agent": {"pane_id": PANE}}})
        raise AssertionError(f"unexpected command: {command}")


def args(tmp_path, target):
    continuation = tmp_path / "continuation"
    continuation.write_text("continue with the approved work", encoding="utf-8")
    continuation.chmod(0o600)
    return [
        "--target-mode",
        target,
        "--session",
        "test",
        "--thread-id",
        THREAD,
        "--cwd",
        str(tmp_path),
        "--marker",
        MARKER,
        "--continuation-file",
        str(continuation),
    ]


def install_harness(monkeypatch, tmp_path, harness):
    monkeypatch.setattr(handoff, "run", harness.run)
    monkeypatch.setattr(handoff, "POLL_SECONDS", 0)
    monkeypatch.setattr(handoff, "STABLE_SECONDS", 0)
    monkeypatch.setattr(handoff, "INPUT_SETTLE_SECONDS", 0)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


@pytest.mark.parametrize(
    "target,start_model,start_mode,expects_plan",
    [
        ("plan", "gpt-5.6-sol", "default", True),
        ("plan", "gpt-6-astra", "default", True),
        ("default", "gpt-6-astra", "default", False),
    ],
)
def test_handoff_switches_mode_without_changing_model_and_continues_once(
    monkeypatch,
    tmp_path,
    target,
    start_model,
    start_mode,
    expects_plan,
):
    harness = Harness(tmp_path, model=start_model, mode=start_mode)
    install_harness(monkeypatch, tmp_path, harness)
    events = []
    monkeypatch.setattr(handoff, "log", events.append)
    assert handoff.main(args(tmp_path, target)) == 0
    assert harness.thread == THREAD
    assert harness.model == start_model
    assert harness.effort == EFFORT_BY_MODEL[start_model]
    assert harness.mode == target
    assert harness.continuations == ["continue with the approved work"]
    flat = [part for call in harness.calls for part in call]
    assert "/model" not in flat
    assert flat.count("/plan") == int(expects_plan)
    assert "/effort" not in flat
    assert "ctrl+c" not in flat
    assert "start" not in flat
    assert "fork" not in flat
    assert "resume" not in flat
    assert not list((tmp_path / "state" / "codex-mode-handoff").glob("*.json"))
    assert events[0].startswith("ARMED ")
    assert next(index for index, event in enumerate(events) if event.startswith("READY ")) > 0


def test_default_handoff_requires_default_mode_instruction(monkeypatch, tmp_path):
    harness = Harness(tmp_path, model="gpt-6-astra", mode="plan")
    install_harness(monkeypatch, tmp_path, harness)
    assert handoff.main(args(tmp_path, "default")) == 1
    flat = [part for call in harness.calls for part in call]
    assert "/model" not in flat
    assert "/plan" not in flat
    assert harness.continuations == []


@pytest.mark.parametrize(
    "target,model,mode",
    [
        ("default", "gpt-5.6-sol", "default"),
        ("plan", "gpt-5.6-sol", "plan"),
    ],
)
def test_handoff_skips_actions_when_target_is_already_active(
    monkeypatch,
    tmp_path,
    target,
    model,
    mode,
):
    harness = Harness(tmp_path, model=model, mode=mode)
    install_harness(monkeypatch, tmp_path, harness)
    events = []
    monkeypatch.setattr(handoff, "log", events.append)
    assert handoff.main(args(tmp_path, target)) == 0
    flat = [part for call in harness.calls for part in call]
    assert "/model" not in flat
    assert "/plan" not in flat
    assert harness.continuations == ["continue with the approved work"]
    if target == "plan":
        assert any(event.startswith("NOOP /plan ") for event in events)


def test_existing_unfinished_marker_fails_before_arming_or_herdr(
    monkeypatch,
    tmp_path,
):
    harness = Harness(tmp_path)
    install_harness(monkeypatch, tmp_path, harness)
    marker = handoff.unfinished_path(
        handoff.parse_args(args(tmp_path, "default"))
    )
    marker.parent.mkdir(parents=True)
    marker.write_text('{"status":"in_progress"}\n', encoding="utf-8")
    events = []
    monkeypatch.setattr(handoff, "log", events.append)
    assert handoff.main(args(tmp_path, "default")) == 1
    assert harness.calls == []
    assert not any(event.startswith("ARMED ") for event in events)
    assert events == [f"FAILED unfinished handoff marker already exists: {marker}"]


def test_wrong_thread_aborts_before_mode_change(monkeypatch, tmp_path):
    harness = Harness(tmp_path, thread="01wrong-thread")
    install_harness(monkeypatch, tmp_path, harness)
    monkeypatch.setattr(handoff, "TIMEOUT_SECONDS", 0.02)
    assert handoff.main(args(tmp_path, "plan")) == 1
    flat = [part for call in harness.calls for part in call]
    assert "/model" not in flat
    assert "ctrl+c" not in flat
    assert "start" not in flat

def test_continuation_failure_keeps_same_process_and_retains_marker(monkeypatch, tmp_path):
    harness = Harness(tmp_path, fail_continuation=True)
    install_harness(monkeypatch, tmp_path, harness)
    assert handoff.main(args(tmp_path, "plan")) == 1
    flat = [part for call in harness.calls for part in call]
    assert "ctrl+c" not in flat
    assert "start" not in flat
    assert "fork" not in flat
    assert "esc" not in flat
    markers = list((tmp_path / "state" / "codex-mode-handoff").glob("*.json"))
    assert len(markers) == 1


@pytest.mark.parametrize("contents,mode", [("", 0o600), ("continue", 0o644)])
def test_invalid_continuation_is_rejected_before_herdr(monkeypatch, tmp_path, contents, mode):
    argv = args(tmp_path, "plan")
    continuation = tmp_path / "continuation"
    continuation.write_text(contents, encoding="utf-8")
    continuation.chmod(mode)
    calls = []
    monkeypatch.setattr(handoff, "run", lambda *call: calls.append(call))
    assert handoff.main(argv) == 1
    assert calls == []


def test_parse_args_requires_existing_cwd(tmp_path):
    argv = args(tmp_path, "plan")
    argv[argv.index("--cwd") + 1] = str(tmp_path / "missing")
    with pytest.raises(SystemExit):
        handoff.parse_args(argv)
