#!/usr/bin/env python3
"""Backend regression tests for the submit tri-state (idle -> submitted -> working -> idle).

Dependency-light (urllib only); spins an isolated hub on 127.0.0.1 with a temp ATELIER_DIR.
Run: python3 test_tristate.py   (exit 0 = all pass)
"""
import json, os, socket, subprocess, sys, tempfile, time, urllib.request

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "serve_atelier.py")


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def _req(method, url, body=None):
    r = urllib.request.Request(url, data=(body.encode() if body else None), method=method)
    if body:
        r.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(r, timeout=10) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    fails = []

    def check(name, cond):
        print(("PASS" if cond else "FAIL"), name)
        if not cond:
            fails.append(name)

    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "pages"))
    open(os.path.join(d, "pages", "p.html"), "w").write("<html><body>hi</body></html>")
    port = _free_port()
    srv = subprocess.Popen([sys.executable, SCRIPT, str(port), "127.0.0.1"],
                           env=dict(os.environ, ATELIER_DIR=d),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                _req("GET", base + "/pages"); break
            except Exception:
                time.sleep(0.1)

        check("initial state idle", _req("GET", base + "/submitted?id=p")["state"] == "idle")
        _req("POST", base + "/submit?id=p")
        check("submit -> submitted", _req("GET", base + "/submitted?id=p")["state"] == "submitted")

        _req("POST", base + "/annotate", json.dumps({"id": "p", "section": "s", "text": "hello"}))
        w = _req("GET", base + "/wait?ids=p&timeout=3")
        check("wait returns id + note", w["id"] == "p" and any(a["text"] == "hello" for a in w["annotations"]))
        check("flicker-fix: state==working after consume (not idle)",
              _req("GET", base + "/submitted?id=p")["state"] == "working")
        check("annotations cleared on consume", _req("GET", base + "/annotations?id=p") == [])

        _req("POST", base + "/rearm?id=p")
        check("rearm while working -> idle", _req("GET", base + "/submitted?id=p")["state"] == "idle")

        _req("POST", base + "/submit?id=p")
        _req("POST", base + "/rearm?id=p")
        check("rearm does NOT drop a pending submit", _req("GET", base + "/submitted?id=p")["state"] == "submitted")

        _req("POST", base + "/annotate", json.dumps({"id": "p", "section": "s", "text": "x"}))
        _req("POST", base + "/clear?id=p")
        check("clear -> idle + wipes notes",
              _req("GET", base + "/submitted?id=p")["state"] == "idle" and _req("GET", base + "/annotations?id=p") == [])

        open(os.path.join(d, "state", "submit-p.json"), "w").write(json.dumps({"submitted": True}))
        check("legacy {submitted:true} -> submitted", _req("GET", base + "/submitted?id=p")["state"] == "submitted")
        open(os.path.join(d, "state", "submit-p.json"), "w").write(json.dumps({"submitted": False}))
        check("legacy {submitted:false} -> idle", _req("GET", base + "/submitted?id=p")["state"] == "idle")

        _req("POST", base + "/submit?id=p")
        s = _req("GET", base + "/submitted?id=p")
        check("submitted bool back-compat field", s.get("submitted") is True and s.get("state") == "submitted")
    finally:
        srv.terminate(); srv.wait()

    print("\nRESULT:", "ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
