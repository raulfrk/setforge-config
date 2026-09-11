from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "tracked/codex/skills/usage-check/scripts/check_usage.py"
SPEC = importlib.util.spec_from_file_location("usage_check", SCRIPT)
assert SPEC and SPEC.loader
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)


def record(record_type: str, payload: dict, timestamp: str = "2026-09-09T14:00:00Z") -> str:
    return json.dumps({"timestamp": timestamp, "type": record_type, "payload": payload})


def token_record(total: dict[str, int], last: dict[str, int] | None = None) -> str:
    return record(
        "event_msg",
        {
            "type": "token_count",
            "info": {
                "total_token_usage": total,
                "last_token_usage": last if last is not None else total,
            },
        },
    )


def counters(
    input_tokens: int = 1000,
    cached_input_tokens: int = 200,
    cache_write_input_tokens: int = 0,
    output_tokens: int = 100,
    reasoning_output_tokens: int = 25,
    total_tokens: int | None = None,
) -> dict[str, int]:
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "cache_write_input_tokens": cache_write_input_tokens,
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning_output_tokens,
        "total_tokens": total_tokens if total_tokens is not None else input_tokens + output_tokens,
    }


def rollout(
    tmp_path: Path,
    name: str,
    *,
    model: str = "gpt-6-astra",
    role: str | None = None,
    samples: list[str] | None = None,
    tier: str | None = None,
    final_fragment: str = "",
) -> Path:
    identity = {"id": name, "agent_nickname": name, "agent_role": role}
    context = {"model": model}
    if tier is not None:
        context["service_tier"] = tier
    lines = [record("session_meta", identity), record("turn_context", context)]
    lines.extend(samples or [token_record(counters())])
    path = tmp_path / f"{name}.jsonl"
    path.write_text("\n".join(lines) + "\n" + final_fragment, encoding="utf-8")
    return path


def thread(name: str, path: Path, role: str | None = None) -> dict:
    return {"id": name, "path": str(path), "agentNickname": name, "agentRole": role}


def test_real_rollout_shapes_price_latest_cumulative_snapshot_once(tmp_path: Path) -> None:
    first = counters(1000, 200, output_tokens=100, reasoning_output_tokens=25)
    latest = counters(2500, 1200, output_tokens=220, reasoning_output_tokens=60)
    path = rollout(
        tmp_path,
        "root",
        samples=[token_record(first), token_record(latest, counters(1500, 1000, output_tokens=120, reasoning_output_tokens=35)), token_record(latest, counters(0, 0, output_tokens=0, reasoning_output_tokens=0))],
    )
    result = usage.summarize_threads([thread("root", path)], "root")
    row = result["agents"][0]
    assert row["status"] == "priced"
    assert row["tokens"]["uncached_input_tokens"] == 1300
    assert row["credits"] == pytest.approx(
        1300 * 250 / 1_000_000 + 1200 * 25 / 1_000_000 + 220 * 1250 / 1_000_000
    )
    assert row["tokens"]["reasoning_output_tokens"] == 60
    assert result["known_credits_subtotal"] == row["credits"]
    assert result["coverage"] == {
        "agents_total": 1,
        "agents_priced": 1,
        "agents_unpriced": 0,
        "discovery_complete": False,
        "root_observed": True,
        "observations_complete": True,
        "status": "partial",
    }


@pytest.mark.parametrize(
    ("name", "kwargs", "reason"),
    [
        (
            "inherited",
            {"samples": [token_record(counters(2000), counters(1000))]},
            "inherited_usage_baseline",
        ),
        (
            "mixed",
            {"samples": [token_record(counters())]},
            "mixed_models",
        ),
        (
            "reset",
            {"samples": [token_record(counters(2000)), token_record(counters(1000))]},
            "non_monotonic_or_reset_usage",
        ),
        (
            "cache-write",
            {"samples": [token_record(counters(cache_write_input_tokens=1))]},
            "cache_write_usage_unsupported",
        ),
        (
            "unknown-model",
            {"model": "gpt-future", "samples": [token_record(counters())]},
            "unknown_model_rate",
        ),
        (
            "special-tier",
            {"tier": "priority", "samples": [token_record(counters())]},
            "unsupported_service_tier",
        ),
    ],
)
def test_ambiguous_accounting_is_explicitly_unpriced(
    tmp_path: Path, name: str, kwargs: dict, reason: str
) -> None:
    path = rollout(tmp_path, name, **kwargs)
    if name == "mixed":
        with path.open("a", encoding="utf-8") as handle:
            handle.write(record("turn_context", {"model": "gpt-5.6-sol"}) + "\n")
    row = usage.analyze_rollout(thread(name, path), "root")
    assert row["status"] == "unpriced"
    assert row["credits"] is None
    assert reason in row["unpriced_reasons"]


def test_missing_and_malformed_history_are_unknown_not_zero(tmp_path: Path) -> None:
    missing_path = rollout(tmp_path, "missing", samples=[])
    missing_path.write_text(
        record("session_meta", {"id": "missing"}) + "\n" + record("turn_context", {"model": "gpt-5.6-sol"}) + "\n",
        encoding="utf-8",
    )
    missing = usage.analyze_rollout(thread("missing", missing_path), "root")
    assert missing["status"] == "unpriced"
    assert "missing_token_usage" in missing["unpriced_reasons"]

    malformed_path = rollout(tmp_path, "malformed")
    with malformed_path.open("a", encoding="utf-8") as handle:
        handle.write(
            '{"type":"event_msg","payload":{"type":"token_count",bad json}\n'
        )
    malformed = usage.analyze_rollout(thread("malformed", malformed_path), "root")
    assert "malformed_history" in malformed["unpriced_reasons"]


def test_truncated_final_line_uses_preceding_valid_sample_with_warning(tmp_path: Path) -> None:
    path = rollout(tmp_path, "partial", final_fragment='{"type":"event_msg"')
    row = usage.analyze_rollout(thread("partial", path), "root")
    assert row["status"] == "priced"
    assert row["credits"] is not None
    assert row["coverage_warnings"] == ["truncated_final_line_ignored"]


def test_truncated_or_interrupted_observation_makes_aggregate_coverage_partial(
    tmp_path: Path,
) -> None:
    path = rollout(tmp_path, "root", final_fragment='{"type":"event_msg"')
    result = usage.summarize_threads(
        [thread("root", path)],
        "root",
        discovery_status={key: {"status": "available"} for key in ("root", "active", "archived")},
    )
    assert result["known_credits_subtotal"] > 0
    assert result["coverage"]["observations_complete"] is False
    assert result["coverage"]["status"] == "partial"


def test_discovery_completeness_requires_root_active_and_archived_only(tmp_path: Path) -> None:
    path = rollout(tmp_path, "root")
    base = {key: {"status": "available"} for key in ("root", "active", "archived", "account")}
    complete = usage.summarize_threads(
        [thread("root", path)], "root", discovery_status=base
    )
    assert complete["coverage"]["status"] == "complete"
    account_failed = {**base, "account": {"status": "unavailable"}}
    assert usage.summarize_threads(
        [thread("root", path)], "root", discovery_status=account_failed
    )["coverage"]["status"] == "complete"
    active_partial = {**base, "active": {"status": "partial"}}
    partial = usage.summarize_threads(
        [thread("root", path)], "root", discovery_status=active_partial
    )
    assert partial["coverage"]["status"] == "partial"
    child_only = usage.summarize_threads(
        [thread("child", path, "worker")], "root", discovery_status=base
    )
    assert child_only["coverage"]["root_observed"] is False
    assert child_only["coverage"]["status"] == "partial"


def test_rollout_processing_deadline_preserves_explicit_partial_result(tmp_path: Path) -> None:
    path = rollout(tmp_path, "deadline")
    row = usage.analyze_rollout(
        thread("deadline", path), "root", deadline=time.monotonic() - 1
    )
    assert row["status"] == "unpriced"
    assert row["unpriced_reasons"] == ["processing_deadline"]
    assert row["coverage_warnings"] == ["rollout_processing_deadline"]


def test_fork_and_synthetic_context_fill_are_unpriced_but_parent_is_not(
    tmp_path: Path,
) -> None:
    normal_path = rollout(tmp_path, "normal")
    normal = thread("normal", normal_path, "worker")
    normal["parentThreadId"] = "root"
    assert usage.analyze_rollout(normal, "root")["status"] == "priced"

    fork = {**normal, "forkedFromId": "ancestor"}
    forked = usage.analyze_rollout(fork, "root")
    assert "recorded_fork_provenance" in forked["unpriced_reasons"]

    synthetic_path = rollout(
        tmp_path,
        "synthetic",
        samples=[token_record(counters(0, 0, 0, 0, 0, total_tokens=10_000))],
    )
    synthetic = usage.analyze_rollout(thread("synthetic", synthetic_path), "root")
    assert "synthetic_context_fill_usage" in synthetic["unpriced_reasons"]
    assert synthetic["credits"] is None

    later_normal = counters(1000, 200, 0, 100, 25, total_tokens=11_100)
    synthetic_then_normal_path = rollout(
        tmp_path,
        "synthetic-then-normal",
        samples=[
            token_record(counters(0, 0, 0, 0, 0, total_tokens=10_000)),
            token_record(later_normal),
        ],
    )
    synthetic_then_normal = usage.analyze_rollout(
        thread("synthetic-then-normal", synthetic_then_normal_path), "root"
    )
    assert synthetic_then_normal["status"] == "unpriced"
    assert "synthetic_context_fill_usage" in synthetic_then_normal["unpriced_reasons"]


def test_usage_freshness_uses_only_selected_valid_token_records(tmp_path: Path) -> None:
    path = rollout(tmp_path, "freshness")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(record("response_item", {"message": "later"}, "2026-09-09T19:00:00Z") + "\n")
        handle.write("not-json conversation payload\n")
    row = usage.analyze_rollout(thread("freshness", path), "root")
    assert row["status"] == "priced"
    assert row["usage_first_timestamp"] == "2026-09-09T14:00:00Z"
    assert row["usage_last_timestamp"] == "2026-09-09T14:00:00Z"
    assert "malformed_history" not in row["unpriced_reasons"]


def test_expired_deadline_does_not_open_rollout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = rollout(tmp_path, "expired")
    opened = 0
    original_open = Path.open

    def counting_open(self: Path, *args: object, **kwargs: object):
        nonlocal opened
        opened += 1
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counting_open)
    row = usage.analyze_rollout(
        thread("expired", path), "root", deadline=time.monotonic() - 1
    )
    assert opened == 0
    assert row["unpriced_reasons"] == ["processing_deadline"]


def test_mid_summary_deadline_keeps_completed_subtotal_and_skips_next_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = [rollout(tmp_path, name) for name in ("root", "later")]
    original_analyze = usage.analyze_rollout
    original_open = Path.open
    calls = 0
    opened = 0

    def counting_open(self: Path, *args: object, **kwargs: object):
        nonlocal opened
        opened += 1
        return original_open(self, *args, **kwargs)

    def deadline_after_first(
        item: dict, root_id: str, *, deadline: float | None = None
    ) -> dict:
        nonlocal calls
        calls += 1
        if calls == 1:
            result = original_analyze(item, root_id, deadline=None)
            time.sleep(0.02)
            return result
        return original_analyze(item, root_id, deadline=deadline)

    monkeypatch.setattr(usage, "analyze_rollout", deadline_after_first)
    monkeypatch.setattr(Path, "open", counting_open)
    result = usage.summarize_threads(
        [thread("root", paths[0]), thread("later", paths[1], "worker")],
        "root",
        deadline=time.monotonic() + 0.01,
        discovery_status={key: {"status": "available"} for key in ("root", "active", "archived")},
    )
    assert result["agents"][0]["status"] == "priced"
    assert result["agents"][1]["unpriced_reasons"] == ["processing_deadline"]
    assert opened == 1
    assert result["known_credits_subtotal"] == result["agents"][0]["credits"]
    assert result["coverage"]["status"] == "partial"


def test_role_subtotals_and_shares_expose_unknown_role(tmp_path: Path) -> None:
    paths = {
        "root": rollout(tmp_path, "root", model="gpt-5.6-sol"),
        "worker": rollout(tmp_path, "worker", model="gpt-5.6-luna", role="worker"),
        "review": rollout(tmp_path, "review", model="gpt-6-astra", role="review_correctness"),
        "other": rollout(tmp_path, "other", model="gpt-5.6-terra", role="planner"),
    }
    result = usage.summarize_threads(
        [thread(name, path, None if name == "root" else ("worker" if name == "worker" else "review_correctness" if name == "review" else "planner")) for name, path in paths.items()],
        "root",
    )
    assert set(result["subtotals"]) == {"primary", "workers", "reviewers", "unknown_role"}
    assert all(value > 0 for value in result["subtotals"].values())
    assert sum(row["share_of_priced_usage"] for row in result["agents"]) == pytest.approx(1.0)


def test_allowance_reports_all_windows_and_past_reset_without_inventing_renewal() -> None:
    result = usage.summarize_allowance(
        {
            "rateLimitsByLimitId": {
                "codex": {
                    "limitId": "codex",
                    "limitName": "Weekly",
                    "primary": {"usedPercent": 40, "windowDurationMins": 10080, "resetsAt": 1100},
                    "secondary": {"usedPercent": 75, "windowDurationMins": 300, "resetsAt": 900},
                },
                "other": {"primary": {"usedPercent": 10, "windowDurationMins": 60, "resetsAt": 1060}},
            }
        },
        1000,
    )
    assert [bucket["limit_id"] for bucket in result["buckets"]] == ["codex", "other"]
    primary, past = result["buckets"][0]["windows"]
    assert primary["remaining_percent"] == 60
    assert primary["time_until_reset_seconds"] == 100
    assert past["time_until_reset_seconds"] == 0
    assert past["reset_is_past"] is True
    assert past["resets_at"] == 900


FAKE_SERVER = r"""
import json, os, sys, time
mode=os.environ.get('FAKE_MODE','pages')
pid_path=os.environ.get('FAKE_PID_PATH')
if pid_path:
    open(pid_path,'w').write(str(os.getpid()))
for line in sys.stdin:
    req=json.loads(line)
    if 'id' not in req:
        continue
    ident=req['id']; method=req['method']; params=req.get('params',{})
    if method == 'initialize':
        result={}
    elif mode == 'timeout':
        time.sleep(30); continue
    elif method == 'thread/read':
        result={'thread':{'id':'root','path':'/tmp/root','agentNickname':None,'agentRole':None}}
    elif method == 'account/rateLimits/read':
        if mode == 'account-error':
            print(json.dumps({'jsonrpc':'2.0','id':ident,'error':{'code':-1}}),flush=True); continue
        result={'rateLimits':{'limitId':'codex','primary':{'usedPercent':5,'windowDurationMins':60,'resetsAt':2000}}}
    elif method == 'thread/list':
        if params.get('archived'):
            result={'data':[{'id':'dup','path':'/tmp/dup'}], 'nextCursor':None}
        elif params.get('cursor') is None:
            if mode == 'cursor-deadline':
                result={'data':[{'id':str(i),'path':'/tmp/x'} for i in range(30000)], 'nextCursor':'next'}
            else:
                result={'data':[{'id':'a','path':'/tmp/a'},{'id':'dup','path':'/tmp/dup'}], 'nextCursor':'next'}
        else:
            result={'data':[{'id':'b','path':'/tmp/b'},{'id':'dup','path':'/tmp/dup'}], 'nextCursor':None}
    print(json.dumps({'jsonrpc':'2.0','id':ident,'result':result}),flush=True)
"""


def fake_command() -> list[str]:
    return [sys.executable, "-u", "-c", textwrap.dedent(FAKE_SERVER)]


def test_native_collection_paginates_deduplicates_and_preserves_independent_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_MODE", "account-error")
    result = usage.collect_native("root", timeout=2, command=fake_command())
    assert {item["id"] for item in result["threads"]} == {"root", "a", "b", "dup"}
    assert result["section_status"]["active"] == {"status": "available"}
    assert result["section_status"]["archived"] == {"status": "available"}
    assert result["section_status"]["account"] == {"status": "unavailable", "reason": "rpc_error"}
    assert result["account"] is None


def test_timeout_cleans_up_only_owned_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_MODE", "timeout")
    pid_path = tmp_path / "owned.pid"
    monkeypatch.setenv("FAKE_PID_PATH", str(pid_path))
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    started = time.monotonic()
    try:
        result = usage.collect_native("root", timeout=0.25, command=fake_command())
        assert time.monotonic() - started < 1.0
        assert result["section_status"]
        owned_pid = int(pid_path.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(owned_pid, 0)
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=1)


def test_outstanding_cursor_at_deadline_is_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_MODE", "cursor-deadline")
    result = usage.collect_native("root", timeout=0.1, command=fake_command())
    assert result["section_status"]["active"]["status"] == "partial"


def test_main_runtime_includes_accounting_and_report_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = rollout(tmp_path, "root")
    native = {
        "threads": [thread("root", path)],
        "account": {},
        "section_status": {key: {"status": "available"} for key in ("root", "active", "archived", "account")},
        "runtime_milliseconds": 1,
    }
    monkeypatch.setattr(usage, "collect_native", lambda *_args, **_kwargs: native)
    original = usage.analyze_rollout

    def slow(*args: object, **kwargs: object) -> dict:
        time.sleep(0.03)
        return original(*args, **kwargs)

    monkeypatch.setattr(usage, "analyze_rollout", slow)
    assert usage.main(["--thread-id", "root"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["runtime_milliseconds"] >= 25


def test_policy_and_manifest_register_only_the_two_usage_resources() -> None:
    policy = " ".join((ROOT / "tracked/codex/AGENTS.md").read_text().split())
    assert "Use usage-check at the start of substantial work" in policy
    assert "Computed estimates must state their basis and coverage" in policy
    manifest = yaml.safe_load((ROOT / "setforge.yaml").read_text())
    expected = {"codex_skill_usage_check", "codex_skill_usage_check_helper"}
    assert expected <= set(manifest["profiles"]["codex"]["tracked_files"])
    assert expected <= set(manifest["profiles"]["codex-policy"]["tracked_files"])
    for resource in expected:
        assert resource in manifest["tracked_files"]
