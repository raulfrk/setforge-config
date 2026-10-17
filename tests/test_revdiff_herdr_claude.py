from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = REPO_ROOT / "plugins/revdiff-herdr-claude"
SHARED_ROOT = REPO_ROOT / "plugins/revdiff-herdr"
HOOK = PLUGIN_ROOT / "scripts/plan-review-hook.py"
EXTRACTOR = PLUGIN_ROOT / "skills/revdiff-plan/scripts/extract-last-message.sh"


@pytest.fixture
def review(tmp_path: Path):
    """Run the hook against a fake reviewer in the plugin data override layer."""
    # A private plugin root keeps the bundled launchers out of reach.
    plugin_root = tmp_path / "plugin"
    (plugin_root / "scripts").mkdir(parents=True)
    (plugin_root / "scripts/resolve-launcher.sh").symlink_to(
        (PLUGIN_ROOT / "scripts/resolve-launcher.sh").resolve()
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    revdiff = fake_bin / "revdiff"
    revdiff.write_text("#!/bin/sh\nexit 0\n")
    revdiff.chmod(0o755)
    data = tmp_path / "data"
    (data / "scripts").mkdir(parents=True)
    snapshots = tmp_path / "tmp"
    snapshots.mkdir()
    calls = tmp_path / "calls.log"

    def fake_reviewer(script: Path, log: Path, rc: int, annotations: str) -> None:
        script.write_text(
            "#!/bin/sh\n"
            f'printf "%s\\n" "$@" >> "{log}"\n'
            f"printf '%s' '{annotations}'\n"
            f"exit {rc}\n"
        )
        script.chmod(0o755)

    def run(
        plan: str,
        *,
        launcher_rc: int = 0,
        annotations: str = "",
        tool_name: str = "ExitPlanMode",
        path: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        fake_reviewer(data / "scripts/launch-revdiff.sh", calls, launcher_rc, annotations)
        env = {
            **os.environ,
            "PATH": path if path is not None else f"{fake_bin}:{os.environ['PATH']}",
            "TMPDIR": str(snapshots),
            "CLAUDE_PLUGIN_ROOT": str(plugin_root),
            "CLAUDE_PLUGIN_DATA": str(data),
        }
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": tool_name,
            "tool_input": {"plan": plan},
            "cwd": str(tmp_path),
        }
        return subprocess.run(
            ["python3", str(HOOK)],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    run.calls = calls
    run.snapshots = snapshots
    return run


def decision(result: subprocess.CompletedProcess[str]) -> dict[str, str]:
    return json.loads(result.stdout)["hookSpecificOutput"]


def test_review_without_annotations_continues_to_native_approval(review) -> None:
    result = review("# Plan\n\nDo the thing.\n")

    assert result.returncode == 0
    assert decision(result)["permissionDecision"] == "ask"
    assert decision(result)["permissionDecisionReason"] == (
        "Plan reviewed in RevDiff with no annotations."
    )
    assert review.calls.read_text().startswith(f"--only={review.snapshots}/plan-rev-")
    assert list(review.snapshots.iterdir()) == []


def test_annotations_block_exit_and_keep_snapshot_for_next_revision(review) -> None:
    result = review("# Plan\n", launcher_rc=10, annotations="## plan.md:1 ( )\nwhy?")

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("The user reviewed the plan in RevDiff and added annotations. ")
    assert "## plan.md:1 ( )\nwhy?" in result.stderr
    (snapshot,) = review.snapshots.iterdir()
    assert f"<!-- previous revision: {snapshot} -->" in result.stderr
    assert snapshot.read_text() == "# Plan\n"


def test_revision_compares_with_previous_snapshot_and_strips_marker(review) -> None:
    review("# Plan\n", launcher_rc=10, annotations="change it")
    (old,) = review.snapshots.iterdir()
    review.calls.write_text("")

    result = review(f"<!-- previous revision: {old} -->\n# Plan v2\n")

    assert decision(result)["permissionDecision"] == "ask"
    old_arg, new_arg = review.calls.read_text().splitlines()
    assert old_arg == f"--compare-old={old}"
    assert new_arg.startswith(f"--compare-new={review.snapshots}/plan-rev-")
    assert list(review.snapshots.iterdir()) == []


def test_untrusted_previous_revision_marker_is_not_opened(review, tmp_path: Path) -> None:
    secret = tmp_path / "secret.md"
    secret.write_text("secret")

    result = review(f"<!-- previous revision: {secret} -->\n# Plan\n")

    assert decision(result)["permissionDecision"] == "ask"
    assert "previous revision snapshot is unavailable" in decision(result)["permissionDecisionReason"]
    assert not review.calls.exists()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"launcher_rc": 1}, "launcher exited with status 1"),
        ({"launcher_rc": 10}, "returned no annotation text"),
        ({"path": "/usr/bin:/bin"}, "revdiff binary is not available"),
    ],
)
def test_failed_review_is_reported_as_not_reviewed(review, kwargs, message) -> None:
    result = review("# Plan\n", **kwargs)

    assert result.returncode == 0
    assert decision(result)["permissionDecision"] == "ask"
    reason = decision(result)["permissionDecisionReason"]
    assert reason.startswith("RevDiff plan review failed: ")
    assert "The plan was NOT reviewed in RevDiff; this is not an annotation-free review." in reason
    assert message in reason
    assert list(review.snapshots.iterdir()) == []


def test_hook_runs_on_exit_plan_mode() -> None:
    hooks = json.loads((PLUGIN_ROOT / "hooks/hooks.json").read_text())

    (entry,) = hooks["hooks"]["PreToolUse"]
    assert entry["matcher"] == "ExitPlanMode"


def test_other_tools_are_ignored(review) -> None:
    result = review("# Plan\n", tool_name="Bash")

    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert not review.calls.exists()


def test_shared_launchers_are_the_shared_plugin_files() -> None:
    links = [path for path in PLUGIN_ROOT.rglob("*") if path.is_symlink()]

    assert links
    for link in links:
        assert link.resolve(strict=True).is_relative_to(SHARED_ROOT), link
    assert (PLUGIN_ROOT / "skills/revdiff/scripts/launch-revdiff.sh").resolve() == (
        SHARED_ROOT / "skills/revdiff/scripts/launch-revdiff.sh"
    )


def test_marketplace_lists_the_claude_plugin() -> None:
    marketplace = json.loads((REPO_ROOT / ".claude-plugin/marketplace.json").read_text())
    manifest = json.loads((PLUGIN_ROOT / ".claude-plugin/plugin.json").read_text())

    (entry,) = [plugin for plugin in marketplace["plugins"] if plugin["name"] == "revdiff-herdr"]
    assert entry["name"] == manifest["name"] == "revdiff-herdr"
    assert (REPO_ROOT / entry["source"]).resolve() == PLUGIN_ROOT


def test_extractor_returns_last_main_conversation_text(tmp_path: Path) -> None:
    def record(message_id: str, block: dict, **extra) -> str:
        return json.dumps({
            "type": "assistant",
            "sessionId": "session-a",
            "message": {"id": message_id, "content": [block]},
            **extra,
        })

    transcript = tmp_path / "session-a.jsonl"
    transcript.write_text("\n".join([
        record("m1", {"type": "text", "text": "older"}),
        record("m2", {"type": "text", "text": "# Plan"}),
        record("m2", {"type": "tool_use", "name": "Bash", "input": {}}),
        record("m2", {"type": "text", "text": "second part"}),
        record("m3", {"type": "text", "text": "subagent"}, isSidechain=True),
        json.dumps({"type": "user", "sessionId": "session-a", "message": {"content": "hi"}}),
    ]) + "\n")

    result = subprocess.run(
        [str(EXTRACTOR), str(transcript), "session-a"],
        capture_output=True, text=True, check=False,
    )
    wrong_session = subprocess.run(
        [str(EXTRACTOR), str(transcript), "session-b"],
        capture_output=True, text=True, check=False,
    )

    assert (result.returncode, result.stdout) == (0, "# Plan\nsecond part\n")
    assert wrong_session.returncode == 1
