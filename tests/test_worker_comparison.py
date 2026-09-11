from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from evals import worker_comparison as comparison


def fixture_sources(tmp_path: Path) -> tuple[Path, Path, Path]:
    runner = tmp_path / "project_principles.py"
    runner.write_text("value = 1\n", encoding="utf-8")
    baseline = tmp_path / "baseline"
    oracle = tmp_path / "oracle"
    baseline.mkdir(); oracle.mkdir()
    for directory, suffix in ((baseline, "old"), (oracle, "new")):
        (directory / "plan_mode_handoff.py").write_text(f"VALUE = '{suffix}'\n")
        (directory / "test_herdr_plan_mode_handoff.py").write_text("def test_public(): assert True\n")
    (oracle / "SKILL.md").write_text("accepted design\n")
    return runner, baseline, oracle


def test_prepare_freezes_models_inputs_oracle_and_readiness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner, baseline, oracle = fixture_sources(tmp_path)
    tests = tmp_path / "tests"
    tests.mkdir(); (tests / "test_project_principles_eval.py").write_text("def test_public(): assert True\n")
    for relative in (
        "tracked/codex/AGENTS.md",
        "tracked/codex/skills/review-gate/references/technical-checkpoints.md",
    ):
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(relative + "\n")
    (tmp_path / "setforge.yaml").write_text("version: 1\n")
    monkeypatch.setattr(comparison, "ROOT", tmp_path)
    prepared = tmp_path / "prepared"
    manifest = comparison.prepare(prepared, runner=runner, herdr_baseline=baseline, herdr_oracle=oracle)
    assert [arm["id"] for arm in manifest["models"]] == ["sol-low", "terra-high", "luna-high", "luna-max"]
    assert manifest["reviewers"]["brief"] == {"model": "gpt-6-astra", "effort": "low"}
    assert (prepared / "cases/runner/evals/project_principles.py").read_text() == "value = 1\n"
    assert (
        prepared
        / "cases/runner/tracked/codex/skills/review-gate/references/technical-checkpoints.md"
    ).is_file()
    assert "plan_mode_handoff.py" in manifest["oracle"]["herdr"]
    assert manifest["limits"]["attempt_seconds"] == 300


def test_prepare_refuses_existing_destination(tmp_path: Path) -> None:
    runner, baseline, oracle = fixture_sources(tmp_path)
    with pytest.raises(comparison.ComparisonError, match="already exists"):
        comparison.prepare(tmp_path, runner=runner, herdr_baseline=baseline, herdr_oracle=oracle)


def minimal_prepared(tmp_path: Path) -> Path:
    prepared = tmp_path / "prepared"; (prepared / "cases/runner").mkdir(parents=True); (prepared / "oracle/herdr").mkdir(parents=True)
    source = prepared / "cases/runner/a"; source.write_text("a")
    oracle = prepared / "oracle/herdr/o"; oracle.write_text("o")
    readiness = prepared / "readiness"; readiness.mkdir()
    ready = readiness / "timeout.json"; ready.write_text('{"status":"PASS"}')
    model_ready = readiness / "model-usage.json"
    binary = Path(comparison.shutil.which("codex") or "").resolve()
    tool_ready = readiness / "model-tool.json"
    checks = {name: True for name in ("tool_exit_zero", "fixture_read", "fixture_write", "protected_originals_unreadable", "protected_host_bytes_unchanged", "identity_match", "usage_complete", "home_removed")}
    tool_ready.write_text(json.dumps({"status": "PASS", "checks": checks, "binary": str(binary), "binary_sha256": comparison.sha256(binary), "model": "gpt-5.6-luna", "effort": "high", "usage_records": 2}))
    success = lambda model, effort: {"returncode": 0, "request": {"model": model, "reasoning": {"effort": effort}, "service_tier": None}, "token_records": [{"response_id": "x"}]}
    model_ready.write_text(json.dumps({"cases": {"candidate": success("gpt-5.6-luna", "max"), "review-sol": success("gpt-5.6-sol", "low"), "review-astra": success("gpt-6-astra", "low"), "failure": {"returncode": 1, "token_records": [{"response_id": "x"}]}}}))
    policy = prepared / "policy/AGENTS.md"; policy.parent.mkdir(); policy.write_text("policy")
    version = comparison.subprocess.run(["codex", "--version"], text=True, capture_output=True, check=True).stdout.strip()
    manifest = {"version": 1, "orchestrator_sha256": comparison.sha256(Path(comparison.__file__)), "codex_runtime": {"version": version, "binary": str(binary), "binary_sha256": comparison.sha256(binary)}, "cases": {"runner": {"hashes": {"a": comparison.sha256(source)}, "allowed": []}}, "oracle": {"herdr": {"o": comparison.sha256(oracle)}}, "policy_sha256": comparison.sha256(policy), "readiness": {"model_usage_report": "readiness/model-usage.json", "model_usage_report_sha256": comparison.sha256(model_ready), "timeout_report": "readiness/timeout.json", "timeout_report_sha256": comparison.sha256(ready), "model_tool_report": "readiness/model-tool.json", "model_tool_report_sha256": comparison.sha256(tool_ready)}}
    comparison.write_json(prepared / "manifest.json", manifest)
    return prepared


def test_validate_prepared_accepts_exact_bytes_and_rejects_drift(tmp_path: Path) -> None:
    prepared = minimal_prepared(tmp_path)
    comparison.validate_prepared(prepared)
    (prepared / "cases/runner/a").write_text("changed")
    with pytest.raises(comparison.ComparisonError, match="input file set drift"):
        comparison.validate_prepared(prepared)


def test_validate_prepared_requires_passing_readiness(tmp_path: Path) -> None:
    prepared = minimal_prepared(tmp_path)
    manifest = json.loads((prepared / "manifest.json").read_text())
    ready = prepared / manifest["readiness"]["timeout_report"]; ready.write_text('{"status":"FAIL"}')
    manifest["readiness"]["timeout_report_sha256"] = comparison.sha256(ready)
    comparison.write_json(prepared / "manifest.json", manifest)
    with pytest.raises(comparison.ComparisonError, match="did not pass"):
        comparison.validate_prepared(prepared)


def test_validate_prepared_rejects_failed_model_tool_readiness(tmp_path: Path) -> None:
    prepared = minimal_prepared(tmp_path)
    manifest = json.loads((prepared / "manifest.json").read_text())
    report = prepared / manifest["readiness"]["model_tool_report"]
    evidence = json.loads(report.read_text()); evidence["checks"]["tool_exit_zero"] = False
    comparison.write_json(report, evidence)
    manifest["readiness"]["model_tool_report_sha256"] = comparison.sha256(report)
    comparison.write_json(prepared / "manifest.json", manifest)
    with pytest.raises(comparison.ComparisonError, match="model tool readiness did not pass"):
        comparison.validate_prepared(prepared)


def test_validate_prepared_rejects_model_tool_readiness_drift(tmp_path: Path) -> None:
    prepared = minimal_prepared(tmp_path)
    report = prepared / "readiness/model-tool.json"
    report.write_text(report.read_text() + "\n")
    with pytest.raises(comparison.ComparisonError, match="model tool readiness evidence missing or drifted"):
        comparison.validate_prepared(prepared)


def test_initialize_workspace_is_clean_git_fixture(tmp_path: Path) -> None:
    source = tmp_path / "source"; source.mkdir(); (source / "x.py").write_text("x=1\n")
    workspace = tmp_path / "workspace"
    assert len(comparison.initialize_workspace(source, workspace)) == 40
    assert comparison.run(["git", "status", "--porcelain"], cwd=workspace).stdout == ""


@pytest.mark.parametrize("unsafe_name", ["selected-oracle.py", ".comparison-evidence.json"])
def test_safe_copy_tree_rejects_reserved_files(tmp_path: Path, unsafe_name: str) -> None:
    source = tmp_path / "source"; source.mkdir(); (source / unsafe_name).write_text("untrusted")
    with pytest.raises(comparison.ComparisonError, match="unsafe fixture entry"):
        comparison.safe_copy_tree(source, tmp_path / "copy")


def test_safe_copy_tree_rejects_symlinks(tmp_path: Path) -> None:
    source = tmp_path / "source"; source.mkdir(); (source / "link").symlink_to(tmp_path / "outside")
    with pytest.raises(comparison.ComparisonError, match="unsafe fixture entry"):
        comparison.safe_copy_tree(source, tmp_path / "copy")


def test_sandbox_environment_grants_exact_resolved_codex_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    codex = tmp_path / "runtime/codex"; codex.parent.mkdir(); codex.write_text("binary")
    helper = tmp_path / "host-helper"; helper.write_text("helper")
    monkeypatch.setattr(comparison.shutil, "which", lambda name: str(codex) if name == "codex" else None)
    monkeypatch.setattr(comparison, "sandbox_binary", lambda: helper)
    home = tmp_path / "home"; workspace = tmp_path / "workspace"; workspace.mkdir()
    env = comparison.sandbox_environment(home, workspace, write=False)
    config = (Path(env["CODEX_HOME"]) / "config.toml").read_text()
    assert f'"{codex.resolve()}" = "read"' in config
    assert f'"{workspace}" = "read"' in config
    assert f'"{codex.parent}" = "read"' not in config


def test_sandbox_timeout_fails_when_terminated_command_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workspace"; workspace.mkdir()
    observed = {"cleanup": 0, "waits": 0}

    class TimeoutThenZero:
        pid = os.getpid()
        returncode: int | None = None
        ready = True

        def wait(self, timeout: float) -> int:
            observed["waits"] += 1
            raise subprocess.TimeoutExpired("mock", timeout)

    process = TimeoutThenZero()

    def cleanup_after_timeout(candidate: TimeoutThenZero, codex_home: Path, process_group: int) -> None:
        observed["cleanup"] += 1
        candidate.returncode = 0

    monkeypatch.setattr(comparison.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(comparison.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(comparison, "cleanup_owned", cleanup_after_timeout)
    passed, _ = comparison.sandbox_check(workspace, tmp_path / "runs", "timeout-zero", ["true"], timeout=0.1)
    assert process.ready and observed["waits"] == 1
    assert process.returncode == 0 and observed["cleanup"] == 2
    assert not passed
    assert not (tmp_path / "runs/timeout-zero-home").exists()


def test_token_records_deduplicate_response_ids(tmp_path: Path) -> None:
    rollout = tmp_path / "sessions/a.jsonl"; rollout.parent.mkdir()
    event = {"type": "token_usage_record", "payload": {"response_id": "r1", "usage": {"input_tokens": 4}}}
    rollout.write_text(json.dumps(event) + "\n" + json.dumps(event) + "\n")
    assert comparison.token_records(tmp_path) == [{"response_id": "r1", "usage": {"input_tokens": 4}}]


def test_static_runner_grade_requires_independent_grader_effort(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prepared = tmp_path / "prepared"; prepared.mkdir()
    comparison.write_json(prepared / "manifest.json", {"cases": {"runner": {"allowed": ["evals/project_principles.py"]}}})
    oracle = prepared / "oracle/runner"; oracle.mkdir(parents=True)
    (oracle / "test_grader_effort_behavior.py").write_text("def test_hidden(): assert True\n")
    workspace = tmp_path / "workspace"; workspace.mkdir()
    (workspace / "evals").mkdir(); (workspace / "evals/project_principles.py").write_text('import argparse\ndef main():\n p=argparse.ArgumentParser(); p.add_argument("--grader-effort"); p.parse_args()\nif __name__=="__main__": main()\n')
    (workspace / "tests").mkdir()
    (workspace / "test_ok.py").write_text("def test_ok(): assert True\n")
    (workspace / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    for command in (["git", "init", "-q"], ["git", "config", "user.email", "x@y"], ["git", "config", "user.name", "x"], ["git", "add", "."], ["git", "commit", "-qm", "base"]): comparison.run(command, cwd=workspace)
    comparison.safe_copy_tree(workspace, prepared / "cases/runner")
    with (workspace / "evals/project_principles.py").open("a") as handle: handle.write("# changed\n")
    commands: dict[str, list[str]] = {}
    def passing_check(workspace: Path, run_dir: Path, check_id: str, command: list[str]) -> tuple[bool, Path]:
        commands[check_id] = command
        return True, run_dir / f"{check_id}.stdout"
    monkeypatch.setattr(comparison, "sandbox_check", passing_check)
    result = comparison.static_grade("runner", workspace, prepared, tmp_path / "evidence")
    assert result["passed"]
    assert commands["public-tests"][-2:] == [
        "--deselect",
        "tests/test_project_principles_eval.py::test_wait_defaults_and_progressive_disclosure_resources",
    ]


def test_static_grade_isolates_public_mutation_from_evidence_and_hidden_test(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prepared = tmp_path / "prepared"
    baseline = prepared / "cases/runner"; (baseline / "evals").mkdir(parents=True); (baseline / "tests").mkdir()
    (baseline / "evals/project_principles.py").write_text("value = 1\n")
    (baseline / "tests/test_project_principles_eval.py").write_text("def test_public(): assert True\n")
    oracle = prepared / "oracle/runner"; oracle.mkdir(parents=True)
    (oracle / "test_grader_effort_behavior.py").write_text("def test_hidden(): assert True\n")
    comparison.write_json(prepared / "manifest.json", {"cases": {"runner": {"allowed": ["evals/project_principles.py"]}}})
    workspace = tmp_path / "workspace"; comparison.safe_copy_tree(baseline, workspace)
    (workspace / "evals/project_principles.py").write_text("value = 2\n")
    outside = tmp_path / "outside"; outside.mkdir(); secret = outside / "secret"; secret.write_text("SECRET")
    observed: dict[str, str | bool] = {}

    def hostile_check(candidate: Path, run_dir: Path, check_id: str, command: list[str]) -> tuple[bool, Path]:
        if check_id == "public-tests":
            target = candidate / "evals/project_principles.py"; target.unlink(); target.symlink_to(secret)
            comparison.shutil.rmtree(candidate / "tests"); (candidate / "tests").symlink_to(outside, target_is_directory=True)
        else:
            observed["hidden_value"] = (candidate / "evals/project_principles.py").read_text()
            observed["hidden_tests_real"] = not (candidate / "tests").is_symlink()
        return True, run_dir / f"{check_id}.stdout"

    monkeypatch.setattr(comparison, "sandbox_check", hostile_check)
    result = comparison.static_grade("runner", workspace, prepared, tmp_path / "evidence")
    assert result["passed"]
    assert observed == {"hidden_value": "value = 2\n", "hidden_tests_real": True}
    assert secret.read_text() == "SECRET"
    assert "SECRET" not in (tmp_path / "evidence/full.diff").read_text()


def test_public_contracts_do_not_disclose_oracle_paths() -> None:
    assert "grader-effort" in comparison.public_contract("runner")
    assert "exactly one plan setter" in comparison.public_contract("herdr")
    assert "/tmp/" not in comparison.public_contract("herdr")


def test_candidate_contract_includes_scope_brief_and_correction() -> None:
    manifest = {"cases": {"runner": {"contract": "public", "allowed": ["one.py"]}}}
    contract = comparison.candidate_contract(manifest, "runner", "frozen brief", correction="fix this")
    assert all(text in contract for text in ("public", "one.py", "frozen brief", "fix this", "300-second"))
    assert " ".join(comparison.public_test_command("runner")) in contract
    assert "frozen network-disabled sandbox intentionally excludes" in contract


def test_repeat_selection_requires_final_passes_then_ranks_first_pass_and_cost() -> None:
    models = [{"id": name} for name in ("sol-low", "cheap", "reliable", "incomplete")]
    stats = {
        "sol-low": {"first_passes": 2, "final_passes": 2, "cost": 10},
        "cheap": {"first_passes": 1, "final_passes": 2, "cost": 2},
        "reliable": {"first_passes": 2, "final_passes": 2, "cost": 8},
        "incomplete": {"first_passes": 2, "final_passes": 1, "cost": 1},
    }
    assert comparison.select_repeat_candidate(models, stats, 2) == {"id": "reliable"}
    stats["sol-low"]["cost_lower_bound"] = True
    assert comparison.select_repeat_candidate(models, stats, 2) is None
    stats["sol-low"]["cost_lower_bound"] = False
    stats["reliable"]["cost_lower_bound"] = True
    assert comparison.select_repeat_candidate(models, stats, 2) == {"id": "cheap"}


def test_paired_repeat_order_is_balanced() -> None:
    sol, best = {"id": "sol-low"}, {"id": "best"}
    assert [(arm["id"], case) for arm, case in comparison.paired_repeat_order(sol, best, ["runner", "herdr"])] == [
        ("sol-low", "runner"), ("best", "runner"), ("best", "herdr"), ("sol-low", "herdr")
    ]


def test_cli_requires_output_for_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert comparison.main(["--run", str(tmp_path)]) == 2
    assert "--output is required" in capsys.readouterr().out


def test_default_arms_and_reviewers_are_fixed() -> None:
    assert comparison.DEFAULT_ARMS == (("sol-low", "gpt-5.6-sol", "low"), ("terra-high", "gpt-5.6-terra", "high"), ("luna-high", "gpt-5.6-luna", "high"), ("luna-max", "gpt-5.6-luna", "max"))
    assert comparison.REVIEWERS == (("sol", "gpt-5.6-sol"), ("astra", "gpt-6-astra"))


@pytest.mark.parametrize("model,expected", [("gpt-5.6-luna", 0.0001675), ("gpt-5.6-terra", 0.001675), ("gpt-5.6-sol", 0.00305), ("gpt-6-astra", 0.007625)])
def test_usage_credits_use_model_rates_without_reasoning_double_count(model: str, expected: float) -> None:
    records = [{"usage": {"input_tokens": 20, "cached_input_tokens": 5, "output_tokens": 3, "reasoning_output_tokens": 2}}]
    assert comparison.usage_credits(records, model) == pytest.approx(expected)


def test_accounting_distinguishes_complete_success_from_partial_failure() -> None:
    records = [{"response_id": "known", "usage": {}}]
    assert comparison.accounting_complete(0, False, ["turn.completed"], records)
    assert not comparison.accounting_complete(1, False, ["turn.failed"], records)
    assert not comparison.accounting_complete(-15, True, ["turn.started"], records)
    assert not comparison.accounting_complete(0, False, ["turn.completed"], [])


def test_mechanical_acceptance_rejects_worker_failure_and_dangerous_scope() -> None:
    worker = {"returncode": 0, "timed_out": False}
    grade = {"passed": True}
    assert comparison.mechanically_acceptable(worker, grade, False)
    assert not comparison.mechanically_acceptable({**worker, "returncode": 1}, grade, False)
    assert not comparison.mechanically_acceptable(worker, grade, True)


def decision_payload(request: dict, action: str = "accept") -> dict:
    return {"trial_id": request["trial_id"], "phase": request["phase"], "evidence_hash": request["evidence_hash"], "action": action, "confirmed_dangerous_scope": False, "validated_findings": [], "rejected_findings": [], "rationale": "checked", "reconciled_prep_credits": 12.5}


def test_primary_decision_checkpoint_consumes_matching_decision(tmp_path: Path) -> None:
    def writer() -> None:
        request_path = tmp_path / "trials/t1/review-request.json"
        while not request_path.exists(): time.sleep(0.01)
        comparison.write_json(request_path.parent / "primary-decision.json", decision_payload(json.loads(request_path.read_text())))
    thread = threading.Thread(target=writer); thread.start()
    decision = comparison.await_primary_decision(tmp_path, "t1", "initial", {"check": True}, timeout=1)
    thread.join()
    assert decision["action"] == "accept"
    assert (tmp_path / "trials/t1/initial-primary-decision.consumed.json").is_file()


def test_primary_decision_rejects_stale_hash_and_second_correction(tmp_path: Path) -> None:
    directory = tmp_path / "trials/t1"; directory.mkdir(parents=True)
    stale = {"trial_id": "t1", "phase": "initial", "evidence_hash": "stale", "action": "accept", "confirmed_dangerous_scope": False, "validated_findings": [], "rejected_findings": [], "rationale": "x", "reconciled_prep_credits": 1}
    comparison.write_json(directory / "primary-decision.json", stale)
    with pytest.raises(comparison.ComparisonError, match="stale"):
        comparison.await_primary_decision(tmp_path, "t1", "initial", {"x": 1}, timeout=.05)
    request = json.loads((directory / "review-request.json").read_text())
    stale.update(phase="corrected", evidence_hash=request["evidence_hash"], action="correct")
    comparison.write_json(directory / "primary-decision.json", stale)
    with pytest.raises(comparison.ComparisonError, match="action"):
        comparison.await_primary_decision(tmp_path, "t1", "corrected", {"x": 1}, timeout=.05)


def test_primary_decision_timeout_has_no_side_effect_dispatch(tmp_path: Path) -> None:
    with pytest.raises(comparison.ComparisonError, match="timed out"):
        comparison.await_primary_decision(tmp_path, "t1", "initial", {"x": 1}, timeout=.02)
    assert {path.name for path in (tmp_path / "trials/t1").iterdir()} == {"review-request.json", "decision-stop.json"}


def fake_attempt(*, timed_out: bool, identity_match: bool = True, usage: bool = True) -> dict:
    return {
        "model": "gpt-5.6-luna",
        "effort": "max",
        "identity_match": identity_match,
        "returncode": -15 if timed_out else 1,
        "timed_out": timed_out,
        "final": "",
        "usage": [{"response_id": "known", "usage": {}}] if usage else [],
        "usage_complete": False,
        "usage_credits": 0.3,
    }


def test_dispatch_retains_candidate_timeout_as_cost_lower_bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prepared = tmp_path / "prepared"; (prepared / "oracle").mkdir(parents=True)
    output = tmp_path / "output"; (output / "workspaces/current").mkdir(parents=True)
    report = {"prep_credits": 10.0, "experiment_credits": 0.0, "dispatches": []}
    persisted = []
    monkeypatch.setattr(comparison, "invoke", lambda **_kwargs: fake_attempt(timed_out=True))
    result = comparison.dispatch_attempt(
        prepared, output, tmp_path / "auth", tmp_path / "policy", {"limits": {"stop_new_dispatch_credits": 100}},
        report, lambda: persisted.append(True), candidate=True, workspace=output / "workspaces/current",
        run_dir=output / "runs/t/worker", prompt="x", model="gpt-5.6-luna", effort="max", read_only=False,
    )
    assert result["cost_lower_bound"] is True
    assert report["experiment_credits"] == pytest.approx(0.3)
    assert report["experiment_cost_lower_bound"] is True
    assert len(report["dispatches"]) == 1 and persisted == [True]


@pytest.mark.parametrize(
    "result,match",
    [
        (fake_attempt(timed_out=True, identity_match=False), "identity mismatch"),
        (fake_attempt(timed_out=True, usage=False), "no response-linked usage"),
        (fake_attempt(timed_out=False), "no response-linked usage"),
    ],
)
def test_dispatch_still_stops_for_nonqualifying_incomplete_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, result: dict, match: str
) -> None:
    prepared = tmp_path / "prepared"; (prepared / "oracle").mkdir(parents=True)
    output = tmp_path / "output"; (output / "workspaces/current").mkdir(parents=True)
    report = {"prep_credits": 10.0, "experiment_credits": 0.0, "dispatches": []}
    monkeypatch.setattr(comparison, "invoke", lambda **_kwargs: result)
    with pytest.raises(comparison.ComparisonError, match=match):
        comparison.dispatch_attempt(
            prepared, output, tmp_path / "auth", tmp_path / "policy", {"limits": {"stop_new_dispatch_credits": 100}},
            report, lambda: None, candidate=True, workspace=output / "workspaces/current",
            run_dir=output / "runs/t/worker", prompt="x", model="gpt-5.6-luna", effort="max", read_only=False,
        )


def test_postbrief_continuation_runs_exact_remaining_jobs_without_regenerating_briefs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "output"; output.mkdir()
    prepared = tmp_path / "prepared"; (prepared / "cases/runner").mkdir(parents=True); (prepared / "cases/herdr").mkdir(parents=True)
    models = [
        {"id": "sol-low", "model": "gpt-5.6-sol", "effort": "low"},
        {"id": "terra-high", "model": "gpt-5.6-terra", "effort": "high"},
        {"id": "luna-high", "model": "gpt-5.6-luna", "effort": "high"},
        {"id": "luna-max", "model": "gpt-5.6-luna", "effort": "max"},
    ]
    manifest = {"models": models, "cases": {"runner": {"allowed": [], "contract": "runner"}, "herdr": {"allowed": [], "contract": "herdr"}}, "limits": {"stop_new_dispatch_credits": 1000}}
    old_sol = {"id": "sol-low-runner", "arm": models[0], "case": "runner", "first_pass": True, "correction": None}
    old_luna = {"id": "luna-max-herdr", "arm": models[3], "case": "herdr", "first_pass": False, "correction": {"passed": False}}
    report = {
        "prep_credits": 0.0, "experiment_credits": 0.0, "experiment_cost_lower_bound": False,
        "dispatches": [], "trials": [old_sol, old_luna],
        "shared_briefs": {"runner": {"usage_credits": 1.0}, "herdr": {"usage_credits": 1.0}}, "repeats": [],
    }
    candidate_jobs: list[str] = []

    def persist() -> None:
        report["total_credits"] = report["prep_credits"] + report["experiment_credits"]

    def initialize(_source: Path, workspace: Path) -> str:
        workspace.mkdir(parents=True)
        (workspace / "candidate.py").write_text("value=1\n")
        return "head"

    def dispatch(**kwargs: object) -> dict:
        run_dir = Path(kwargs["run_dir"])
        if kwargs.get("candidate"):
            candidate_jobs.append(run_dir.parent.name)
        result = {
            "returncode": 0, "timed_out": False, "identity_match": True, "usage": [{}],
            "usage_complete": True, "usage_credits": 1.0,
            "final": json.dumps({"passed": True, "dangerous_scope": False, "findings": []}) if kwargs.get("schema") else "done",
        }
        report["dispatches"].append({"run_dir": str(run_dir), **result})
        report["experiment_credits"] += 1.0; persist()
        return result

    def grade(_case: str, _workspace: Path, _prepared: Path, evidence: Path) -> dict:
        evidence.mkdir(parents=True); diff = evidence / "full.diff"; diff.write_text("patch\n")
        return {"passed": True, "checks": {"allowed_paths": True}, "changed_paths": ["candidate.py"], "workspace_digest": "digest", "full_diff_sha256": comparison.sha256(diff), "private_evidence": {"full_diff": str(diff)}}

    monkeypatch.setattr(comparison, "initialize_workspace", initialize)
    monkeypatch.setattr(comparison, "static_grade", grade)
    monkeypatch.setattr(comparison, "revalidated_workspace_digest", lambda *_args: "digest")
    monkeypatch.setattr(comparison, "await_primary_decision", lambda *_args, **_kwargs: {"action": "accept", "confirmed_dangerous_scope": False, "validated_findings": [], "reconciled_prep_credits": 0.0})
    by_id = {arm["id"]: arm for arm in models}
    names = ["luna-high-herdr", "luna-high-runner", "luna-max-runner", "terra-high-herdr", "sol-low-herdr", "terra-high-runner"]
    order = [(by_id[name.rsplit("-", 1)[0]], name.rsplit("-", 1)[1]) for name in names]
    comparison._run_postbrief_jobs(prepared, output, manifest, report, {"runner": "frozen runner", "herdr": "frozen herdr"}, order, dispatch, persist, decision_timeout=1, schema=tmp_path / "schema")
    assert candidate_jobs == names
    assert len(report["trials"]) == 8
    assert report["repeats"]["status"] == "skipped"


def test_postbrief_finalizes_retained_timed_out_correction_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "output"; output.mkdir()
    prepared = tmp_path / "prepared"; (prepared / "cases/herdr").mkdir(parents=True)
    workspace = tmp_path / "old-workspace"; workspace.mkdir(); (workspace / "candidate.py").write_text("value=1\n")
    arm = {"id": "sol-low", "model": "gpt-5.6-sol", "effort": "low"}
    manifest = {"models": [arm], "cases": {"herdr": {"allowed": [], "contract": "herdr"}}, "limits": {"stop_new_dispatch_credits": 1000}}
    trial = {"id": "sol-low-herdr", "arm": arm, "case": "herdr", "first_pass": False, "correction": None}
    report = {
        "prep_credits": 0.0, "experiment_credits": 0.3, "experiment_cost_lower_bound": True,
        "dispatches": [{"run_dir": "/old/runs/sol-low-herdr/correction", "usage_credits": 0.3, "cost_lower_bound": True}],
        "trials": [trial], "shared_briefs": {"herdr": {"usage_credits": 1.0}}, "repeats": [],
    }
    dispatch_kinds: list[bool] = []

    def persist() -> None:
        report["total_credits"] = report["prep_credits"] + report["experiment_credits"]

    def dispatch(**kwargs: object) -> dict:
        dispatch_kinds.append(bool(kwargs.get("candidate")))
        return {"returncode": 0, "timed_out": False, "usage_credits": 0.0, "final": json.dumps({"passed": False, "dangerous_scope": False, "findings": ["timeout"]})}

    def grade(_case: str, _workspace: Path, _prepared: Path, evidence: Path) -> dict:
        evidence.mkdir(parents=True); diff = evidence / "full.diff"; diff.write_text("patch\n")
        return {"passed": False, "checks": {"allowed_paths": True}, "changed_paths": ["candidate.py"], "workspace_digest": "digest", "full_diff_sha256": comparison.sha256(diff), "private_evidence": {"full_diff": str(diff)}}

    monkeypatch.setattr(comparison, "static_grade", grade)
    monkeypatch.setattr(comparison, "await_primary_decision", lambda *_args, **_kwargs: {"action": "fail", "confirmed_dangerous_scope": False, "reconciled_prep_credits": 0.0})
    timeout = fake_attempt(timed_out=True); timeout["cost_lower_bound"] = True
    comparison._run_postbrief_jobs(
        prepared, output, manifest, report, {"herdr": "frozen"}, [], dispatch, persist,
        decision_timeout=1, schema=tmp_path / "schema",
        terminal_correction={"trial_id": trial["id"], "workspace": str(workspace), "prompt": "corrected", "diagnosis": {"final": "fix"}, "worker": timeout},
    )
    assert dispatch_kinds == [False, False]
    assert trial["correction"]["terminal_failure"] is True
    assert trial["correction"]["passed"] is False
    assert report["arm_accounting"]["sol-low"]["cost_lower_bound"] is True


def test_owned_processes_finds_current_process_by_codex_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    owned = comparison.owned_processes(tmp_path, os.getpgrp())
    assert any(pid == os.getpid() for pid, _ in owned)
