import coordinatorPlugin from "../../tracked/opencode/plugins/setforge-agent-coordinator.ts"
import planPlugin from "../../tracked/opencode/plugins/setforge-plan-workflow.ts"
import { chmod, mkdir, rm, stat, writeFile } from "node:fs/promises"
import { join } from "node:path"

const KEY = "setforgeCoordinator"

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message)
}

function response(data: any) {
  return { data }
}

class FakeClient {
  sessions = new Map<string, any>()
  messageStore = new Map<string, any[]>()
  statuses: Record<string, any> = {}
  promptBodies: { id: string; directory: string; body: any }[] = []
  forkQueries: string[] = []
  createQueries: string[] = []
  removedWorktrees: string[] = []
  events: any[] = []
  eventWaiters: ((value: IteratorResult<any>) => void)[] = []
  nextID = 1
  createDelay = 0
  failNextCreate = false
  failNextFork = false
  hooks: any

  constructor(rootID = "root") {
    this.sessions.set(rootID, {
      id: rootID,
      directory: "/project",
      metadata: { foreign: "preserve" },
      agent: "build",
      model: { providerID: "openai", id: "gpt-5.6-sol", variant: "medium" },
    })
    this.messageStore.set(rootID, [{
      info: { id: "root-user", sessionID: rootID, role: "user" },
      parts: [{ type: "text", text: "root context" }],
    }])
    this.statuses[rootID] = { type: "idle" }
  }

  clone<T>(value: T): T {
    return structuredClone(value)
  }

  emit(event: any) {
    const waiter = this.eventWaiters.shift()
    if (waiter) waiter({ value: event, done: false })
    else this.events.push(event)
  }

  stream = {
    [Symbol.asyncIterator]: () => ({
      next: async (): Promise<IteratorResult<any>> => {
        const event = this.events.shift()
        if (event) return { value: event, done: false }
        return await new Promise((resolve) => this.eventWaiters.push(resolve))
      },
    }),
  }

  session: any

  provider = {
    list: async () => response({
      all: [{ id: "openai", models: {
        "gpt-5.6-sol": { id: "gpt-5.6-sol", variants: { low: {}, medium: {}, high: {}, max: {} } },
        "gpt-5.6-luna": { id: "gpt-5.6-luna", variants: { max: {} } },
        "gpt-6-astra": { id: "gpt-6-astra", variants: { low: {} } },
        "gpt-5.6-terra": { id: "gpt-5.6-terra", variants: { low: {} } },
      } }],
    }),
  }

  global = {
    event: async () => ({ stream: this.stream }),
  }

  initialize() {
    this.session = {
      get: async ({ path }: any) => {
        const item = this.sessions.get(path.id)
        if (!item) return { error: "missing session" }
        return response(this.clone(item))
      },
      list: async () => response(this.clone([...this.sessions.values()])),
      status: async () => response(this.clone(this.statuses)),
      messages: async ({ path }: any) => response(this.clone(this.messageStore.get(path.id) ?? [])),
      update: async ({ path, body }: any) => {
        const current = this.sessions.get(path.id)
        if (!current) return { error: "missing session" }
        const updated = { ...current, ...body }
        this.sessions.set(path.id, updated)
        return response(this.clone(updated))
      },
      create: async ({ query, body }: any) => {
        this.createQueries.push(query.directory)
        if (this.failNextCreate) {
          this.failNextCreate = false
          return { error: "forced create failure" }
        }
        if (this.createDelay) await Bun.sleep(this.createDelay)
        const id = `session-${this.nextID++}`
        const created = {
          id,
          directory: query.directory,
          parentID: body.parentID,
          title: body.title,
          agent: body.agent,
          model: body.model ? { providerID: body.model.providerID, id: body.model.id } : undefined,
          metadata: body.metadata ?? {},
        }
        this.sessions.set(id, created)
        this.messageStore.set(id, [])
        this.statuses[id] = { type: "idle" }
        return response(this.clone(created))
      },
      fork: async ({ path, query }: any) => {
        this.forkQueries.push(query.directory)
        if (this.failNextFork) {
          this.failNextFork = false
          return { error: "forced fork failure" }
        }
        const id = `session-${this.nextID++}`
        const created = { id, directory: query.directory, metadata: {} }
        this.sessions.set(id, created)
        this.messageStore.set(id, this.clone(this.messageStore.get(path.id) ?? []))
        this.statuses[id] = { type: "idle" }
        return response(this.clone(created))
      },
      delete: async ({ path }: any) => {
        this.sessions.delete(path.id)
        this.messageStore.delete(path.id)
        delete this.statuses[path.id]
        return response(true)
      },
      promptAsync: async ({ path, query, body }: any) => {
        this.promptBodies.push({ id: path.id, directory: query.directory, body: this.clone(body) })
        const messages = this.messageStore.get(path.id) ?? []
        const userID = `user-${this.nextID++}`
        messages.push({ info: { id: userID, sessionID: path.id, role: "user", agent: body.agent }, parts: this.clone(body.parts ?? []) })
        this.messageStore.set(path.id, messages)
        if (body.noReply) return response(true)
        const text = (body.parts ?? []).map((part: any) => part.text ?? "").join("")
        if (text.includes("HOLD")) {
          messages.push({
            info: { id: `assistant-${this.nextID++}`, sessionID: path.id, role: "assistant", parentID: userID, finish: "tool-calls", time: { completed: Date.now() } },
            parts: [{ type: "text", text: "PARTIAL" }],
          })
          this.statuses[path.id] = { type: "busy" }
          return response(true)
        }
        messages.push({
          info: { id: `assistant-${this.nextID++}`, sessionID: path.id, role: "assistant", parentID: userID, finish: "tool-calls", time: { completed: Date.now() } },
          parts: [{ type: "text", text: "PARTIAL" }],
        })
        messages.push({
          info: { id: `assistant-${this.nextID++}`, sessionID: path.id, role: "assistant", parentID: userID, finish: "stop", time: { completed: Date.now() } },
          parts: [{ type: "text", text: `DONE:${text}` }],
        })
        this.statuses[path.id] = { type: "idle" }
        return response(true)
      },
      prompt: async () => ({ error: "unexpected synchronous prompt" }),
      abort: async ({ path }: any) => {
        this.statuses[path.id] = { type: "idle" }
        queueMicrotask(() => void this.hooks?.event?.({ event: { type: "session.status", properties: { sessionID: path.id, status: { type: "idle" } } } }))
        return response(true)
      },
    }
  }
}

function toolContext(rootID = "root") {
  return { sessionID: rootID, messageID: "root-user", directory: "/project" }
}

async function makeCoordinator(rootID = "root") {
  const client = new FakeClient(rootID)
  client.initialize()
  const originalFetch = globalThis.fetch
  globalThis.fetch = (async (input: any, init?: RequestInit) => {
    const url = new URL(String(input))
    if (url.pathname !== "/experimental/worktree") return new Response("missing", { status: 404 })
    if (init?.method === "DELETE") {
      const body = JSON.parse(String(init.body))
      client.removedWorktrees.push(body.directory)
      return new Response(JSON.stringify({ data: true }), { status: 200 })
    }
    const body = JSON.parse(String(init?.body))
    const info = { name: body.name, branch: `opencode/${body.name}`, directory: `/worktrees/${body.name}` }
    queueMicrotask(() => client.emit({ directory: info.directory, payload: { type: "worktree.ready", properties: { name: info.name, branch: info.branch } } }))
    return new Response(JSON.stringify({ data: info }), { status: 200 })
  }) as any
  const hooks = await coordinatorPlugin({ client, directory: "/project", serverUrl: new URL("http://opencode.test") } as any)
  client.hooks = hooks
  return { client, hooks, restore: () => { globalThis.fetch = originalFetch } }
}

async function coordinatorRecoveryChecks() {
  const { client, hooks, restore } = await makeCoordinator()
  try {
    const context = toolContext()
    const mailed = JSON.parse(await hooks.tool.spawn_agent.execute({
      task_name: "mailed", message: "HOLD tool-using child", fork_turns: "none",
    }, context))
    await hooks.tool.send_message.execute({ target: mailed.id, message: "mail during tool use" }, context)
    const pending = JSON.parse(await hooks.tool.wait_agent.execute({ targets: [mailed.id], after_generation: 0, timeout_ms: 30 }, context))
    assert(pending.timeout === true, "wait returned mail delivery as completed work")
    const mailedMessages = client.messageStore.get(mailed.id)!
    const mailUser = mailedMessages.findLast((message) => message.info.role === "user")
    mailedMessages.push({
      info: { id: "mailed-final", sessionID: mailed.id, role: "assistant", parentID: mailUser.info.id, finish: "stop", time: { completed: Date.now() } },
      parts: [{ type: "text", text: "DONE after mailed evidence" }],
    })
    client.statuses[mailed.id] = { type: "idle" }
    const mailedResult = JSON.parse(await hooks.tool.wait_agent.execute({ targets: [mailed.id], after_generation: 0, timeout_ms: 1000 }, context))
    assert(mailedResult.output === "DONE after mailed evidence", "busy mail detached the terminal response from its generation")

    const reviewer = JSON.parse(await hooks.tool.spawn_agent.execute({
      task_name: "reviewer", message: "HOLD reviewer", agent_type: "review_correctness", fork_turns: "none",
    }, context))
    await hooks.tool.send_message.execute({ target: reviewer.id, message: "new evidence" }, context)
    const mail = client.promptBodies.at(-1)!.body
    assert(mail.agent === "review_correctness", "send_message changed the reviewer role")
    assert(mail.model?.providerID === "openai" && mail.model?.modelID === "gpt-6-astra", "send_message changed the reviewer model")
    assert(mail.variant === "low", "send_message changed the reviewer effort")

    await hooks.tool.followup_task.execute({ target: reviewer.id, message: "queued before interrupt" }, context)
    const interrupted = JSON.parse(await hooks.tool.interrupt_agent.execute({ target: reviewer.id }, context))
    assert(interrupted.previous_state === "busy", "interrupt did not report the previous state")
    await Bun.sleep(0)
    const interruptedMeta = client.sessions.get(reviewer.id).metadata[KEY]
    assert(interruptedMeta.interrupted === true, "interrupt state was not persisted")
    assert(interruptedMeta.queue.every((item: any) => !["queued", "dispatching", "accepted"].includes(item.state)), "interrupt left dispatchable work")

    const recovery = JSON.parse(await hooks.tool.followup_task.execute({ target: reviewer.id, message: "recover explicitly" }, context))
    const recovered = JSON.parse(await hooks.tool.wait_agent.execute({ targets: [reviewer.id], after_generation: recovery.generation - 1, timeout_ms: 1000 }, context))
    assert(recovered.output.includes("DONE:recover explicitly"), "explicit follow-up did not recover the interrupted child")

    const terminal = JSON.parse(await hooks.tool.spawn_agent.execute({ task_name: "terminal", message: "terminal response", fork_turns: "none" }, context))
    const first = JSON.parse(await hooks.tool.wait_agent.execute({ targets: [terminal.id], after_generation: 0, timeout_ms: 1000 }, context))
    const second = JSON.parse(await hooks.tool.wait_agent.execute({ targets: [terminal.id], after_generation: 0, timeout_ms: 1000 }, context))
    assert(first.output.includes("DONE:terminal response") && !first.output.includes("PARTIAL"), "wait returned an intermediate tool response")
    assert(JSON.stringify(first) === JSON.stringify(second), "wait consumed another observer's result")

    client.messageStore.get("root")!.push({
      info: { id: "root-tool", sessionID: "root", role: "assistant" },
      parts: [{ type: "tool", tool: "read", state: { status: "completed", output: "tool-output-sentinel" } }],
    })
    const isolated = JSON.parse(await hooks.tool.spawn_agent.execute({ task_name: "isolated", message: "isolated fork", fork_turns: "all", isolation: true }, context))
    assert(client.createQueries.at(-1) === isolated.directory, "isolated all-context child used the root directory")
    const seed = client.promptBodies.find((item) => item.id === isolated.id && item.body.noReply && item.body.parts?.[0]?.text?.startsWith("CONTEXT FROM PARENT:"))
    assert(seed, "isolated all-context child was not seeded before dispatch")
    assert(seed.body.parts[0].text.includes("tool-output-sentinel"), "isolated all-context seed dropped tool output")
    client.failNextCreate = true
    let failed = false
    try {
      await hooks.tool.spawn_agent.execute({ task_name: "cleanup", message: "fail after readiness", fork_turns: "all", isolation: true }, context)
    } catch {
      failed = true
    }
    assert(failed, "forced isolated setup failure unexpectedly succeeded")
    assert(client.removedWorktrees.includes("/worktrees/setforge-cleanup"), "failed isolated setup retained its worktree")
    const rootMeta = client.sessions.get("root").metadata[KEY]
    assert(!rootMeta.reservations?.some((item: any) => item.taskPath === "/root/cleanup"), "failed setup retained its slot reservation")
    assert(!rootMeta.children?.some((item: any) => item.taskPath === "/root/cleanup"), "failed setup retained its child link")
  } finally {
    restore()
  }
}

async function coordinatorCapacityChecks() {
  const { client, hooks, restore } = await makeCoordinator("capacity-root")
  client.createDelay = 25
  try {
    const context = toolContext("capacity-root")
    const attempts = await Promise.allSettled(Array.from({ length: 13 }, (_, index) => hooks.tool.spawn_agent.execute({
      task_name: `child_${index}`, message: `work ${index}`, fork_turns: "none",
    }, context)))
    const fulfilled = attempts.filter((item) => item.status === "fulfilled") as PromiseFulfilledResult<string>[]
    const rejected = attempts.filter((item) => item.status === "rejected")
    assert(fulfilled.length === 12 && rejected.length === 1, "concurrent spawn exceeded the active-child cap")
    for (const item of fulfilled) {
      const child = JSON.parse(item.value)
      await hooks.tool.wait_agent.execute({ targets: [child.id], after_generation: 0, timeout_ms: 1000 }, context)
    }
    const replacement = JSON.parse(await hooks.tool.spawn_agent.execute({ task_name: "replacement", message: "after completion", fork_turns: "none" }, context))
    assert(replacement.task_path === "/root/replacement", "historical completed children exhausted the active-child cap")
    await hooks.tool.wait_agent.execute({ targets: [replacement.id], after_generation: 0, timeout_ms: 1000 }, context)
    for (const item of fulfilled.slice(0, 11)) {
      const child = JSON.parse(item.value)
      await hooks.tool.followup_task.execute({ target: child.id, message: "HOLD active" }, context)
    }
    client.createDelay = 50
    const pendingSpawn = hooks.tool.spawn_agent.execute({ task_name: "reserved_spawn", message: "reserved overlap", fork_turns: "none" }, context)
    await Bun.sleep(5)
    let activationRejected = false
    try {
      const idleChild = JSON.parse(fulfilled[11].value)
      await hooks.tool.followup_task.execute({ target: idleChild.id, message: "overlap with reserved spawn" }, context)
    } catch {
      activationRejected = true
    }
    assert(activationRejected, "follow-up activation bypassed a reserved active slot")
    await pendingSpawn
  } finally {
    restore()
  }
}

async function coordinatorRestartChecks() {
  const { client, hooks, restore } = await makeCoordinator("restart-root")
  try {
    const context = toolContext("restart-root")
    const child = JSON.parse(await hooks.tool.spawn_agent.execute({
      task_name: "restart", message: "completed before acknowledgement", fork_turns: "none",
    }, context))
    const stored = client.sessions.get(child.id)
    stored.metadata[KEY].queue[0].state = "dispatching"
    client.sessions.get("restart-root").metadata[KEY].reservations = [{ taskPath: "/root/stale", created: Date.now() - 1000 }]
    const promptsBefore = client.promptBodies.filter((item) => item.id === child.id && !item.body.noReply).length

    const restarted = await coordinatorPlugin({ client, directory: "/project", serverUrl: new URL("http://opencode.test") } as any)
    client.hooks = restarted
    await Bun.sleep(25)
    const recoveredEnvelope = client.sessions.get(child.id).metadata[KEY].queue[0]
    const promptsAfter = client.promptBodies.filter((item) => item.id === child.id && !item.body.noReply).length
    assert(recoveredEnvelope.state === "completed" && recoveredEnvelope.result.includes("DONE:completed before acknowledgement"), "startup did not recover a completed response")
    assert(promptsAfter === promptsBefore, "restart replayed an accepted request")
    assert(client.sessions.get("restart-root").metadata[KEY].reservations.length === 0, "startup retained an abandoned slot reservation")

    const meta = client.sessions.get(child.id).metadata[KEY]
    meta.queue.push({
      id: "restart-queued", kind: "followup", text: "dispatch after restart",
      state: "queued", generation: 2, created: Date.now(),
    })
    const restartedAgain = await coordinatorPlugin({ client, directory: "/project", serverUrl: new URL("http://opencode.test") } as any)
    client.hooks = restartedAgain
    await Bun.sleep(25)
    const dispatched = client.sessions.get(child.id).metadata[KEY].queue.find((item: any) => item.generation === 2)
    assert(dispatched.state === "completed" && dispatched.result.includes("DONE:dispatch after restart"), "startup did not dispatch persisted queued work")
    const queuedUsers = (client.messageStore.get(child.id) ?? []).filter((message) =>
      message.info.role === "user" && message.parts.some((part: any) => part.metadata?.setforge_operation_id === "restart-queued"),
    )
    assert(queuedUsers.length === 1, "restart dispatched persisted queued work more than once")
  } finally {
    restore()
  }
}

async function planFailureChecks() {
  const runtime = process.env.PLAN_TEST_RUNTIME
  assert(runtime, "PLAN_TEST_RUNTIME is missing")
  const scripts = join(runtime, "scripts")
  await mkdir(scripts, { recursive: true })
  const launcher = join(scripts, "launch-plan-review.sh")
  await writeFile(launcher, "#!/bin/sh\nprintf 'credential=do-not-publish\\n' >&2\nexit 1\n")
  await chmod(launcher, 0o755)

  const client = new FakeClient("plan-root")
  client.initialize()
  client.sessions.get("plan-root").agent = "plan"
  const hooks = await planPlugin({ client, directory: "/project" } as any)
  await hooks["chat.message"]({ sessionID: "plan-root", agent: "plan", model: { providerID: "openai", modelID: "gpt-5.6-sol" }, variant: "medium" })
  const warnings: string[] = []
  const originalWarn = console.warn
  console.warn = (...items: any[]) => warnings.push(items.join(" "))
  try {
    const output = { text: "<proposed_plan>\nunsafe original\n</proposed_plan>" }
    await hooks["experimental.text.complete"]({ sessionID: "plan-root" }, output)
    assert(output.text.includes("failed closed"), "review failure did not fail closed")
    assert(!output.text.includes("unsafe original") && !output.text.includes("credential="), "review failure exposed plan or diagnostic details")
    const retained = warnings.map((line) => line.match(/snapshot (\/tmp\/opencode-plan-review-[^ ]+)/)?.[1]).filter(Boolean) as string[]
    assert(retained.length === 1, "review failure did not report retained secured evidence")
    assert((await stat(retained[0])).mode % 0o1000 === 0o700, "retained evidence directory mode changed")
    assert((await stat(join(retained[0], "plan.md"))).mode % 0o1000 === 0o600, "retained plan mode changed")
    await rm(retained[0], { recursive: true })
  } finally {
    console.warn = originalWarn
  }

  const lookupFailure = await planPlugin({ client: { session: { get: async () => ({ error: "credential=lookup-secret" }) } }, directory: "/project" } as any)
  const output = { text: "<proposed_plan>\nunsafe lookup\n</proposed_plan>" }
  await lookupFailure["experimental.text.complete"]({ sessionID: "missing" }, output)
  assert(output.text.includes("failed closed") && !output.text.includes("lookup-secret") && !output.text.includes("unsafe lookup"), "lookup failure escaped the fail-closed boundary")
}

await coordinatorRecoveryChecks()
await coordinatorCapacityChecks()
await coordinatorRestartChecks()
await planFailureChecks()
console.log(JSON.stringify({ coordinator_recovery: "passed", coordinator_capacity: "passed", coordinator_restart: "passed", plan_failure: "passed" }))
