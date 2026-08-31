from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

from evals.project_principles import (
    CASES,
    CANDIDATE_AGENTS,
    changed_paths,
    codex_command,
    copy_auth,
    create_runtime,
    grader_schema,
    grade_case,
    initialize_fixture,
    isolated_environment,
    observed_success_probe,
    plan_has_representative_snippets,
    remove_auth,
    setforge_install_command,
    valid_success_probe,
    validate_agent_grade,
)


def test_policy_contains_approved_principles() -> None:
    policy = " ".join(CANDIDATE_AGENTS.read_text(encoding="utf-8").split())
    for phrase in (
        "smallest cheap runnable experiment",
        "Do not spike routine work",
        "Do not add frameworks",
        "Superficial duplication or hypothetical reuse is insufficient evidence",
        "include representative snippets",
    ):
        assert phrase in policy


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
