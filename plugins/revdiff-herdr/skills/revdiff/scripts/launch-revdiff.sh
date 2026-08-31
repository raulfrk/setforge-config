#!/usr/bin/env bash
# Prefer RevDiff's bundled Herdr backend whenever the caller is inside Herdr,
# even when the Herdr server inherited tmux, Zellij, or agterm selectors.
set -euo pipefail

if [[ ${HERDR_ENV:-} == 1 ]]; then
    unset AGTERM_SESSION_ID TMUX TMUX_PANE ZELLIJ ZELLIJ_PANE_ID
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$script_dir/launch-revdiff.upstream.sh" "$@"
