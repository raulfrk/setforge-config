import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "tracked/codex/skills/herdr/scripts/plan_mode_handoff.py"
SPEC = importlib.util.spec_from_file_location("plan_mode_handoff", SCRIPT)
handoff = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(handoff)

MARKER = "READY_TOKEN"
DEFAULT = "gpt-6-astra low · ~/setforge · weekly 90% left · Context 95% left"
TRUNCATED_DEFAULT = "gpt-5.6-sol low · ~/setforge · weekly 96% left · Context 59% left ·…"
PARTIAL_CONTEXT = "gpt-6-astra low · ~/setforge · weekly 92% left · Context 40%…"
PLAN = DEFAULT + " · Plan mode (shift+tab to cycle)"
DISABLED_PLAN = (
    "? for shortcuts · Plan mode (shift+tab to cycle)"
    "                                                   100% context left"
)
REORDERED_PLAN = (
    "01a0765d · weekly 72% left · /tmp"
    "                         Plan mode (shift+tab to cycle)"
)


def screen(footer=DEFAULT, extra="", marker=MARKER):
    return f"assistant final\n  {marker}\n{extra}\n› Ask Codex to do anything\n\n  {footer}"


def test_recognizes_full_default_and_compact_plan_footers():
    assert handoff.footer_mode([DEFAULT]) == "default"
    assert handoff.footer_mode([TRUNCATED_DEFAULT]) == "default"
    assert handoff.footer_mode(["gpt-6-astra low · ~/setforge · Context… Plan mode"]) == "plan"
    assert handoff.footer_mode(["gpt-6-astra low · ~/setforge · Contex… Plan mode"]) == "plan"
    assert handoff.footer_mode([PLAN]) == "plan"
    assert handoff.footer_mode(["gpt-6-astra low · ~/setforge · Context 1… Plan mode"]) == "plan"


def test_terminally_truncated_full_context_footer_identifies_default_mode():
    assert handoff.footer_evidence([TRUNCATED_DEFAULT]) == TRUNCATED_DEFAULT
    assert handoff.footer_mode([TRUNCATED_DEFAULT]) == "default"


@pytest.mark.parametrize(
    "footer",
    [
        DISABLED_PLAN,
        REORDERED_PLAN,
        "Plan mode",
        "Plan mode (shift+tab to cycle) · IDE context",
        "gpt-6-astra low · ~/setforge · Context… Plan mode",
        "gpt-6-astra low · ~/setforge · Contex… Plan mode",
        "gpt-6-astra low · ~/setforge · Context 1… Plan mode",
    ],
)
def test_native_plan_indicator_is_read_from_actual_footer_row(footer):
    assert handoff.native_plan_visible(screen(footer), MARKER)


@pytest.mark.parametrize(
    "footer,extra",
    [
        ("Main [plan]", ""),
        ("Context 10% left ·…", ""),
        ("custom status", "Plan mode (shift+tab to cycle) in transcript prose"),
        ("custom Plan mode value", ""),
    ],
)
def test_missing_or_misleading_plan_indicator_is_not_native(footer, extra):
    assert not handoff.native_plan_visible(screen(footer, extra), MARKER)


def test_home_and_arbitrary_status_are_ready_without_proving_mode():
    home = "gpt-6-astra low · ~ · weekly 72% left · Context 100% left"
    arbitrary = "approval budget · Working set · custom status"
    assert handoff.completion(screen(home), MARKER) == (None, True)
    assert handoff.completion(screen(arbitrary), MARKER) == (None, True)


def test_current_dir_status_containing_interrupt_text_is_not_activity():
    footer = "/tmp/esc to interrupt"
    assert handoff.completion(screen(footer), MARKER) == (None, True)


def test_current_plan_menu_cannot_inherit_stale_empty_composer():
    rendered = screen(DISABLED_PLAN) + "\n› /plan\n\n  /plan  switch to Plan mode\n"
    assert handoff.completion(rendered, MARKER, ("› /plan",)) == (None, False)
    assert not handoff.native_plan_visible(rendered, MARKER)


def test_prose_does_not_prove_mode_or_marker():
    assert handoff.footer_mode(["The session is in Plan mode."]) is None
    assert handoff.marker_tail(f"mentioned {MARKER} in prose", MARKER) is None


def test_actual_assistant_bullet_marker_is_recognized():
    rendered = screen(marker=f"• {MARKER}")
    assert handoff.completion(rendered, MARKER) == ("default", True)


@pytest.mark.parametrize("unsafe", [f"› {MARKER}", f"│ {MARKER}", f'“{MARKER}”', f"quoted {MARKER}"])
def test_unsafe_marker_forms_are_rejected(unsafe):
    assert handoff.marker_tail(screen(marker=unsafe), MARKER) is None


@pytest.mark.parametrize("extra", ["• Working (1s • esc to interrupt)", "• Thinking"])
def test_active_turn_is_not_complete(extra):
    assert handoff.completion(screen(extra=extra), MARKER) == ("default", False)


@pytest.mark.parametrize("extra", ["› a new user message", "› drafted text"])
def test_new_input_or_draft_aborts(extra):
    with pytest.raises(handoff.HandoffError, match="new user input"):
        handoff.completion(screen(extra=extra), MARKER)


def test_only_known_plan_command_may_appear_during_verification():
    text = screen(PLAN, "› /plan")
    assert handoff.completion(text, MARKER, ("› /plan",)) == ("plan", True)
    with pytest.raises(handoff.HandoffError):
        handoff.completion(text, MARKER)


@pytest.mark.parametrize("extra", ["Do you trust this directory?", "Press enter to continue", "Allow command", "approval required"])
def test_dialog_aborts(extra):
    with pytest.raises(handoff.HandoffError, match="dialog"):
        handoff.completion(screen(extra=extra), MARKER)


def test_unknown_footer_is_not_complete_mode():
    assert handoff.completion(screen(footer="status unavailable"), MARKER) == (None, True)
    assert handoff.footer_mode([DEFAULT + " · Code mode"]) is None
    assert handoff.footer_mode(["gpt-6-astra low · ~/setforge · Context…"]) is None


def test_unknown_footer_diagnostic_is_bounded_and_preserves_candidate(capsys):
    footer = "gpt-6-astra low · ~/setforge · future status " + "x" * 300
    handoff.log_observation("target-timeout", screen(footer), MARKER)
    diagnostic = capsys.readouterr().err
    assert "phase=target-timeout marker=True" in diagnostic
    assert "footer_valid=False" in diagnostic
    assert footer[:240] in diagnostic
    assert diagnostic.count("x") == 240 - len(footer.rstrip("x"))


def test_default_requires_reason():
    with pytest.raises(SystemExit):
        handoff.parse_args(["--target-mode", "default", "--session", "s", "--thread-id", "t", "--marker", "m", "--continuation-file", "f"])


def test_stability_resets_when_mode_changes():
    since, signature = handoff.advance_stability(None, None, "default", True, DEFAULT, "default", 1.0)
    assert since == 1.0
    since, signature = handoff.advance_stability(since, signature, "plan", True, PLAN, "default", 1.5)
    assert since == 1.5


def test_ambiguous_footer_is_stable_only_for_plan_entry():
    clipped = PARTIAL_CONTEXT
    assert handoff.advance_stability(None, None, None, True, clipped, "plan", 1.0)[0] == 1.0
    assert handoff.advance_stability(None, None, None, True, clipped, "default", 1.0)[0] is None


def test_plan_readiness_stability_ignores_dynamic_status_changes():
    since, signature = handoff.advance_stability(None, None, None, True, "status one", "plan", 1.0)
    same_since, next_signature = handoff.advance_stability(since, signature, None, True, "status two", "plan", 1.5)
    assert same_since == since
    assert next_signature == signature


def test_real_subprocess_wrapper_gates_return_code(tmp_path):
    fake = tmp_path / "fake-herdr"
    fake.write_text("#!/bin/sh\nprintf ok")
    fake.chmod(0o755)
    assert handoff.run([str(fake)], handoff.time.monotonic() + 2) == "ok"
    fake.write_text("#!/bin/sh\nexit 7")
    with pytest.raises(handoff.HandoffError, match=r"failed \(7\)"):
        handoff.run([str(fake)], handoff.time.monotonic() + 2)


class Harness:
    def __init__(self, modes, identities=None, fail=None):
        self.modes = iter(modes)
        self.current = None
        self.calls = []
        self.identities = iter(identities or [("p1", "t1", "w1")] * 20)
        self.fail = fail

    def run(self, command, deadline):
        self.calls.append(command)
        if self.fail and self.fail in command:
            raise handoff.HandoffError("command failed")
        if command[-2:] == ["pane", "list"]:
            location = next(self.identities)
            locations = [] if location == "missing" else [("p1", "t1", "w1"), ("p2", "t2", "w1")] if location == "duplicate" else [location]
            panes = [{"pane_id": pane, "tab_id": tab, "workspace_id": workspace, "agent_session": {"agent": "codex", "value": "thread"}} for pane, tab, workspace in locations]
            return json.dumps({"result": {"panes": panes}})
        if "read" in command:
            try:
                self.current = next(self.modes)
            except StopIteration:
                pass
            if self.current == "newplan":
                return screen(PLAN, "› newer user input")
            if self.current == "ambiguous":
                return screen(PARTIAL_CONTEXT)
            if self.current == "truncateddefault":
                return screen(TRUNCATED_DEFAULT)
            if self.current == "custom":
                return screen("approval budget · Working set · custom status")
            if self.current == "disabledplan":
                return screen(DISABLED_PLAN)
            if self.current == "reorderedplan":
                return screen(REORDERED_PLAN)
            if self.current == "compactplan":
                return screen("gpt-6-astra low · ~/setforge · Context 1… Plan mode")
            if self.current == "unknown":
                return screen("unrecognized footer")
            return screen(PLAN if self.current == "plan" else DEFAULT)
        if "prompt" in command:
            return json.dumps({"result": {"agent": {"pane_id": "p1", "agent_session": {"value": "thread"}}}})
        return "{}"


def invoke(monkeypatch, tmp_path, harness, target="plan"):
    continuation = tmp_path / "continuation"
    continuation.write_text("continue")
    continuation.chmod(0o600)
    monkeypatch.setattr(handoff, "run", harness.run)
    monkeypatch.setattr(handoff, "STABLE_SECONDS", 0)
    monkeypatch.setattr(handoff, "TIMEOUT_SECONDS", 1)
    clock = [0.0]
    def monotonic():
        clock[0] += 0.1
        return clock[0]
    monkeypatch.setattr(handoff.time, "monotonic", monotonic)
    monkeypatch.setattr(handoff.time, "sleep", lambda _: None)
    args = ["--target-mode", target, "--session", "s", "--thread-id", "thread", "--marker", MARKER, "--continuation-file", str(continuation)]
    if target == "default":
        args += ["--reason", "task changed"]
    handoff.main(args)


def test_entry_sends_plan_once_then_continuation(monkeypatch, tmp_path):
    harness = Harness(["default", "default", "plan", "plan", "plan"])
    invoke(monkeypatch, tmp_path, harness)
    prompts = [call[-1] for call in harness.calls if "prompt" in call]
    assert prompts == ["/plan", "continue"]


def test_ambiguous_entry_sends_plan_once_then_requires_plan(monkeypatch, tmp_path):
    harness = Harness(["ambiguous", "ambiguous", "plan", "plan", "plan"])
    invoke(monkeypatch, tmp_path, harness)
    prompts = [call[-1] for call in harness.calls if "prompt" in call]
    assert prompts == ["/plan", "continue"]


def test_ambiguous_after_plan_action_never_continues(monkeypatch, tmp_path):
    harness = Harness(["ambiguous"] * 30)
    with pytest.raises(handoff.HandoffError, match="target plan footer was not verified"):
        invoke(monkeypatch, tmp_path, harness)
    prompts = [call[-1] for call in harness.calls if "prompt" in call]
    assert prompts == ["/plan"]


@pytest.mark.parametrize("proved", ["disabledplan", "reorderedplan", "compactplan"])
def test_any_initial_status_sends_one_plan_then_continues_on_native_proof(monkeypatch, tmp_path, proved):
    harness = Harness(["custom", "custom", proved, proved, proved])
    invoke(monkeypatch, tmp_path, harness)
    prompts = [call[-1] for call in harness.calls if "prompt" in call]
    assert prompts == ["/plan", "continue"]


def test_missing_native_plan_after_setter_never_continues(monkeypatch, tmp_path):
    harness = Harness(["custom"] * 30)
    with pytest.raises(handoff.HandoffError, match="target plan footer was not verified"):
        invoke(monkeypatch, tmp_path, harness)
    prompts = [call[-1] for call in harness.calls if "prompt" in call]
    assert prompts == ["/plan"]


@pytest.mark.parametrize("post_action", ["default", "truncateddefault"])
def test_exit_sends_raw_shift_tab_once_then_continuation(monkeypatch, tmp_path, post_action):
    harness = Harness(["plan", "plan", post_action, post_action, post_action])
    invoke(monkeypatch, tmp_path, harness, "default")
    raw = [call for call in harness.calls if "send-text" in call]
    assert len(raw) == 1 and raw[0][-1] == "\x1b[Z"


@pytest.mark.parametrize("ready", ["default", "truncateddefault"])
def test_already_default_skips_mode_action_then_continues(monkeypatch, tmp_path, ready):
    harness = Harness([ready] * 5)
    invoke(monkeypatch, tmp_path, harness, "default")
    prompts = [call[-1] for call in harness.calls if "prompt" in call]
    assert prompts == ["continue"]
    assert not any("send-text" in call for call in harness.calls)


def test_already_plan_still_sends_one_idempotent_setter(monkeypatch, tmp_path):
    harness = Harness(["plan", "plan", "plan", "plan"])
    invoke(monkeypatch, tmp_path, harness)
    prompts = [call[-1] for call in harness.calls if "prompt" in call]
    assert prompts == ["/plan", "continue"]
    assert not any("send-text" in call for call in harness.calls)


@pytest.mark.parametrize("identities", [
    [("p1", "t1", "w1"), ("p2", "t1", "w1")],
    [("p1", "t1", "w1"), ("p1", "t2", "w1")],
])
def test_moved_identity_aborts_before_mode_input(monkeypatch, tmp_path, identities):
    harness = Harness(["default"] * 5, identities=identities)
    with pytest.raises(handoff.HandoffError, match="moved"):
        invoke(monkeypatch, tmp_path, harness)
    assert not any(call[-1:] == ["/plan"] for call in harness.calls)


def test_command_failure_prevents_continuation(monkeypatch, tmp_path):
    harness = Harness(["default"] * 5, fail="/plan")
    with pytest.raises(handoff.HandoffError, match="command failed"):
        invoke(monkeypatch, tmp_path, harness)
    assert not any(call[-1:] == ["continue"] for call in harness.calls)


@pytest.mark.parametrize("identity", ["missing", "duplicate"])
def test_missing_or_duplicate_identity_sends_nothing(monkeypatch, tmp_path, identity):
    harness = Harness(["default"], identities=[identity])
    with pytest.raises(handoff.HandoffError, match="immutable thread match"):
        invoke(monkeypatch, tmp_path, harness)
    assert not any("prompt" in call or "send-text" in call for call in harness.calls)


def test_new_input_after_mode_action_prevents_continuation(monkeypatch, tmp_path):
    harness = Harness(["default", "default", "plan", "newplan"])
    with pytest.raises(handoff.HandoffError, match="new user input"):
        invoke(monkeypatch, tmp_path, harness)
    assert not any(call[-1:] == ["continue"] for call in harness.calls)


@pytest.mark.parametrize("contents,mode", [("", 0o600), ("continue", 0o644)])
def test_invalid_continuation_is_rejected_before_herdr(monkeypatch, tmp_path, contents, mode):
    continuation = tmp_path / "continuation"
    continuation.write_text(contents)
    continuation.chmod(mode)
    harness = Harness(["default"])
    monkeypatch.setattr(handoff, "run", harness.run)
    args = ["--target-mode", "plan", "--session", "s", "--thread-id", "thread", "--marker", MARKER, "--continuation-file", str(continuation)]
    with pytest.raises(handoff.HandoffError):
        handoff.main(args)
    assert harness.calls == []


def test_subprocess_timeout_fails_closed(tmp_path):
    fake = tmp_path / "fake-herdr"
    fake.write_text("#!/bin/sh\nsleep 1")
    fake.chmod(0o755)
    with pytest.raises(handoff.HandoffError, match="timed out"):
        handoff.run([str(fake)], handoff.time.monotonic() + 0.01)


@pytest.mark.parametrize("marker_style", ["bare", "bullet"])
@pytest.mark.parametrize("target,initial,action", [("plan", "default", "/plan"), ("default", "plan", "shift-tab")])
@pytest.mark.parametrize("default_footer", [DEFAULT, TRUNCATED_DEFAULT])
def test_real_cli_with_fake_herdr_observes_stability_and_one_action(tmp_path, target, initial, action, marker_style, default_footer):
    fake = tmp_path / "herdr"
    fake.write_text(textwrap.dedent("""\
        #!/usr/bin/env python3
        import json, os, sys, time
        path = os.environ['FAKE_HERDR_STATE']
        with open(path) as stream: state = json.load(stream)
        args = sys.argv[1:]
        if args[:2] == ['--session', 'fake']: args = args[2:]
        if args == ['pane', 'list']:
            out = {'result': {'panes': [{'pane_id':'p1','tab_id':'t1','workspace_id':'w1','agent_session':{'agent':'codex','value':'thread'}}]}}
        elif args[:2] == ['agent', 'read']:
            state['first_read'] = state.get('first_read', time.monotonic())
            footer = state['plan_footer'] if state['mode'] == 'plan' else state['default_footer']
            out = f"assistant final\\n{state['rendered_marker']}\\n\\n› Ask Codex to do anything\\n\\n  {footer}"
        elif args[:3] == ['agent', 'prompt', 'p1'] and args[3] == '/plan':
            state['mode'] = 'plan'; state['action'] = '/plan'; state['action_time'] = time.monotonic()
            out = {'result': {'agent': {'pane_id':'p1','agent_session':{'value':'thread'}}}}
        elif args[:3] == ['pane', 'send-text', 'p1'] and args[3] == '\\x1b[Z':
            state['mode'] = 'default'; state['action'] = 'shift-tab'; state['action_time'] = time.monotonic(); out = {}
        elif args[:3] == ['agent', 'prompt', 'p1']:
            state['continuations'] += 1
            out = {'result': {'agent': {'pane_id':'p1','agent_session':{'value':'thread'}}}}
        else: raise SystemExit(9)
        with open(path, 'w') as stream: json.dump(state, stream)
        print(json.dumps(out) if not isinstance(out, str) else out)
    """))
    fake.chmod(0o755)
    state_path = tmp_path / "state.json"
    rendered_marker = MARKER if marker_style == "bare" else f"• {MARKER}"
    state_path.write_text(json.dumps({
        "mode": initial,
        "rendered_marker": rendered_marker,
        "default_footer": default_footer,
        "plan_footer": PLAN,
        "continuations": 0,
    }))
    continuation = tmp_path / "continuation"
    continuation.write_text("continue")
    continuation.chmod(0o600)
    env = os.environ | {"PATH": f"{tmp_path}:{os.environ['PATH']}", "FAKE_HERDR_STATE": str(state_path)}
    command = [sys.executable, str(SCRIPT), "--target-mode", target, "--session", "fake", "--thread-id", "thread", "--marker", MARKER, "--continuation-file", str(continuation)]
    if target == "default": command += ["--reason", "test fallback"]
    result = subprocess.run(command, text=True, capture_output=True, env=env, timeout=10)
    assert result.returncode == 0, result.stderr
    state = json.loads(state_path.read_text())
    assert state["action"] == action
    assert state["action_time"] - state["first_read"] >= 0.95
    assert state["continuations"] == 1
    assert state["mode"] == target
    assert " READY " in result.stderr and " SUCCESS " in result.stderr
