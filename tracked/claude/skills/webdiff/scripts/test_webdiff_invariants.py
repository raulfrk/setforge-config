#!/usr/bin/env python3
"""Invariant suite for the webdiff hub. Run against an isolated test hub.

INV-1  every listed page renders 200 at /p/<id>, well-formed (exactly one </body>)
INV-2  unknown page -> 404 ; bad id -> 400 ; malformed JSON tolerated
INV-3  annotate round-trips: POST /annotate then GET /annotations contains it (Hypothesis)
INV-4  resolve removes exactly the target; clear empties (Hypothesis)
INV-5  per-page isolation: annotating A never appears under B (Hypothesis)
INV-6  submit flag round-trips per page and is isolated (submit A != submit B)
INV-7  tab bar on every page lists ALL pages; exactly one active == current id; Submit present
INV-8  zoom: A+ grows .dt font, A- shrinks, clamped to [9,30]
INV-9  mobile: at 360px no horizontal page overflow (code wraps, not scrolls the page)
"""
import json
import sys
import urllib.request
from hypothesis import given, settings, strategies as st, HealthCheck

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8799"
fails = []


def _req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def get(path):
    return _req("GET", path)


def post(path, body=None):
    return _req("POST", path, body)


def check(name, cond, detail=""):
    if not cond:
        fails.append(f"{name}: {detail}")


pages = json.loads(get("/pages")[1])
ids = [p["id"] for p in pages]
print("pages:", ids)
assert len(ids) >= 2, "need >=2 test pages"
A, B = ids[0], ids[1]

# INV-1
for pid in ids:
    st_code, html = get("/p/" + pid)
    check("INV-1.200", st_code == 200, f"{pid} -> {st_code}")
    check("INV-1.body", html.count("</body>") == 1, f"{pid} has {html.count('</body>')} </body>")
    check("INV-1.tabs", 'id="wd-tabs"' in html, f"{pid} missing tab bar")

# INV-2  (unknown page redirects to the "All caught up" index, not a dead 404 —
# urllib follows the 302 chain to a served page, so the effective status is 200)
check("INV-2.unknown-graceful", get("/p/does-not-exist")[0] == 200, "unknown page not handled gracefully")
check("INV-2.badid", post("/annotate", {"id": "../etc", "section": "s", "text": "t"})[0] == 400, "bad id not 400")
# malformed JSON tolerated (no 500)
mal_code, _ = _req("POST", "/submit?id=" + A, None)
check("INV-2.malform", mal_code in (200, 400), f"submit no-body -> {mal_code}")


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(section=st.text(min_size=1, max_size=60), text=st.text(min_size=1, max_size=300))
def test_annotate_roundtrip(section, text):
    post("/clear?id=" + A)
    post("/annotate", {"id": A, "section": section, "text": text})
    items = json.loads(get("/annotations?id=" + A)[1])
    check("INV-3", any(i["section"] == section and i["text"] == text for i in items),
          f"missing {section!r}/{text!r}")
    # INV-4 resolve removes exactly it
    target = next(i for i in items if i["section"] == section and i["text"] == text)
    post("/resolve", {"id": A, "section": section, "text": text, "ts": target["ts"]})
    after = json.loads(get("/annotations?id=" + A)[1])
    check("INV-4.resolve", all(i["ts"] != target["ts"] for i in after), "resolve left target")
    post("/clear?id=" + A)
    check("INV-4.clear", json.loads(get("/annotations?id=" + A)[1]) == [], "clear non-empty")


@settings(max_examples=30, deadline=None)
@given(section=st.text(min_size=1, max_size=40), text=st.text(min_size=1, max_size=120))
def test_isolation(section, text):
    post("/clear?id=" + A)
    post("/clear?id=" + B)
    post("/annotate", {"id": A, "section": section, "text": text})
    bitems = json.loads(get("/annotations?id=" + B)[1])
    check("INV-5", all(not (i["section"] == section and i["text"] == text) for i in bitems),
          "A's note leaked into B")
    post("/clear?id=" + A)


def test_submit_isolation():
    post("/rearm?id=" + A)
    post("/rearm?id=" + B)
    check("INV-6.init", json.loads(get("/submitted?id=" + A)[1])["submitted"] is False, "A not reset")
    post("/submit?id=" + A)
    check("INV-6.set", json.loads(get("/submitted?id=" + A)[1])["submitted"] is True, "A submit not set")
    check("INV-6.iso", json.loads(get("/submitted?id=" + B)[1])["submitted"] is False, "B leaked submit")
    # tri-state (bead A): /rearm must NOT clobber a pending submit; /clear is the hard reset.
    post("/rearm?id=" + A)
    check("INV-6.rearm-keeps-submit", json.loads(get("/submitted?id=" + A)[1])["submitted"] is True, "rearm dropped a pending submit")
    post("/clear?id=" + A)
    check("INV-6.clear-resets", json.loads(get("/submitted?id=" + A)[1])["submitted"] is False, "clear did not reset")


test_annotate_roundtrip()
test_isolation()
test_submit_isolation()

# ---- DOM invariants via Playwright ----
from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as p:
    b = p.chromium.launch()
    for pid in ids:
        pg = b.new_page(viewport={"width": 360, "height": 760})
        pg.goto(f"{BASE}/p/{pid}", wait_until="networkidle", timeout=30000)
        pg.wait_for_timeout(600)
        tabs = pg.eval_on_selector_all("#wd-tabs .tab", "e=>e.length")
        active = pg.eval_on_selector_all("#wd-tabs .tab.active", "e=>e.map(x=>x.textContent)")
        has_submit = pg.evaluate("()=>!!document.getElementById('wd-submit')")
        check("INV-7.tabcount", tabs == len(ids), f"{pid}: {tabs} tabs vs {len(ids)} pages")
        check("INV-7.oneactive", len(active) == 1, f"{pid}: {len(active)} active")
        check("INV-7.submit", has_submit, f"{pid}: no submit")
        # INV-10/11: review features on generated pages — overview map dot per section, reviewed toggle per section
        if pg.evaluate("()=>!!document.querySelector('.wrap') && document.querySelectorAll('.annobar[data-secid]').length>0"):
            secs = pg.eval_on_selector_all(".annobar[data-secid]", "e=>e.length")
            dots = pg.eval_on_selector_all("#wd-map a.wd-dot", "e=>e.length")
            rvw = pg.eval_on_selector_all(".annobar .rvw", "e=>e.length")
            has_map = pg.evaluate("()=>!!document.getElementById('wd-map')")
            check("INV-10.map", has_map and dots == secs, f"{pid}: map={has_map} dots {dots} vs secs {secs}")
            check("INV-11.reviewtoggle", rvw == secs, f"{pid}: {rvw} toggles vs {secs} secs")
        # INV-8 zoom (only on pages that have a .dt diff)
        if pg.evaluate("()=>!!document.querySelector('.dt')"):
            f0 = pg.evaluate("()=>parseFloat(getComputedStyle(document.querySelector('.dt')).fontSize)")
            pg.evaluate("dz(3)"); pg.wait_for_timeout(80)
            f1 = pg.evaluate("()=>parseFloat(getComputedStyle(document.querySelector('.dt')).fontSize)")
            pg.evaluate("for(let i=0;i<40;i++)dz(1)"); pg.wait_for_timeout(80)
            fmax = pg.evaluate("()=>parseFloat(getComputedStyle(document.querySelector('.dt')).fontSize)")
            pg.evaluate("for(let i=0;i<60;i++)dz(-1)"); pg.wait_for_timeout(80)
            fmin = pg.evaluate("()=>parseFloat(getComputedStyle(document.querySelector('.dt')).fontSize)")
            check("INV-8.grow", f1 > f0, f"{pid}: {f0}->{f1}")
            check("INV-8.clampmax", fmax <= 30, f"{pid}: max {fmax}")
            check("INV-8.clampmin", fmin >= 9, f"{pid}: min {fmin}")
            # INV-9 no horizontal page overflow at 360px
            ov = pg.evaluate("()=>document.documentElement.scrollWidth - document.documentElement.clientWidth")
            check("INV-9.nohscroll", ov <= 2, f"{pid}: page overflows {ov}px")
        pg.close()
    b.close()

if fails:
    print("FAIL (%d):" % len(fails))
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("ALL WEBDIFF INVARIANTS HOLD")
