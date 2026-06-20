#!/usr/bin/env python3
"""DOM test for the 'Claude is working' overlay (Atelier).

Asserts the overlay sits BELOW the tab bar (so tabs stay clickable while a page
works) and that it re-shows on page LOAD when the page is still in the working
state (so switching tabs away and back keeps the overlay until Claude clears it).
Needs the .venv python (Playwright).
"""
import json, os, socket, subprocess, sys, tempfile, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SERVE = os.path.join(HERE, "serve_atelier.py")
fails = []


def ck(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c:
        fails.append(n)


def req(method, url, body=None):
    r = urllib.request.Request(url, data=(body.encode() if body else None), method=method)
    if body:
        r.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(r, timeout=10) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    from playwright.sync_api import sync_playwright
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "pages")); os.makedirs(os.path.join(d, "state"))
    # two pages so the tab bar has real tabs to switch between
    open(os.path.join(d, "pages", "p.html"), "w").write("<html><body><div class='wrap'>page p</div></body></html>")
    open(os.path.join(d, "pages", "q.html"), "w").write("<html><body><div class='wrap'>page q</div></body></html>")
    port = (lambda s: (s.bind(("127.0.0.1", 0)), s.getsockname()[1], s.close())[1])(socket.socket())
    srv = subprocess.Popen([sys.executable, SERVE, str(port), "127.0.0.1"],
                           env=dict(os.environ, ATELIER_DIR=d),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                req("GET", base + "/pages"); break
            except Exception:
                time.sleep(0.1)
        # drive page p into the working state: submit, then /wait consumes -> working
        req("POST", base + "/submit?id=p")
        req("GET", base + "/wait?ids=p&timeout=3")
        ck("state is working after consume", req("GET", base + "/submitted?id=p")["state"] == "working")
        with sync_playwright() as p:
            b = p.chromium.launch(); pg = b.new_page(viewport={"width": 900, "height": 800})
            pg.goto(f"{base}/p/p", wait_until="networkidle", timeout=30000); pg.wait_for_timeout(700)
            zwork = pg.evaluate("()=>parseInt(getComputedStyle(document.getElementById('wd-working')).zIndex)||0")
            ztabs = pg.evaluate("()=>parseInt(getComputedStyle(document.getElementById('wd-tabs')).zIndex)||0")
            ck(f"overlay below tab bar (overlay z={zwork} < tabs z={ztabs})", zwork < ztabs)
            ck("overlay visible on LOAD while working (no 3s gap)",
               pg.evaluate("()=>document.getElementById('wd-working').classList.contains('on')"))
            # the tab bar is above the overlay -> its tab links are hit-testable (clickable)
            ck("tab bar clickable above overlay",
               pg.evaluate("""()=>{var t=document.querySelector('#wd-tabs .tab');if(!t)return false;
                 var r=t.getBoundingClientRect();var el=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
                 return !!(el&&el.closest('#wd-tabs'));}"""))
            # clear -> idle -> reload -> overlay gone
            req("POST", base + "/clear?id=p")
            pg.goto(f"{base}/p/p", wait_until="networkidle", timeout=30000); pg.wait_for_timeout(700)
            ck("overlay gone on load once cleared/idle",
               not pg.evaluate("()=>document.getElementById('wd-working').classList.contains('on')"))
            b.close()
    finally:
        srv.terminate(); srv.wait()
    print("\nRESULT:", "ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
