#!/usr/bin/env bash
# Extract the last assistant text message from a Claude Code transcript.
#
# usage: extract-last-message.sh <transcript.jsonl> [session-id]
#   transcript.jsonl  explicit path to the session transcript; there is no
#                     newest-file discovery, which could select another session
#   session-id        when given, require every selected record to carry it
# output: raw Markdown of the last main-conversation assistant text message
set -euo pipefail

if ! command -v jq >/dev/null 2>&1; then
    echo "error: jq is required but not installed" >&2
    exit 1
fi
transcript=${1:-}
session_id=${2:-}
if [ -z "$transcript" ]; then
    echo "error: usage: extract-last-message.sh <transcript.jsonl> [session-id]" >&2
    exit 1
fi
if [ ! -f "$transcript" ]; then
    echo "error: transcript not found: $transcript" >&2
    exit 1
fi

# One API response is stored as several records; join the text blocks of the
# last response (same message id) that contains any text.
msg=$(jq -rs --arg sid "$session_id" '
    [.[]
     | select(.type == "assistant" and (.isSidechain // false) == false)
     | select($sid == "" or .sessionId == $sid)
     | {id: .message.id, text: ([.message.content[]? | select(.type == "text") | .text] | join("\n"))}
     | select(.text != "")
    ] as $texts
    | if ($texts | length) == 0 then empty
      else ($texts | last | .id) as $last
           | [$texts[] | select(.id == $last) | .text] | join("\n")
      end
' "$transcript" 2>/dev/null) || msg=

if [ -z "$msg" ]; then
    echo "error: no assistant text message found in $transcript" >&2
    exit 1
fi
printf '%s\n' "$msg"
