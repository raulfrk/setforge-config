import type { On } from 'claude-code'
import { expect, mock, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'

const MINUTE = 60_000

// The suite's timings are for the 5-minute lifetime; the defaults (1 hour) have their own tests.
const FIVE = { options: { ttl: '5m' } }

const usage = (read: number, written: number) => ({
  input_tokens: 10,
  output_tokens: 200,
  cache_read_input_tokens: read,
  cache_creation_input_tokens: written,
  model: 'claude-test',
})

const setup = (on: On) => {
  const clock = mock.clock(on, { now: 0 })
  const seen = {
    statuses: [] as (string | undefined)[],
    toasts: [] as string[],
    logs: [] as string[],
    forks: [] as string[],
    agents: [
      { id: 'a2', name: 'worker', description: 'named agent', type: 'general-purpose', status: 'idle' },
    ],
    forkFails: false,
    context: 90_000,
    pingRead: 90_000,
    pingOutput: 3,
  }

  on('ui.status', (_$, e) => {
    seen.statuses.push(e.text)

    return { value: undefined }
  })
  on('ui.toast', (_$, e) => {
    seen.toasts.push(e.text)

    return { value: undefined }
  })
  on('ui.log', (_$, e) => {
    seen.logs.push(e.text)

    return { value: undefined }
  })
  on('agent.list', () => ({ value: seen.agents }))
  on('command.register', (_$, e) => ({ value: { command: e.name } }))
  on('session.usage', () => ({
    value: { startedAt: 0, context: { window: 200_000, tokens: seen.context }, rateLimits: [] },
  }))
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('session.end', (_$, e) => ({ sessionId: e.reason }))
  on('turn.start', (_$, e) => ({ turnId: e.turnId }))
  on('turn.complete', (_$, e) => ({ text: e.answer }))
  on('model.fork', (_$, e) => {
    seen.forks.push(e.prompt)
    if (seen.forkFails) {
      throw new Error('refused')
    }

    return {
      value: {
        isAnswered: true as const,
        text: 'ok',
        usage: { ...usage(seen.pingRead, 0), output_tokens: seen.pingOutput },
      },
    }
  })
  on('tool.call', async (_$, e) => {
    // A test tool takes as many milliseconds as its command says.
    const ms = 'command' in e ? Number(e.command) : 0
    if (ms > 0) {
      await clock.sleep(ms)
    }

    return { deny: 'test' }
  })
  on('command.run', { command: 'model' }, () => ({ text: 'picker opened' }))

  return { clock, seen }
}

const start = ($: Engine) => $.session.start({ cwd: '/w', surface: null, isInteractive: true })

const complete = ($: Engine, id: string, used: ReturnType<typeof usage>) =>
  $.turn.complete({
    answer: 'ok',
    durationMs: 1000,
    isAborted: false,
    turnId: id,
    reason: 'answer',
    usage: used,
  })

const turn = async ($: Engine, id: string, used: ReturnType<typeof usage>) => {
  await $.turn.start({ text: 'go', turnId: id })
  await complete($, id, used)
}

const bash = (ms: number) => ({ tool: 'Bash' as const, command: String(ms) })

const run = ($: Engine, command: string, args = '') =>
  $.command.run({
    command,
    args,
    origin: { kind: 'composer' },
    presentation: { isFullscreen: false, columns: 120 },
  })

const cacheReport = async ($: Engine) => (await run($, 'cache')).text ?? ''

test('counts down while the cache is warm, then says it is cold', FIVE, async ($, on) => {
  const { clock, seen } = setup(on)
  await start($)
  await turn($, 't1', usage(0, 90_000))
  expect(seen.statuses.at(-1)).toBe('cache warm 5:00 · 90k ctx')

  await clock.advance(2 * MINUTE)
  expect(seen.statuses.at(-1)).toBe('cache warm 3:00 · 90k ctx')

  await clock.advance(3 * MINUTE + 5000)
  expect(seen.statuses.at(-1)).toBe('cache cold · next prompt re-caches ~90k')
})

test('reports a cache that lapsed while idle and counts it', FIVE, async ($, on) => {
  const { clock, seen } = setup(on)
  await start($)
  await turn($, 't1', usage(0, 90_000))
  await clock.advance(7 * MINUTE)
  await turn($, 't2', usage(0, 90_000))

  expect(seen.toasts).toEqual(['Cache lapsed after 7m without a request: ~90k tokens re-cached.'])
  expect(await cacheReport($)).toContain('1 after idling past the lifetime, 0 while warm; ~90k')
})

test('flags a miss that happened while the cache was warm', FIVE, async ($, on) => {
  const { clock, seen } = setup(on)
  await start($)
  await turn($, 't1', usage(0, 90_000))
  await clock.advance(MINUTE)
  await turn($, 't2', usage(2000, 88_000))

  expect(seen.toasts).toHaveLength(1)
  expect(seen.toasts[0]).toStartWith('Cache miss while warm: ~88k tokens re-cached.')
})

test('stays quiet on a hit, however much the turn adds', FIVE, async ($, on) => {
  const { clock, seen } = setup(on)
  await start($)
  await turn($, 't1', usage(0, 90_000))
  await clock.advance(MINUTE)
  seen.context = 150_000
  await turn($, 't2', usage(90_000, 60_000))

  expect(seen.toasts).toEqual([])
  expect(await cacheReport($)).toContain('hit rate 37%')
})

test('holds /model once while the cache is warm, then lets it through', FIVE, async ($, on) => {
  const { clock } = setup(on)
  await start($)
  await turn($, 't1', usage(0, 90_000))
  await clock.advance(MINUTE)

  const first = await run($, 'model', 'sonnet')
  expect(first.text).toStartWith('/model held: the prompt cache is warm (90k tokens, 4:00 left)')

  await clock.advance(10_000)
  expect((await run($, 'model', 'sonnet')).text).toBe('picker opened')

  expect((await run($, 'model', 'sonnet')).text).toStartWith(
    '/model held',
  )
})

test('does not hold /model once the cache is cold', FIVE, async ($, on) => {
  const { clock } = setup(on)
  await start($)
  await turn($, 't1', usage(0, 90_000))
  await clock.advance(6 * MINUTE)

  expect((await run($, 'model')).text).toBe('picker opened')
})

test('ignores contexts too small to matter', FIVE, async ($, on) => {
  const { seen } = setup(on)
  seen.context = 8000
  await start($)
  await turn($, 't1', usage(0, 8000))

  expect(seen.statuses.filter(Boolean)).toEqual([])
  expect((await run($, 'model')).text).toBe('picker opened')
})

test('forgets the session on /clear', FIVE, async ($, on) => {
  const { seen } = setup(on)
  await start($)
  await turn($, 't1', usage(0, 90_000))
  await $.session.end({ reason: 'clear', sessionId: 's1', resume: { id: 's1' } })

  expect(seen.statuses.at(-1)).toBeUndefined()
  expect(await cacheReport($)).toContain('no response yet')
})

const WARM = { options: { ttl: '5m', keepWarm: true, keepWarmMax: 3 } }

test('keeps the cache warm shortly before it lapses, up to the limit', WARM, async ($, on) => {
  const { clock, seen } = setup(on)
  await start($)
  await turn($, 't1', usage(0, 90_000))

  await clock.advance(3 * MINUTE)
  expect(seen.forks).toEqual([])

  await clock.advance(MINUTE + 5000)
  expect(seen.forks).toEqual(['Reply with exactly one word: ok'])
  expect(seen.statuses.at(-1)).toBe('cache warm 4:55 · 90k ctx · keep-warm 1/3')

  await clock.advance(8 * MINUTE)
  expect(seen.forks).toHaveLength(3)

  await clock.advance(10 * MINUTE)
  expect(seen.forks).toHaveLength(3)
  expect(seen.statuses.at(-1)).toBe('cache cold · next prompt re-caches ~90k')
  expect(seen.toasts).toEqual([])
  expect(seen.logs).toHaveLength(3)
  expect(seen.logs[0]).toBe(
    'Keep-warm ping 1/3: read 90k tokens from the cache, 3 output tokens. The cache timer restarted.',
  )
})

test('sends nothing unless keep-warm is on', FIVE, async ($, on) => {
  const { clock, seen } = setup(on)
  await start($)
  await turn($, 't1', usage(0, 90_000))
  await clock.advance(4.5 * MINUTE)

  expect(seen.forks).toEqual([])
})

test('does not ping while a turn is running', WARM, async ($, on) => {
  const { clock, seen } = setup(on)
  await start($)
  await turn($, 't1', usage(0, 90_000))
  await clock.advance(3 * MINUTE)
  await $.turn.start({ text: 'again', turnId: 't2' })
  await clock.advance(10 * MINUTE)

  expect(seen.forks).toEqual([])
})

test('turns keep-warm off when a ping does not read the cache', WARM, async ($, on) => {
  const { clock, seen } = setup(on)
  seen.pingRead = 0
  await start($)
  await turn($, 't1', usage(0, 90_000))
  await clock.advance(10 * MINUTE)

  expect(seen.forks).toHaveLength(1)
  expect(seen.toasts).toHaveLength(1)
  expect(seen.toasts[0]).toStartWith('Keep-warm stopped: a ping read only 0 tokens')
  expect(await cacheReport($)).toContain('keep-warm off (/cache warm on); 1 pings, read 0, 3 output')
})

test('turns keep-warm off when a ping writes too much output', WARM, async ($, on) => {
  const { clock, seen } = setup(on)
  seen.pingOutput = 6000
  await start($)
  await turn($, 't1', usage(0, 90_000))
  await clock.advance(10 * MINUTE)

  expect(seen.forks).toHaveLength(1)
  expect(seen.toasts[0]).toStartWith('Keep-warm stopped: a ping wrote 6000 output tokens')
})

test('/cache warm turns keep-warm on and off for the session', FIVE, async ($, on) => {
  const { clock, seen } = setup(on)
  await start($)
  await turn($, 't1', usage(0, 90_000))

  expect((await run($, 'cache', 'warm maybe')).text).toBe('Usage: /cache warm on|off')
  expect((await run($, 'cache', 'warm on')).text).toStartWith('Keep-warm on:')
  await clock.advance(5 * MINUTE)
  expect(seen.forks).toHaveLength(1)

  expect((await run($, 'cache', 'warm off')).text).toBe('Keep-warm off.')
  await clock.advance(10 * MINUTE)
  expect(seen.forks).toHaveLength(1)
})

test('counts the cache from when the last request started, not when the reply ended', FIVE, async ($, on) => {
  const { clock, seen } = setup(on)
  await start($)
  await $.turn.start({ text: 'go', turnId: 't1' })
  await clock.advance(250_000)
  await $.turn.complete({
    answer: 'ok',
    durationMs: 250_000,
    isAborted: false,
    turnId: 't1',
    reason: 'answer',
    usage: usage(0, 90_000),
  })

  expect(seen.statuses.at(-1)).toBe('cache warm 0:50 · 90k ctx')
})

test('counts a turn with tools from when its last tool finished', FIVE, async ($, on) => {
  const { clock, seen } = setup(on)
  await start($)
  await $.turn.start({ text: 'go', turnId: 't1' })
  await clock.advance(200_000)
  await $.tool.call({ tool: 'Bash', command: 'true' })
  await clock.advance(50_000)
  await $.turn.complete({
    answer: 'ok',
    durationMs: 250_000,
    isAborted: false,
    turnId: 't1',
    reason: 'answer',
    usage: usage(0, 90_000),
  })

  expect(seen.statuses.at(-1)).toBe('cache warm 4:10 · 90k ctx')
})

test('clears the status line on load and on turn start, in case an earlier load left text there', FIVE, async ($, on) => {
  const { seen } = setup(on)
  await start($)
  expect(seen.statuses).toEqual([undefined])

  await $.turn.start({ text: 'go', turnId: 't1' })
  expect(seen.statuses).toEqual([undefined, undefined])
})

test('ignores the tools a subagent runs', FIVE, async ($, on) => {
  const { clock, seen } = setup(on)
  await start($)
  await turn($, 't1', usage(0, 90_000))
  await clock.advance(3 * MINUTE)
  await $.turn.start({ text: 'again', turnId: 't2' })
  await clock.advance(MINUTE)
  // @ts-expect-error The call's type leaves out the loop id, but the engine passes it to the hooks.
  await $.tool.call({ ...bash(0), agentId: 'a1' })
  await complete($, 't2', usage(90_000, 500))

  expect(seen.statuses.at(-1)).toBe('cache warm 4:00 · 90k ctx')
})

test('restarts the cache clock only when the last parallel tool is done', FIVE, async ($, on) => {
  const { clock, seen } = setup(on)
  await start($)
  await $.turn.start({ text: 'go', turnId: 't1' })
  const slow = $.tool.call(bash(200_000))
  const quick = $.tool.call(bash(10_000))

  await clock.advance(20_000)
  await quick
  expect(seen.statuses.at(-1)).toBe('cache warm 4:40 · 90k ctx')

  await clock.advance(180_000)
  await slow
  await complete($, 't1', usage(0, 90_000))
  expect(seen.statuses.at(-1)).toBe('cache warm 5:00 · 90k ctx')
})

test('pings while the main thread waits on a long tool', WARM, async ($, on) => {
  const { clock, seen } = setup(on)
  await start($)
  await $.turn.start({ text: 'go', turnId: 't1' })
  const long = $.tool.call(bash(20 * MINUTE))

  await clock.advance(4 * MINUTE + 5000)
  expect(seen.forks).toHaveLength(1)
  expect(seen.logs[0]).toStartWith('Keep-warm ping 1/3: read 90k tokens')

  await clock.advance(20 * MINUTE)
  await long
  expect(seen.forks).toHaveLength(3)
})

test('labels a lapse inside a long turn, which summed reads would hide', FIVE, async ($, on) => {
  const { clock, seen } = setup(on)
  await start($)
  await turn($, 't1', usage(0, 90_000))
  await clock.advance(MINUTE)
  await $.turn.start({ text: 'again', turnId: 't2' })
  const wait = $.tool.call(bash(8 * MINUTE))
  await clock.advance(8 * MINUTE + 1000)
  await wait
  seen.context = 93_000
  await complete($, 't2', usage(182_000, 94_000))

  expect(seen.toasts).toEqual(['Cache lapsed after 8m without a request: ~91k tokens re-cached.'])
})

test('turns keep-warm off when a ping is refused', WARM, async ($, on) => {
  const { clock, seen } = setup(on)
  seen.forkFails = true
  await start($)
  await turn($, 't1', usage(0, 90_000))
  await clock.advance(10 * MINUTE)

  expect(seen.forks).toHaveLength(1)
  expect(seen.toasts).toEqual(['Keep-warm stopped: the ping was refused. Turn it back on with /cache warm on.'])
})

test('counts a 1-hour lifetime by default', async ($, on) => {
  const { clock, seen } = setup(on)
  await start($)
  await turn($, 't1', usage(0, 90_000))
  expect(seen.statuses.at(-1)).toBe('cache warm 60:00 · 90k ctx')

  await clock.advance(10 * MINUTE)
  expect(seen.statuses.at(-1)).toBe('cache warm 50:00 · 90k ctx')
})

test('pings a minute before the 1-hour cache lapses, up to 24 times by default', async ($, on) => {
  const { clock, seen } = setup(on)
  await start($)
  await turn($, 't1', usage(0, 90_000))
  expect((await run($, 'cache', 'warm on')).text).toContain('up to 24 times')

  await clock.advance(58 * MINUTE)
  expect(seen.forks).toEqual([])

  await clock.advance(MINUTE + 10_000)
  expect(seen.forks).toHaveLength(1)
  expect(seen.statuses.at(-1)).toStartWith('cache warm 59:')
  expect(seen.statuses.at(-1)).toEndWith('keep-warm 1/24')
})

const agentTurn = ($: Engine, agentId: string, written: number) =>
  $.turn.complete({
    answer: 'done',
    durationMs: 1000,
    isAborted: false,
    turnId: `turn-${agentId}`,
    agentId,
    reason: 'answer',
    usage: usage(0, written),
  })

const send = ($: Engine, to: string) => $.tool.call({ tool: 'SendMessage', to, message: 'carry on' })

test('holds a resume of a large subagent whose cache has lapsed, once', FIVE, async ($, on) => {
  const { clock } = setup(on)
  await start($)
  await agentTurn($, 'a1', 120_000)
  await clock.advance(6 * MINUTE)

  const first = await send($, 'a1')
  expect(first.deny).toStartWith('cache-guard: this agent has been idle 6m')
  expect(first.deny).toContain('about 120k tokens')

  expect((await send($, 'a1')).deny).toBe('test')
})

test('finds the agent by the name a message addresses it with', FIVE, async ($, on) => {
  const { clock } = setup(on)
  await start($)
  await agentTurn($, 'a2', 120_000)
  await clock.advance(6 * MINUTE)

  expect((await send($, 'worker')).deny).toStartWith('cache-guard: this agent has been idle 6m')
})

test('lets a message through to a warm, a small or an unknown agent', FIVE, async ($, on) => {
  const { clock } = setup(on)
  await start($)
  await agentTurn($, 'a1', 120_000)
  await agentTurn($, 'a3', 5000)
  await clock.advance(2 * MINUTE)
  expect((await send($, 'a1')).deny).toBe('test')

  await clock.advance(6 * MINUTE)
  expect((await send($, 'a3')).deny).toBe('test')
  expect((await send($, 'someone-else')).deny).toBe('test')
})

test('nudges once when the context first passes the threshold', FIVE, async ($, on) => {
  const { seen } = setup(on)
  await start($)
  seen.context = 310_000
  await turn($, 't1', usage(0, 310_000))
  await turn($, 't2', usage(310_000, 500))

  expect(seen.toasts).toHaveLength(1)
  expect(seen.toasts[0]).toStartWith('Context is at 310k tokens')
})

test('keeps pinging when a ping writes about a thousand output tokens', WARM, async ($, on) => {
  const { clock, seen } = setup(on)
  seen.pingOutput = 1170
  await start($)
  await turn($, 't1', usage(0, 90_000))
  await clock.advance(10 * MINUTE)

  expect(seen.forks).toHaveLength(2)
  expect(seen.toasts).toEqual([])
})

test('a second cold agent does not cancel the hold on the first', FIVE, async ($, on) => {
  const { clock } = setup(on)
  await start($)
  await agentTurn($, 'a1', 120_000)
  await agentTurn($, 'b1', 120_000)
  await clock.advance(6 * MINUTE)

  expect((await send($, 'a1')).deny).toStartWith('cache-guard:')
  expect((await send($, 'b1')).deny).toStartWith('cache-guard:')
  expect((await send($, 'a1')).deny).toBe('test')
  expect((await send($, 'b1')).deny).toBe('test')
})

test('the repeat goes through however late it comes', FIVE, async ($, on) => {
  const { clock } = setup(on)
  await start($)
  await agentTurn($, 'a1', 120_000)
  await clock.advance(6 * MINUTE)
  expect((await send($, 'a1')).deny).toStartWith('cache-guard:')

  await clock.advance(3 * MINUTE)
  expect((await send($, 'a1')).deny).toBe('test')
})

test('does not hold a message to a running agent or a teammate', FIVE, async ($, on) => {
  const { clock, seen } = setup(on)
  seen.agents = [
    { id: 'a1', name: 'runner', description: 'busy', type: 'general-purpose', status: 'running' },
    { id: 'a4', name: 'mate', description: 'teammate', type: 'teammate', status: 'idle' },
  ]
  await start($)
  await agentTurn($, 'a1', 120_000)
  await agentTurn($, 'a4', 120_000)
  await clock.advance(6 * MINUTE)

  expect((await send($, 'a1')).deny).toBe('test')
  expect((await send($, 'mate')).deny).toBe('test')
})

test('a run that re-caches its context does not double the size estimate', FIVE, async ($, on) => {
  const { clock } = setup(on)
  await start($)
  await agentTurn($, 'a1', 12_000)
  await agentTurn($, 'a1', 12_000)
  await agentTurn($, 'a1', 12_000)
  await clock.advance(6 * MINUTE)

  expect((await send($, 'a1')).deny).toBe('test')
})

test('a cold resume with several requests does not double the size estimate', FIVE, async ($, on) => {
  const { clock } = setup(on)
  await start($)
  await agentTurn($, 'a1', 120_000)
  await $.turn.complete({
    answer: 'done',
    durationMs: 1000,
    isAborted: false,
    turnId: 'turn-a1-again',
    agentId: 'a1',
    reason: 'answer',
    usage: usage(240_000, 122_000),
  })
  await clock.advance(6 * MINUTE)

  expect((await send($, 'a1')).deny).toContain('about 122k tokens')
})
