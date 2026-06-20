#!/usr/bin/env python3
"""Backend regression tests for the per-section reviewed-tick.

Dependency-light (urllib only); spins an isolated hub on 127.0.0.1 with a temp WEBDIFF_DIR.
Run: python3 test_reviewed.py   (exit 0 = all pass)
"""
import json, os, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "serve_webdiff.py")

# A page carrying two live sections (s_a, s_b). s_ghost is deliberately NOT present, so the
# server must prune it (orphan prune via live-secid intersection).
PAGE = (
    '<html><body>'
    '<div class="annobar" data-section="A" data-secid="s_a" data-sechash="h1"></div>'
    '<div class="annobar" data-section="B" data-secid="s_b" data-sechash="h2"></div>'
    '</body></html>'
)


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def _req(method, url, body=None):
    r = urllib.request.Request(url, data=(body.encode() if body else None), method=method)
    if body:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None


def main() -> int:
    fails = []

    def check(name, cond):
        print(("PASS" if cond else "FAIL"), name)
        if not cond:
            fails.append(name)

    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "pages"))
    open(os.path.join(d, "pages", "p.html"), "w").write(PAGE)
    port = _free_port()
    srv = subprocess.Popen([sys.executable, SCRIPT, str(port), "127.0.0.1"],
                           env=dict(os.environ, WEBDIFF_DIR=d),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                _req("GET", base + "/pages"); break
            except Exception:
                time.sleep(0.1)

        check("initial reviewed empty", _req("GET", base + "/reviewed?id=p")[1] == {})

        _req("POST", base + "/review", json.dumps({"id": "p", "secid": "s_a", "hash": "h1", "reviewed": True}))
        check("review s_a persists with hash", _req("GET", base + "/reviewed?id=p")[1] == {"s_a": "h1"})

        # survives a submit + a clear (reviewed state is independent of annotations/submit)
        _req("POST", base + "/submit?id=p")
        check("reviewed survives submit", _req("GET", base + "/reviewed?id=p")[1] == {"s_a": "h1"})
        _req("POST", base + "/clear?id=p")
        check("reviewed survives clear", _req("GET", base + "/reviewed?id=p")[1] == {"s_a": "h1"})

        # toggling off removes exactly it
        _req("POST", base + "/review", json.dumps({"id": "p", "secid": "s_a", "hash": "h1", "reviewed": False}))
        check("toggle off removes s_a", _req("GET", base + "/reviewed?id=p")[1] == {})

        # orphan prune: a secid not present in the page is never stored
        _req("POST", base + "/review", json.dumps({"id": "p", "secid": "s_ghost", "hash": "x", "reviewed": True}))
        check("orphan secid pruned on write", "s_ghost" not in _req("GET", base + "/reviewed?id=p")[1])

        # bad payloads -> 400 (validate secid str/non-empty, reviewed bool, hash str when reviewed)
        check("bad: missing secid -> 400",
              _req("POST", base + "/review", json.dumps({"id": "p", "reviewed": True, "hash": "h"}))[0] == 400)
        check("bad: reviewed not bool -> 400",
              _req("POST", base + "/review", json.dumps({"id": "p", "secid": "s_a", "reviewed": "yes", "hash": "h"}))[0] == 400)
        check("bad: reviewed True without hash -> 400",
              _req("POST", base + "/review", json.dumps({"id": "p", "secid": "s_a", "reviewed": True}))[0] == 400)

        # stale detection is a client concern (hash mismatch) but the server stores the hash
        # it was told, so a regenerated section (new hash) shows old hash != live -> amber.
        _req("POST", base + "/review", json.dumps({"id": "p", "secid": "s_b", "hash": "OLD", "reviewed": True}))
        check("server stores the supplied hash verbatim (drives client stale check)",
              _req("GET", base + "/reviewed?id=p")[1].get("s_b") == "OLD")
    finally:
        srv.terminate(); srv.wait()

    print("\nRESULT:", "ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
