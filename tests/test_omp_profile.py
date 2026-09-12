from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import socketserver
import stat
import subprocess
import threading
import time

import pytest
import yaml


REPO = Path(__file__).resolve().parents[1]
PROFILE = REPO / "tracked/omp"
CONFIG = REPO / "setforge.yaml"
FIXTURES = REPO / "tests/fixtures"
HELPER = PROFILE / "skills/herdr/scripts/omp_plan_mode_handoff.py"
MARKER = "OMP_PLAN_HANDOFF_0123456789abcdef0123456789abcdef"


def _profile_resources() -> tuple[dict, list[str], dict]:
    config = yaml.safe_load(CONFIG.read_text())
    profile = config["profiles"]["omp"]
    return config["tracked_files"], profile["tracked_files"], config


def test_omp_profile_owns_exact_independent_surface() -> None:
    resources, ids, config = _profile_resources()
    files = sorted(path.relative_to(PROFILE).as_posix() for path in PROFILE.rglob("*") if path.is_file())
    assert len(files) == 36
    assert len(ids) == len(set(ids)) == 36
    assert all(item.startswith("omp_") for item in ids)
    mapped = {Path(resources[item]["src"]).relative_to("omp").as_posix() for item in ids}
    assert mapped == set(files)
    assert all(resources[item]["dst"].startswith("~/.omp/agent/") for item in ids)
    assert not any("codex" in resources[item]["dst"].lower() for item in ids)
    assert not any("opencode" in resources[item]["dst"].lower() for item in ids)
    excluded = {
        "agent.db",
        "models.yml",
        "settings.json",
        "keybindings.json",
        "config.yaml",
        "extensions/herdr-omp-agent-state.ts",
    }
    assert not (set(files) & excluded)
    assert set(config["profiles"]["omp"]["packages"]) == {
        "omp",
        "beads",
        "revdiff",
        "worktrunk",
        "rtk",
    }


def test_omp_profile_declares_exact_modes_and_binary_pin() -> None:
    resources, ids, config = _profile_resources()
    executable = {item for item in ids if resources[item].get("mode") == "0o755"}
    assert len(executable) == 11
    for item in executable:
        source = REPO / "tracked" / resources[item]["src"]
        assert stat.S_IMODE(source.stat().st_mode) == 0o755
    package = config["packages"]["omp"]
    assert package == {
        "type": "github_release",
        "repo": "can1357/oh-my-pi",
        "tag": "v18.1.18",
        "asset": "omp-linux-x64",
        "checksum": "sha256:45421f9a5f112bc47cb9f77c4b4d7927631f8ff859624f821287ec854eb239fc",
        "binary": "omp-linux-x64",
        "rename": "omp",
        "install": "~/.local/bin",
        "chmod": "755",
        "extract": False,
    }


def test_omp_config_and_agent_policy_are_effective() -> None:
    config = yaml.safe_load((PROFILE / "config.yml").read_text())
    assert config["setupVersion"] == 2
    assert config["enabledProviders"] == []
    assert config["modelRoles"] == {
        "default": "openai-codex/gpt-5.6-sol:medium",
        "plan": "openai-codex/gpt-5.6-sol:medium",
        "smol": "openai-codex/gpt-5.6-luna:medium",
        "worker": "openai-codex/gpt-5.6-luna:max",
        "review_correctness": "openai-codex/gpt-6-astra:low",
        "review_critical": "openai-codex/gpt-5.6-sol:low",
        "review_general": "openai-codex/gpt-5.6-terra:low",
    }
    assert config["plan"] == {"enabled": True, "defaultOnStartup": False}
    assert config["async"] == {"enabled": True, "maxJobs": 12}
    assert config["task"] == {
        "batch": True,
        "enableEffort": True,
        "enableLsp": True,
        "maxEffort": "max",
        "maxConcurrency": 12,
        "maxRecursionDepth": 1,
        "disabledAgents": ["task", "sonic", "reviewer", "security-reviewer"],
        "isolation": {"enabled": True, "apply": False, "merge": "patch"},
    }

    expected = {
        "worker": {
            "model": "@worker",
            "thinkingLevel": "max",
            "blocking": None,
            "tools": {"read", "bash", "edit", "write", "grep", "glob", "lsp"},
        },
        "review_correctness": {
            "model": "@review_correctness",
            "thinkingLevel": "low",
            "blocking": True,
            "tools": {"read", "grep", "glob", "web_search"},
        },
        "review_critical": {
            "model": "@review_critical",
            "thinkingLevel": "low",
            "blocking": True,
            "tools": {"read", "grep", "glob", "web_search"},
        },
        "review_general": {
            "model": "@review_general",
            "thinkingLevel": "low",
            "blocking": True,
            "tools": {"read", "grep", "glob", "web_search"},
        },
    }
    for name, wanted in expected.items():
        document = (PROFILE / f"agents/{name}.md").read_text()
        frontmatter = yaml.safe_load(document.split("---", 2)[1])
        assert frontmatter["model"] == wanted["model"]
        assert frontmatter["thinkingLevel"] == wanted["thinkingLevel"]
        assert frontmatter.get("blocking") == wanted["blocking"]
        assert set(item.strip() for item in frontmatter["tools"].split(",")) == wanted["tools"]
        assert "task" not in frontmatter["tools"]


def test_omp_destinations_resolve_only_below_isolated_agent_root(tmp_path: Path) -> None:
    resources, ids, _ = _profile_resources()
    home = tmp_path / "home"
    agent_root = home / ".omp/agent"
    agent_root.mkdir(parents=True)
    resolved_root = agent_root.resolve()
    for item in ids:
        destination = Path(resources[item]["dst"].replace("~", str(home), 1))
        existing = destination
        while not existing.exists():
            existing = existing.parent
        canonical = existing.resolve() / destination.relative_to(existing)
        assert canonical == resolved_root or resolved_root in canonical.parents
    assert {
        home / ".omp/agent/extensions/herdr-omp-agent-state.ts",
        home / ".omp/agent/extensions/herdr-agent-state.ts",
    }.isdisjoint(Path(resources[item]["dst"].replace("~", str(home), 1)) for item in ids)


def test_omp_extension_compiles_and_pure_contracts(tmp_path: Path) -> None:
    build = subprocess.run(
        [
            "bun",
            "build",
            str(PROFILE / "extensions/setforge-plan-workflow.ts"),
            "--target=node",
            "--external",
            "@oh-my-pi/pi-coding-agent",
            f"--outfile={tmp_path / 'extension.js'}",
        ],
        cwd=REPO,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert build.returncode == 0, build.stderr
    env = os.environ | {"HOME": str(tmp_path / "home")}
    result = subprocess.run(
        ["bun", str(FIXTURES / "omp_extension_harness.ts")],
        cwd=REPO,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "activation": "passed",
        "proposal_paths": "passed",
        "resolver": "passed",
        "review_ordering": "passed",
        "registered_tools": ["plan_enter", "revdiff_plan"],
        "registered_commands": ["revdiff-plan"],
    }
    source = (PROFILE / "extensions/setforge-plan-workflow.ts").read_text()
    assert 'pi.on("session_stop"' not in source
    assert 'pi.on("shutdown"' not in source
    assert "Promise.race" not in source


class _HerdrServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, path: str, case: dict[str, object]):
        self.case = case
        self.prompts: list[str] = []
        super().__init__(path, _HerdrHandler)


class _HerdrHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        request = json.loads(self.rfile.readline())
        server = self.server
        case = server.case
        if request["method"] == "agent.get":
            value = {
                "workspace_id": "w1",
                "tab_id": "w1:t1",
                "pane_id": "w1:p1",
                "agent": "omp",
                "agent_session": {
                    "agent": "omp",
                    "kind": "path",
                    "source": "herdr:omp",
                    "value": str(case["session"]),
                },
                "agent_status": "done",
            }
            value.update(case.get("agent", {}))
            response = {"id": request["id"], "result": {"agent": value, "type": "agent_info"}}
        elif request["method"] == "agent.read":
            response = {
                "id": request["id"],
                "result": {
                    "read": {
                        "text": case["screen"],
                        "truncated": case.get("truncated", False),
                        "source": "recent_unwrapped",
                    }
                },
            }
        elif request["method"] == "agent.prompt":
            text = request["params"]["text"]
            server.prompts.append(text)
            if case.get("prompt_error"):
                response = {"id": request["id"], "error": {"code": "injected", "message": "failure"}}
            else:
                if text == "/plan":
                    with Path(case["session"]).open("a") as stream:
                        stream.write(json.dumps({"type": "mode_change", "mode": "plan", "data": {"planFilePath": "local://PLAN.md"}}) + "\n")
                    case["screen"] = str(case["screen"]).replace("build", "🗺 Plan")
                response = {"id": request["id"], "result": {"type": "agent_prompted", "agent": {}}}
        else:
            response = {"id": request["id"], "error": {"code": "unknown", "message": request["method"]}}
        self.wfile.write(json.dumps(response).encode() + b"\n")


def _message(role: str, text: str) -> dict:
    return {"type": "message", "message": {"role": role, "content": [{"type": "text", "text": text}]}}


def _run_handoff_case(
    tmp_path: Path,
    *,
    entries: list[dict],
    screen: str,
    expected_prompts: list[str],
    success: bool = False,
    agent: dict | None = None,
    truncated: bool = False,
    prompt_error: bool = False,
    sent: str | None = None,
    deadline_seconds: float = 0.7,
) -> subprocess.CompletedProcess[str]:
    runtime = tmp_path / "runtime"
    evidence = tmp_path / "evidence"
    runtime.mkdir()
    evidence.mkdir(mode=0o700)
    session = runtime / "session.jsonl"
    session.write_text("".join(json.dumps(entry) + "\n" for entry in entries))
    continuation = evidence / "continuation"
    continuation.write_text("PRIVATE_CONTINUATION")
    continuation.chmod(0o600)
    socket_path = str(runtime / "herdr.sock")
    case = {
        "session": session,
        "screen": screen,
        "agent": agent or {},
        "truncated": truncated,
        "prompt_error": prompt_error,
    }
    server = _HerdrServer(socket_path, case)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state = {
        "socket": socket_path,
        "workspace": "w1",
        "tab": "w1:t1",
        "pane": "w1:p1",
        "session": str(session),
        "marker": MARKER,
        "continuation_file": str(continuation),
        "deadline": time.time() + deadline_seconds,
    }
    state_path = evidence / "state.json"
    state_path.write_text(json.dumps(state))
    state_path.chmod(0o600)
    if sent:
        marker = evidence / sent
        marker.write_text("1\n")
        marker.chmod(0o600)
    try:
        result = subprocess.run(
            [str(HELPER), str(evidence)],
            env=os.environ | {"PYTHONDONTWRITEBYTECODE": "1"},
            text=True,
            capture_output=True,
            timeout=8,
        )
    finally:
        server.shutdown()
        server.server_close()
    assert server.prompts == expected_prompts
    if success:
        assert result.returncode == 0, result.stderr
        assert not evidence.exists()
    else:
        assert result.returncode != 0
        assert (evidence / "FAILURE").is_file()
        for path in evidence.iterdir():
            if path.is_file():
                assert stat.S_IMODE(path.stat().st_mode) == 0o600
    return result


@pytest.mark.parametrize(
    ("name", "changes"),
    [
        ("nonempty-composer", {"screen_suffix": " typed"}),
        ("dialog", {"screen": f"Select an option\n{MARKER}\n╰─"}),
        ("duplicate-marker", {"extra": [_message("assistant", MARKER)]}),
        ("new-input", {"extra": [_message("user", "NEW INPUT")]}),
        ("identity-drift", {"agent": {"tab_id": "w1:t2"}}),
        ("truncated", {"truncated": True}),
        ("restart-plan", {"sent": "SENT_PLAN"}),
        ("restart-continuation", {"sent": "SENT_CONTINUATION"}),
        ("timeout", {"screen": "no marker\n╰─"}),
    ],
)
def test_omp_handoff_refuses_unsafe_or_replayed_boundaries(tmp_path: Path, name: str, changes: dict) -> None:
    entries = [_message("user", "SUBSTANTIAL"), _message("assistant", MARKER), *changes.get("extra", [])]
    base = f"transcript\n{MARKER}\n π > model > build\n╰─"
    _run_handoff_case(
        tmp_path,
        entries=entries,
        screen=changes.get("screen", base + changes.get("screen_suffix", "")),
        expected_prompts=[],
        agent=changes.get("agent"),
        truncated=changes.get("truncated", False),
        sent=changes.get("sent"),
    )


def test_omp_handoff_crosses_each_input_boundary_once_and_cleans_up(tmp_path: Path) -> None:
    entries = [_message("user", "SUBSTANTIAL"), _message("assistant", MARKER)]
    screen = f"transcript\n{MARKER}\n π > model > build\n╰─"
    _run_handoff_case(
        tmp_path,
        entries=entries,
        screen=screen,
        expected_prompts=["/plan", "PRIVATE_CONTINUATION"],
        success=True,
        deadline_seconds=5,
    )


def test_omp_handoff_is_idempotent_when_native_plan_is_already_active(tmp_path: Path) -> None:
    entries = [
        _message("user", "SUBSTANTIAL"),
        _message("assistant", MARKER),
        {"type": "mode_change", "mode": "plan", "data": {"planFilePath": "local://PLAN.md"}},
    ]
    screen = f"transcript\n{MARKER}\n π > model > 🗺 Plan\n╰─"
    _run_handoff_case(
        tmp_path,
        entries=entries,
        screen=screen,
        expected_prompts=["PRIVATE_CONTINUATION"],
        success=True,
        deadline_seconds=4,
    )


def test_omp_handoff_retains_evidence_after_prompt_failure(tmp_path: Path) -> None:
    entries = [_message("user", "SUBSTANTIAL"), _message("assistant", MARKER)]
    screen = f"transcript\n{MARKER}\n π > model > build\n╰─"
    _run_handoff_case(
        tmp_path,
        entries=entries,
        screen=screen,
        expected_prompts=["/plan"],
        prompt_error=True,
        deadline_seconds=4,
    )


def _omp_test_binary() -> Path:
    configured = os.environ.get("OMP_TEST_BIN")
    if not configured:
        pytest.skip("set OMP_TEST_BIN to the pinned OMP binary for runtime acceptance")
    binary = Path(configured)
    assert binary.is_file()
    return binary


def test_omp_runtime_loads_profile_agents_skills_and_extension(tmp_path: Path) -> None:
    binary = _omp_test_binary()
    home = tmp_path / "home"
    agent = home / ".omp/agent"
    shutil.copytree(PROFILE, agent)
    (agent / "models.yml").write_text(
        """providers:
  profile-test:
    baseUrl: http://127.0.0.1:9/v1
    api: openai-completions
    auth: none
    models:
      - id: mock
        name: Profile Test
        contextWindow: 131072
        maxTokens: 8192
"""
    )
    overlay = tmp_path / "overlay.yml"
    overlay.write_text("modelRoles:\n  default: profile-test/mock\n  plan: profile-test/mock\n")
    env = os.environ.copy()
    for name in (
        "PI_CODING_AGENT_DIR",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_OAUTH_TOKEN",
        "CODEX_HOME",
    ):
        env.pop(name, None)
    env["HOME"] = str(home)
    result = subprocess.run(
        [
            str(binary),
            "--mode",
            "rpc",
            "--no-session",
            "--cwd",
            str(tmp_path),
            "--config",
            str(overlay),
        ],
        input='{"id":"probe","type":"get_state"}\n',
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    frames = [json.loads(line) for line in result.stdout.splitlines()]
    assert not [frame for frame in frames if frame.get("type") == "extension_error"]
    response = next(frame for frame in frames if frame.get("command") == "get_state")
    assert response["success"] is True
    state = response["data"]
    tools = {item["name"]: item for item in state["dumpTools"]}
    assert {"plan_enter", "revdiff_plan", "task", "hub"} <= tools.keys()
    task_schema = tools["task"]["parameters"]
    assert "isolated" in task_schema["properties"]["tasks"]["items"]["properties"]
    hub_ops = tools["hub"]["parameters"]["properties"]["op"]["enum"]
    assert {"list", "send", "wait", "jobs", "cancel"} <= set(hub_ops)
    available_agents = tools["task"]["description"].split("# Available Agents", 1)[1]
    for name in ("worker", "review_correctness", "review_critical", "review_general", "scout"):
        assert f"### {name}" in available_agents
    for disabled in ("task", "sonic", "reviewer", "security-reviewer"):
        assert f"### {disabled}" not in available_agents
    system_prompt = "\n".join(state["systemPrompt"])
    for name in (
        "beads",
        "beads-adapt",
        "beads-bootstrap",
        "cross-project-planning",
        "herdr",
        "revdiff",
        "revdiff-plan",
        "review-gate",
        "setforge",
        "usage-check",
    ):
        assert f"- {name}:" in system_prompt
    commands = {
        command["name"]: command.get("source")
        for frame in frames
        if frame.get("type") == "available_commands_update"
        for command in frame["commands"]
    }
    assert commands["revdiff-plan"] == "extension"


class _ModelProbeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        self.requests: list[dict] = []
        super().__init__(("127.0.0.1", 0), _ModelProbeHandler)


class _ModelProbeHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        return

    def do_GET(self) -> None:
        models = ["root", "worker", "correctness", "critical", "general", "smol"]
        body = json.dumps(
            {
                "object": "list",
                "data": [
                    {"id": model, "object": "model", "created": 0, "owned_by": "profile-test"}
                    for model in models
                ],
            }
        ).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        request = json.loads(self.rfile.read(length))
        self.server.requests.append(request)
        model = request.get("model")
        messages = request.get("messages", [])
        last = messages[-1] if messages else {}
        last_text = json.dumps(last.get("content", ""))
        tool_names = [tool.get("function", {}).get("name") for tool in request.get("tools", [])]
        if model == "root" and "RUN_CHILD_SCHEMA_PROBE" in last_text:
            agents = [
                ("WorkerProbe", "worker"),
                ("CorrectnessProbe", "review_correctness"),
                ("CriticalProbe", "review_critical"),
                ("GeneralProbe", "review_general"),
                ("ScoutProbe", "scout"),
            ]
            arguments = {
                "context": "# Goal\nProbe child schemas\n# Constraints\nRead only\n# Contract\nYield model and tools",
                "tasks": [
                    {
                        "name": name,
                        "agent": agent,
                        "task": "# Target\nInspect schema\n# Change\nYield once\n# Acceptance\nReturn done",
                        "effort": "hi",
                        "isolated": False,
                    }
                    for name, agent in agents
                ],
            }
            event = ("tool", "task", json.dumps(arguments), "call-task-probe")
        elif "yield" in tool_names:
            event = ("tool", "yield", json.dumps({"data": "DONE"}), f"call-yield-{len(self.server.requests)}")
        else:
            event = ("text", "DONE", "", "")

        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.end_headers()
        base = {
            "id": f"profile-test-{len(self.server.requests)}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
        }

        def send(value: dict) -> None:
            self.wfile.write(("data: " + json.dumps(value, separators=(",", ":")) + "\n\n").encode())
            self.wfile.flush()

        if event[0] == "tool":
            send(
                base
                | {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": event[3],
                                        "type": "function",
                                        "function": {"name": event[1], "arguments": event[2]},
                                    }
                                ],
                            },
                            "finish_reason": None,
                        }
                    ]
                }
            )
            send(base | {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]})
        else:
            send(
                base
                | {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": event[1]},
                            "finish_reason": None,
                        }
                    ]
                }
            )
            send(base | {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def test_omp_runtime_child_roles_and_tools_are_effective(tmp_path: Path) -> None:
    binary = _omp_test_binary()
    server = _ModelProbeServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    home = tmp_path / "home"
    agent = home / ".omp/agent"
    shutil.copytree(PROFILE, agent)
    models = ["root", "worker", "correctness", "critical", "general", "smol"]
    (agent / "models.yml").write_text(
        "providers:\n"
        "  profile-test:\n"
        f"    baseUrl: http://127.0.0.1:{server.server_port}/v1\n"
        "    api: openai-completions\n"
        "    auth: none\n"
        "    models:\n"
        + "".join(
            f"      - id: {model}\n"
            f"        name: {model}\n"
            "        contextWindow: 131072\n"
            "        maxTokens: 8192\n"
            for model in models
        )
    )
    overlay = tmp_path / "overlay.yml"
    overlay.write_text(
        "modelRoles:\n"
        "  default: profile-test/root\n"
        "  plan: profile-test/root\n"
        "  worker: profile-test/worker\n"
        "  review_correctness: profile-test/correctness\n"
        "  review_critical: profile-test/critical\n"
        "  review_general: profile-test/general\n"
        "  smol: profile-test/smol\n"
    )
    env = os.environ.copy()
    for name in (
        "PI_CODING_AGENT_DIR",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_OAUTH_TOKEN",
        "CODEX_HOME",
    ):
        env.pop(name, None)
    env["HOME"] = str(home)
    stdout_path = tmp_path / "rpc.out"
    stderr_path = tmp_path / "rpc.err"
    with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
        process = subprocess.Popen(
            [
                str(binary),
                "--mode",
                "rpc",
                "--no-session",
                "--no-title",
                "--cwd",
                str(tmp_path),
                "--config",
                str(overlay),
            ],
            stdin=subprocess.PIPE,
            stdout=stdout,
            stderr=stderr,
            env=env,
            text=True,
        )
        assert process.stdin is not None
        process.stdin.write('{"id":"probe","type":"prompt","message":"RUN_CHILD_SCHEMA_PROBE"}\n')
        process.stdin.flush()
        deadline = time.monotonic() + 20
        wanted_models = {"worker", "correctness", "critical", "general", "smol"}
        while time.monotonic() < deadline:
            observed = {request.get("model") for request in server.requests}
            if wanted_models <= observed:
                break
            time.sleep(0.05)
        process.stdin.close()
        process.stdin = None
        process.wait(timeout=15)
    server.shutdown()
    server.server_close()
    assert process.returncode == 0, stderr_path.read_text()

    child_requests: dict[str, dict] = {}
    for request in server.requests:
        model = request.get("model")
        names = [tool.get("function", {}).get("name") for tool in request.get("tools", [])]
        if model in wanted_models and names:
            child_requests.setdefault(model, request)
    assert child_requests.keys() == wanted_models
    tool_sets = {
        model: {tool["function"]["name"] for tool in request["tools"]}
        for model, request in child_requests.items()
    }
    assert tool_sets["worker"] == {
        "read",
        "bash",
        "edit",
        "write",
        "grep",
        "glob",
        "lsp",
        "yield",
        "hub",
    }
    for model in ("correctness", "critical", "general"):
        assert tool_sets[model] == {"read", "grep", "glob", "web_search", "yield", "hub"}
    for model, names in tool_sets.items():
        assert "plan_enter" not in names, model
        assert "revdiff_plan" not in names, model
        assert "task" not in names, model
