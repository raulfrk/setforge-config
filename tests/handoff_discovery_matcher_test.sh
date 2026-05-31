#!/usr/bin/env sh
# Acceptance test for the handoff-discovery multi-directory matcher.
#
# Exercises the REAL matcher: it extracts the inline `python3 -c '...'` block
# verbatim from tracked/claude/scripts/handoff-discovery.sh (no copy, no
# refactor of the hook) and pipes synthetic `bd list --json`-shaped JSON into
# it with PROJECT_DIR set, asserting on the emitted hookSpecificOutput.
#
# Verifies:
#   1. A handoff with TWO Workdir: lines matches when PROJECT_DIR is set to
#      EACH tagged dir in turn (multi-dir surfacing).
#   2. A legacy single-Workdir handoff matches its own dir and does NOT match
#      an unrelated sibling dir (no regression).
#
# Exit 0 on pass, non-zero on fail.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
HOOK="$SCRIPT_DIR/../tracked/claude/scripts/handoff-discovery.sh"

[ -f "$HOOK" ] || { echo "FAIL: hook not found at $HOOK" >&2; exit 1; }

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

MATCHER="$TMP/matcher.py"
# Extract the matcher: lines strictly between the `python3 -c '` opener and the
# closing `')"` line. This is the exact source the hook runs.
awk "/python3 -c '/{f=1;next} /^')\"/{f=0} f" "$HOOK" >"$MATCHER"

[ -s "$MATCHER" ] || { echo "FAIL: extracted matcher is empty" >&2; exit 1; }

ENGINE="/home/raul/setforge"
CONFIG="/home/raul/projects/setforge-config"
SIBLING="/home/raul/projects/borrowsmith"

# Synthetic bd list --json output.
MULTI_JSON='[
  {"id":"h-multi","title":"Handoff: multidir (/home/raul/setforge)","status":"open",
   "description":"Workdir: /home/raul/setforge\nWorkdir: /home/raul/projects/setforge-config\nProject: setforge\n"}
]'

LEGACY_JSON='[
  {"id":"h-legacy","title":"Handoff: legacy (/home/raul/projects/setforge-config)","status":"open",
   "description":"Workdir: /home/raul/projects/setforge-config\nProject: setforge-config\n"}
]'

run_matcher() {
  # $1 = PROJECT_DIR, stdin = JSON. Echoes matcher stdout.
  PROJECT_DIR="$1" python3 "$MATCHER"
}

emits_match() {
  # True (0) if output is non-empty AND has additionalContext.
  out=$(printf '%s' "$2" | run_matcher "$1")
  [ -n "$out" ] && printf '%s' "$out" | grep -q 'additionalContext'
}

fail() { echo "FAIL: $1" >&2; exit 1; }

# 1a. Multi-dir handoff matches from the engine dir.
emits_match "$ENGINE" "$MULTI_JSON" \
  || fail "multi-dir handoff did NOT match engine dir $ENGINE"
echo "PASS: multi-dir handoff matches engine dir"

# 1b. Multi-dir handoff matches from the config dir.
emits_match "$CONFIG" "$MULTI_JSON" \
  || fail "multi-dir handoff did NOT match config dir $CONFIG"
echo "PASS: multi-dir handoff matches config dir"

# 2a. Legacy single-Workdir handoff matches its own dir.
emits_match "$CONFIG" "$LEGACY_JSON" \
  || fail "legacy handoff did NOT match its own dir $CONFIG"
echo "PASS: legacy single-Workdir handoff matches its own dir"

# 2b. Legacy single-Workdir handoff does NOT match an unrelated sibling.
if emits_match "$SIBLING" "$LEGACY_JSON"; then
  fail "legacy handoff WRONGLY matched unrelated sibling $SIBLING"
fi
echo "PASS: legacy handoff does not match unrelated sibling"

echo "ALL PASS"
