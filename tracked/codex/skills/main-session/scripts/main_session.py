#!/usr/bin/env python3
"""Host-local main-session coordination. No daemon; native Codex owns execution."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import struct
import tempfile
import time
import uuid


class Refused(RuntimeError):
    pass


class RpcError(Refused):
    """A definitive RPC rejection, as opposed to a lost/uncertain response."""
    def __init__(self, error):
        self.error = error
        super().__init__(json.dumps(error))


class Native:
    def __init__(self, endpoint):
        # websocket-client is already provided by this host's Python environment.
        import websocket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(15)
        sock.connect(endpoint)
        pid, uid, _ = struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != os.getuid():
            sock.close()
            raise Refused("App server peer belongs to another user")
        start = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
        self.ws = websocket.create_connection("ws://localhost/", socket=sock, timeout=15)
        self.seq = 0
        self.notifications = []
        init = self.rpc("initialize", {"clientInfo": {"name": "main_session", "version": "1"},
                                       "capabilities": {"experimentalApi": True}})
        self.identity = {"pid": pid, "uid": uid, "start": start, "codex_home": init["codexHome"]}
        self.ws.send(json.dumps({"method": "initialized"}))

    def close(self):
        self.ws.close()

    def rpc(self, method, params):
        self.seq += 1
        self.ws.send(json.dumps({"id": self.seq, "method": method, "params": params}))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            reply = json.loads(self.ws.recv())
            if "method" in reply:
                self.notifications.append(reply)
            if reply.get("id") == self.seq:
                if "error" in reply:
                    raise RpcError(reply["error"])
                return reply["result"]
        raise TimeoutError(f"Uncertain result from {method}; do not retry blindly")

    def pages(self, method, params):
        cursor = None
        while True:
            page = self.rpc(method, dict(params, limit=100, cursor=cursor))
            yield from page["data"]
            cursor = page.get("nextCursor")
            if not cursor:
                break

    def read(self, tid, turns=False):
        return self.rpc("thread/read", {"threadId": tid, "includeTurns": turns})["thread"]

    def loaded(self):
        return set(self.pages("thread/loaded/list", {}))

    def items(self, tid):
        return list(self.pages("thread/items/list", {"threadId": tid}))

    def turns(self, tid):
        return list(self.pages("thread/turns/list", {"threadId": tid}))

    def deliver(self, tid, text, message_id):
        state = self.read(tid)["status"]["type"]
        if state not in ("active", "idle"):
            raise Refused("Recipient is not healthy and loaded")
        # Persisted history can contain old unfinished turns. Native turn pages
        # are newest first; only an active recipient needs a steering precondition.
        running = ([t for t in self.turns(tid) if t["status"] == "inProgress"]
                   if state == "active" else [])
        if state == "active" and not running:
            raise Refused("Cannot identify recipient's active turn")
        params = {"threadId": tid, "input": [{"type": "text", "text": text}],
                  "clientUserMessageId": message_id}
        if running:
            params["expectedTurnId"] = running[0]["id"]
            return self.rpc("turn/steer", params)
        # Never cold-resume an independent recipient or change its settings.
        if tid not in self.loaded():
            raise Refused("Recipient is not loaded; ask its owner to resume it")
        return self.rpc("turn/start", params)


def private_path(path, directory=False):
    s = path.lstat()
    if (s.st_uid != os.getuid() or stat.S_ISLNK(s.st_mode)
            or (s.st_mode & 0o077) or
            (directory and not stat.S_ISDIR(s.st_mode)) or
            (not directory and not stat.S_ISREG(s.st_mode))):
        raise Refused(f"Expected private user-owned {'directory' if directory else 'file'}: {path}")


class Store:
    def __init__(self, endpoint, directory=None):
        self.endpoint = os.path.abspath(endpoint)  # stable configured endpoint, not inode
        digest = hashlib.sha256(self.endpoint.encode()).hexdigest()[:20]
        self.directory = Path(directory) if directory else Path.home() / ".codex/main-session" / digest
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        private_path(self.directory, True)
        self.path = self.directory / "owner.json"
        self.guard = self.directory / "guard.lock"  # never replace/unlink this inode

    @contextlib.contextmanager
    def locked(self):
        fd = os.open(self.guard, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            private_path(self.guard)
            deadline = time.monotonic() + 45
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise Refused("Coordinator is busy; no operation was admitted")
                    time.sleep(0.05)  # bounded file-lock backoff, not an agent wait
            if self.path.exists() or self.path.is_symlink():
                private_path(self.path)
                try:
                    state = json.loads(self.path.read_text())
                except (ValueError, OSError) as exc:
                    raise Refused("Corrupt owner pointer; preserve it for reconciliation") from exc
                if state.get("version") != 1 or state.get("endpoint") != self.endpoint:
                    raise Refused("Wrong pointer version/server scope")
            else:
                state = {"version": 1, "endpoint": self.endpoint, "enabled": True,
                         "owner": None, "generation": None, "phase": "empty",
                         "jobs": {}, "grants": {}, "actions": {}}
            yield state
        finally:
            os.close(fd)

    def save(self, state):
        fd, name = tempfile.mkstemp(prefix="owner-", dir=self.directory)
        try:
            with os.fdopen(fd, "w") as out:
                json.dump(state, out, indent=2)
                out.write("\n")
                out.flush()
                os.fsync(out.fileno())
            os.replace(name, self.path)
            dfd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        finally:
            if os.path.exists(name):
                os.unlink(name)


def token():
    return uuid.uuid4().hex


def pending(state):
    return [a for a in state["actions"].values() if a["status"] == "pending"]


def policy(result):
    return {k: result.get(k) for k in ("model", "modelProvider", "cwd", "approvalPolicy",
            "approvalsReviewer", "sandbox", "activePermissionProfile", "reasoningEffort")}


def root(native, tid):
    t = native.read(tid)
    if t.get("parentThreadId"):
        raise Refused("Only an independent root may become main or issue user requests")
    return t


def owner(state, caller, generation, ready=True):
    if not caller or caller != state["owner"] or generation != state["generation"]:
        raise Refused("Wrong owner/generation; reload status")
    if ready and (state["phase"] != "ready" or not state["enabled"]):
        raise Refused("Main is not ready to admit work")


class Coordinator:
    def __init__(self, store, native, caller, generation=None):
        self.store, self.native, self.caller, self.generation = store, native, caller, generation

    def eligible(self, state):
        if state.get("server") != self.native.identity:
            raise Refused("Server instance changed; ensure/reconcile ownership first")
        if state["owner"] not in self.native.loaded():
            raise Refused("Main is not loaded; ensure/reconcile it before admitting work")
        if root(self.native, state["owner"])["status"]["type"] not in ("idle", "active"):
            raise Refused("Main is not healthy; inspect it before admitting work")

    def ensure(self, state, activate=False):
        root(self.native, self.caller)
        if not state["enabled"]:
            if not activate:
                raise Refused("Main was stopped; explicit activate is required")
            state["enabled"] = True
            self.store.save(state)
        tid = state["owner"]
        loaded = self.native.loaded()
        same_server = state.get("server") == self.native.identity
        if state["phase"] == "ready" and tid in loaded and same_server:
            if root(self.native, tid)["status"]["type"] not in ("idle", "active"):
                raise Refused("Main is loaded but unhealthy; inspect it, do not replace it")
            return state
        if state["phase"] in ("creating", "resuming", "blocked", "draining"):
            raise Refused("Recovery is blocked/draining; reconcile the recorded operation")
        if state["phase"] == "booting" and tid in loaded and same_server:
            return state  # existing startup/reconciliation, do not dispatch twice
        if pending(state):
            raise Refused("Unresolved admitted action blocks recovery")
        if tid:
            # Use the same ID. A failed or uncertain resume never means 'missing'.
            state["phase"] = "resuming"
            self.store.save(state)
            try:
                result = self.native.rpc("thread/resume", {"threadId": tid, "excludeTurns": True})
            except RpcError as exc:
                # Exact observed native absence, never a timeout/permission/transport error.
                if exc.error != {"code": -32600, "message": f"no rollout found for thread id {tid}"}:
                    raise
                if any(not j["drained"] for j in state["jobs"].values()):
                    state["phase"] = "blocked"
                    self.store.save(state)
                    raise Refused("Missing root still owns undrained event handles; reconcile them first")
                state.update(owner=None, phase="empty", jobs={}, grants={}, actions={})
                self.store.save(state)
                return self.ensure(state)
            if result["thread"].get("parentThreadId") or policy(result) != state.get("policy"):
                state["phase"] = "blocked"
                self.store.save(state)
                raise Refused("Resume settings differ; no work started; reconcile policy")
            state.update(phase="booting", server=self.native.identity)
            self.store.save(state)
        else:
            state.update(phase="creating", generation=token())
            self.store.save(state)  # unknown creation result must never be retried
            script = str(Path(__file__).resolve())
            result = self.native.rpc("thread/start", {
                "model": "gpt-6.1-sol", "allowProviderModelFallback": False,
                "cwd": root(self.native, self.caller)["cwd"],
                "config": {"features.multi_agent_v2.enabled": True,
                           "features.multi_agent_v2.tool_namespace": "collaboration",
                           "features.sleep_tool.enabled": True,
                           "features.sleep_tool.mode": "always_on"},
                "developerInstructions": (
                    "You coordinate the user's main-session workflow on this app server. "
                    f"Read {Path(script).parents[1] / 'SKILL.md'} before work. "
                    "The user explicitly requests native event subagents. Use GPT-6.1 Sol. "
                    "Observe/report by default; guidance needs recorded user authorisation. "
                    "Reconcile existing jobs, then mark ready. Keep your turn open with "
                    "native waits while children run. Do not edit global runtime settings.")})
            if result["model"] != "gpt-6.1-sol" or result["thread"].get("parentThreadId"):
                raise Refused("Creation returned unexpected root/model; pointer stays blocked")
            state.update(owner=result["thread"]["id"], policy=policy(result), phase="booting",
                         server=self.native.identity)
            self.store.save(state)  # BEFORE any bootstrap turn, same connection
        # Persist a startup receipt before dispatch. Crashes/lost replies remain visible.
        aid = token()
        state["boot_action"] = aid
        state["actions"][aid] = {"kind": "boot", "status": "pending",
                                  "generation": state["generation"], "target": state["owner"]}
        self.store.save(state)
        text = (f"MAIN_BOOT {aid}\nYou are the designated main, generation {state['generation']}. "
                f"Coordinator socket={self.store.endpoint} state-dir={self.store.directory}. "
                "Load main-session. Reconcile native history/children with the pointer, "
                "mark ready with the helper, then await requested events. "
                "No unsolicited messages to independent sessions.")
        try:
            # Fresh metadata has no readable turn history until the first turn.
            if tid:
                receipt = self.native.deliver(state["owner"], text, aid)
            else:
                receipt = self.native.rpc("turn/start", {"threadId": state["owner"],
                    "input": [{"type": "text", "text": text}], "clientUserMessageId": aid})
        except RpcError as exc:
            state["actions"][aid].update(status="failed", error=str(exc))
            state["phase"] = "blocked"
            self.store.save(state)
            raise
        state["actions"][aid].update(status="sent", receipt=receipt)
        self.store.save(state)
        return state

    def activities(self, state):
        entries = self.native.items(state["owner"])
        return [x["item"] for x in entries if x["item"]["type"] == "subAgentActivity"]

    def bind(self, state, job_id):
        job = state["jobs"][job_id]
        ids = {a["agentThreadId"] for a in self.activities(state)
               if a["kind"] == "started" and a["agentPath"] == job["path"]}
        if len(ids) != 1:
            raise Refused("No unique native child receipt yet; never respawn blindly")
        child_id = ids.pop()
        if self.native.read(child_id).get("parentThreadId") != state["owner"]:
            raise Refused("Child ancestry mismatch")
        if job.get("child") and job["child"] != child_id:
            raise Refused("Child changed for an existing job")
        job["child"] = child_id
        self.store.save(state)
        return job

    def cancel(self, state, job_id):
        job = state["jobs"][job_id]
        job["active"] = False  # cancellation closes admission BEFORE interrupt
        self.store.save(state)
        if not job.get("child"):
            self.bind(state, job_id)  # a spawn reply may have been lost
        child = self.native.read(job["child"], True)
        if child.get("parentThreadId") != state["owner"]:
            raise Refused("Refusing to interrupt a thread outside owned ancestry")
        for turn in child.get("turns", []):
            if turn["status"] == "inProgress":
                self.native.rpc("turn/interrupt", {"threadId": child["id"], "turnId": turn["id"]})
        job["drained"] = True
        self.store.save(state)
        return job

    def run(self, command, data):
        with self.store.locked() as s:
            if command == "status":
                return s
            if command == "claim":
                if s["owner"] == self.caller and s["phase"] == "ready":
                    self.eligible(s)
                    return s
                if (s["owner"] or s["phase"] != "empty" or pending(s)
                        or s["jobs"] or s["grants"]):
                    raise Refused("An owner or unresolved work already exists; drain/release before claiming")
                if self.caller not in self.native.loaded():
                    raise Refused("This session must already be loaded; claim never cold-resumes it")
                if root(self.native, self.caller)["status"]["type"] not in ("idle", "active"):
                    raise Refused("This session is not healthy")
                # Metadata-only warm resume returns effective policy without overrides,
                # new turns, or changes to this live conversation's runtime settings.
                result = self.native.rpc("thread/resume", {"threadId": self.caller, "excludeTurns": True})
                if result["thread"]["id"] != self.caller:
                    raise Refused("Unexpected session; ownership was not changed")
                previous = {x["item"]["agentThreadId"] for x in self.native.items(self.caller)
                            if x["item"].get("type") == "subAgentActivity"
                            and x["item"].get("kind") == "started"}
                s.update(enabled=True, owner=self.caller, generation=token(), phase="ready",
                         server=self.native.identity, policy=policy(result), prior_children=sorted(previous))
                self.eligible(s)
                self.store.save(s)
                return s
            if command in ("ensure", "activate"):
                return self.ensure(s, command == "activate")
            if command == "discover":
                return [t for tid in sorted(self.native.loaded())
                        if not (t := self.native.read(tid)).get("parentThreadId")]
            if command == "read":
                return self.native.read(data["thread"], True)
            if command == "request":
                self.ensure(s)
                aid = token()
                text = f"MAIN_REQUEST {aid} from {self.caller}\n" + data["text"]
                s["actions"][aid] = {"kind": "request", "status": "pending",
                    "generation": s["generation"], "target": s["owner"],
                    "source": self.caller}
                self.store.save(s)
                try:
                    result = self.native.deliver(s["owner"], text, aid)
                except RpcError as exc:
                    s["actions"][aid].update(status="failed", error=str(exc))
                    self.store.save(s)
                    raise
                s["actions"][aid].update(status="sent", receipt=result)
                self.store.save(s)
                return {"main": s["owner"], "phase": s["phase"], "request": aid, "receipt": result}
            if command == "validate":
                a = s["actions"][data["action"]]
                if (a["kind"] != "guidance" or a["target"] != self.caller or
                        a["generation"] != s["generation"] or s["phase"] != "ready" or
                        not s["enabled"] or a["status"] not in ("pending", "sent")):
                    raise Refused("Stale or ineligible guidance")
                grant = s["grants"].get(a["grant"])
                job = s["jobs"].get(a.get("job"))
                if not grant or not grant["active"] or (a.get("job") and (not job or not job["active"])):
                    raise Refused("Guidance cancelled/revoked")
                self.eligible(s)
                return dict(a, permission=grant)
            owner(s, self.caller, self.generation, ready=command not in
                  ("ready", "bind", "cancel", "abandon", "stop", "release", "settle"))
            if command not in ("stop", "release", "settle"):
                self.eligible(s)
            if command == "ready":
                if s["phase"] != "booting" or pending(s):
                    raise Refused("Startup has unresolved actions; inspect history and settle receipts first")
                for jid, job in s["jobs"].items():
                    if not job.get("child") and not job["drained"]:
                        self.bind(s, jid)
                activities = self.activities(s)
                known = {j["child"] for j in s["jobs"].values() if j.get("child")}
                known.update(s.get("prior_children", []))
                if any(a["kind"] == "started" and a["agentThreadId"] not in known for a in activities):
                    raise Refused("Unregistered native child; reconcile history before becoming ready")
                for job in s["jobs"].values():
                    if any(a["kind"] == "completed" and a["agentThreadId"] == job.get("child") for a in activities):
                        job["drained"] = True
                s["phase"] = "ready"
            elif command == "register":
                if any(j["request"] == data["request"] for j in s["jobs"].values()):
                    raise Refused("Request already registered; reuse its existing event handle")
                jid = token()
                s["jobs"][jid] = {"request": data["request"], "path": "/root/event_" + jid,
                    "generation": s["generation"], "active": True, "child": None, "drained": False}
                self.store.save(s)
                return {"job": jid, **s["jobs"][jid]}
            elif command == "bind":
                return self.bind(s, data["job"])
            elif command == "cancel":
                return self.cancel(s, data["job"])
            elif command == "abandon":
                job = s["jobs"][data["job"]]
                if job.get("child") or any(a["agentPath"] == job["path"] for a in self.activities(s)):
                    raise Refused("Native child exists; use cancel")
                if not data.get("evidence"):
                    raise Refused("Need history evidence that this reservation never spawned")
                job.update(active=False, drained=True, evidence=data["evidence"])
            elif command == "grant":
                root(self.native, data["target"])
                gid = token()
                s["grants"][gid] = {"target": data["target"], "scope": data["scope"],
                    "authorisation": data["authorisation"], "active": True}
                self.store.save(s)
                return {"grant": gid, **s["grants"][gid]}
            elif command == "revoke":
                s["grants"][data["grant"]]["active"] = False
            elif command == "admit":
                job = s["jobs"].get(data.get("job"))
                if data.get("job") and (not job or not job["active"] or not job.get("child")):
                    raise Refused("Inactive/unbound event cannot admit actions")
                if data["kind"] == "guidance":
                    grant = s["grants"].get(data.get("grant"))
                    if not grant or not grant["active"] or grant["target"] != data["target"]:
                        raise Refused("No active user-authorised guidance grant for this target")
                    root(self.native, data["target"])
                elif data["kind"] != "effect" or not data.get("authorisation"):
                    raise Refused("External effects need an explicit user authorisation reference")
                # Caller supplies a stable deduplication key from event/report identity.
                key = data["key"]
                matches = [(k, a) for k, a in s["actions"].items() if a.get("key") == key]
                if matches:
                    raise Refused(f"Action already admitted: {matches[0][0]}; inspect its receipt")
                aid = token()
                s["actions"][aid] = dict(data, status="pending", generation=s["generation"])
                self.store.save(s)
                return {"action": aid, **s["actions"][aid]}
            elif command == "dispatch":
                a = s["actions"][data["action"]]
                if a["status"] != "pending" or a.get("dispatched") or a["kind"] != "effect":
                    raise Refused("External effect is not eligible for first dispatch")
                if a.get("job") and not s["jobs"][a["job"]]["active"]:
                    raise Refused("Event cancelled before dispatch")
                a["dispatched"] = True
            elif command == "send":
                a = s["actions"][data["action"]]
                if a["status"] != "pending" or a["kind"] != "guidance" or a.get("dispatched"):
                    raise Refused("Action is not eligible for its first dispatch")
                if not s["grants"][a["grant"]]["active"] or (
                        a.get("job") and not s["jobs"][a["job"]]["active"]):
                    raise Refused("Guidance cancelled/revoked before dispatch")
                a["dispatched"] = True
                self.store.save(s)  # lost result remains pending; no second send
                text = f"MAIN_GUIDANCE {data['action']}\n" + a["text"]
                try:
                    result = self.native.deliver(a["target"], text, data["action"])
                except RpcError as exc:
                    a.update(status="failed", error=str(exc))
                    self.store.save(s)
                    raise
                a.update(status="sent", receipt=result)
            elif command == "settle":
                a = s["actions"][data["action"]]
                if a["generation"] != s["generation"] or a["status"] != "pending":
                    raise Refused("Not an unresolved current-generation action")
                if data["status"] not in ("sent", "failed") or not data.get("evidence"):
                    raise Refused("Settlement needs positive receipt/history/effect evidence; silence is insufficient")
                a.update(status=data["status"], evidence=data["evidence"])
            elif command == "stop":
                s.update(enabled=False, phase="draining")
                self.store.save(s)
                self.eligible(s)  # disable lookup first, then prove the interrupt target
                for jid in s["jobs"]:
                    if not s["jobs"][jid]["drained"]:
                        self.cancel(s, jid)
                return {"state": s, "unresolved_actions": pending(s)}
            elif command == "release":
                if s["phase"] != "draining" or pending(s) or any(not j["drained"] for j in s["jobs"].values()):
                    raise Refused("Drain owned children/actions before release")
                s.update(owner=None, generation=None, phase="empty", jobs={}, grants={}, actions={})
                # enabled remains false: lookup cannot undo a deliberate stop.
            else:
                raise Refused("Unknown command")
            self.store.save(s)
            return s


COMMANDS = ("status", "claim", "ensure", "activate", "ready", "request", "discover", "read",
            "register", "bind", "cancel", "abandon", "grant", "revoke", "admit", "dispatch", "send",
            "settle", "validate", "stop", "release")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", default=str(Path.home() / ".codex/app-server-control/app-server-control.sock"))
    parser.add_argument("--state-dir")
    parser.add_argument("--caller", default=os.environ.get("CODEX_THREAD_ID"))
    parser.add_argument("--generation")
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--data", type=Path, help="JSON payload file (never shell-interpolate message text)")
    args = parser.parse_args()
    native = None
    try:
        store = Store(args.socket, args.state_dir)
        data = json.loads(args.data.read_text()) if args.data else {}
        if args.command != "status":
            if not args.caller:
                raise Refused("Supply the actual caller thread ID")
            native = Native(store.endpoint)
        print(json.dumps(Coordinator(store, native, args.caller, args.generation).run(args.command, data), indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc), "instruction": "Inspect status and native history; do not blindly retry uncertain operations"}))
        return 1
    finally:
        if native:
            native.close()


if __name__ == "__main__":
    raise SystemExit(main())
