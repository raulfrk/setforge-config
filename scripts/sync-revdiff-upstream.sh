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
current_version=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' \
    "$plugin_root/.codex-plugin/plugin.json")
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

cp -a "$manual_src/revdiff/references/." "$plugin_root/skills/revdiff/references/"
cp "$manual_src/revdiff/scripts/agentdeck-window.sh" "$plugin_root/skills/revdiff/scripts/agentdeck-window.sh"
cp "$manual_src/revdiff/scripts/detect-ref.sh" "$plugin_root/skills/revdiff/scripts/detect-ref.sh"
cp "$manual_src/revdiff/scripts/read-latest-history.sh" "$plugin_root/skills/revdiff/scripts/read-latest-history.sh"
cp "$manual_src/revdiff/scripts/launch-revdiff.sh" "$plugin_root/skills/revdiff/scripts/launch-revdiff.upstream.sh"
cp "$manual_src/revdiff-plan/scripts/extract-last-message.sh" "$plugin_root/skills/revdiff-plan/scripts/extract-last-message.sh"
cp "$planning_src/scripts/codex-plan-review-hook.py" "$plugin_root/scripts/codex-plan-review-hook.py"
cp "$planning_src/scripts/resolve-launcher.sh" "$plugin_root/scripts/resolve-launcher.sh"
cp "$planning_src/scripts/launch-plan-review.sh" "$plugin_root/scripts/launch-plan-review.upstream.sh"
cp "$worktree/source/LICENSE" "$plugin_root/LICENSE"

python3 - "$plugin_root" "$local_version" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
local_version = sys.argv[2]

def replace_exact(path: pathlib.Path, old: str, new: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f"error: upstream text changed; adapt manually: {path}")
    path.write_text(text.replace(old, new, 1))

def remove_frontmatter_field(path: pathlib.Path, field: str) -> None:
    lines = path.read_text().splitlines(keepends=True)
    path.write_text("".join(line for line in lines if not line.startswith(f"{field}:")))

plan = root / "skills/revdiff-plan/SKILL.md"
remove_frontmatter_field(plan, "argument-hint")

hook = root / "scripts/codex-plan-review-hook.py"
replace_exact(
    hook,
    '''    if event.get("permission_mode") != "plan":
        respond()
        return

''',
    '''
    # Codex permission_mode describes approval behavior, not collaboration
    # mode. A complete proposed_plan block is the stable plan-review signal.

''',
)

manifest_path = root / ".codex-plugin/plugin.json"
manifest = json.loads(manifest_path.read_text())
manifest["version"] = local_version
manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
PY

chmod +x \
    "$plugin_root/scripts/"*.py \
    "$plugin_root/scripts/"*.sh \
    "$plugin_root/skills/revdiff/scripts/"*.sh \
    "$plugin_root/skills/revdiff-plan/scripts/"*.sh

cat > "$plugin_root/UPSTREAM.md" <<EOF
# Upstream provenance

This plugin vendors selected Codex components from
[\`umputun/revdiff\`](https://github.com/umputun/revdiff) under the upstream MIT
license retained in [\`LICENSE\`](LICENSE).

- Upstream revision: \`$upstream_commit\`
- RevDiff release: \`$revdiff_release\`
- Manual Codex plugin: \`$manual_version\`
- Planning plugin: \`$planning_version\`
- Local plugin: \`$local_version\`
- Synchronized: \`$(date -u +%F)\`

The \`*.upstream.sh\`, hook, extractor, manual references, and manual-review
scripts originate from that revision. The manual-review skill, advanced
workflow reference, \`launch-*.sh\` dispatchers, responsive plan launcher,
formatter/runtime helpers, and plan-review skill are local. Inside
Herdr they remove competing multiplexer selectors, open a dedicated tab, format
the plan for the live pane width, map annotations back to canonical Markdown,
and restore the caller's tab without changing the review result. The planning
hook detects complete \`<proposed_plan>\` blocks instead of assuming that
Codex's approval-oriented \`permission_mode\` identifies Plan mode.

Refresh with:

\`\`\`bash
./scripts/sync-revdiff-upstream.sh <upstream-ref> <new-local-semver>
\`\`\`

The command requires an explicit upstream revision and local version, imports
only the allowlisted upstream files, reapplies the Codex cache-path and
plan-trigger adaptations, and leaves the local responsive formatter, plan
skill, and Herdr launchers intact. Review the resulting diff and run the full
test suite before publishing the new marketplace version.
EOF

echo "synchronized RevDiff $upstream_commit as local plugin $local_version"
