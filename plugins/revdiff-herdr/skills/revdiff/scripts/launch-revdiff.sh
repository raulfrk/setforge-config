#!/usr/bin/env bash
# Public RevDiff entry point. Markdown documents use the responsive review
# runtime; every other invocation preserves the bundled upstream behavior.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
responsive_launcher="$script_dir/../../../scripts/launch-plan-review-herdr.sh"

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

markdown_only=
compare_old=
compare_new=
responsive=true
description_args=()
for arg in "$@"; do
    case "$arg" in
        --only=*.md|--only=*.markdown)
            [[ -z $markdown_only && -z $compare_old && -z $compare_new ]] || responsive=false
            markdown_only=${arg#--only=}
            ;;
        --compare-old=*.md|--compare-old=*.markdown)
            [[ -z $markdown_only && -z $compare_old ]] || responsive=false
            compare_old=${arg#--compare-old=}
            ;;
        --compare-new=*.md|--compare-new=*.markdown)
            [[ -z $markdown_only && -z $compare_new ]] || responsive=false
            compare_new=${arg#--compare-new=}
            ;;
        --description=*|--description-file=*) description_args+=("$arg") ;;
        *) responsive=false ;;
    esac
done
if [[ $responsive == true && -n $markdown_only && -z $compare_old && -z $compare_new ]]; then
    if [[ ${HERDR_ENV:-} == 1 ]]; then
        "$responsive_launcher" "$markdown_only" "${description_args[@]}"
        exit $?
    fi
    exec "$responsive_launcher" "$markdown_only" "${description_args[@]}"
fi
if [[ $responsive == true && -z $markdown_only && -n $compare_old && -n $compare_new ]]; then
    if [[ ${HERDR_ENV:-} == 1 ]]; then
        "$responsive_launcher" "$compare_new" "$compare_old" "${description_args[@]}"
        exit $?
    fi
    exec "$responsive_launcher" "$compare_new" "$compare_old" "${description_args[@]}"
fi

if [[ ${HERDR_ENV:-} == 1 ]]; then
    "$script_dir/launch-revdiff.upstream.sh" "$@"
else
    exec "$script_dir/launch-revdiff.upstream.sh" "$@"
fi
