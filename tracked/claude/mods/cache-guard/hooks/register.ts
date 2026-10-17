import type { EngineInterface, Register } from 'claude-code'

const SECOND = 1000
const MINUTE = 60 * SECOND
const HOUR = 60 * MINUTE
const TICK_MS = 5 * SECOND
const CONFIRM_MS = 30 * SECOND
// Keep-warm pings start this long before the cache would lapse.
const LEAD_MS = 60 * SECOND
// Output costs about five times input, so a ping whose output (thinking included) passes this
// share of the context costs a meaningful part of the rewrite it avoids. Never under the floor:
// a live ping at high effort writes about a thousand tokens.
const MAX_PING_OUTPUT_SHARE = 0.05
const MIN_PING_OUTPUT_LIMIT = 4000
// Subagents write the 5-minute cache tier, whatever the main thread's lifetime is.
const AGENT_TTL_MS = 5 * MINUTE
const PING_PROMPT = 'Reply with exactly one word: ok'
// A turn that wrote at least this share of the previous context to the cache beyond what the
// turn added is counted as a miss; a ping that read less than this share did not hit the cache.
const MISS_SHARE = 0.5

const emptyStats = () => ({
  read: 0,
  written: 0,
  uncached: 0,
  lapsed: 0,
  unexpected: 0,
  recached: 0,
  pings: 0,
  pingRead: 0,
  pingOutput: 0,
})

// What `register` reads from the options, and what the session has shown so far.
// A reload runs the module again, so both start over with it.
const config = {
  ttlLabel: '1h',
  ttlMs: HOUR,
  minTokens: 30_000,
  isGuarding: true,
  keepWarmMax: 24,
  contextNudgeTokens: 300_000,
}
const state = {
  // When the latest request that touches the cache started: the cache's own clock runs from here.
  requestAt: undefined as number | undefined,
  // The longest stretch this turn went without a request, before its first and between tool batches.
  gapMs: 0,
  contextTokens: undefined as number | undefined,
  // The context when the turn began: what the turn's cache reads and writes are measured against.
  priorContext: undefined as number | undefined,
  isBusy: false,
  // Main-thread tools running now: while any are, the model has no request in flight.
  toolsInFlight: 0,
  heldAt: undefined as number | undefined,
  isKeepingWarm: false,
  isPinging: false,
  idlePings: 0,
  shown: undefined as string | undefined,
  hasNudged: false,
  // Each subagent's last activity and how much it has written to its cache, which is about
  // the size of its context.
  agents: new Map<string, { at: number; tokens: number }>(),
  // Agents whose resume was held once; the next message to one goes through.
  heldResumes: new Set<string>(),
  stats: emptyStats(),
}

const count = (n: number) =>
  n >= 1_000_000
    ? `${(n / 1_000_000).toFixed(1)}M`
    : n >= 1000
      ? `${Math.round(n / 1000)}k`
      : `${n}`

const clock = (ms: number) => {
  const seconds = Math.max(0, Math.ceil(ms / SECOND))

  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

const minutes = (ms: number) => `${Math.round(ms / MINUTE)}m`

// No request of the main thread is in flight: it is idle, or waiting on its own tools or agents.
const isCacheUnused = () => !state.isBusy || state.toolsInFlight > 0

const markRequest = (now: number) => {
  if (state.requestAt !== undefined) {
    state.gapMs = Math.max(state.gapMs, now - state.requestAt)
  }
  state.requestAt = now
  state.idlePings = 0
}

const msLeft = (now: number) =>
  state.requestAt === undefined ? 0 : state.requestAt + config.ttlMs - now

const isWorthGuarding = () =>
  state.contextTokens !== undefined && state.contextTokens >= config.minTokens

const statusText = (now: number) => {
  if (!isCacheUnused() || state.requestAt === undefined || !isWorthGuarding()) {
    return undefined
  }
  const left = msLeft(now)
  const tokens = count(state.contextTokens ?? 0)
  const pings = state.isKeepingWarm ? ` · keep-warm ${state.idlePings}/${config.keepWarmMax}` : ''

  return left > 0
    ? `cache warm ${clock(left)} · ${tokens} ctx${pings}`
    : `cache cold · next prompt re-caches ~${tokens}`
}

const refresh = async ($: EngineInterface) => {
  const text = statusText(await $.clock.now())
  if (text !== state.shown) {
    state.shown = text
    $.ui.status(text)
  }
}

// One cheap request over the session's own transcript while the cache is about to lapse: the
// API serves the prefix from the cache and restarts its timer. Any sign it does not pay off
// turns keep-warm off for the session.
const pingIfDue = async ($: EngineInterface) => {
  const startedAt = await $.clock.now()
  const left = msLeft(startedAt)
  const isDue =
    state.isKeepingWarm &&
    isCacheUnused() &&
    !state.isPinging &&
    state.idlePings < config.keepWarmMax &&
    isWorthGuarding() &&
    left > 0 &&
    left <= LEAD_MS
  if (!isDue) {
    return
  }

  state.isPinging = true
  const stop = (why: string) => {
    const text = `Keep-warm stopped: ${why} Turn it back on with /cache warm on.`
    state.isKeepingWarm = false
    $.ui.toast(text, { timeoutMs: 10_000 })
    $.ui.log(text)
  }
  try {
    const reply = await $.model.fork({ prompt: PING_PROMPT })
    if (!('usage' in reply)) {
      stop('there is nothing to keep warm yet.')

      return
    }
    const read = reply.usage.cache_read_input_tokens
    const output = reply.usage.output_tokens
    state.stats.pings += 1
    state.stats.pingRead += read
    state.stats.pingOutput += output

    if (!reply.isAnswered && reply.reason === 'api-error') {
      stop(`the ping failed (${reply.error}).`)
    } else if (read < (state.contextTokens ?? 0) * MISS_SHARE) {
      stop(`a ping read only ${count(read)} tokens from the cache, so it would just re-cache them.`)
    } else {
      state.requestAt = Math.max(state.requestAt ?? startedAt, startedAt)
      state.idlePings += 1
      $.ui.log(
        `Keep-warm ping ${state.idlePings}/${config.keepWarmMax}: read ${count(read)} tokens from the cache, ${output} output tokens. The cache timer restarted.`,
      )
      const limit = Math.max(
        MIN_PING_OUTPUT_LIMIT,
        (state.contextTokens ?? 0) * MAX_PING_OUTPUT_SHARE,
      )
      if (output > limit) {
        stop(`a ping wrote ${output} output tokens, too much for what it saves.`)
      }
    }
  } catch {
    stop('the ping was refused.')
  } finally {
    state.isPinging = false
  }
}

const report = (now: number) => {
  const { stats } = state
  const lines = [`Prompt cache (lifetime ${config.ttlLabel})`]
  const left = msLeft(now)
  if (state.requestAt === undefined) {
    lines.push('  state    no response yet')
  } else if (!isCacheUnused()) {
    lines.push('  state    in use')
  } else {
    const waiting = state.isBusy ? ' (waiting on tools)' : ''
    lines.push(
      left > 0
        ? `  state    warm, ${clock(left)} left${waiting}`
        : `  state    cold for ${minutes(-left)}${waiting}`,
    )
  }
  if (state.contextTokens !== undefined) {
    lines.push(`  context  ${count(state.contextTokens)} tokens`)
  }
  const input = stats.read + stats.written + stats.uncached
  if (input > 0) {
    lines.push(
      `  hit rate ${Math.round((100 * stats.read) / input)}% (read ${count(stats.read)}, written ${count(stats.written)}, uncached ${count(stats.uncached)})`,
    )
  }
  lines.push(
    `  misses   ${stats.lapsed} after idling past the lifetime, ${stats.unexpected} while warm; ~${count(stats.recached)} tokens re-cached`,
  )
  lines.push(
    `  keep-warm ${state.isKeepingWarm ? `on, up to ${config.keepWarmMax} per idle stretch` : 'off (/cache warm on)'}; ${stats.pings} pings, read ${count(stats.pingRead)}, ${stats.pingOutput} output tokens`,
  )
  if (!state.isBusy && state.requestAt !== undefined && left <= 0 && isWorthGuarding()) {
    lines.push(
      '',
      'The next prompt re-caches the whole context; /clear first if the next task is unrelated.',
    )
  }

  return lines.join('\n')
}

const touchAgent = (agentId: string, now: number) => {
  state.agents.set(agentId, { at: now, tokens: state.agents.get(agentId)?.tokens ?? 0 })
  state.heldResumes.delete(agentId)
}

export const register: Register = (on, options) => {
  config.ttlLabel = options.ttl === '5m' ? '5m' : '1h'
  config.ttlMs = config.ttlLabel === '5m' ? 5 * MINUTE : HOUR
  config.minTokens = typeof options.minTokens === 'number' ? options.minTokens : 30_000
  config.isGuarding = options.guardModelSwitch !== false
  config.keepWarmMax = typeof options.keepWarmMax === 'number' ? options.keepWarmMax : 24
  state.isKeepingWarm = options.keepWarm === true
  config.contextNudgeTokens =
    typeof options.contextNudgeTokens === 'number' ? options.contextNudgeTokens : 300_000

  on('session.start', async ($, e, next) => {
    // A reload starts with empty state, so text an earlier load left on the status line would
    // sit there frozen.
    state.shown = undefined
    $.ui.status(undefined)
    await $.command.register({
      name: 'cache',
      description: 'Prompt-cache state and the re-caching this session paid for',
      immediate: true,
    })
    $.clock.every(TICK_MS, () => {
      refresh($).catch(() => undefined)
      pingIfDue($).catch(() => undefined)
    })

    return next(e)
  })

  on('session.end', ($, e, next) => {
    state.requestAt = undefined
    state.contextTokens = undefined
    state.priorContext = undefined
    state.gapMs = 0
    state.idlePings = 0
    state.toolsInFlight = 0
    state.isBusy = false
    state.heldAt = undefined
    state.shown = undefined
    state.hasNudged = false
    state.agents.clear()
    state.heldResumes.clear()
    state.stats = emptyStats()
    $.ui.status(undefined)

    return next(e)
  })

  on('turn.start', async ($, e, next) => {
    state.gapMs = 0
    state.priorContext = state.contextTokens
    state.toolsInFlight = 0
    state.isBusy = true
    markRequest(await $.clock.now())
    // The status line is blank while a turn runs; clear it outright rather than only when this
    // load last drew something.
    state.shown = undefined
    $.ui.status(undefined)

    return next(e)
  })

  on('tool.call', { tool: 'SendMessage' }, async ($, e, next) => {
    // A message to a subagent that has sat idle past its cache's lifetime makes it read its
    // whole context uncached. Hold the first such send so a fresh agent can be chosen instead;
    // the next message to that agent goes through, however long the model takes to send it.
    const now = await $.clock.now()
    const listed = await $.agent.list().catch(() => [])
    const to = String(e.to)
    const info = listed.find(one => one.id === to || one.name === to)
    const agentId = info?.id ?? (state.agents.has(to) ? to : undefined)
    const agent = agentId === undefined ? undefined : state.agents.get(agentId)
    if (
      !config.isGuarding ||
      agentId === undefined ||
      agent === undefined ||
      info?.status === 'running' ||
      info?.type === 'teammate' ||
      agent.tokens < config.minTokens ||
      now - agent.at <= AGENT_TTL_MS
    ) {
      return next(e)
    }
    if (state.heldResumes.delete(agentId)) {
      return next(e)
    }
    state.heldResumes.add(agentId)

    return {
      deny: `cache-guard: this agent has been idle ${minutes(now - agent.at)} and its cache has lapsed, so resuming it re-caches about ${count(agent.tokens)} tokens. If its context is not needed, a fresh agent with a short brief is cheaper. If it owns a correction or a later review phase, or you need its context anyway, send the message again to resume it.`,
    }
  })

  on('tool.call', async ($, e, next) => {
    if (e.agentId !== undefined) {
      touchAgent(e.agentId, await $.clock.now())

      return next(e)
    }
    if (!state.isBusy) {
      return next(e)
    }
    // The cache's clock keeps running while the model's tools work; its next request starts
    // when the last of them is done. A subagent's own tools say nothing about the main cache.
    const isFirst = state.toolsInFlight === 0
    state.toolsInFlight += 1
    try {
      if (isFirst) {
        const usage = await $.session.usage().catch(() => undefined)
        state.contextTokens = usage?.context.tokens ?? state.contextTokens
      }

      return await next(e)
    } finally {
      state.toolsInFlight = Math.max(0, state.toolsInFlight - 1)
      if (state.toolsInFlight === 0 && state.isBusy) {
        markRequest(await $.clock.now())
      }
    }
  })

  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    if (e.agentId !== undefined) {
      // What an agent writes to its cache or sends uncached adds up to about its context size.
      // A run that wrote about as much as the agent already held cached it again after a lapse,
      // so that run's figure replaces the estimate instead of adding to it.
      touchAgent(e.agentId, await $.clock.now())
      const agent = state.agents.get(e.agentId)
      if (agent !== undefined && e.usage !== undefined) {
        const grown = e.usage.cache_creation_input_tokens + e.usage.input_tokens
        const isRewrite = agent.tokens > 0 && grown >= agent.tokens * MISS_SHARE
        agent.tokens = isRewrite ? grown : agent.tokens + grown
      }

      return result
    }

    state.isBusy = false
    state.toolsInFlight = 0

    if (e.usage !== undefined) {
      const read = e.usage.cache_read_input_tokens
      const written = e.usage.cache_creation_input_tokens
      state.stats.read += read
      state.stats.written += written
      state.stats.uncached += e.usage.input_tokens
      const end = (await $.session.usage()).context.tokens
      state.contextTokens = end ?? state.contextTokens
      if (!state.hasNudged && end !== undefined && end >= config.contextNudgeTokens) {
        state.hasNudged = true
        $.ui.toast(
          `Context is at ${count(end)} tokens and every request re-reads it. At a task boundary, /compact or /clear keeps later requests cheaper.`,
          { timeoutMs: 10_000 },
        )
      }

      // Each request writes only what is new since the one before, so what the turn wrote beyond
      // its own growth is context that had to be cached again.
      const previous = state.priorContext
      if (previous !== undefined && end !== undefined && previous >= config.minTokens) {
        const recached = Math.max(0, written - Math.max(0, end - previous))
        if (recached >= previous * MISS_SHARE) {
          state.stats.recached += recached
          if (state.gapMs > config.ttlMs) {
            state.stats.lapsed += 1
            $.ui.toast(
              `Cache lapsed after ${minutes(state.gapMs)} without a request: ~${count(recached)} tokens re-cached.`,
              { timeoutMs: 8000 },
            )
          } else {
            state.stats.unexpected += 1
            $.ui.toast(
              `Cache miss while warm: ~${count(recached)} tokens re-cached. Something early in the prompt changed (model, tools, instructions).`,
              { timeoutMs: 8000 },
            )
          }
        }
      }
    }
    await refresh($)

    return result
  })

  on('session.compact', async ($, e, next) => {
    const result = await next(e)
    if (e.agentId === undefined && e.trigger !== 'precompute' && result.skip === undefined) {
      state.requestAt = undefined
      state.contextTokens = undefined
      state.priorContext = undefined
      state.hasNudged = false
      await refresh($)
    }

    return result
  })

  on('command.run', { command: 'cache' }, async ($, e) => {
    const [verb, value] = e.args.trim().split(/\s+/)
    if (verb !== 'warm') {
      return { text: report(await $.clock.now()) }
    }
    if (value !== 'on' && value !== 'off') {
      return { text: 'Usage: /cache warm on|off' }
    }
    state.isKeepingWarm = value === 'on'
    await refresh($)

    return {
      text: state.isKeepingWarm
        ? `Keep-warm on: a one-word background request keeps the cache alive, up to ${config.keepWarmMax} times per idle stretch.`
        : 'Keep-warm off.',
    }
  })

  on('command.run', { command: 'model' }, async ($, e, next) => {
    const now = await $.clock.now()
    const isWarm = state.isBusy || msLeft(now) > 0
    if (!config.isGuarding || !isWarm || !isWorthGuarding() || state.contextTokens === undefined) {
      return next(e)
    }
    if (state.heldAt !== undefined && now - state.heldAt < CONFIRM_MS) {
      state.heldAt = undefined

      return next(e)
    }
    state.heldAt = now
    const window = state.isBusy ? 'in use' : `${clock(msLeft(now))} left`

    return {
      text: `/model held: the prompt cache is warm (${count(state.contextTokens)} tokens, ${window}) and a new model re-caches all of it. Run /model again within 30s to switch anyway.`,
    }
  })
}
