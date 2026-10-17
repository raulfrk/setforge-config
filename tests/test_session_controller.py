"""Redaction and typed-prompt filtering in the session-controller status script."""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "tracked/claude/skills/session-controller/scripts/session_status.py"
spec = importlib.util.spec_from_file_location("session_status", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

SECRETS = [  # (text, the part that must not survive)
    ("https://example.com/callback?code=abc123&state=xyz", "abc123"),
    ("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKfakefakefake raul@devbox", "AAAAC3Nza"),
    ("-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXk\n-----END OPENSSH PRIVATE KEY-----", "b3Bl"),
    ("ghp_" + "a1B2" * 9, "a1B2"),
    ("sk-ant-api03-" + "Zz9" * 10, "Zz9"),
    ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig", "eyJhbG"),
    ("password=hunter2", "hunter2"),
    ("tskey-auth-kAbC123DEF", "kAbC123"),
    ("Q2xhdWRlIGlzIGEgZ29vZCBmcmllbmQ0Mg9xYz", "Q2xhdWRl"),
    ("access_token=ya29abcdefSECRET", "ya29abcdef"),
    ("client_secret=GOCSPXsecretvalue", "GOCSPX"),
    ("ANTHROPIC_API_KEY=abcdefghij", "abcdefghij"),
    ('{"password": "hunter2"}', "hunter2"),
    ("wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "bPxRfiCY"),
    ("localhost:54545/callback?code=4%2F0AbcXyz&state=st8xyzRandom", "0AbcXyz"),
]


@pytest.mark.parametrize(("text", "sensitive"), SECRETS)
def test_redact_removes_secret(text, sensitive):
    out = m.redact(f"before {text} after", limit=1000)
    assert out.startswith("before ") and out.endswith(" after")
    assert sensitive not in out


def test_redact_keeps_plain_text_and_bounds_after_redacting():
    assert m.redact("deploy the cache guest  now") == "deploy the cache guest now"
    assert m.redact("the code and state look fine") == "the code and state look fine"
    out = m.redact("x " * 50 + "ghp_" + "a1B2" * 20, limit=110)
    assert len(out) <= 110 and "a1B2" not in out


def user(content, **extra):
    return {"type": "user", "message": {"content": content}, **extra}


@pytest.mark.parametrize("record", [
    user("<system-reminder>context</system-reminder>"),
    user("<task-notification>done</task-notification>"),
    user("<local-command-stdout>x</local-command-stdout>"),
    user("<command-name>/clear</command-name>"),
    user("<cross-session>relay</cross-session>"),
    user("[SYSTEM] note"),
    user("This session is being continued from a previous conversation"),
    user("typed", isMeta=True),
    user("typed", isSidechain=True),
    user("typed", toolUseResult={}),
    user([{"type": "tool_result", "content": "x"}]),
    {"type": "assistant", "message": {"content": "typed"}},
])
def test_typed_prompt_skips_non_prompts(record):
    assert m.typed_prompt(record) is None


def test_typed_prompt_accepts_plain_user_string():
    assert m.typed_prompt(user("check the cache guest")) == "check the cache guest"


def test_summarize_takes_last_values(tmp_path):
    log = tmp_path / "s.jsonl"
    records = [
        user("first", timestamp="t1"),
        {"type": "assistant", "timestamp": "t2", "message": {"content": [
            {"type": "tool_use", "name": "Bash"}, {"type": "text", "text": "reply one"}]}},
        user("<system-reminder>x", timestamp="t3"),
        user("second", timestamp="t4"),
        {"type": "assistant", "timestamp": "t5", "message": {"content": [
            {"type": "tool_use", "name": "Read"}]}},
    ]
    log.write_text("\n".join(json.dumps(r) for r in records) + "\nnot json\n")
    last = m.summarize(log)
    assert last == {"time": "t5", "prompt": "second", "tools": ["Bash", "Read"], "reply": "reply one"}
