#!/usr/bin/env bash
# Present a responsive Codex plan review in a dedicated Herdr tab.
set -euo pipefail

sq() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }

if [[ $# == 1 ]]; then
    new_file=$1
    old_file=
elif [[ $# == 2 ]]; then
    new_file=$1
    old_file=$2
else
    echo "usage: launch-plan-review.sh <plan-file-path> | <new-path> <old-path>" >&2
    exit 1
fi

if [[ ! -f $new_file ]]; then
    echo "error: file not found: $new_file" >&2
    exit 1
fi
if [[ -n $old_file && ! -f $old_file ]]; then
    echo "error: file not found: $old_file" >&2
    exit 1
fi
if ! command -v herdr >/dev/null 2>&1; then
    echo "error: herdr not found in PATH" >&2
    exit 1
fi

revdiff_bin=$(command -v revdiff 2>/dev/null || true)
python_bin=$(command -v python3 2>/dev/null || true)
if [[ -z $revdiff_bin ]]; then
    echo "error: revdiff not found in PATH" >&2
    exit 1
fi
if [[ -z $python_bin ]]; then
    echo "error: python3 not found in PATH" >&2
    exit 1
fi

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
runtime=$script_dir/plan-review-runtime.py
if [[ ! -f $runtime ]]; then
    echo "error: plan review runtime not found: $runtime" >&2
    exit 1
fi

new_abs=$(cd "$(dirname "$new_file")" && echo "$(pwd)/$(basename "$new_file")")
old_abs=
if [[ -n $old_file ]]; then
    old_abs=$(cd "$(dirname "$old_file")" && echo "$(pwd)/$(basename "$old_file")")
fi

tmpbase=${TMPDIR:-/tmp}
output_file=$(mktemp "$tmpbase/plan-review-output-XXXXXX")
ready_file=$(mktemp "$tmpbase/plan-review-ready-XXXXXX")
sentinel=$(mktemp "$tmpbase/plan-review-done-XXXXXX")
launch_script=$(mktemp "$tmpbase/plan-review-launch-XXXXXX")
rm -f "$ready_file" "$sentinel"
created_tab_id=

# Invoked indirectly by the EXIT trap below.
# shellcheck disable=SC2329
cleanup() {
    cleanup_rc=$?
    trap - EXIT
    if [[ -n $created_tab_id ]]; then
        herdr tab close "$created_tab_id" >/dev/null 2>&1 || true
    fi
    rm -f "$output_file" "$ready_file" "$sentinel" "$sentinel.tmp" "$launch_script"
    exit "$cleanup_rc"
}
trap cleanup EXIT

runtime_command="PYTHONDONTWRITEBYTECODE=1 $(sq "$python_bin") $(sq "$runtime") $(sq "--revdiff=$revdiff_bin") $(sq "--new=$new_abs") $(sq "--output=$output_file") $(sq "--ready=$ready_file")"
if [[ -n $old_abs ]]; then
    runtime_command="$runtime_command $(sq "--old=$old_abs")"
fi

cat > "$launch_script" <<LAUNCHER
#!/bin/sh
$runtime_command; rc=\$?; printf "%s" "\$rc" > $(sq "$sentinel").tmp && mv -f $(sq "$sentinel").tmp $(sq "$sentinel")
LAUNCHER
chmod +x "$launch_script"

tab_args=(tab create --cwd "$(pwd)" --label "plan: $(basename "$new_file")")
[[ -n ${HERDR_WORKSPACE_ID:-} ]] && tab_args+=(--workspace "$HERDR_WORKSPACE_ID")
tab_args+=(--focus)
created=$(herdr "${tab_args[@]}" 2>&1) || {
    echo "error: herdr tab create failed: $created" >&2
    exit 1
}

created_tab_id=
pane_id=
if command -v jq >/dev/null 2>&1; then
    created_tab_id=$(printf '%s' "$created" | jq -r '.result.tab.tab_id // empty' 2>/dev/null || true)
    pane_id=$(printf '%s' "$created" | jq -r '.result.root_pane.pane_id // empty' 2>/dev/null || true)
fi
if [[ -z $created_tab_id ]]; then
    created_tab_id=$(printf '%s' "$created" | grep -o '"tab_id":"[^"]*"' | head -1 | cut -d'"' -f4 || true)
fi
if [[ -z $pane_id ]]; then
    pane_id=$(printf '%s' "$created" | grep -o '"pane_id":"[^"]*"' | head -1 | cut -d'"' -f4 || true)
fi
if [[ -z $created_tab_id || -z $pane_id ]]; then
    echo "error: herdr tab create did not return pane/tab ids: $created" >&2
    exit 1
fi

if ! herdr pane run "$pane_id" "sh $(sq "$launch_script")" >/dev/null 2>&1; then
    echo "error: herdr pane run failed for pane $pane_id" >&2
    exit 1
fi

# The runtime measures the target pty, then writes its width just before
# RevDiff starts. Hide the file tree below 90 columns once RevDiff is the
# foreground process; users can still toggle it with `t`.
for _ in $(seq 1 50); do
    if [[ -f $ready_file ]]; then
        columns=$(sed -n 's/.*"columns":[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$ready_file" | head -1)
        if [[ -n $columns && $columns -lt 90 ]]; then
            for _ in $(seq 1 50); do
                if herdr pane process-info --pane "$pane_id" 2>/dev/null \
                        | grep -Eq '"name"[[:space:]]*:[[:space:]]*"revdiff"'; then
                    sleep 0.1
                    herdr pane send-keys "$pane_id" t >/dev/null 2>&1 || true
                    break
                fi
                [[ -f $sentinel ]] && break
                sleep 0.1
            done
        fi
        break
    fi
    [[ -f $sentinel ]] && break
    sleep 0.1
done

while [[ ! -f $sentinel ]]; do
    sleep 0.3
done
review_rc=$(cat "$sentinel" 2>/dev/null || echo 1)
case $review_rc in
    ''|*[!0-9]*) review_rc=1 ;;
esac

herdr tab close "$created_tab_id" >/dev/null 2>&1 || true
created_tab_id=
cat "$output_file"
exit "$review_rc"
