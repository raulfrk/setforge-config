from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess

import pytest
import yaml


REPO = Path(__file__).resolve().parents[1]
PROFILE = REPO / "tracked/opencode"
CONFIG = REPO / "setforge.yaml"
FIXTURES = REPO / "tests/fixtures"


def _profile_resources() -> tuple[dict, list[str]]:
    config = yaml.safe_load(CONFIG.read_text())
    ids = config["profiles"]["opencode"]["tracked_files"]
    return config["tracked_files"], ids


def test_opencode_profile_owns_exact_independent_surface() -> None:
    resources, ids = _profile_resources()
    files = sorted(path.relative_to(PROFILE).as_posix() for path in PROFILE.rglob("*") if path.is_file())
    assert len(files) == 37
    assert len(ids) == len(set(ids)) == 37
    mapped = {Path(resources[item]["src"]).relative_to("opencode").as_posix() for item in ids}
    assert mapped == set(files)
    assert all(resources[item]["dst"].startswith("~/.config/opencode/") for item in ids)
    assert not any(path in mapped for path in {"opencode.json", "opencode.jsonc", "tui.jsonc", "package.json"})
    assert not any("codex" in resources[item]["dst"] for item in ids)
    assert set(yaml.safe_load(CONFIG.read_text())["profiles"]["opencode"]["packages"]) == {
        "beads",
        "revdiff",
        "worktrunk",
        "rtk",
    }


def test_opencode_profile_declares_script_modes() -> None:
    resources, ids = _profile_resources()
    executable = {item for item in ids if resources[item].get("mode") == "0o755"}
    assert len(executable) == 10
    for item in executable:
        source = REPO / "tracked" / resources[item]["src"]
        assert stat.S_IMODE(source.stat().st_mode) == 0o755


@pytest.fixture(scope="module")
def opencode_debug(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    root = tmp_path_factory.mktemp("opencode-profile")
    config_root = root / "config"
    shutil.copytree(PROFILE, config_root / "opencode")
    worktree = root / "worktree"
    worktree.mkdir()
    env = os.environ | {
        "HOME": str(root / "home"),
        "XDG_CONFIG_HOME": str(config_root),
        "XDG_DATA_HOME": str(root / "data"),
        "XDG_STATE_HOME": str(root / "state"),
        "XDG_CACHE_HOME": str(root / "cache"),
    }
    executable = shutil.which("opencode")
    assert executable is not None

    def run(*args: str) -> object:
        output = root / ("-".join(args) + ".json")
        with output.open("w") as stream:
            subprocess.run(
                [executable, "debug", *args],
                cwd=worktree,
                env=env,
                text=True,
                stdout=stream,
                stderr=subprocess.PIPE,
                timeout=60,
                check=True,
            )
        return json.loads(output.read_text())

    return {
        "build": run("agent", "build"),
        "plan": run("agent", "plan"),
        "worker": run("agent", "worker"),
        "correctness": run("agent", "review_correctness"),
        "skills": run("skill"),
    }


def test_opencode_agents_resolve_models_and_permissions(opencode_debug: dict[str, object]) -> None:
    build = opencode_debug["build"]
    plan = opencode_debug["plan"]
    worker = opencode_debug["worker"]
    correctness = opencode_debug["correctness"]
    assert build["model"] == {"providerID": "openai", "modelID": "gpt-5.6-sol"}
    assert build["variant"] == "medium"
    assert plan["model"] == build["model"] and plan["variant"] == "medium"
    assert worker["model"] == {"providerID": "openai", "modelID": "gpt-5.6-luna"}
    assert worker["variant"] == "max"
    assert correctness["model"] == {"providerID": "openai", "modelID": "gpt-6-astra"}
    assert correctness["variant"] == "low"
    assert any(rule["permission"] == "setforge_plan_enter" and rule["action"] == "allow" for rule in build["permission"])
    edit_rules = [rule for rule in plan["permission"] if rule["permission"] == "edit"]
    assert edit_rules[0] == {"permission": "edit", "pattern": "*", "action": "deny"}
    assert any(rule["action"] == "allow" and rule["pattern"] == ".opencode/plans/*.md" for rule in edit_rules[1:])
    assert any(rule["action"] == "allow" and rule["pattern"].endswith("/data/opencode/plans/*.md") for rule in edit_rules[1:])
    assert any(rule["permission"] == "setforge_plan_enter" and rule["action"] == "deny" for rule in plan["permission"])
    assert any(rule["permission"] == "setforge_plan_exit" and rule["action"] == "ask" for rule in plan["permission"])
    assert any(rule["permission"] == "spawn_agent" and rule["action"] == "deny" for rule in worker["permission"])
    assert {rule["permission"] for rule in correctness["permission"] if rule["action"] == "allow"} >= {"read", "glob", "grep"}


def test_opencode_discovers_all_profile_skills(opencode_debug: dict[str, object]) -> None:
    skills = {item["name"] for item in opencode_debug["skills"]}
    assert skills >= {
        "review-gate",
        "setforge",
        "usage-check",
        "herdr",
        "beads",
        "beads-bootstrap",
        "beads-adapt",
        "cross-project-planning",
        "revdiff",
        "revdiff-plan",
    }


def test_opencode_plugins_recover_without_replay_or_policy_drift(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    plugins = runtime / "plugins"
    plugins.mkdir(parents=True)
    fake_plugin = FIXTURES / "fake_opencode_plugin.ts"
    harness = FIXTURES / "opencode_plugin_harness.ts"
    build_env = os.environ | {"PLAN_TEST_RUNTIME": str(runtime)}
    plugin_module = runtime / "node_modules/@opencode-ai/plugin"
    plugin_module.mkdir(parents=True)
    shutil.copy2(fake_plugin, plugin_module / "index.ts")
    (plugin_module / "package.json").write_text('{"type":"module","exports":"./index.ts"}\n')
    for source, target in (
        (PROFILE / "plugins/setforge-agent-coordinator.ts", plugins / "setforge-agent-coordinator.js"),
        (PROFILE / "plugins/setforge-plan-workflow.ts", plugins / "setforge-plan-workflow.js"),
    ):
        build_source = plugins / f"{source.stem}.source.ts"
        shutil.copy2(source, build_source)
        subprocess.run(
            [
                "bun",
                "build",
                str(build_source),
                "--target=bun",
                f"--outfile={target}",
            ],
            cwd=REPO,
            env=build_env,
            text=True,
            capture_output=True,
            timeout=60,
            check=True,
        )
    source = harness.read_text().replace(
        '"../../tracked/opencode/plugins/setforge-agent-coordinator.ts"',
        '"./plugins/setforge-agent-coordinator.js"',
    ).replace(
        '"../../tracked/opencode/plugins/setforge-plan-workflow.ts"',
        '"./plugins/setforge-plan-workflow.js"',
    )
    generated_harness = runtime / "opencode_plugin_harness.ts"
    generated_harness.write_text(source)
    result = subprocess.run(
        ["bun", str(generated_harness)],
        cwd=REPO,
        env=build_env,
        text=True,
        capture_output=True,
        timeout=60,
        check=True,
    )
    assert json.loads(result.stdout) == {
        "coordinator_recovery": "passed",
        "coordinator_capacity": "passed",
        "coordinator_restart": "passed",
        "plan_failure": "passed",
    }
