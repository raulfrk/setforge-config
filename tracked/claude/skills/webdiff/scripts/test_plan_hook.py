#!/usr/bin/env python3
"""Logic tests for plan-review-webdiff-hook.py (bead 3.13.7).

Spins an isolated webdiff hub, drives the hook through stdin, simulates the user
(annotate/submit) against the served plan page, and asserts the ask/deny contract,
marker rollover, and revdiff-fallback delegation. The live 'only one hook fires'
+ real-ExitPlanMode check is manual (interactive) and done at the gate.

Run: python3 test_plan_hook.py   (exit 0 = all pass)
"""
import json, os, re, socket, subprocess, sys, tempfile, threading, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "plan-review-webdiff-hook.py")
SERVE = os.path.join(HERE, "serve_webdiff.py")
MARKER_RE = re.compile(r"<!--\s*previous revision:\s*(.+?)\s*-->")
fails = []


def ck(n, c, d=""):
    print(("PASS" if c else "FAIL"), n, d if not c else "")
    if not c:
        fails.append(n)


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def req(method, url, body=None):
    r = urllib.request.Request(url, data=(body.encode() if body else None), method=method)
    if body:
        r.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(r, timeout=10) as resp:
        return json.loads(resp.read().decode())


def run_hook(plan, env, simulate):
    """Run the hook with a plan; `simulate(base, page_id)` is called once the page
    appears to drive the user side. Returns (returncode, stdout, stderr)."""
    base = env["WEBDIFF_HUB_URL"]
    proc = subprocess.Popen([sys.executable, HOOK], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env={**os.environ, **env})
    out = {}

    def feed():
        out["r"] = proc.communicate(input=json.dumps({"tool_input": {"plan": plan}}))
    t = threading.Thread(target=feed); t.start()
    # wait for the plan page to appear, then simulate the user
    page_id = None
    for _ in range(100):
        try:
            pages = req("GET", base + "/pages")
            hit = [p for p in pages if p["id"].startswith("plan-plan-rev")]
            if hit:
                page_id = hit[-1]["id"]; break
        except Exception:
            pass
        time.sleep(0.1)
    if page_id:
        simulate(base, page_id)
    t.join(timeout=30)
    so, se = out.get("r", ("", ""))
    return proc.returncode, so, se, page_id


def main() -> int:
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "pages")); os.makedirs(os.path.join(d, "state"))
    port = free_port()
    srv = subprocess.Popen([sys.executable, SERVE, str(port), "127.0.0.1"],
                           env=dict(os.environ, WEBDIFF_DIR=d),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    env = {"WEBDIFF_HUB_URL": base, "WEBDIFF_DIR": d, "REVIEW_SURFACE": "webdiff"}
    try:
        for _ in range(50):
            try:
                req("GET", base + "/pages"); break
            except Exception:
                time.sleep(0.1)

        # (1) webdiff DENY: annotate then submit -> exit 2, stderr carries notes + marker
        def sim_annotate(b, pid):
            req("POST", b + "/annotate", json.dumps({"id": pid, "section": "1 · Plan",
                "text": "tighten step 2", "file": "plan"}))
            req("POST", b + "/submit?id=" + pid)
        rc, so, se, pid = run_hook("# Plan\n\nstep 1\nstep 2\n", env, sim_annotate)
        ck("deny: exit 2", rc == 2, f"rc={rc} se={se[:200]}")
        ck("deny: notes in stderr", "tighten step 2" in se)
        ck("deny: revdiff-format header in notes", "## " in se and "(file-level)" in se)
        ck("deny: marker emitted", bool(MARKER_RE.search(se)))
        ck("deny: page archived (not in tabs)", pid not in [p["id"] for p in req("GET", base + "/pages")])
        marker_path = MARKER_RE.search(se).group(1) if MARKER_RE.search(se) else None

        # (2) webdiff ASK: submit with no annotation -> exit 0, permissionDecision ask
        def sim_submit(b, pid):
            req("POST", b + "/submit?id=" + pid)
        rc, so, se, pid = run_hook("# Plan2\n\nbody\n", env, sim_submit)
        ck("ask: exit 0", rc == 0, f"rc={rc}")
        ck("ask: permissionDecision ask", '"permissionDecision": "ask"' in so)

        # (3) marker rollover: revise with the kept marker -> page has a compare block
        ck("rollover: marker snapshot exists", marker_path and os.path.exists(marker_path))
        captured = {}

        def sim_check_compare(b, pid):
            captured["html"] = open(os.path.join(d, "pages", pid + ".html"), encoding="utf-8").read()
            req("POST", b + "/submit?id=" + pid)
        plan2 = f"<!-- previous revision: {marker_path} -->\n# Plan\n\nstep 1\nstep 2 revised\n"
        rc, so, se, pid = run_hook(plan2, env, sim_check_compare)
        ck("rollover: exit 0 (empty submit)", rc == 0)
        ck("rollover: compare block rendered", "Changes since your last review" in captured.get("html", ""))

        # (4) revdiff fallback: REVIEW_SURFACE=revdiff -> delegate to a stub plugin hook
        stub = tempfile.mkdtemp(); os.makedirs(os.path.join(stub, "scripts"))
        open(os.path.join(stub, "scripts", "plan-review-hook.py"), "w").write(
            "import sys; sys.stdin.read(); print('STUB_ASK_OK'); sys.exit(0)\n")
        r = subprocess.run([sys.executable, HOOK], input=json.dumps({"tool_input": {"plan": "p"}}),
                           capture_output=True, text=True,
                           env={**os.environ, "REVIEW_SURFACE": "revdiff",
                                "REVDIFF_PLANNING_ROOT": stub})
        ck("fallback: delegates to revdiff-planning hook", "STUB_ASK_OK" in r.stdout and r.returncode == 0,
           f"rc={r.returncode} out={r.stdout[:120]} err={r.stderr[:120]}")

        # (5) empty plan -> ask (no surface work)
        r = subprocess.run([sys.executable, HOOK], input=json.dumps({"tool_input": {"plan": ""}}),
                           capture_output=True, text=True, env={**os.environ, **env})
        ck("empty plan: ask exit 0", r.returncode == 0 and '"ask"' in r.stdout)
    finally:
        srv.terminate(); srv.wait()

    print("\nRESULT:", "ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
