#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import selectors
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


PRICING_DATE = "2026-09-09"
STANDARD_RATES = {
    "gpt-6-astra": (250.0, 25.0, 1250.0),
    "gpt-5.6-sol": (100.0, 10.0, 500.0),
    "gpt-5.6-terra": (50.0, 5.0, 300.0),
    "gpt-5.6-luna": (5.0, 0.5, 30.0),
    "gpt-5.5": (125.0, 12.5, 750.0),
}
CATEGORIES = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)
BILLING_CATEGORIES = CATEGORIES[:-1]
SOURCE_KINDS = [
    "subAgent",
    "subAgentReview",
    "subAgentCompact",
    "subAgentThreadSpawn",
    "subAgentOther",
]
MAX_ROLLOUT_LINE_BYTES = 4 * 1024 * 1024
RELEVANT_RECORD = re.compile(
    rb'"type"\s*:\s*"(?:session_meta|turn_context|event_msg)"'
)


def _utc_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def _number(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _usage_categories(value: Any) -> dict[str, int] | None:
    if not isinstance(value, Mapping):
        return None
    result = {name: _number(value.get(name)) for name in CATEGORIES}
    return result if all(item is not None for item in result.values()) else None


def _role_group(thread_id: str, root_id: str, role: Any) -> str:
    if thread_id == root_id:
        return "primary"
    text = str(role or "").lower()
    if "review" in text:
        return "reviewers"
    if text == "worker":
        return "workers"
    return "unknown_role"


def analyze_rollout(
    thread: Mapping[str, Any], root_id: str, *, deadline: float | None = None
) -> dict[str, Any]:
    path_value = thread.get("path")
    row: dict[str, Any] = {
        "thread_id": thread.get("id"),
        "parent_thread_id": thread.get("parentThreadId"),
        "forked_from_id": thread.get("forkedFromId"),
        "history_mode": thread.get("historyMode"),
        "nickname": thread.get("agentNickname"),
        "role": thread.get("agentRole"),
        "role_group": _role_group(str(thread.get("id", "")), root_id, thread.get("agentRole")),
        "model": None,
        "tokens": None,
        "credits": None,
        "share_of_priced_usage": None,
        "pricing_basis": None,
        "status": "unpriced",
        "unpriced_reasons": [],
        "coverage_warnings": [],
    }
    if thread.get("forkedFromId") is not None:
        row["unpriced_reasons"].append("recorded_fork_provenance")
    if deadline is not None and time.monotonic() >= deadline:
        row["unpriced_reasons"].append("processing_deadline")
        row["coverage_warnings"].append("rollout_processing_deadline")
        return row
    if not isinstance(path_value, str):
        row["unpriced_reasons"].append("missing_rollout_path")
        return row
    path = Path(path_value)
    try:
        handle = path.open("rb")
    except OSError:
        row["unpriced_reasons"].append("rollout_unreadable")
        return row

    identity_count = 0
    identity: Mapping[str, Any] | None = None
    models: set[str] = set()
    tiers: set[str] = set()
    first_sample: dict[str, dict[str, int]] | None = None
    latest_sample: dict[str, dict[str, int]] | None = None
    previous_total: dict[str, int] | None = None
    non_monotonic = False
    saw_synthetic = False
    usage_first_timestamp: str | None = None
    usage_last_timestamp: str | None = None
    malformed = False
    with handle:
        while True:
            if deadline is not None and time.monotonic() >= deadline:
                row["coverage_warnings"].append("rollout_processing_deadline")
                break
            encoded = handle.readline(MAX_ROLLOUT_LINE_BYTES + 1)
            if not encoded:
                break
            if len(encoded) > MAX_ROLLOUT_LINE_BYTES:
                malformed = True
                row["coverage_warnings"].append("rollout_line_too_long")
                break
            if not encoded.endswith((b"\n", b"\r")):
                row["coverage_warnings"].append("truncated_final_line_ignored")
                break
            if RELEVANT_RECORD.search(encoded) is None:
                continue
            try:
                record = json.loads(encoded)
            except (UnicodeDecodeError, json.JSONDecodeError):
                malformed = True
                continue
            if not isinstance(record, Mapping):
                continue
            record_type = record.get("type")
            payload = record.get("payload")
            if record_type == "session_meta" and isinstance(payload, Mapping):
                identity_count += 1
                if identity is None:
                    identity = payload
                if payload.get("forked_from_id") is not None:
                    row["unpriced_reasons"].append("recorded_fork_provenance")
            elif record_type == "turn_context" and isinstance(payload, Mapping):
                if isinstance(payload.get("model"), str):
                    models.add(payload["model"])
                tier = payload.get("service_tier")
                if isinstance(tier, str):
                    tiers.add(tier)
            elif (
                record_type == "event_msg"
                and isinstance(payload, Mapping)
                and payload.get("type") == "token_count"
            ):
                info = payload.get("info")
                if not isinstance(info, Mapping):
                    malformed = True
                    continue
                total = _usage_categories(info.get("total_token_usage"))
                last = _usage_categories(info.get("last_token_usage"))
                if total is None or last is None:
                    malformed = True
                else:
                    sample = {"total": total, "last": last}
                    if first_sample is None:
                        first_sample = sample
                    if previous_total is not None and any(
                        total[key] < previous_total[key] for key in CATEGORIES
                    ):
                        non_monotonic = True
                    if total["total_tokens"] > 0 and all(
                        total[key] == 0 for key in BILLING_CATEGORIES
                    ):
                        saw_synthetic = True
                    previous_total = total
                    latest_sample = sample
                    timestamp = record.get("timestamp")
                    if isinstance(timestamp, str):
                        usage_first_timestamp = (
                            timestamp
                            if usage_first_timestamp is None
                            else min(usage_first_timestamp, timestamp)
                        )
                        usage_last_timestamp = (
                            timestamp
                            if usage_last_timestamp is None
                            else max(usage_last_timestamp, timestamp)
                        )

    if identity_count != 1:
        row["unpriced_reasons"].append("session_identity_count_not_one")
    else:
        assert identity is not None
        if identity.get("id") != row["thread_id"]:
            row["unpriced_reasons"].append("session_identity_mismatch")
        for source_key, target_key in (
            ("agent_nickname", "nickname"),
            ("agent_role", "role"),
        ):
            if identity.get(source_key) is not None:
                row[target_key] = identity.get(source_key)
        row["role_group"] = _role_group(
            str(row["thread_id"]), root_id, row.get("role")
        )
    if malformed:
        row["unpriced_reasons"].append("malformed_history")
    if len(models) != 1:
        row["unpriced_reasons"].append("missing_model" if not models else "mixed_models")
    else:
        row["model"] = next(iter(models))
    if len(tiers) > 1:
        row["unpriced_reasons"].append("mixed_service_tiers")
    elif tiers and next(iter(tiers)) not in {"default", "standard"}:
        row["unpriced_reasons"].append("unsupported_service_tier")
    elif not tiers:
        row["pricing_basis"] = "standard_rates_assumed_missing_tier"
    else:
        row["pricing_basis"] = "standard_rates"
    if first_sample is None or latest_sample is None:
        row["unpriced_reasons"].append("missing_token_usage")
    else:
        row["tokens"] = latest_sample["total"]
        if first_sample["total"] != first_sample["last"]:
            row["unpriced_reasons"].append("inherited_usage_baseline")
        if non_monotonic:
            row["unpriced_reasons"].append("non_monotonic_or_reset_usage")
        if latest_sample["total"]["cache_write_input_tokens"]:
            row["unpriced_reasons"].append("cache_write_usage_unsupported")
        if (
            latest_sample["total"]["reasoning_output_tokens"]
            > latest_sample["total"]["output_tokens"]
        ):
            row["unpriced_reasons"].append("reasoning_exceeds_output")
        if saw_synthetic:
            row["unpriced_reasons"].append("synthetic_context_fill_usage")
    if row["model"] not in STANDARD_RATES and row["model"] is not None:
        row["unpriced_reasons"].append("unknown_model_rate")

    row["usage_first_timestamp"] = usage_first_timestamp
    row["usage_last_timestamp"] = usage_last_timestamp
    row["unpriced_reasons"] = sorted(set(row["unpriced_reasons"]))
    if not row["unpriced_reasons"] and row["tokens"] is not None:
        input_rate, cached_rate, output_rate = STANDARD_RATES[row["model"]]
        tokens = row["tokens"]
        uncached = tokens["input_tokens"] - tokens["cached_input_tokens"]
        if uncached < 0:
            row["unpriced_reasons"] = ["cached_input_exceeds_input"]
        else:
            row["tokens"] = {**tokens, "uncached_input_tokens": uncached}
            row["cost_breakdown"] = {
                "uncached_input": uncached * input_rate / 1_000_000,
                "cached_input": tokens["cached_input_tokens"] * cached_rate / 1_000_000,
                "output": tokens["output_tokens"] * output_rate / 1_000_000,
            }
            row["credits"] = sum(row["cost_breakdown"].values())
            row["status"] = "priced"
    return row


def summarize_threads(
    threads: Iterable[Mapping[str, Any]],
    root_id: str,
    *,
    deadline: float | None = None,
    discovery_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rows = [analyze_rollout(thread, root_id, deadline=deadline) for thread in threads]
    known = sum(row["credits"] or 0.0 for row in rows)
    subtotals = {key: 0.0 for key in ("primary", "workers", "reviewers", "unknown_role")}
    token_totals = {key: 0 for key in (*CATEGORIES, "uncached_input_tokens")}
    cost_breakdown = {key: 0.0 for key in ("uncached_input", "cached_input", "output")}
    for row in rows:
        if row["status"] != "priced":
            continue
        subtotals[row["role_group"]] += row["credits"]
        for key in token_totals:
            token_totals[key] += row["tokens"][key]
        for key in cost_breakdown:
            cost_breakdown[key] += row["cost_breakdown"][key]
        row["share_of_priced_usage"] = row["credits"] / known if known else None
    discovery_status = discovery_status or {}
    discovery_complete = all(
        isinstance(discovery_status.get(key), Mapping)
        and discovery_status[key].get("status") == "available"
        for key in ("root", "active", "archived")
    )
    observations_complete = bool(rows) and all(
        row["status"] == "priced" and not row["coverage_warnings"] for row in rows
    )
    root_observed = any(row["thread_id"] == root_id for row in rows)
    return {
        "agents": rows,
        "subtotals": subtotals,
        "token_totals": token_totals,
        "cost_breakdown": cost_breakdown,
        "known_credits_subtotal": known,
        "coverage": {
            "agents_total": len(rows),
            "agents_priced": sum(row["status"] == "priced" for row in rows),
            "agents_unpriced": sum(row["status"] != "priced" for row in rows),
            "discovery_complete": discovery_complete,
            "root_observed": root_observed,
            "observations_complete": observations_complete,
            "status": "complete"
            if discovery_complete and root_observed and observations_complete
            else "partial",
        },
        "unpriced_reasons": sorted(
            {reason for row in rows for reason in row["unpriced_reasons"]}
        ),
    }


def summarize_allowance(result: Any, now: float) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        return {"status": "unavailable", "reason": "invalid_account_response", "buckets": []}
    raw_buckets = result.get("rateLimitsByLimitId")
    if isinstance(raw_buckets, Mapping):
        entries = list(raw_buckets.items())
    elif isinstance(result.get("rateLimits"), Mapping):
        snapshot = result["rateLimits"]
        entries = [(snapshot.get("limitId") or "default", snapshot)]
    else:
        return {"status": "unavailable", "reason": "missing_rate_limits", "buckets": []}
    buckets = []
    for fallback_id, snapshot in entries:
        if not isinstance(snapshot, Mapping):
            continue
        windows = []
        for name in ("primary", "secondary"):
            window = snapshot.get(name)
            if not isinstance(window, Mapping):
                continue
            used = window.get("usedPercent")
            reset = window.get("resetsAt")
            windows.append(
                {
                    "name": name,
                    "window_duration_minutes": window.get("windowDurationMins"),
                    "used_percent": used,
                    "remaining_percent": 100 - used if isinstance(used, (int, float)) else None,
                    "resets_at": reset,
                    "time_until_reset_seconds": max(0, int(reset - now)) if isinstance(reset, (int, float)) else None,
                    "reset_is_past": bool(isinstance(reset, (int, float)) and reset <= now),
                }
            )
        buckets.append(
            {
                "limit_id": snapshot.get("limitId") or fallback_id,
                "limit_name": snapshot.get("limitName"),
                "windows": windows,
            }
        )
    return {"status": "available" if buckets else "unavailable", "buckets": buckets}


class AppServerClient:
    def __init__(self, command: list[str], deadline: float):
        self.deadline = deadline
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        self.selector = selectors.DefaultSelector()
        assert self.process.stdout is not None
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.next_id = 1
        self.buffer = b""
        self.messages: list[bytes] = []

    def send(self, method: str, params: Mapping[str, Any] | None = None) -> int:
        request_id = self.next_id
        self.next_id += 1
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        assert self.process.stdin is not None
        self.process.stdin.write(
            (json.dumps(message, separators=(",", ":")) + "\n").encode()
        )
        self.process.stdin.flush()
        return request_id

    def notify(self, method: str) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(
            (json.dumps({"jsonrpc": "2.0", "method": method}) + "\n").encode()
        )
        self.process.stdin.flush()

    def receive(self) -> Mapping[str, Any]:
        while not self.messages:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise TimeoutError("app_server_deadline")
            assert self.process.stdout is not None
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError("app_server_closed")
            self.buffer += chunk
            parts = self.buffer.split(b"\n")
            self.buffer = parts.pop()
            self.messages.extend(part for part in parts if part)
        value = json.loads(self.messages.pop(0))
        if not isinstance(value, Mapping):
            raise RuntimeError("invalid_app_server_message")
        return value

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=max(0.05, min(0.25, self.deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=0.25)


def collect_native(
    root_id: str,
    *,
    timeout: float = 5.0,
    deadline: float | None = None,
    command: list[str] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    deadline = deadline if deadline is not None else started + timeout
    statuses: dict[str, dict[str, Any]] = {}
    threads: dict[str, Mapping[str, Any]] = {}
    account: Any = None
    try:
        client = AppServerClient(command or ["codex", "app-server", "--stdio"], deadline)
    except OSError:
        return {
            "threads": [],
            "account": None,
            "section_status": {"collector": {"status": "unavailable", "reason": "process_start_failed"}},
            "runtime_milliseconds": round((time.monotonic() - started) * 1000, 3),
        }
    try:
        init_id = client.send(
            "initialize",
            {"clientInfo": {"name": "codex_usage_probe", "version": "0.1.0"}, "capabilities": {"experimentalApi": True}},
        )
        while True:
            message = client.receive()
            if message.get("id") == init_id:
                if "error" in message:
                    raise RuntimeError("initialize_failed")
                break
        client.notify("initialized")
        pending: dict[int, tuple[str, bool, str | None]] = {}
        pending[client.send("thread/read", {"threadId": root_id, "includeTurns": False})] = ("root", False, None)
        for archived in (False, True):
            key = "archived" if archived else "active"
            params = {"ancestorThreadId": root_id, "sourceKinds": SOURCE_KINDS, "useStateDbOnly": True, "archived": archived, "limit": 100}
            pending[client.send("thread/list", params)] = (key, archived, None)
        pending[client.send("account/rateLimits/read", {})] = ("account", False, None)
        while pending and time.monotonic() < deadline:
            try:
                message = client.receive()
            except TimeoutError:
                break
            request_id = message.get("id")
            if request_id not in pending:
                continue
            key, archived, _ = pending.pop(request_id)
            if "error" in message:
                statuses[key] = {"status": "unavailable", "reason": "rpc_error"}
                continue
            result = message.get("result")
            if key == "root":
                thread = result.get("thread") if isinstance(result, Mapping) else None
                if isinstance(thread, Mapping) and isinstance(thread.get("id"), str):
                    threads[thread["id"]] = thread
                    statuses[key] = {"status": "available"}
                else:
                    statuses[key] = {"status": "unavailable", "reason": "invalid_response"}
            elif key == "account":
                account = result
                statuses[key] = {"status": "available"}
            else:
                data = result.get("data") if isinstance(result, Mapping) else None
                if not isinstance(data, list):
                    statuses[key] = {"status": "unavailable", "reason": "invalid_response"}
                    continue
                for thread in data:
                    if isinstance(thread, Mapping) and isinstance(thread.get("id"), str):
                        threads[thread["id"]] = thread
                cursor = result.get("nextCursor")
                if isinstance(cursor, str) and cursor:
                    if time.monotonic() < deadline:
                        params = {"ancestorThreadId": root_id, "sourceKinds": SOURCE_KINDS, "useStateDbOnly": True, "archived": archived, "limit": 100, "cursor": cursor}
                        pending[client.send("thread/list", params)] = (key, archived, cursor)
                    else:
                        statuses[key] = {"status": "partial", "reason": "deadline_with_cursor"}
                else:
                    statuses[key] = {"status": "available"}
        for key, _, _ in pending.values():
            statuses.setdefault(key, {"status": "partial", "reason": "deadline"})
    except (OSError, RuntimeError, json.JSONDecodeError, TimeoutError) as error:
        statuses.setdefault("collector", {"status": "unavailable", "reason": type(error).__name__})
    finally:
        client.close()
    return {
        "threads": list(threads.values()),
        "account": account,
        "section_status": statuses,
        "runtime_milliseconds": round((time.monotonic() - started) * 1000, 3),
    }


def build_report(
    root_id: str,
    native: Mapping[str, Any],
    now: float,
    *,
    deadline: float | None = None,
) -> dict[str, Any]:
    usage = summarize_threads(
        native.get("threads", []),
        root_id,
        deadline=deadline,
        discovery_status=native.get("section_status", {}),
    )
    source_times = [
        row[key]
        for row in usage["agents"]
        for key in ("usage_first_timestamp", "usage_last_timestamp")
        if row.get(key)
    ]
    return {
        "schema_version": 1,
        "root_thread_id": root_id,
        "snapshot_timestamp": _utc_iso(now),
        "source_timestamp_range": {"first": min(source_times) if source_times else None, "last": max(source_times) if source_times else None},
        "runtime_milliseconds": native.get("runtime_milliseconds"),
        "pricing": {"date": PRICING_DATE, "basis": "standard comparative credit estimate", "source": "https://learn.chatgpt.com/docs/pricing#token-rates"},
        "session_tree": usage,
        "account_allowance": summarize_allowance(native.get("account"), now),
        "section_status": native.get("section_status", {}),
        "notes": [
            "account allowance is shared across sessions and projects",
            "account changes are not attributed to this session tree",
            "estimated credits are not subscription deductions or task budget",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report bounded Codex usage for one session tree")
    parser.add_argument("--thread-id", default=os.environ.get("CODEX_THREAD_ID"))
    args = parser.parse_args(argv)
    if not args.thread_id:
        print(json.dumps({"status": "unavailable", "reason": "missing_thread_id"}, separators=(",", ":")))
        return 2
    started = time.monotonic()
    hard_deadline = started + 5.0
    native = collect_native(args.thread_id, deadline=hard_deadline - 0.5)
    now = time.time()
    report = build_report(
        args.thread_id, native, now, deadline=hard_deadline - 0.1
    )
    report["runtime_milliseconds"] = round((time.monotonic() - started) * 1000, 3)
    encoded = json.dumps(report, separators=(",", ":"), sort_keys=True)
    report["runtime_milliseconds"] = round((time.monotonic() - started) * 1000, 3)
    encoded = json.dumps(report, separators=(",", ":"), sort_keys=True)
    print(encoded)
    return 0 if native["threads"] or native["account"] is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
