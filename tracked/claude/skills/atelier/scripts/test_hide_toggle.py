#!/usr/bin/env python3
"""DOM test for the hide-annotation-chrome toggle (Atelier).

Generates a page, spins an isolated hub, and asserts the toggle hides all review
chrome (annobars + overview map + note button), keeps content + Submit visible,
persists across reload via localStorage, and toggles back. Needs the .venv python
(Playwright). Run: /home/raul/setforge/.venv/bin/python test_hide_toggle.py
"""
import json, os, socket, subprocess, sys, tempfile, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SERVE = os.path.join(HERE, "serve_atelier.py")
GEN = os.path.join(HERE, "gen_atelier.py")
fails = []


def ck(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c:
        fails.append(n)


def main() -> int:
    from playwright.sync_api import sync_playwright
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "pages")); os.makedirs(os.path.join(d, "state"))
    # a generated page guarantees annobars + an overview map exist to hide
    spec = {"title": "hide test", "repo": HERE, "range": "HEAD",
            "callouts": [{"html": "<b>ov</b>"}],
            "groups": [{"heading": "G", "blocks": [
                {"mode": "text", "content": "design sample", "label": "s", "why": "y"}]}]}
    sf = os.path.join(d, "_s.json"); open(sf, "w").write(json.dumps(spec))
    subprocess.run([sys.executable, GEN, sf, os.path.join(d, "pages", "h.html")], check=True, capture_output=True)

    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = subprocess.Popen([sys.executable, SERVE, str(port), "127.0.0.1"],
                           env=dict(os.environ, ATELIER_DIR=d),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(base + "/pages", timeout=5); break
            except Exception:
                time.sleep(0.1)
        with sync_playwright() as p:
            b = p.chromium.launch(); pg = b.new_page(viewport={"width": 900, "height": 900})
            pg.goto(f"{base}/p/h", wait_until="networkidle", timeout=30000); pg.wait_for_timeout(700)
            vis = lambda sel: pg.evaluate(f"()=>[...document.querySelectorAll('{sel}')].some(e=>e.offsetParent!==null)")
            mapvis = lambda: pg.evaluate("()=>{var m=document.getElementById('wd-map');return !!(m&&m.offsetParent);}")
            ck("hide button present", pg.evaluate("()=>!!document.getElementById('wd-hide')"))
            ck("chrome visible initially", vis(".annobar") and mapvis())
            pg.evaluate("()=>document.getElementById('wd-hide').click()"); pg.wait_for_timeout(300)
            ck("hide -> annobars gone", not vis(".annobar"))
            ck("hide -> map gone", not mapvis())
            ck("hide -> note button gone", pg.evaluate("()=>{var m=document.getElementById('wd-master');return !(m&&m.offsetParent);}"))
            ck("hide -> content visible", pg.evaluate("()=>!!document.querySelector('.wrap')&&document.querySelector('.wrap').offsetHeight>0"))
            ck("hide -> Submit still usable", pg.evaluate("()=>{var s=document.getElementById('wd-submit');return !!(s&&s.offsetParent);}"))
            ck("label flips to Show", "Show annotations" in pg.evaluate("()=>document.getElementById('wd-hide').textContent"))
            ck("localStorage persisted", pg.evaluate("()=>localStorage.getItem('atelier-hide-anno')") == "1")
            pg.reload(wait_until="networkidle"); pg.wait_for_timeout(700)
            ck("persists across reload (still hidden)", not vis(".annobar"))
            pg.evaluate("()=>document.getElementById('wd-hide').click()"); pg.wait_for_timeout(300)
            ck("show -> annobars back", vis(".annobar"))
            b.close()
    finally:
        srv.terminate(); srv.wait()
    print("\nRESULT:", "ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
