#!/usr/bin/env python3
"""Render test for mockup pages on the Atelier hub + the CSS kit.

Builds a self-contained mockup HTML that inlines the three kit stylesheets
(terminal / browser-frame / device) with an annobar, serves it as a hub page,
and asserts the framed elements render and there is no horizontal overflow at
390px or wide. Needs the .venv python (Playwright).
"""
import os, socket, subprocess, sys, tempfile, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SERVE = os.path.join(HERE, "serve_atelier.py")
KIT = os.path.join(HERE, "kit")
fails = []


def ck(n, c):
    print(("PASS" if c else "FAIL"), n)
    if not c:
        fails.append(n)


def build_page() -> str:
    css = "\n".join(open(os.path.join(KIT, f)).read() for f in
                    ("terminal.css", "browser-frame.css", "device.css"))
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>kit demo</title>
<style>body{{margin:0;background:#16161e;color:#c0caf5;font:15px sans-serif;padding:16px}}
.wrap{{max-width:1000px;margin:0 auto}} h2{{font-size:16px}}
{css}</style></head><body><div class="wrap">
<h2>Terminal</h2>
<div class="term"><div class="term-bar"><i></i><i></i><i></i><span class="term-title">zsh</span></div>
<pre class="term-body"><span class="t-prompt">~ &#10095;</span> <span class="t-cmd">cargo build</span>
<span class="t-err">error[E0382]</span>: borrow of moved value</pre></div>
<div class="annobar" data-section="1 · Terminal"></div>
<h2>Browser frame</h2>
<div class="bf"><div class="bf-bar"><i></i><i></i><i></i><div class="bf-url">https://example.com</div></div>
<div class="bf-view"><div style="padding:24px"><h1>Pricing</h1><p>Plans and tiers.</p></div></div></div>
<div class="annobar" data-section="2 · Site"></div>
<h2>Device</h2>
<div class="dev dev-phone"><div class="dev-screen"><div style="padding:18px"><h3>Mobile</h3><p>Responsive.</p></div></div></div>
<div class="annobar" data-section="3 · Phone"></div>
</div></body></html>"""


def main() -> int:
    from playwright.sync_api import sync_playwright
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "pages")); os.makedirs(os.path.join(d, "state"))
    open(os.path.join(d, "pages", "kit.html"), "w").write(build_page())
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
            b = p.chromium.launch()
            for w in (390, 1100):
                pg = b.new_page(viewport={"width": w, "height": 900})
                pg.goto(f"{base}/p/kit", wait_until="networkidle", timeout=30000); pg.wait_for_timeout(500)
                ck(f"@{w} terminal renders", pg.evaluate("()=>!!document.querySelector('.term .term-body')"))
                ck(f"@{w} browser-frame renders", pg.evaluate("()=>!!document.querySelector('.bf .bf-view')"))
                ck(f"@{w} device frame renders", pg.evaluate("()=>!!document.querySelector('.dev .dev-screen')"))
                ck(f"@{w} mockup annobars injected (runtime ran on authored HTML)",
                   pg.eval_on_selector_all(".annobar .add", "e=>e.length") == 3)
                ck(f"@{w} no overview map on a no-reviewable-section mockup (no 0/0 count)",
                   not pg.evaluate("()=>!!document.getElementById('wd-map')"))
                ov = pg.evaluate("()=>document.documentElement.scrollWidth-document.documentElement.clientWidth")
                ck(f"@{w} no horizontal overflow (ov={ov})", ov <= 2)
                pg.close()
            b.close()
    finally:
        srv.terminate(); srv.wait()
    print("\nRESULT:", "ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
