import type { Register } from 'claude-code'

// Runs `sh <repo>/.claude/format <file>` from the repo root; repos without that file are skipped.
const FORMAT = [
  'root=$(git -C "$(dirname "$1")" rev-parse --show-toplevel 2>/dev/null) || exit 0',
  '[ -f "$root/.claude/format" ] || exit 0',
  'cd "$root" && exec sh .claude/format "$1"',
].join('\n')

export const register: Register = on => {
  for (const tool of ['Edit', 'Write'] as const) {
    on('tool.call', { tool }, async ($, e, next) => {
      const ran = await next(e)
      if (ran.deny !== undefined || ran.isError === true) {
        return ran
      }
      const { exitCode, stderr, stdout } = await $.process.run(['sh', '-c', FORMAT, 'format', e.file_path], {
        timeoutMs: 60_000,
      }).catch((error: unknown) => ({ exitCode: 1, stderr: String(error), stdout: '' }))
      if (exitCode !== 0) {
        $.ui.toast(`format failed on ${e.file_path}: ${(stderr || stdout).trim().split('\n')[0] ?? ''}`)
      }

      return ran
    })
  }
}
