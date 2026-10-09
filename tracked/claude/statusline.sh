#!/usr/bin/env bash
# Claude Code status line. Row 1: model with effort, weekly limit left, context
# left, and output tokens per second of the latest model call.
# Row 2: current directory. Reads the status JSON on stdin; absent fields are
# omitted rather than guessed.
set -u

command -v jq >/dev/null 2>&1 || exit 0

IFS=$'\t' read -r model effort dir weekly context api_ms out_tokens session < <(
    jq -r '[
        .model.display_name // "",
        .effort.level // "",
        .workspace.current_dir // .cwd // "",
        (.rate_limits.seven_day.used_percentage // "" | if . == "" then "" else (100 - . | floor | tostring) end),
        (.context_window.remaining_percentage // "" | if . == "" then "" else (floor | tostring) end),
        (.cost.total_api_duration_ms // "" | if . == "" then "" else floor | tostring end),
        (.context_window.current_usage.output_tokens // "" | tostring),
        (.session_id // "" | gsub("[^A-Za-z0-9-]"; ""))
    ] | map(if . == "" then "-" else . end) | @tsv' 2>/dev/null
) || exit 0

dim=$'\033[2m' cyan=$'\033[36m' blue=$'\033[34m' green=$'\033[32m' yellow=$'\033[33m' red=$'\033[31m' reset=$'\033[0m'

# Colour a remaining-percentage by how little is left.
level() {
    if [ "$1" -le 10 ]; then printf '%s' "$red"
    elif [ "$1" -le 30 ]; then printf '%s' "$yellow"
    else printf '%s' "$green"; fi
}

# The status JSON only carries the latest call's output tokens, so measure that
# call against the API time added since the previous refresh, and remember the
# last rate per session for refreshes where nothing new ran.
tps=-
if [ "${session:--}" != "-" ] && [ "${api_ms:--}" != "-" ]; then
    state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/claude-statusline"
    state="$state_dir/$session"
    prev_ms=0 prev_tps=-
    [ -r "$state" ] && read -r prev_ms prev_tps < "$state"
    tps=$prev_tps
    delta=$((api_ms - ${prev_ms:-0}))
    if [ "$delta" -gt 0 ] && [ "${out_tokens:--}" != "-" ] && [ "$out_tokens" -gt 0 ] 2>/dev/null; then
        # A first sighting has no baseline, so wait for the next call.
        if [ -r "$state" ]; then tps=$((out_tokens * 1000 / delta)); fi
    fi
    if [ "$delta" -ne 0 ]; then
        mkdir -p "$state_dir" && printf '%s %s\n' "$api_ms" "$tps" > "$state"
    fi
fi

parts=()
if [ "${model:--}" != "-" ]; then
    [ "${effort:--}" != "-" ] && model="$model $effort"
    parts+=("${cyan}${model}${reset}")
fi
if [ "${weekly:--}" != "-" ]; then
    parts+=("$(level "$weekly")weekly ${weekly}% left${reset}")
fi
if [ "${context:--}" != "-" ]; then
    parts+=("$(level "$context")context ${context}% left${reset}")
fi
if [ "${tps:--}" != "-" ]; then
    parts+=("${dim}${tps} tok/s${reset}")
fi

sep=" ${dim}·${reset} "
out=
for part in "${parts[@]}"; do
    out+="${out:+$sep}$part"
done
printf '%s\n' "$out"
if [ "${dir:--}" != "-" ]; then
    printf '%s\n' "${blue}${dir/#$HOME/\~}${reset}"
fi
