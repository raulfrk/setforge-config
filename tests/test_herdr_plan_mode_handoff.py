import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

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
EFFORT_BY_MODEL = {
    "gpt-5.6-sol": "medium", "gpt-6-astra": "xhigh", "GPT-6.1-Sol": "high",
}


def footer(model, cwd, mode="default", effort=None):
    effort = effort or EFFORT_BY_MODEL[model]
    suffix = (
        "Plan mode (shift+tab to cycle)"
        if mode == "plan"
        else "Main [default] · ← for agents"
    )
    return f"{model} {effort} · {cwd} · weekly 97% left · Context 95% left · {suffix}"


def status_panel(model, cwd, mode, thread=THREAD, serial=1, effort=None, *, boxed=True):
    effort = effort or EFFORT_BY_MODEL[model]
    rendered = (
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
    if boxed:
        return rendered
    return "\n".join(
        line.strip().strip("│").strip()
        for line in rendered.replace("v0.155.0", "v0.159.0").splitlines()
        if not line.startswith(("╭", "╰"))
    ) + "\n"


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


@pytest.mark.parametrize("mode", ["default", "plan"])
def test_handoff_accepts_fast_service_label(monkeypatch, tmp_path, mode):
    harness = Harness(tmp_path, mode=mode)
    original = harness.screen
    harness.screen = lambda: original().replace(" medium ·", " medium fast ·")
    install_harness(monkeypatch, tmp_path, harness)
    monkeypatch.setattr(handoff, "TIMEOUT_SECONDS", 1.0)
    assert handoff.main(args(tmp_path, "plan")) == 0
    assert harness.continuations == ["continue with the approved work"]
    assert harness.model == "gpt-5.6-sol"


def test_completion_rejects_custom_working_label(tmp_path):
    rendered = idle_screen(
        "gpt-5.6-sol", str(tmp_path),
        extra="• Reviewing proposed plan (2s • esc to interrupt)\n",
    )
    assert not handoff.completion(rendered, MARKER)


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


def test_status_panel_accepts_unboxed_native_layout(tmp_path):
    rendered = idle_screen(
        "GPT-6.1-Sol", str(tmp_path),
        status=status_panel("GPT-6.1-Sol", str(tmp_path), "default", boxed=False),
    )
    assert handoff.status_panel(rendered) == handoff.Status(
        THREAD, "GPT-6.1-Sol", "high", str(tmp_path), "default",
    )


def test_unboxed_status_does_not_merge_older_boxed_fields(tmp_path):
    old = status_panel("gpt-5.6-sol", str(tmp_path), "plan", thread="old-thread")
    current = idle_screen(
        "GPT-6.1-Sol", str(tmp_path),
        status=status_panel("GPT-6.1-Sol", str(tmp_path), "default", boxed=False),
    )
    assert handoff.status_panel(old + current) == handoff.Status(
        THREAD, "GPT-6.1-Sol", "high", str(tmp_path), "default",
    )


@pytest.mark.parametrize(
    "missing", ["header", "Session", "Model", "Directory", "Collaboration mode", "composer", "tail"],
)
def test_unboxed_status_rejects_incomplete_or_changed_input(tmp_path, missing):
    rendered = idle_screen(
        "GPT-6.1-Sol", str(tmp_path),
        status=status_panel("GPT-6.1-Sol", str(tmp_path), "default", boxed=False),
    )
    if missing == "header":
        rendered = rendered.replace(">_ OpenAI Codex (v0.159.0)", "not a native status header")
    elif missing == "composer":
        rendered = rendered.replace(handoff.PLACEHOLDER, "› user draft")
    elif missing == "tail":
        rendered = rendered.split(handoff.PLACEHOLDER)[0]
    else:
        rendered = "\n".join(
            line for line in rendered.splitlines()
            if not line.lstrip().startswith(missing + ":")
        )
    with pytest.raises(handoff.HandoffError):
        handoff.status_panel(rendered)


@pytest.mark.parametrize("border", ["╭", "╰"])
def test_clipped_boxed_status_has_no_unboxed_fallback(tmp_path, border):
    rendered = "\n".join(
        line for line in status_panel("gpt-5.6-sol", str(tmp_path), "default").splitlines()
        if not line.startswith(border)
    )
    with pytest.raises(handoff.HandoffError):
        handoff.status_panel(rendered)


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
        self.status_serial = 0
        self.status = ""
        self.calls = []
        self.continuations = []
        self.history_replays = 0

    def pane(self):
        return {
            "agent": "codex",
            "agent_session": {"agent": "codex", "kind": "id", "value": self.thread},
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
            # Herdr harvests alternate-screen history by scrolling a detected
            # idle agent when a recent read requests more rows than its screen.
            if args[args.index("--source") + 1] in {"recent", "recent-unwrapped"}:
                self.history_replays += 1
            return self.screen()
        if args[:2] == ["pane", "process-info"]:
            return json.dumps(
                {"result": {"process_info": {"foreground_processes": [{"cwd": self.cwd}]}}}
            )
        if args[:2] == ["pane", "run"]:
            command_text = args[-1]
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
    monkeypatch.setattr(handoff, "native_reader", lambda _endpoint: None)
    monkeypatch.setattr(handoff, "POLL_SECONDS", 0)
    monkeypatch.setattr(handoff, "STABLE_SECONDS", 0)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


class ActiveTurnRace(Harness):
    """A final marker is visible before Codex permits a mode change."""

    def __init__(self, cwd, *, settle=True, change="", reject_twice=False):
        super().__init__(cwd, model="GPT-6.1-Sol")
        self.settle = settle
        self.change = change
        self.reject_twice = reject_twice
        self.plan_attempts = 0
        self.rejection_reads = 0

    def screen(self):
        rendered = super().screen()
        if self.plan_attempts:
            rejected = "■ '/plan' is disabled while a task is in\n  progress.\n"
            rendered = rendered.replace(handoff.PLACEHOLDER, rejected + handoff.PLACEHOLDER)
            if self.settle and self.rejection_reads > 1:
                rendered = rendered.replace(handoff.PLACEHOLDER, "Worked for 2m 10s\n" + handoff.PLACEHOLDER)
                if self.change == "draft":
                    rendered = rendered.replace(handoff.PLACEHOLDER, "› my unsent draft")
                elif self.change == "user":
                    rendered = rendered.replace(handoff.PLACEHOLDER, "› try again\n" + handoff.PLACEHOLDER)
                elif self.change == "approval":
                    rendered = rendered.replace(handoff.PLACEHOLDER, "Allow command\n" + handoff.PLACEHOLDER)
                elif self.change == "thread":
                    self.thread = "replacement-thread"
        return rendered

    def run(self, command, deadline):
        if list(command[3:5]) == ["pane", "read"] and self.plan_attempts:
            self.rejection_reads += 1
        if list(command[3:5]) == ["pane", "run"] and command[-1] == "/plan":
            self.plan_attempts += 1
            if self.plan_attempts == 1 or self.reject_twice:
                self.calls.append(list(command))
                if self.plan_attempts == 2:
                    self.status += "■ '/plan' is disabled while a task is in progress.\n"
                return json.dumps({"result": {"type": "ok"}})
        return super().run(command, deadline)


def test_public_handoff_recovers_after_active_turn_rejection(monkeypatch, tmp_path):
    harness = ActiveTurnRace(tmp_path)
    install_harness(monkeypatch, tmp_path, harness)
    monkeypatch.setattr(handoff, "TIMEOUT_SECONDS", 1.0)
    assert handoff.main(args(tmp_path, "plan")) == 0
    commands = [call[-1] for call in harness.calls if call[3:5] == ["pane", "run"]]
    assert commands == ["/status", "/plan", "/status", "/plan", "/status"]
    assert harness.plan_attempts == 2
    assert harness.continuations == ["continue with the approved work"]
    assert harness.history_replays == 0
    assert harness.thread == THREAD
    assert harness.model == "GPT-6.1-Sol"


@pytest.mark.parametrize("change", ["draft", "user", "approval", "thread"])
def test_active_turn_recovery_refuses_changed_input_or_identity(monkeypatch, tmp_path, change):
    harness = ActiveTurnRace(tmp_path, change=change)
    install_harness(monkeypatch, tmp_path, harness)
    monkeypatch.setattr(handoff, "TIMEOUT_SECONDS", 0.05)
    assert handoff.main(args(tmp_path, "plan")) == 1
    assert harness.plan_attempts == 1
    assert harness.continuations == []


def test_active_turn_recovery_requires_new_idle_evidence(monkeypatch, tmp_path):
    harness = ActiveTurnRace(tmp_path, settle=False)
    install_harness(monkeypatch, tmp_path, harness)
    monkeypatch.setattr(handoff, "TIMEOUT_SECONDS", 0.03)
    assert handoff.main(args(tmp_path, "plan")) == 1
    assert harness.plan_attempts == 1
    assert harness.continuations == []


def test_active_turn_recovery_retries_mode_change_only_once(monkeypatch, tmp_path):
    harness = ActiveTurnRace(tmp_path, reject_twice=True)
    install_harness(monkeypatch, tmp_path, harness)
    monkeypatch.setattr(handoff, "TIMEOUT_SECONDS", 1.0)
    assert handoff.main(args(tmp_path, "plan")) == 1
    assert harness.plan_attempts == 2
    assert harness.continuations == []
    assert list((tmp_path / "state" / "codex-mode-handoff").glob("*.json"))


class NativeReadiness:
    def __init__(self, harness, states):
        self.harness = harness
        self.states = iter(states)
        self.last = "idle"
        self.calls = []
        self.closed = False

    def read(self, tid):
        self.last = next(self.states, self.last)
        self.calls.append((tid, self.last, len(self.harness.calls)))
        return {"id": tid, "cwd": self.harness.cwd, "status": {"type": self.last}}

    def close(self):
        self.closed = True


def test_native_active_turn_blocks_commands_despite_rendered_final(monkeypatch, tmp_path):
    harness = Harness(tmp_path, model="GPT-6.1-Sol")
    install_harness(monkeypatch, tmp_path, harness)
    native = NativeReadiness(harness, ["active", "active", "idle"])
    monkeypatch.setattr(handoff, "native_reader", lambda _: native)
    assert handoff.main(args(tmp_path, "plan")) == 0
    for _, state, count in native.calls[:2]:
        assert state == "active"
        assert all(call[3:5] in (["pane", "list"], ["pane", "read"]) for call in harness.calls[:count])
    assert native.closed
    assert harness.continuations == ["continue with the approved work"]


@pytest.mark.parametrize("state", ["active", "notLoaded", "systemError"])
def test_native_unready_thread_never_receives_commands(monkeypatch, tmp_path, state):
    harness = Harness(tmp_path)
    install_harness(monkeypatch, tmp_path, harness)
    native = NativeReadiness(harness, [state])
    monkeypatch.setattr(handoff, "native_reader", lambda _: native)
    monkeypatch.setattr(handoff, "TIMEOUT_SECONDS", 0.03)
    assert handoff.main(args(tmp_path, "plan")) == 1
    assert all(call[3:5] in (["pane", "list"], ["pane", "read"]) for call in harness.calls)
    assert harness.continuations == []
    assert native.closed


def test_uncertain_mode_delivery_never_retries_or_continues(monkeypatch, tmp_path):
    harness = Harness(tmp_path)
    install_harness(monkeypatch, tmp_path, harness)
    original = harness.run

    def uncertain(command, deadline):
        result = original(command, deadline)
        if command[-1] == "/plan":
            raise handoff.HandoffError("Herdr command timed out: herdr")
        return result

    monkeypatch.setattr(handoff, "run", uncertain)
    assert handoff.main(args(tmp_path, "plan")) == 1
    assert harness.mode == "plan"
    assert [call[-1] for call in harness.calls].count("/plan") == 1
    assert harness.continuations == []
    assert list((tmp_path / "state" / "codex-mode-handoff").glob("*.json"))


@pytest.mark.xfail(
    importlib.util.find_spec("websocket") is None,
    strict=True,
    reason="the native readiness read imports websocket-client, which the test interpreter lacks",
)
def test_public_handoff_reads_only_native_state_on_isolated_socket(monkeypatch, tmp_path):
    from websockets.sync.server import unix_serve

    harness = Harness(tmp_path, model="GPT-6.1-Sol")
    reader = handoff.native_reader
    install_harness(monkeypatch, tmp_path, harness)
    monkeypatch.setattr(handoff, "native_reader", reader)
    endpoint = tmp_path / "native.sock"
    calls = []
    policy = {"approvalPolicy": "on-request", "sandbox": {"type": "readOnly"}}
    original_policy = json.dumps(policy, sort_keys=True)

    def serve(connection):
        reads = 0
        for raw in connection:
            request = json.loads(raw)
            method = request["method"]
            calls.append((method, len(harness.calls)))
            if method == "initialized":
                continue
            if method == "initialize":
                result = {"codexHome": str(tmp_path / "codex")}
            elif method == "thread/read":
                assert request["params"] == {"threadId": THREAD, "includeTurns": False}
                reads += 1
                result = {"thread": {
                    "id": THREAD, "cwd": str(tmp_path),
                    "status": {"type": "active" if reads <= 2 else "idle"},
                    **policy,
                }}
            else:
                raise AssertionError(f"unexpected native mutation: {method}")
            connection.send(json.dumps({"id": request["id"], "result": result}))

    with unix_serve(serve, path=str(endpoint)) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            assert handoff.main(args(tmp_path, "plan") + ["--app-server-socket", str(endpoint)]) == 0
        finally:
            server.shutdown()
            worker.join(timeout=5)
        assert not worker.is_alive()
    read_calls = [count for method, count in calls if method == "thread/read"]
    assert len(read_calls) >= 3
    for count in read_calls[:2]:
        assert all(call[3:5] in (["pane", "list"], ["pane", "read"]) for call in harness.calls[:count])
    assert {method for method, _ in calls} == {"initialize", "initialized", "thread/read"}
    assert json.dumps(policy, sort_keys=True) == original_policy
    assert harness.thread == THREAD
    assert harness.continuations == ["continue with the approved work"]


def test_command_line_handoff_uses_isolated_targets(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state = tmp_path / "terminal.json"
    state.write_text(json.dumps(Harness(tmp_path, model="GPT-6.1-Sol").__dict__))
    fake_herdr = fake_bin / "herdr"
    fake_herdr.write_text(
        f"#!{sys.executable}\n"
        "import importlib.util, json, os, pathlib, sys\n"
        "spec = importlib.util.spec_from_file_location('fixture', os.environ['HANDOFF_TEST_MODULE'])\n"
        "m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)\n"
        "path = pathlib.Path(os.environ['HANDOFF_TEST_STATE'])\n"
        "h = m.Harness(os.environ['HANDOFF_TEST_CWD']); h.__dict__.update(json.loads(path.read_text()))\n"
        "result = h.run(['herdr'] + sys.argv[1:], 0)\n"
        "path.write_text(json.dumps(h.__dict__)); print(result)\n"
    )
    fake_herdr.chmod(0o700)
    env = {**os.environ, "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
           "XDG_STATE_HOME": str(tmp_path / "state"), "HANDOFF_TEST_STATE": str(state),
           "HANDOFF_TEST_MODULE": str(Path(__file__).resolve()), "HANDOFF_TEST_CWD": str(tmp_path)}
    # Both terminal and private handoff writes resolve inside this disposable directory.
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args(tmp_path, "plan"),
         "--app-server-socket", str(tmp_path / "absent.sock")],
        env=env, text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "SUCCESS target=plan" in result.stderr
    final = json.loads(state.read_text())
    assert final["mode"] == "plan"
    assert final["thread"] == THREAD
    assert final["model"] == "GPT-6.1-Sol"
    assert final["continuations"] == ["continue with the approved work"]
    assert final["history_replays"] == 0
    assert not list((tmp_path / "state" / "codex-mode-handoff").glob("*.json"))


@pytest.mark.parametrize("mode", ["default", "plan"])
def test_public_handoff_accepts_unboxed_native_status(monkeypatch, tmp_path, mode):
    renderer = status_panel
    monkeypatch.setattr(
        sys.modules[__name__], "status_panel",
        lambda *args, **kwargs: renderer(*args, **kwargs, boxed=False),
    )
    harness = Harness(tmp_path, model="GPT-6.1-Sol", mode=mode)
    install_harness(monkeypatch, tmp_path, harness)
    assert handoff.main(args(tmp_path, "plan")) == 0
    assert harness.model == "GPT-6.1-Sol"
    assert harness.effort == "high"
    assert harness.thread == THREAD
    assert harness.mode == "plan"
    assert harness.history_replays == 0
    assert harness.continuations == ["continue with the approved work"]
    commands = [call[-1] for call in harness.calls if call[3:5] == ["pane", "run"]]
    assert commands.count("/plan") == int(mode == "default")


@pytest.mark.parametrize(
    "target,start_model",
    [
        ("plan", "gpt-5.6-sol"),
        ("plan", "gpt-6-astra"),
        ("default", "gpt-6-astra"),
    ],
)
def test_handoff_switches_mode_without_changing_model_and_continues_once(
    monkeypatch,
    tmp_path,
    target,
    start_model,
):
    harness = Harness(tmp_path, model=start_model)
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
    assert flat.count("/plan") == int(target == "plan")
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


def test_handoff_submits_slash_commands_without_separate_key_events(monkeypatch, tmp_path):
    harness = Harness(tmp_path)
    install_harness(monkeypatch, tmp_path, harness)
    assert handoff.main(args(tmp_path, "plan")) == 0
    assert not any("send-text" in call or "send-keys" in call for call in harness.calls)
    commands = [call[-1] for call in harness.calls if call[3:5] == ["pane", "run"]]
    assert commands == ["/status", "/plan", "/status"]
    assert harness.continuations == ["continue with the approved work"]


def test_handoff_polling_does_not_scroll_alternate_screen_history(monkeypatch, tmp_path):
    harness = Harness(tmp_path)
    install_harness(monkeypatch, tmp_path, harness)
    assert handoff.main(args(tmp_path, "plan")) == 0
    assert harness.history_replays == 0
    assert harness.mode == "plan"
    assert harness.continuations == ["continue with the approved work"]


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
    assert "/status" in flat
    assert "/plan" not in flat
    assert harness.continuations == []
    assert "/model" not in flat
    assert "ctrl+c" not in flat
    assert "start" not in flat


def test_stale_herdr_thread_metadata_does_not_override_fresh_status(monkeypatch, tmp_path):
    harness = Harness(tmp_path)
    original = harness.pane
    harness.pane = lambda: {
        **original(),
        "agent_session": {"agent": "codex", "kind": "id", "value": "stale-thread"},
    }
    install_harness(monkeypatch, tmp_path, harness)
    assert handoff.main(args(tmp_path, "plan")) == 0
    assert harness.thread == THREAD
    assert harness.continuations == ["continue with the approved work"]


def test_missing_marker_never_controls_replacement_conversation(monkeypatch, tmp_path):
    harness = Harness(tmp_path, thread="replacement-thread")
    original = harness.screen
    harness.screen = lambda: original().replace(MARKER, "unrelated-final")
    install_harness(monkeypatch, tmp_path, harness)
    monkeypatch.setattr(handoff, "TIMEOUT_SECONDS", 0.02)
    events = []
    monkeypatch.setattr(handoff, "log", events.append)
    assert handoff.main(args(tmp_path, "plan")) == 1
    assert "completed marker not found" in events[-1]
    assert all(call[3:5] in (["pane", "list"], ["pane", "read"]) for call in harness.calls)
    assert harness.continuations == []


def test_unknown_footer_fails_with_diagnostic_without_terminal_input(monkeypatch, tmp_path):
    harness = Harness(tmp_path)
    original = harness.screen
    harness.screen = lambda: original().replace(" medium ·", " unknown-format ·")
    install_harness(monkeypatch, tmp_path, harness)
    monkeypatch.setattr(handoff, "TIMEOUT_SECONDS", 0.01)
    events = []
    monkeypatch.setattr(handoff, "log", events.append)
    assert handoff.main(args(tmp_path, "plan")) == 1
    assert "footer format is unrecognized" in events[-1]
    assert all(call[3:5] in (["pane", "list"], ["pane", "read"]) for call in harness.calls)


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
