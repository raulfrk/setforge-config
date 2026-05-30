#!/usr/bin/env bash
# SessionStart hook: surface handoff beads from ~/handoff that match the
# directory the session started in, so resuming never needs to be typed.
#
# Local-only by design: the ~/handoff repo is a local concept. The hook is a
# safe no-op when bd is missing, ~/handoff is absent (it creates+inits it for
# next time), or nothing matches. It NEVER claims anything — it only injects
# context pointing at the `pickup` skill, which runs the resume gate.
#
# Matching rule: a handoff matches when its tagged working path is AT OR BELOW
# the session's start dir ($CLAUDE_PROJECT_DIR) using a true path-boundary test
# (so /foo/bar never matches /foo/barbaz). A monorepo root therefore surfaces
# every sub-project handoff beneath it; a sub-project dir surfaces only its own.
set -uo pipefail

HANDOFF_DIR="${HANDOFF_DIR:-$HOME/handoff}"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$PWD}"

# bd required; no-op if absent.
command -v bd >/dev/null 2>&1 || exit 0

# Create + init the handoff repo if missing, then exit (nothing to resume yet).
if [ ! -d "$HANDOFF_DIR" ]; then
  mkdir -p "$HANDOFF_DIR" 2>/dev/null || exit 0
  ( cd "$HANDOFF_DIR" && bd init --stealth >/dev/null 2>&1 ) || true
  exit 0
fi

# Collect open handoffs as JSON and do robust parsing + matching in python.
# python emits the SessionStart hook JSON when there are matches, else nothing.
result="$(cd "$HANDOFF_DIR" && bd list --status open --json 2>/dev/null \
  | PROJECT_DIR="$PROJECT_DIR" python3 -c '
import json, os, re, sys

project = os.environ["PROJECT_DIR"]

def norm(p):
    return os.path.realpath(os.path.expanduser(p)) if p else ""

def at_or_below(tagged, base):
    # tagged path is the base itself or strictly inside it (boundary-safe).
    t, b = norm(tagged), norm(base)
    return bool(t) and bool(b) and (t == b or t.startswith(b + os.sep))

def tagged_path(item):
    # Prefer an explicit "Workdir: <path>" line in the description; fall back
    # to the path in the title format "Handoff: <name> (<path>)".
    desc = item.get("description") or ""
    for line in desc.splitlines():
        m = re.match(r"\s*Workdir:\s*(.+?)\s*$", line)
        if m:
            return m.group(1)
    m = re.search(r"\(([^()]+)\)\s*$", item.get("title") or "")
    return m.group(1) if m else ""

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
items = data if isinstance(data, list) else next(
    (v for v in data.values() if isinstance(v, list)), [])

matched = []
for it in items:
    # Defensive: bd list --status open can include closed beads in JSON mode,
    # so filter status ourselves.
    if (it.get("status") or "").lower() == "closed":
        continue
    if at_or_below(tagged_path(it), project):
        matched.append(it)

if not matched:
    sys.exit(0)

lines = ["Open handoff(s) match this directory — invoke the `pickup` skill to resume:"]
for it in matched:
    lines.append(f"  - {it.get(\"id\")}: {it.get(\"title\")}")
if len(matched) > 1:
    lines.append("Multiple matched (monorepo root); pickup will let you choose one or several.")

out = {"hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "\n".join(lines),
}}
print(json.dumps(out))
')" || exit 0

[ -n "$result" ] && printf '%s\n' "$result"
exit 0
