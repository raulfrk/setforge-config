#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 2 ]]; then
    echo "usage: $0 <upstream-ref> <new-local-semver>" >&2
    exit 2
fi

upstream_ref=$1
local_version=$2
if [[ ! $local_version =~ ^[0-9]+\.[0-9]+\.[0-9]+([+-][0-9A-Za-z.-]+)?$ ]]; then
    echo "error: local version must be semver" >&2
    exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
plugin_root="$repo_root/plugins/revdiff-herdr"
manifest_path="$repo_root/plugins/revdiff-herdr-claude/.claude-plugin/plugin.json"
current_version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' \
    "$manifest_path")
if [[ $local_version == "$current_version" ]]; then
    echo "error: choose a new local plugin version (current: $current_version)" >&2
    exit 2
fi

worktree=$(mktemp -d "${TMPDIR:-/tmp}/revdiff-herdr-sync.XXXXXX")
trap 'rm -rf "$worktree"' EXIT
git clone --quiet https://github.com/umputun/revdiff.git "$worktree/source"
git -C "$worktree/source" checkout --quiet --detach "$upstream_ref"
upstream_commit=$(git -C "$worktree/source" rev-parse HEAD)
revdiff_release=$(git -C "$worktree/source" describe --tags --abbrev=0 --match 'v*')

marketplace="$worktree/source/.claude-plugin/marketplace.json"
manual_version=$(jq -r '.plugins[] | select(.name == "revdiff") | .version' "$marketplace")
planning_version=$(jq -r '.plugins[] | select(.name == "revdiff-planning") | .version' "$marketplace")
if [[ -z $manual_version || $manual_version == null || -z $planning_version || $planning_version == null ]]; then
    echo "error: upstream marketplace is missing RevDiff plugin versions" >&2
    exit 1
fi

manual_src="$worktree/source/plugins/codex/skills"
planning_src="$worktree/source/plugins/revdiff-planning"

cp "$manual_src/revdiff/references/config.md" "$plugin_root/skills/revdiff/references/config.md"
cp "$manual_src/revdiff/references/usage.md" "$plugin_root/skills/revdiff/references/usage.md"
cp "$manual_src/revdiff/scripts/agentdeck-window.sh" "$plugin_root/skills/revdiff/scripts/agentdeck-window.sh"
cp "$manual_src/revdiff/scripts/detect-ref.sh" "$plugin_root/skills/revdiff/scripts/detect-ref.sh"
cp "$manual_src/revdiff/scripts/read-latest-history.sh" "$plugin_root/skills/revdiff/scripts/read-latest-history.sh"
cp "$manual_src/revdiff/scripts/launch-revdiff.sh" "$plugin_root/skills/revdiff/scripts/launch-revdiff.upstream.sh"
cp "$planning_src/scripts/launch-plan-review.sh" "$plugin_root/scripts/launch-plan-review.upstream.sh"
cp "$worktree/source/LICENSE" "$plugin_root/LICENSE"

python3 - "$manifest_path" "$local_version" <<'PY'
import json
import pathlib
import sys

manifest_path = pathlib.Path(sys.argv[1])
local_version = sys.argv[2]

manifest = json.loads(manifest_path.read_text())
manifest["version"] = local_version
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
PY

chmod +x \
    "$plugin_root/scripts/"*.py \
    "$plugin_root/scripts/"*.sh \
    "$plugin_root/skills/revdiff/scripts/"*.sh

cat > "$plugin_root/UPSTREAM.md" <<EOF
# Upstream provenance

These shared scripts and references back the \`revdiff-herdr\` Claude plugin in
\`plugins/revdiff-herdr-claude/\`, whose launchers are symlinks into this
directory. Some files are vendored from upstream's Codex plugin in
[\`umputun/revdiff\`](https://github.com/umputun/revdiff) under the upstream MIT
license retained in [\`LICENSE\`](LICENSE).

- Upstream revision: \`$upstream_commit\`
- RevDiff release: \`$revdiff_release\`
- Upstream manual plugin: \`$manual_version\`
- Planning plugin: \`$planning_version\`
- Local plugin: \`$local_version\`
- Synchronized: \`$(date -u +%F)\`

The \`*.upstream.sh\`, the \`config.md\` and \`usage.md\` references, and the
manual-review scripts originate from that revision. The launcher resolver,
\`launch-*.sh\` dispatchers, responsive plan launcher, and formatter/runtime
helpers are locally maintained. Inside Herdr they remove competing multiplexer
selectors, open a dedicated tab, format the plan for the live pane width, map
annotations back to canonical Markdown, and restore the caller's tab without
changing the review result.

Refresh with:

\`\`\`bash
./scripts/sync-revdiff-upstream.sh <upstream-ref> <new-local-semver>
\`\`\`

The command requires an explicit upstream revision and local version, imports
only the allowlisted upstream files, and leaves the locally maintained resolver,
responsive formatter, and Herdr launchers intact.
Review the resulting diff and run the full test suite before publishing the new
marketplace version.
EOF

echo "synchronized RevDiff $upstream_commit as local plugin $local_version"
