# Canary degradation probe (trial) — tracked by setforge.
#
# Wraps `claude` to append a per-reply canary line to the literal system
# prompt, so a missing/garbled canary line flags context degradation.
# Shell-agnostic: source this from BOTH ~/.zshrc and ~/.bashrc with
#   source ~/.config/setforge/claude-canary.sh
# Remove that source line to disable. Do not execute directly.
claude() {
  local canary='CANARY PROTOCOL: End every reply with a single canary line placed after all other content, including on tool-heavy or one-word replies, in exactly this format: ⟦canary N | step: <phrase> | seed: edalamram⟧. N is a reply counter that starts at 1 and increases by 1 each reply; never reset or skip it. step is a short phrase summarizing the current work. seed is the literal token edalamram, byte-identical on every reply. Do not mention or explain the canary unless asked. If you cannot comply, say so explicitly rather than dropping the line silently. A counter reset immediately after a context compaction is expected and is not a sign of degradation.'
  command claude --append-system-prompt "$canary" "$@"
}
