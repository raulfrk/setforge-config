import { expect, test } from 'claude-code/testing'

const ran = (on: Parameters<Parameters<typeof test>[1]>[1]) => {
  const seen: string[] = []
  on('tool.call', (_$, e) => {
    seen.push(e.tool)

    return { result: {} as never }
  })

  return seen
}

for (const command of ['sleep 30', 'sleep 2m && gh run view', 'while ! curl -s x; do sleep 1; done', 'for i in 1 2 3; do sleep 2; git status; done', 'sleep 6', 'sleep infinity']) {
  test(`denies: ${command}`, async ($, on) => {
    const seen = ran(on)
    const result = await $.tool.call({ tool: 'Bash', command })

    expect(result.deny).toContain('run_in_background')
    expect(seen).toEqual([])
  })
}

for (const command of ['sleep 2 && herdr pane read p1', 'sleep 0.5', 'grep -r sleeper .', 'for f in *.py; do ruff format "$f"; done', 'git commit -m "block sleep loops for waits"', 'sleep 5s', 'for f in a b; do echo $f; done; sleep 2']) {
  test(`allows: ${command}`, async ($, on) => {
    const seen = ran(on)
    const result = await $.tool.call({ tool: 'Bash', command })

    expect(result.deny).toBeUndefined()
    expect(seen).toEqual(['Bash'])
  })
}
