import type { Register } from 'claude-code'

const UNIT: Record<string, number> = { '': 1, s: 1, m: 60, h: 3600, d: 86400 }
const MAX_SECONDS = 5
const DENY = 'Waiting with sleep is blocked. Run the command with run_in_background and act on its completion notification, or use Monitor to wait for a specific condition.'

export const sleepsTooLong = (command: string): boolean => {
  if (!/\bsleep\b/.test(command)) { return false }
  // shortcut: plain text matching, so quoted prose like `-m "sleep 30"` is refused and `sleep $N` passes; parse the shell if that bites.
  if (/\bsleep\s+inf/.test(command) || /\b(while|until|for)\b[\s\S]*?\bdo\b[\s\S]*?\bsleep\b[\s\S]*?\bdone\b/.test(command)) { return true }

  return [...command.matchAll(/\bsleep\s+([\d.]+)([smhd]?)\b/g)]
    .some(([, n, unit]) => Number(n) * (UNIT[unit ?? ''] ?? 1) > MAX_SECONDS)
}

export const register: Register = on => {
  on('tool.call', { tool: 'Bash' }, async (_$, e, next) => sleepsTooLong(e.command) ? { deny: DENY } : next(e))
}
