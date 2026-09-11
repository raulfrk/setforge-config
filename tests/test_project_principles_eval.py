from __future__ import annotations

import json
import os
import stat
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

from evals import project_principles as evaluator
from evals.project_principles import (
    CASES,
    CANDIDATE_AGENTS,
    DEFAULT_MODEL,
    EvaluationError,
    REVIEW_CRITICAL_AGENT,
    REVIEW_CORRECTNESS_AGENT,
    REVIEW_GATE_SKILL,
    REVIEW_GATE_TECHNICAL_CHECKPOINTS,
    REVIEW_GATE_REVDIFF_RETURNS,
    REVIEW_GENERAL_AGENT,
    HERDR_SKILL,
    HERDR_MODE_HANDOFF,
    HERDR_PLAN_MODE_HELPER,
    HERDR_WORKSPACE_OPERATIONS,
    changed_paths,
    candidate_tracked_resources,
    codex_command,
    copy_auth,
    create_runtime,
    deploy_candidate,
    grader_schema,
    grade_case,
    initialize_fixture,
    isolated_environment,
    observed_success_probe,
    plan_has_representative_snippets,
    remove_auth,
    run_codex,
    setforge_install_command,
    valid_success_probe,
    validate_agent_grade,
)


def test_policy_contains_approved_principles() -> None:
    policy = " ".join(CANDIDATE_AGENTS.read_text(encoding="utf-8").split())
    for phrase in (
        "smallest cheap runnable experiment",
        "Do not spike routine work",
        "Establish the failure before proving a proposed solution",
        "Review requirements do not authorize extra software",
        "Superficial duplication or hypothetical reuse is insufficient evidence",
        "The primary owns design, implementation, tests, corrections, integration, and acceptance",
        "Delegate implementation only when useful independent work can run in parallel",
        "Honor configured models and explicit user selections",
        "Before coding, state a proportional intended result",
        "preserving all remaining user-requested outcomes in the existing plan",
        "Use separate worktrees when edits overlap",
        "the primary integrates the results",
        "Compare suspected regressions with the baseline",
        "Use completion notifications and native agent waits",
        "A timeout or early wakeup alone does not justify redispatch",
        "Unchanged pending status is not progress",
        "Distinguish execution time from human review, approval, and external waits",
        "Keep routine work outside Plan Mode",
        "each phase requires a fresh completion and verdict",
        "an earlier checkpoint cannot certify a later diff",
        "focused independent checkpoint before a consequential action",
        "same action, risk, and complete current evidence",
        "the primary reassesses the evidence and approach",
        "An invalid harness assertion may be removed only with evidence",
        "include representative snippets",
    ):
        assert phrase in policy


def test_review_gate_requires_complete_evidence_and_independent_validation() -> None:
    skill = " ".join(
        " ".join(path.read_text(encoding="utf-8").split())
        for path in (
            REVIEW_GATE_SKILL,
            REVIEW_GATE_TECHNICAL_CHECKPOINTS,
            REVIEW_GATE_REVDIFF_RETURNS,
        )
    )
    for phrase in (
        "complete draft—not a placeholder, outline, or summary",
        "command run only by a reviewer is not primary-agent validation",
        "reviewer suggestion is evidence to evaluate, not a new requirement",
        "Hypothetical alternate implementations",
        "dispatch output is stale lifecycle state",
        'use `fork_turns="none"`',
        "never short-circuits the batch",
        "Routine UI work and ordinary feature work",
        "Plan Mode alone does not make a phase material",
        "Judge materiality from the change and its consequences",
        "gate itself does not require new evidence bundles, manifests, recovery tooling",
        "cannot enlarge the execution contract",
        "multi-file change, and Plan Mode alone do not require independent review",
        "Review-only escalation does not require a design author",
        "The primary owns routine gate validation",
        "same independent thread may cover checkpoints and successive phases",
        "Send material revisions back to the same author",
        "checkpoint before a consequential action",
        "Actual credential exposure across logs, exceptions",
        "merely mentions credentials requires no specialist",
        "After an inconclusive material spike",
        "Remove an invalid harness assertion only when evidence",
        "it is not a mandatory extra step",
        "defer reading its contents until the initial gate is complete",
        "explicitly tell every initial reviewer",
    ):
        assert phrase in skill


def test_isolated_home_and_auth_permissions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EVAL_SENTINEL_SECRET", "must-not-leak")
    monkeypatch.setenv("PYTHONPATH", "/host/override")
    home = tmp_path / "home"
    env = isolated_environment(home)
    assert env["CODEX_HOME"] == str(home / ".codex")
    assert env["XDG_DATA_HOME"] == str(home / ".local/share")
    assert "EVAL_SENTINEL_SECRET" not in env
    assert "PYTHONPATH" not in env
    assert stat.S_IMODE(home.stat().st_mode) == 0o700
    source = tmp_path / "auth.json"
    source.write_text("{}", encoding="utf-8")
    copied = copy_auth(source, home / ".codex")
    assert stat.S_IMODE(copied.stat().st_mode) == 0o600
    remove_auth(home / ".codex")
    assert not copied.exists()


def test_runtime_uses_xdg_cache(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    runtime, parent = create_runtime()
    assert runtime.parent == parent
    assert runtime.is_relative_to(tmp_path)


def test_setforge_candidate_install_is_bounded() -> None:
    command = setforge_install_command()
    for option in ("--locked", "--no-fetch", "--no-git-check", "--yes"):
        assert option in command
    assert "--no-secrets-scan" not in command
    assert "--auto=use-tracked" not in command


def test_fixtures_start_clean_and_use_pytest(tmp_path: Path) -> None:
    for case in CASES:
        workspace = tmp_path / case.id
        assert len(initialize_fixture(case, workspace)) == 40
        assert changed_paths(workspace) == set()
        assert "unittest" not in "".join(case.files.values())
        assert any(name.startswith("test_") for name in case.files)
        python_files = [str(path) for path in workspace.glob("*.py")]
        syntax = subprocess.run(
            ["python3", "-m", "py_compile", *python_files],
            cwd=workspace,
            capture_output=True,
            text=True,
        )
        assert syntax.returncode == 0, syntax.stderr
        tests = subprocess.run(
            ["python3", "-m", "pytest", "-q"],
            cwd=workspace,
            capture_output=True,
            text=True,
        )
        oracle = (
            subprocess.run(case.oracle, cwd=workspace, capture_output=True, text=True)
            if case.oracle
            else None
        )
        if case.kind != "plan":
            assert tests.returncode != 0 or (
                oracle is not None and oracle.returncode != 0
            )
        if case.executable:
            assert os.access(workspace / case.executable, os.X_OK)


def test_review_runner_config_is_statically_observable() -> None:
    assert DEFAULT_MODEL == "gpt-5.6-luna"
    config = tomllib.loads(
        (CANDIDATE_AGENTS.parent / "config.toml").read_text(encoding="utf-8")
    )
    assert config["agents"]["max_threads"] == 12
    assert config["model"] == "gpt-5.6-sol"
    assert config["model_reasoning_effort"] == "medium"
    assert config["plan_mode_reasoning_effort"] == "medium"
    assert config["model_reasoning_summary"] == "detailed"
    assert config["hide_agent_reasoning"] is False
    assert config["show_raw_agent_reasoning"] is True
    assert config["service_tier"] == "default"
    assert config["agents"]["default_subagent_model"] == "gpt-5.6-luna"
    assert config["agents"]["default_subagent_reasoning_effort"] == "max"
    expected = {
        "review_correctness": (REVIEW_CORRECTNESS_AGENT, "gpt-6-astra"),
        "review_critical": (REVIEW_CRITICAL_AGENT, "gpt-5.6-sol"),
        "review_general": (REVIEW_GENERAL_AGENT, "gpt-5.6-terra"),
    }
    for name, (path, model) in expected.items():
        registration = config["agents"][name]
        assert (CANDIDATE_AGENTS.parent / registration["config_file"]).resolve() == path
        runner = tomllib.loads(path.read_text(encoding="utf-8"))
        assert runner["model"] == model
        assert runner["model_reasoning_effort"] == "low"
        assert runner["sandbox_mode"] == "read-only"
        if name == "review_correctness":
            assert runner["service_tier"] == "default"


def test_review_correctness_resource_is_in_codex_manifest() -> None:
    manifest = (CANDIDATE_AGENTS.parents[2] / "setforge.yaml").read_text(
        encoding="utf-8"
    )
    resource = "codex_agent_review_correctness"
    assert f"  {resource}:" in manifest
    assert "src: codex/agents/review-correctness.toml" in manifest
    assert "dst: ~/.codex/agents/review-correctness.toml" in manifest
    assert f"      - {resource}" in manifest
    tracked = candidate_tracked_resources(Path("/candidate-home"))
    assert (
        REVIEW_CORRECTNESS_AGENT,
        Path("/candidate-home/.codex/agents/review-correctness.toml"),
    ) in tracked


def test_codex_policy_profile_selects_only_policy_resources() -> None:
    manifest = yaml.safe_load(
        (CANDIDATE_AGENTS.parents[2] / "setforge.yaml").read_text(encoding="utf-8")
    )
    profile = manifest["profiles"]["codex-policy"]
    assert set(profile) == {"tracked_files"}
    assert set(profile["tracked_files"]) == {
        "codex_global_agents",
        "codex_skill_review_gate",
        "codex_skill_review_gate_reference_technical_checkpoints",
        "codex_skill_usage_check",
        "codex_skill_usage_check_helper",
    }
    assert len(profile["tracked_files"]) == 5
    assert "extends" not in profile
    assert "packages" not in profile
    assert "plugins" not in profile


def test_spike_fixture_records_order_without_git_drift(tmp_path: Path) -> None:
    case = next(case for case in CASES if case.probe_expectation == "success")
    workspace = tmp_path / case.id
    initialize_fixture(case, workspace)
    failed = subprocess.run(
        ["./mystery-normalizer"], cwd=workspace, check=False, capture_output=True
    )
    assert failed.returncode == 2
    assert not (workspace / ".eval-probe-log").exists()
    subprocess.run(
        ["./mystery-normalizer", "test"], cwd=workspace, check=True, capture_output=True
    )
    assert case.production_file
    (workspace / case.production_file).write_text("changed\n", encoding="utf-8")
    subprocess.run(["git", "add", case.production_file], cwd=workspace, check=True)
    subprocess.run(
        ["./mystery-normalizer", "test"], cwd=workspace, check=True, capture_output=True
    )
    assert (workspace / ".eval-probe-log").read_text().splitlines() == [
        "clean|test|TEST",
        "modified|test|TEST",
    ]
    assert valid_success_probe("clean|  hello  |HELLO", "clean")
    assert not valid_success_probe("clean|hello|wrong", "clean")
    assert not valid_success_probe("clean||", "clean")
    transcript = [
        {
            "command": "./mystery-normalizer '  hello  '",
            "status": "completed",
            "exit_code": 0,
            "output": "HELLO\nclean|  hello  |HELLO$\n",
        },
        {"file_changes": [{"path": "/fixture/adapter.py", "kind": "update"}]},
    ]
    assert observed_success_probe(transcript)
    assert not observed_success_probe(list(reversed(transcript)))
    inspection = [{**transcript[0], "command": "cat ./mystery-normalizer", "output": "#!/bin/sh"}]
    assert not observed_success_probe(inspection)
    assert ".eval-probe-log" not in changed_paths(workspace)


def test_codex_command_is_ephemeral_and_bounded(tmp_path: Path) -> None:
    command = codex_command(
        tmp_path, tmp_path / "final", "work", model="gpt-5.6-luna", effort="medium"
    )
    assert command[:4] == ["codex", "-a", "never", "exec"]
    for option in ("--ephemeral", "workspace-write", "hooks", "apps", "plugins"):
        assert option in command


def test_run_codex_retains_partial_output_on_timeout(tmp_path: Path) -> None:
    stdout_path = tmp_path / "events.jsonl"
    stderr_path = tmp_path / "stderr.txt"
    command = [
        "python3",
        "-c",
        "import sys, time; print('partial', flush=True); "
        "print('diagnostic', file=sys.stderr, flush=True); time.sleep(10)",
    ]
    with pytest.raises(EvaluationError, match="partial events"):
        run_codex(
            command,
            cwd=tmp_path,
            env=os.environ,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timeout=1,
        )
    assert stdout_path.read_text(encoding="utf-8") == "partial\n"
    assert stderr_path.read_text(encoding="utf-8") == "diagnostic\n"


def test_main_retains_runtime_artifacts_after_evaluation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setattr(evaluator, "create_runtime", lambda: (runtime, tmp_path))

    def fail_auth(*_args: object, **_kwargs: object) -> Path:
        raise EvaluationError("auth unavailable")

    monkeypatch.setattr(evaluator, "copy_auth", fail_auth)
    assert evaluator.main(["--case", CASES[0].id]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["runtime"] == str(runtime)
    assert runtime.exists()


def test_plan_snippet_check_accepts_typed_multiline_signature() -> None:
    response = (
        "widget.py and test_widget.py\n```python\n"
        "def format_name(\n    value: str,\n    uppercase: bool = False,\n): ...\n"
        "assert format_name('Ada', uppercase=True) == 'ADA'\n```"
    )
    assert plan_has_representative_snippets(response)


def completed_subject() -> subprocess.CompletedProcess[str]:
    event = json.dumps(
        {
            "command": "python3 -m pytest -q",
            "status": "completed",
            "exit_code": 0,
            "output": "2 passed in 0.10s",
        }
    )
    return subprocess.CompletedProcess([], 0, event, "")


def test_static_grader_enforces_behavior_and_complexity_budgets(tmp_path: Path) -> None:
    case = CASES[0]
    workspace = tmp_path / case.id
    initial = initialize_fixture(case, workspace)
    production = workspace / case.production_file
    production.write_text(
        "def clamp(value, lower, upper):\n    return max(lower, min(upper, value))\n",
        encoding="utf-8",
    )
    subject = completed_subject()
    assert grade_case(case, workspace, initial, subject, "done")["passed"]
    with production.open("a", encoding="utf-8") as handle:
        handle.write("\nclass UnneededLayer:\n    pass\n" + "# padding\n" * 12)
    failed = grade_case(case, workspace, initial, subject, "done")
    assert not failed["checks"]["line_budget"]


def test_failed_subject_pytest_is_not_verification(tmp_path: Path) -> None:
    case = CASES[0]
    workspace = tmp_path / case.id
    initial = initialize_fixture(case, workspace)
    assert case.production_file
    (workspace / case.production_file).write_text(
        "def clamp(value, lower, upper):\n    return max(lower, min(upper, value))\n",
        encoding="utf-8",
    )
    failed_event = json.dumps(
        {
            "command": "python3 -m pytest -q",
            "status": "failed",
            "exit_code": 1,
            "output": "1 failed",
        }
    )
    subject = subprocess.CompletedProcess([], 0, failed_event, "")
    assert not grade_case(case, workspace, initial, subject, "done")["checks"][
        "subject_ran_pytest"
    ]


def test_pytest_evidence_is_checked_before_timeline_display_truncation(
    tmp_path: Path,
) -> None:
    case = CASES[0]
    workspace = tmp_path / case.id
    initial = initialize_fixture(case, workspace)
    assert case.production_file
    (workspace / case.production_file).write_text(
        "def clamp(value, lower, upper):\n    return max(lower, min(upper, value))\n",
        encoding="utf-8",
    )
    event = json.dumps(
        {
            "command": "python3 -m pytest -q; git diff",
            "status": "completed",
            "exit_code": 0,
            "output": "2 passed in 0.10s\n" + "diff output\n" * 150,
        }
    )
    subject = subprocess.CompletedProcess([], 0, event, "")
    result = grade_case(case, workspace, initial, subject, "done")
    assert result["checks"]["subject_ran_pytest"]
    assert len(result["activity_timeline"][0]["output"]) == 1200


def test_static_grader_rejects_missing_test_and_disallowed_dependency(tmp_path: Path) -> None:
    case = next(case for case in CASES if case.id == "small_feature")
    workspace = tmp_path / case.id
    initial = initialize_fixture(case, workspace)
    (workspace / "report.py").write_text(
        "import json\n\ndef render(rows, output_format='text'):\n"
        "    if output_format == 'json':\n        return json.dumps(rows)\n"
        "    return '\\n'.join(f\"{r['name']}: {r['total']}\" for r in rows)\n",
        encoding="utf-8",
    )
    (workspace / "requirements.txt").write_text("framework\n", encoding="utf-8")
    result = grade_case(case, workspace, initial, completed_subject(), "done")
    assert not result["checks"]["required_changes"]
    assert not result["checks"]["allowed_paths"]


def test_static_grader_requires_early_probe_and_final_delegation(tmp_path: Path) -> None:
    case = next(case for case in CASES if case.probe_expectation == "success")
    workspace = tmp_path / case.id
    initial = initialize_fixture(case, workspace)
    subprocess.run(
        ["./mystery-normalizer", "hello"], cwd=workspace, check=True, capture_output=True
    )
    assert case.production_file
    (workspace / case.production_file).write_text(
        "def normalize(value):\n    return value.strip().upper()\n", encoding="utf-8"
    )
    result = grade_case(case, workspace, initial, completed_subject(), "done")
    assert result["checks"]["preimplementation_proof"]
    assert not result["checks"]["final_delegation_proved"]


def test_stop_and_plan_cases_grade_their_observable_outcomes(tmp_path: Path) -> None:
    stop = next(case for case in CASES if case.kind == "stop")
    stop_workspace = tmp_path / stop.id
    stop_initial = initialize_fixture(stop, stop_workspace)
    subprocess.run(
        ["./flaky-normalizer", "hello"],
        cwd=stop_workspace,
        check=False,
        capture_output=True,
    )
    failed_probe_event = json.dumps(
        {
            "command": "./flaky-normalizer hello; echo exit=$rc",
            "status": "completed",
            "exit_code": 0,
            "output": "exit=69\nnormalizer unavailable",
        }
    )
    stopped_subject = subprocess.CompletedProcess([], 0, failed_probe_event, "")
    assert grade_case(stop, stop_workspace, stop_initial, stopped_subject, "stopped")["passed"]

    plan = next(case for case in CASES if case.kind == "plan")
    plan_workspace = tmp_path / plan.id
    plan_initial = initialize_fixture(plan, plan_workspace)
    response = (
        "widget.py\n```python\ndef format_name(value, uppercase=False): ...\n```\n"
        "test_widget.py\n```python\n"
        "assert format_name('Ada') == 'Ada'\n"
        "assert format_name('Ada', uppercase=True) == 'ADA'\n```"
    )
    assert grade_case(plan, plan_workspace, plan_initial, completed_subject(), response)[
        "passed"
    ]


def valid_grade() -> dict:
    return {
        "cases": [
            {"id": case.id, "passed": True, "evidence": "verified", "findings": []}
            for case in CASES
        ],
        "overall_pass": True,
    }


def test_grader_schema_is_strict_and_bounded() -> None:
    schema = grader_schema(len(CASES))
    cases = schema["properties"]["cases"]
    assert schema["additionalProperties"] is False
    assert cases["minItems"] == cases["maxItems"] == len(CASES)


def test_agent_grade_requires_exact_ids_and_consistent_verdict() -> None:
    expected = {case.id for case in CASES}
    grade = valid_grade()
    assert validate_agent_grade(grade, expected)
    grade["cases"][0]["passed"] = False
    assert not validate_agent_grade(grade, expected)
    grade = valid_grade()
    grade["cases"][1]["id"] = grade["cases"][0]["id"]
    assert not validate_agent_grade(grade, expected)


def test_wait_defaults_and_progressive_disclosure_resources(tmp_path: Path) -> None:
    config = tomllib.loads((CANDIDATE_AGENTS.parent / "config.toml").read_text(encoding="utf-8"))
    assert config["agents"]["max_threads"] == 12
    assert config["features"]["multi_agent_v2"] == {
        "default_wait_timeout_ms": 600000,
        "max_wait_timeout_ms": 3600000,
    }

    review_router = REVIEW_GATE_SKILL.read_text(encoding="utf-8")
    assert "references/technical-checkpoints.md" in review_router
    assert "references/revdiff-returns.md" in review_router
    assert "Send material revisions back to the same author" in REVIEW_GATE_TECHNICAL_CHECKPOINTS.read_text(encoding="utf-8")
    revdiff = " ".join(REVIEW_GATE_REVDIFF_RETURNS.read_text(encoding="utf-8").split())
    assert "Do not discard or defer later actionable feedback" in revdiff

    herdr_router = HERDR_SKILL.read_text(encoding="utf-8")
    assert "references/mode-handoff.md" in herdr_router
    assert "references/workspace-operations.md" in herdr_router
    mode = HERDR_MODE_HANDOFF.read_text(encoding="utf-8")
    assert "../scripts/plan_mode_handoff.py" in mode
    assert (HERDR_MODE_HANDOFF.parent / "../scripts/plan_mode_handoff.py").resolve().is_file()
    assert "Resolve the calling pane" in HERDR_WORKSPACE_OPERATIONS.read_text(encoding="utf-8")

    manifest = (CANDIDATE_AGENTS.parents[2] / "setforge.yaml").read_text(encoding="utf-8")
    for resource, relative in (
        ("codex_skill_review_gate_reference_technical_checkpoints", "review-gate/references/technical-checkpoints.md"),
        ("codex_skill_review_gate_reference_revdiff_returns", "review-gate/references/revdiff-returns.md"),
        ("codex_skill_herdr_reference_mode_handoff", "herdr/references/mode-handoff.md"),
        ("codex_skill_herdr_reference_workspace_operations", "herdr/references/workspace-operations.md"),
    ):
        assert f"  {resource}:" in manifest
        assert f"src: codex/skills/{relative}" in manifest
        assert f"dst: ~/.codex/skills/{relative}" in manifest
        assert f"      - {resource}" in manifest

    home = tmp_path / "candidate-home"
    env = isolated_environment(home)
    deploy_candidate(env)

    deployed_review = home / ".codex/skills/review-gate/SKILL.md"
    deployed_herdr = home / ".codex/skills/herdr/SKILL.md"
    for source, destination in (
        (REVIEW_GATE_TECHNICAL_CHECKPOINTS, deployed_review.parent / "references/technical-checkpoints.md"),
        (REVIEW_GATE_REVDIFF_RETURNS, deployed_review.parent / "references/revdiff-returns.md"),
        (HERDR_MODE_HANDOFF, deployed_herdr.parent / "references/mode-handoff.md"),
        (HERDR_WORKSPACE_OPERATIONS, deployed_herdr.parent / "references/workspace-operations.md"),
    ):
        assert destination.is_file()
        assert destination.read_bytes() == source.read_bytes()

    for entrypoint, relative_links in (
        (deployed_review, ("references/technical-checkpoints.md", "references/revdiff-returns.md")),
        (deployed_herdr, ("references/mode-handoff.md", "references/workspace-operations.md")),
    ):
        text = entrypoint.read_text(encoding="utf-8")
        for relative in relative_links:
            assert f"]({relative})" in text
            assert (entrypoint.parent / relative).resolve().is_file()

    deployed_mode = deployed_herdr.parent / "references/mode-handoff.md"
    helper_relative = "../scripts/plan_mode_handoff.py"
    assert helper_relative in deployed_mode.read_text(encoding="utf-8")
    deployed_helper = (deployed_mode.parent / helper_relative).resolve()
    assert deployed_helper.is_file()
    assert deployed_helper.read_bytes() == HERDR_PLAN_MODE_HELPER.read_bytes()
