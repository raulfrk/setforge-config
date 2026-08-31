#!/usr/bin/env bash
# Prefer RevDiff's bundled Herdr backend whenever the caller is inside Herdr,
# even when the Herdr server inherited tmux, Zellij, or agterm selectors.
set -euo pipefail

if [[ ${HERDR_ENV:-} == 1 ]]; then
    herdr_caller_tab_id=${HERDR_TAB_ID:-}
    restore_herdr_caller_tab() {
        launcher_rc=$?
        trap - EXIT
        if [[ -n $herdr_caller_tab_id ]] && command -v herdr >/dev/null 2>&1; then
            herdr tab focus "$herdr_caller_tab_id" >/dev/null 2>&1 || true
        fi
        exit "$launcher_rc"
    }
    trap restore_herdr_caller_tab EXIT
    unset AGTERM_SESSION_ID TMUX TMUX_PANE ZELLIJ ZELLIJ_PANE_ID
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ ${HERDR_ENV:-} == 1 ]]; then
    "$script_dir/launch-revdiff.upstream.sh" "$@"
else
    exec "$script_dir/launch-revdiff.upstream.sh" "$@"
fi
