#!/usr/bin/env python3
"""plan-review-atelier-hook.py — custom PreToolUse hook for ExitPlanMode.

Owns review-surface dispatch for plan review:
  • review-surface = atelier (default) AND the hub is reachable/startable →
    serve the plan as a atelier page (plan-file render; two-file compare for the
    previous-revision rollover), block on /wait?timeout=0, and map the captured
    annotations onto the ask/deny contract (deny-with-notes / ask-when-empty).
  • review-surface = revdiff, OR no browser/hub → delegate to the revdiff-planning
    plugin's own plan-review-hook.py (reused unmodified), passing stdin through.

Disable revdiff-planning's OWN ExitPlanMode hook (toggle the plugin off) so only
this hook fires — otherwise both review the plan and the ask/deny decisions race.

Hook contract (Claude Code):
  deny  → plain text on stderr + exit 2  (tool blocked; text shown as feedback)
  ask   → JSON on stdout + exit 0        (proceed to normal confirmation)

Env overrides (also used by the test harness; WEBDIFF_* are back-compat aliases for one cycle):
  REVIEW_SURFACE      atelier | revdiff   (default atelier; "webdiff" also accepted)
  ATELIER_HUB_URL     explicit hub base (e.g. http://127.0.0.1:8730); else derived
  ATELIER_DIR         hub pages/state root (default ~/.local/share/atelier)
  ATELIER_PORT        hub port (default 8730)
  REVDIFF_PLANNING_ROOT  override the revdiff-planning plugin root for fallback
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

# --- shared marker/snapshot security (ported verbatim from revdiff-planning) ---
MARKER_RE = re.compile(r"^\s*<!--\s*previous revision:\s*(.+?)\s*-->\s*$")
SNAPSHOT_PREFIX = "plan-rev-"
SCRIPTS = Path(__file__).resolve().parent


def trusted_snapshot(p: Path) -> Path | None:
    try:
        resolved = p.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not resolved.is_file() or not resolved.name.startswith(SNAPSHOT_PREFIX):
        return None
    try:
        resolved.relative_to(Path(tempfile.gettempdir()).resolve())
    except ValueError:
        return None
    return resolved


def make_response(decision: str, reason: str = "") -> None:
    if decision == "deny":
        print(reason, file=sys.stderr)
        sys.exit(2)
    resp = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision}}
    if reason:
        resp["hookSpecificOutput"]["permissionDecisionReason"] = reason
    print(json.dumps(resp, indent=2))
    sys.exit(0)


# ------------------------------- hub helpers -------------------------------
def _hub_base() -> str:
    explicit = os.environ.get("ATELIER_HUB_URL") or os.environ.get("WEBDIFF_HUB_URL")  # WEBDIFF_*: back-compat
    if explicit:
        return explicit.rstrip("/")
    port = os.environ.get("ATELIER_PORT") or os.environ.get("WEBDIFF_PORT", "8730")
    host = "127.0.0.1"
    try:
        out = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5).stdout.split()
        if out:
            host = out[0].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return f"http://{host}:{port}"


def _probe(base: str, timeout: float = 2.0) -> bool:
    try:
        urllib.request.urlopen(base + "/pages", timeout=timeout)
        return True
    except Exception:
        return False


def ensure_hub() -> str | None:
    """Return a reachable hub base URL, starting the hub once if needed (race-safe:
    a concurrent start that loses the port just means the winner is already up, so
    we re-probe). Returns None if the hub is neither reachable nor startable."""
    base = _hub_base()
    if _probe(base):
        return base
    serve = SCRIPTS / "serve_atelier.py"
    if not serve.exists():
        return None
    port = os.environ.get("ATELIER_PORT") or os.environ.get("WEBDIFF_PORT", "8730")
    try:
        subprocess.Popen(
            ["setsid", "nohup", sys.executable, str(serve), port],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, start_new_session=True, env={**os.environ})
    except OSError:
        pass
    for _ in range(40):  # ~8s for the listener (ours or a racing peer's) to bind
        if _probe(base):
            return base
        time.sleep(0.2)
    return None


def _get(base: str, path: str, timeout: float | None = None):
    r = urllib.request.Request(base + path, method="GET")
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _post(base: str, path: str):
    try:
        urllib.request.urlopen(urllib.request.Request(base + path, data=b"", method="POST"), timeout=10)
    except Exception:
        pass


def _pages_dir() -> Path:
    root = (os.environ.get("ATELIER_DIR") or os.environ.get("WEBDIFF_DIR")  # WEBDIFF_DIR: back-compat
            or os.path.expanduser("~/.local/share/atelier"))
    d = Path(root) / "pages"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _gen_page(spec: dict, out: Path) -> bool:
    gen = SCRIPTS / "gen_atelier.py"
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as sf:
        json.dump(spec, sf)
        spec_path = sf.name
    try:
        subprocess.run([sys.executable, str(gen), spec_path, str(out)],
                       check=True, capture_output=True, text=True)
        return True
    except (subprocess.CalledProcessError, OSError):
        return False
    finally:
        Path(spec_path).unlink(missing_ok=True)


def _build_spec(new_snap: Path, old_snap: Path | None) -> dict:
    repo = str(new_snap.parent)
    if old_snap is not None and old_snap.parent == new_snap.parent:
        blocks = [
            {"mode": "compare", "old": old_snap.name, "new": new_snap.name,
             "label": "Changes since your last review",
             "why": "Only what changed in this revision — review the delta first."},
            {"mode": "plan", "file": new_snap.name, "label": "Full plan",
             "why": "The complete current plan, for context."},
        ]
    else:
        blocks = [{"mode": "plan", "file": new_snap.name, "label": "Plan",
                   "why": "Review the plan; annotate any section, then Submit."}]
    return {"title": "Plan review", "repo": repo,
            "sub": "Plan review — annotate any section; Submit resumes the agent.",
            "groups": [{"heading": "Plan review", "blocks": blocks}]}


def _is_html(content: str) -> bool:
    """A plan authored as a full HTML document is served VERBATIM as a mockup page
    (the hub injects the annotation runtime on GET /p/), instead of the markdown
    plan-render which html-escapes everything (so HTML never rendered as graphics).
    Detected by a leading ``<!doctype html>`` / ``<html`` after optional whitespace."""
    head = content.lstrip()[:256].lower()
    return head.startswith("<!doctype html") or head.startswith("<html")


def atelier_review(plan_content: str, base: str) -> None:
    """Serve the plan, block until Submit, then deny-with-notes or ask-when-empty.
    Exits via make_response. The page is always /close'd (archived) on the way out."""
    first_line, sep, rest = plan_content.partition("\n")
    m = MARKER_RE.match(first_line)
    old_snap = trusted_snapshot(Path(m.group(1))) if m else None
    stripped = rest if (m and sep) else (("" if m else plan_content))

    with tempfile.NamedTemporaryFile("w", suffix=".md", prefix=SNAPSHOT_PREFIX, delete=False) as tmp:
        tmp.write(stripped)
        new_snap = Path(tmp.name)

    page_id = "plan-" + new_snap.stem
    page_file = _pages_dir() / (page_id + ".html")
    if _is_html(stripped):
        # HTML plan: serve verbatim as a mockup page; the hub injects the annotation
        # runtime on serve, so author per-section `annobar` divs for inline notes.
        # (Markdown rollover-compare does not apply; the HTML page stands alone.)
        page_file.write_text(stripped, encoding="utf-8")
    elif not _gen_page(_build_spec(new_snap, old_snap), page_file):
        new_snap.unlink(missing_ok=True)
        make_response("ask", "could not generate the plan page; plan not reviewed this round")

    _post(base, "/rearm?id=" + page_id)            # clear any stale flag before arming
    md = ""
    try:
        while True:                                 # /wait?timeout=0 blocks; loop defends against a null
            w = _get(base, "/wait?ids=" + page_id + "&timeout=0")
            if w.get("id"):
                md = (w.get("markdown") or "").strip()
                break
    except Exception as exc:
        page_file.unlink(missing_ok=True)
        new_snap.unlink(missing_ok=True)
        make_response("ask", f"atelier plan review failed ({exc}); plan not reviewed this round")
    finally:
        _post(base, "/close?id=" + page_id)         # trap: always archive the page out of the tabs
        page_file.unlink(missing_ok=True)

    if md:
        # keep new_snap for the next revision's compare baseline; drop the consumed old one
        if old_snap is not None:
            old_snap.unlink(missing_ok=True)
        make_response(
            "deny",
            "user reviewed the plan in atelier and added annotations (revdiff markdown "
            "below; plan notes are section/file-level, i.e. '## <section> (file-level)'). "
            "Each carries the user's feedback.\n\n"
            f"{md}\n\n"
            "Address each annotation, then call ExitPlanMode again.\n\n"
            "IMPORTANT: the very first line of your revised plan MUST be exactly the marker "
            "below — do NOT substitute any other plan-rev-*.md path from earlier in the "
            "conversation (older markers belong to unrelated tasks and would diff against the "
            "wrong baseline).\n"
            f"<!-- previous revision: {new_snap} -->\n"
            "This lets atelier show only what changed in your revision.")
    else:
        new_snap.unlink(missing_ok=True)
        if old_snap is not None:
            old_snap.unlink(missing_ok=True)
        make_response("ask", "plan reviewed in atelier, no annotations")


def _revdiff_planning_root() -> Path | None:
    if os.environ.get("REVDIFF_PLANNING_ROOT"):
        return Path(os.environ["REVDIFF_PLANNING_ROOT"])
    cands = sorted(glob.glob(os.path.expanduser(
        "~/.claude/plugins/cache/revdiff/revdiff-planning/*")))
    if cands:
        return Path(cands[-1])
    mk = Path(os.path.expanduser(
        "~/.claude/plugins/marketplaces/revdiff/plugins/revdiff-planning"))
    return mk if mk.exists() else None


def delegate_to_revdiff(raw: str) -> None:
    """Hand the original event to revdiff-planning's hook, unmodified, and propagate
    its stdout/stderr/exit verbatim so the ask/deny contract is preserved."""
    root = _revdiff_planning_root()
    hook = root / "scripts" / "plan-review-hook.py" if root else None
    if hook is None or not hook.exists():
        make_response("ask", "no plan-review surface available (atelier hub down, revdiff-planning absent)")
    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(root)}
    try:
        r = subprocess.run([sys.executable, str(hook)], input=raw,
                           capture_output=True, text=True, env=env, timeout=345600)
    except (OSError, subprocess.SubprocessError) as exc:
        make_response("ask", f"revdiff plan review failed to start ({exc})")
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    sys.exit(r.returncode)


def main() -> None:
    raw = sys.stdin.read()
    plan = ""
    if raw.strip():
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            event = {}
        # event / tool_input may be any JSON shape — guard so a list/scalar can't raise
        # AttributeError and crash past the ask/deny contract.
        ti = event.get("tool_input", {}) if isinstance(event, dict) else {}
        plan = ti.get("plan", "") if isinstance(ti, dict) else ""
    if not plan:
        make_response("ask", "no plan content in hook event")

    surface = (os.environ.get("REVIEW_SURFACE") or "atelier").strip().lower()
    if surface != "revdiff":
        base = ensure_hub()
        if base is not None:
            atelier_review(plan, base)             # exits via make_response
        # hub unreachable/unstartable → fall through to the revdiff fallback
    delegate_to_revdiff(raw)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\r\033[K", end="")
        sys.exit(130)
