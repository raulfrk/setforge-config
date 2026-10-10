"""Public coordinator commands against private stores and a native API fixture."""
import importlib.util
import multiprocessing
from pathlib import Path
import threading

import pytest


SCRIPT = Path(__file__).parents[1] / "tracked/codex/skills/main-session/scripts/main_session.py"
spec = importlib.util.spec_from_file_location("main_session", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class NativeFixture:
    def __init__(self):
        self.identity = {"pid": 123, "uid": 1000, "start": "fixture", "codex_home": "/isolated/codex"}
        self.threads = {"caller": self.thread("caller"), "other": self.thread("other")}
        self.calls = []
        self.entries = []
        self.failure = None
        self.settings = {"model": "gpt-6.1-sol", "modelProvider": "fixture", "cwd": "/isolated",
                         "approvalPolicy": "never", "approvalsReviewer": "user",
                         "sandbox": {"type": "readOnly"}, "reasoningEffort": "medium",
                         "activePermissionProfile": None}

    def thread(self, tid, parent=None):
        return {"id": tid, "parentThreadId": parent, "cwd": "/isolated",
                "status": {"type": "idle"}, "turns": []}

    def loaded(self):
        return {k for k, t in self.threads.items() if t["status"]["type"] != "notLoaded"}

    def read(self, tid, turns=False):
        return self.threads[tid]

    def items(self, tid):
        return self.entries

    def rpc(self, method, params):
        self.calls.append((method, params))
        if self.failure and self.failure[0] == method:
            raise self.failure[1]
        if method == "thread/start":
            tid = "main" + str(sum(x[0] == method for x in self.calls))
            self.threads[tid] = self.thread(tid)
            return dict(self.settings, thread=self.threads[tid])
        if method == "thread/resume":
            t = self.threads[params["threadId"]]
            t["status"] = {"type": "idle"}
            return dict(self.settings, thread=t)
        if method == "turn/start":
            tid = params["threadId"]
            self.threads[tid]["turns"].append({"id": "turn1", "status": "inProgress", "items": []})
            self.threads[tid]["status"] = {"type": "active"}
            return {"turn": self.threads[tid]["turns"][-1]}
        if method == "turn/interrupt":
            for turn in self.threads[params["threadId"]]["turns"]:
                if turn["id"] == params["turnId"]:
                    turn["status"] = "interrupted"
            return {}
        raise AssertionError(method)

    def deliver(self, tid, text, mid):
        self.calls.append(("deliver", {"threadId": tid, "text": text, "id": mid}))
        if self.failure and self.failure[0] == "deliver":
            raise self.failure[1]
        return {"turnId": "turn1"}


@pytest.fixture
def setup(tmp_path):
    store = m.Store(str(tmp_path / "app.sock"), tmp_path / "state")
    native = NativeFixture()
    caller = m.Coordinator(store, native, "caller")
    state = caller.run("ensure", {})
    main = m.Coordinator(store, native, state["owner"], state["generation"])
    main.run("ready", {})
    return store, native, caller, main


def state_of(store):
    with store.locked() as state:
        return state


def event(setup):
    store, native, caller, main = setup
    registered = main.run("register", {"request": {"thread": main.caller, "turn": "user-turn", "item": "user-item"}})
    child = native.thread("child", main.caller)
    child["turns"] = [{"id": "child-turn", "status": "inProgress"}]
    native.threads["child"] = child
    native.entries.append({"turnId": "turn1", "item": {"type": "subAgentActivity", "kind": "started",
        "agentPath": registered["path"], "agentThreadId": "child"}})
    main.run("bind", {"job": registered["job"]})
    return registered["job"]


def grant(main):
    return main.run("grant", {"target": "other", "scope": "only suggest finishing its current tests",
        "authorisation": {"thread": main.caller, "turn": "authorised-turn", "item": "user-item"}})["grant"]


def guidance(main, gid, job=None, key="report1"):
    data = {"kind": "guidance", "target": "other", "grant": gid, "key": key, "text": "Finish the current tests."}
    if job:
        data["job"] = job
    return main.run("admit", data)["action"]


def test_concurrent_ensure_yields_one_owner_and_never_takes_busy_or_idle(setup):
    store, native, caller, main = setup
    ids = []
    threads = [threading.Thread(target=lambda: ids.append(caller.run("ensure", {})["owner"])) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert ids == [main.caller] * 8
    native.threads[main.caller]["status"] = {"type": "idle"}
    assert caller.run("ensure", {})["owner"] == main.caller
    assert sum(c[0] == "thread/start" for c in native.calls) == 1


def test_owner_published_booting_before_first_turn(tmp_path):
    store = m.Store(str(tmp_path / "app.sock"), tmp_path / "state")
    native = NativeFixture()
    original = native.rpc
    def rpc(method, params):
        if method == "turn/start":
            import json
            s = json.loads(store.path.read_text())
            assert s["owner"] == params["threadId"] and s["phase"] == "booting"
            assert m.pending(s)[0]["kind"] == "boot"
        return original(method, params)
    native.rpc = rpc
    m.Coordinator(store, native, "caller").run("ensure", {})


@pytest.mark.parametrize("model", ["gpt-6.1-sol", "gpt-6-astra"])
def test_claim_current_live_root_without_new_thread_turn_or_settings_override(tmp_path, model):
    store = m.Store(str(tmp_path / "app.sock"), tmp_path / "state")
    native = NativeFixture()
    native.settings["model"] = model
    native.entries = [{"item": {"type": "subAgentActivity", "kind": "started",
        "agentThreadId": "ordinary-review-child", "agentPath": "/root/reviewer"}}]
    caller = m.Coordinator(store, native, "caller")
    s = caller.run("claim", {})
    assert s["owner"] == "caller" and s["phase"] == "ready"
    assert s["policy"]["model"] == model
    assert s["prior_children"] == ["ordinary-review-child"]
    assert s["jobs"] == {}
    assert native.calls == [("thread/resume", {"threadId": "caller", "excludeTurns": True})]
    assert caller.run("claim", {})["generation"] == s["generation"]
    native.threads["caller"]["status"] = {"type": "notLoaded"}
    caller.run("ensure", {})
    m.Coordinator(store, native, "caller", s["generation"]).run("ready", {})


def test_claim_refuses_existing_owner_and_unloaded_or_child_caller(setup, tmp_path):
    store, native, caller, main = setup
    with pytest.raises(m.Refused, match="owner"):
        caller.run("claim", {})
    empty = m.Store(str(tmp_path / "other.sock"), tmp_path / "other-state")
    native.threads["caller"]["status"] = {"type": "notLoaded"}
    with pytest.raises(m.Refused, match="already be loaded"):
        m.Coordinator(empty, native, "caller").run("claim", {})
    native.threads["child"] = native.thread("child", "caller")
    with pytest.raises(m.Refused, match="independent root"):
        m.Coordinator(empty, native, "child").run("claim", {})
    assert state_of(empty)["owner"] is None


def test_lost_claim_policy_reply_leaves_pointer_empty(tmp_path):
    store = m.Store(str(tmp_path / "app.sock"), tmp_path / "state")
    native = NativeFixture()
    native.failure = ("thread/resume", TimeoutError("lost metadata reply"))
    with pytest.raises(TimeoutError):
        m.Coordinator(store, native, "caller").run("claim", {})
    assert state_of(store)["owner"] is None


def test_same_id_resume_preserves_generation_and_adopts_existing_children(setup):
    store, native, caller, main = setup
    jid = event(setup)
    native.threads[main.caller]["status"] = {"type": "notLoaded"}
    s = caller.run("ensure", {})
    assert s["owner"] == main.caller and s["generation"] == main.generation
    main.run("ready", {})
    assert state_of(store)["jobs"][jid]["child"] == "child"
    assert sum(c[0] == "thread/start" for c in native.calls) == 1


def test_changed_resume_policy_blocks_bootstrap(setup):
    store, native, caller, main = setup
    native.threads[main.caller]["status"] = {"type": "notLoaded"}
    native.settings["approvalPolicy"] = "on-request"
    before = len(native.calls)
    with pytest.raises(m.Refused, match="settings differ"):
        caller.run("ensure", {})
    assert state_of(store)["phase"] == "blocked"
    assert all(c[0] != "turn/start" for c in native.calls[before:])


def test_lost_creation_reply_blocks_retry(tmp_path):
    store = m.Store(str(tmp_path / "app.sock"), tmp_path / "state")
    native = NativeFixture()
    native.failure = ("thread/start", TimeoutError("lost reply"))
    caller = m.Coordinator(store, native, "caller")
    with pytest.raises(TimeoutError):
        caller.run("ensure", {})
    native.failure = None
    with pytest.raises(m.Refused, match="blocked"):
        caller.run("ensure", {})
    assert sum(c[0] == "thread/start" for c in native.calls) == 1


def test_definitive_missing_root_replaces_but_unknown_failure_does_not(setup):
    store, native, caller, main = setup
    native.threads[main.caller]["status"] = {"type": "notLoaded"}
    native.failure = ("thread/resume", m.RpcError({"code": -32600,
        "message": f"no rollout found for thread id {main.caller}"}))
    s = caller.run("ensure", {})
    assert s["owner"] != main.caller and s["generation"] != main.generation
    assert s["phase"] == "booting"


def test_cancel_closes_admission_before_interrupt_and_queued_guidance(setup):
    store, native, caller, main = setup
    jid = event(setup)
    gid = grant(main)
    aid = guidance(main, gid, jid)
    original = native.rpc
    def rpc(method, params):
        if method == "turn/interrupt":
            import json
            assert not json.loads(store.path.read_text())["jobs"][jid]["active"]
        return original(method, params)
    native.rpc = rpc
    main.run("cancel", {"job": jid})
    with pytest.raises(m.Refused, match="Inactive"):
        guidance(main, gid, jid, key="late-report")
    with pytest.raises(m.Refused, match="cancelled"):
        main.run("send", {"action": aid})
    with pytest.raises(m.Refused, match="cancelled"):
        m.Coordinator(store, native, "other").run("validate", {"action": aid})
    assert not native.threads["other"]["turns"]


def test_guidance_needs_grant_and_revocation_invalidates_delivery(setup):
    store, native, caller, main = setup
    with pytest.raises(m.Refused, match="No active"):
        guidance(main, "absent")
    gid = grant(main)
    aid = guidance(main, gid)
    main.run("send", {"action": aid})
    assert m.Coordinator(store, native, "other").run("validate", {"action": aid})["text"] == "Finish the current tests."
    main.run("revoke", {"grant": gid})
    with pytest.raises(m.Refused, match="revoked"):
        m.Coordinator(store, native, "other").run("validate", {"action": aid})


def test_uncertain_action_blocks_recovery_release_and_duplicate_dispatch(setup):
    store, native, caller, main = setup
    aid = guidance(main, grant(main))
    native.failure = ("deliver", TimeoutError("lost receipt"))
    with pytest.raises(TimeoutError):
        main.run("send", {"action": aid})
    native.failure = None
    with pytest.raises(m.Refused, match="first dispatch"):
        main.run("send", {"action": aid})
    with pytest.raises(m.Refused, match="already admitted"):
        guidance(main, state_of(store)["actions"][aid]["grant"])
    native.threads[main.caller]["status"] = {"type": "notLoaded"}
    with pytest.raises(m.Refused, match="Unresolved"):
        caller.run("ensure", {})
    with pytest.raises(m.Refused, match="not loaded"):
        main.run("stop", {})  # recovery is disabled even when drain target is unavailable
    with pytest.raises(m.Refused, match="Drain"):
        main.run("release", {})
    main.run("settle", {"action": aid, "status": "sent", "evidence": {"recipient_item": "actual-positive-receipt"}})
    main.run("release", {})


def test_lost_resume_reply_cannot_bypass_policy_checks_when_it_loaded_root(setup):
    store, native, caller, main = setup
    native.threads[main.caller]["status"] = {"type": "notLoaded"}
    original = native.rpc
    def rpc(method, params):
        if method == "thread/resume":
            native.threads[main.caller]["status"] = {"type": "idle"}
            raise TimeoutError("resume succeeded but reply was lost")
        return original(method, params)
    native.rpc = rpc
    with pytest.raises(TimeoutError):
        caller.run("ensure", {})
    assert state_of(store)["phase"] == "resuming"
    with pytest.raises(m.Refused, match="blocked"):
        caller.run("request", {"text": "create new event"})
    with pytest.raises(m.Refused, match="Startup"):
        main.run("ready", {})


def test_admission_refuses_unloaded_owner_and_changed_server_instance(setup):
    store, native, caller, main = setup
    effect = {"kind": "effect", "key": "effect-1", "authorisation": "user-turn", "text": "authorised effect"}
    native.threads[main.caller]["status"] = {"type": "notLoaded"}
    with pytest.raises(m.Refused, match="not loaded"):
        main.run("admit", effect)
    native.threads[main.caller]["status"] = {"type": "idle"}
    admitted = main.run("admit", effect)
    native.identity = dict(native.identity, start="new-server-instance")
    with pytest.raises(m.Refused, match="instance changed"):
        main.run("dispatch", {"action": admitted["action"]})
    with pytest.raises(m.Refused, match="Unresolved"):
        caller.run("ensure", {})


def test_guidance_validation_returns_atomic_permission_scope(setup):
    store, native, caller, main = setup
    aid = guidance(main, grant(main))
    result = m.Coordinator(store, native, "other").run("validate", {"action": aid})
    assert result["permission"]["scope"] == "only suggest finishing its current tests"
    assert result["permission"]["authorisation"]["turn"] == "authorised-turn"


def test_busy_recipient_uses_expected_turn_without_changing_settings():
    client = m.Native.__new__(m.Native)
    client.read = lambda tid: {"status": {"type": "active"}}
    client.turns = lambda tid: [{"id": "active-turn", "status": "inProgress"},
                              {"id": "old-unfinished-turn", "status": "inProgress"}]
    client.loaded = lambda: {"recipient"}
    calls = []
    client.rpc = lambda method, params: calls.append((method, params)) or {"turnId": "active-turn"}
    client.deliver("recipient", "authorised suggestion", "receipt-id")
    assert calls == [("turn/steer", {"threadId": "recipient", "expectedTurnId": "active-turn",
        "input": [{"type": "text", "text": "authorised suggestion"}], "clientUserMessageId": "receipt-id"})]


def test_idle_recipient_starts_new_turn_despite_old_unfinished_history():
    client = m.Native.__new__(m.Native)
    client.read = lambda tid: {"status": {"type": "idle"}}
    client.turns = lambda tid: pytest.fail("Idle history is not active-turn evidence")
    client.loaded = lambda: {"recipient"}
    calls = []
    client.rpc = lambda method, params: calls.append((method, params)) or {"turn": {"id": "new-turn"}}
    client.deliver("recipient", "informational notice", "receipt-id")
    assert calls == [("turn/start", {"threadId": "recipient",
        "input": [{"type": "text", "text": "informational notice"}], "clientUserMessageId": "receipt-id"})]


def test_stop_drains_only_owned_children_and_requires_explicit_activation(setup):
    store, native, caller, main = setup
    event(setup)
    native.threads["other"]["turns"] = [{"id": "other-turn", "status": "inProgress"}]
    main.run("stop", {})
    main.run("release", {})
    with pytest.raises(m.Refused, match="explicit activate"):
        caller.run("ensure", {})
    assert native.threads["other"]["turns"][0]["status"] == "inProgress"
    assert caller.run("activate", {})["owner"] != main.caller


def test_wrong_generation_and_child_caller_cannot_own_or_route(setup):
    store, native, caller, main = setup
    with pytest.raises(m.Refused, match="generation"):
        m.Coordinator(store, native, main.caller, "old-generation").run("register", {"request": "bad"})
    native.threads["child"] = native.thread("child", main.caller)
    with pytest.raises(m.Refused, match="independent root"):
        m.Coordinator(store, native, "child").run("request", {"text": "spawn more"})


def test_corrupt_wrong_scope_and_symlink_pointer_fail_closed(tmp_path):
    store = m.Store(str(tmp_path / "app.sock"), tmp_path / "state")
    store.path.write_text("broken")
    store.path.chmod(0o600)
    with pytest.raises(m.Refused, match="Corrupt"):
        m.Coordinator(store, None, None).run("status", {})
    store.save({"version": 1, "endpoint": "another-socket"})
    with pytest.raises(m.Refused, match="scope"):
        m.Coordinator(store, None, None).run("status", {})
    store.path.unlink()
    store.path.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(m.Refused, match="private"):
        m.Coordinator(store, None, None).run("status", {})


def _locked_increment(directory, endpoint):
    store = m.Store(endpoint, directory)
    for _ in range(8):
        with store.locked() as s:
            s["counter"] = s.get("counter", 0) + 1
            store.save(s)


def test_guard_serializes_independent_processes_and_keeps_inode(tmp_path):
    store = m.Store(str(tmp_path / "app.sock"), tmp_path / "state")
    with store.locked() as s:
        store.save(s)
    inode = store.guard.stat().st_ino
    ctx = multiprocessing.get_context("fork")
    processes = [ctx.Process(target=_locked_increment, args=(store.directory, store.endpoint)) for _ in range(4)]
    for p in processes:
        p.start()
    for p in processes:
        p.join(10)
        assert p.exitcode == 0
    assert state_of(store)["counter"] == 32
    assert store.guard.stat().st_ino == inode
