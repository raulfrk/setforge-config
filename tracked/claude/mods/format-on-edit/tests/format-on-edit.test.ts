import type { On } from 'claude-code'
import { expect, test } from 'claude-code/testing'

const setup = (on: On, exitCode = 0) => {
  const seen = { runs: [] as (readonly string[])[], toasts: [] as string[] }
  on('process.run', (_$, e) => {
    seen.runs.push(e.argv)

    return { value: { exitCode, stdout: '', stderr: 'ruff: bad syntax', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('ui.toast', (_$, e) => {
    seen.toasts.push(e.text)

    return { value: undefined }
  })
  on('tool.call', () => ({ result: {} as never }))

  return seen
}

test('formats the edited file through the repo script', async ($, on) => {
  const seen = setup(on)
  await $.tool.call({ tool: 'Edit', file_path: '/r/a.py', old_string: 'a', new_string: 'b' })

  expect(seen.runs).toHaveLength(1)
  expect(seen.runs[0]?.at(-1)).toBe('/r/a.py')
  expect(seen.toasts).toEqual([])
})

test('reports a formatter failure without failing the edit', async ($, on) => {
  const seen = setup(on, 1)
  const result = await $.tool.call({ tool: 'Write', file_path: '/r/b.py', content: 'x' })

  expect(result.isError).not.toBe(true)
  expect(seen.toasts[0]).toContain('ruff: bad syntax')
})

test('leaves other tools alone', async ($, on) => {
  const seen = setup(on)
  await $.tool.call({ tool: 'Bash', command: 'true' })

  expect(seen.runs).toEqual([])
})
