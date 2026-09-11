import { tool, type Plugin } from "@opencode-ai/plugin"

type Json = Record<string, any>
type EnvelopeState = "queued" | "dispatching" | "accepted" | "completed" | "interrupted"
type Envelope = {
  id: string
  kind: "initial" | "followup" | "message" | "notification"
  text: string
  state: EnvelopeState
  generation: number
  created: number
  messageID?: string
  result?: string
}
type CoordinatorMeta = {
  version: 1
  kind: "root" | "child"
  coordinatorDirectory: string
  rootID: string
  taskPath?: string
  role?: string
  model?: { providerID: string; modelID: string }
  variant?: string
  worktree?: { directory: string; branch?: string; state: "creating" | "ready" | "failed" }
  generation?: number
  queue?: Envelope[]
  notifications?: Envelope[]
  children?: { id: string; taskPath: string; directory: string }[]
  reservations?: { taskPath: string; created: number }[]
  interrupted?: boolean
}

const KEY = "setforgeCoordinator"
const MAX_CHILDREN = 12
const VALID_ROLES = new Set(["default", "explorer", "worker", "review_correctness", "review_critical", "review_general"])
const ROLE_AGENT: Record<string, string> = {
  default: "general",
  explorer: "explore",
  worker: "worker",
  review_correctness: "review_correctness",
  review_critical: "review_critical",
  review_general: "review_general",
}
const ROLE_PIN: Record<string, { providerID: string; modelID: string; variant: string } | undefined> = {
  worker: { providerID: "openai", modelID: "gpt-5.6-luna", variant: "max" },
  review_correctness: { providerID: "openai", modelID: "gpt-6-astra", variant: "low" },
  review_critical: { providerID: "openai", modelID: "gpt-5.6-sol", variant: "low" },
  review_general: { providerID: "openai", modelID: "gpt-5.6-terra", variant: "low" },
}

function unwrap<T = any>(response: any): T {
  if (response?.error) throw new Error(typeof response.error === "string" ? response.error : JSON.stringify(response.error))
  return response?.data as T
}

function nowID(prefix: string) {
  return `${prefix}-${Date.now().toString(36)}-${crypto.randomUUID()}`
}

function partsText(message: any): string {
  return (message?.parts ?? []).filter((part: any) => part.type === "text").map((part: any) => part.text ?? "").join("")
}

function operationID(message: any): string | undefined {
  for (const part of message?.parts ?? []) {
    if (part.type === "text" && typeof part.metadata?.setforge_operation_id === "string") return part.metadata.setforge_operation_id
  }
}

function resolveTarget(target: string, sessions: any[], rootID: string): any {
  const exact = sessions.filter((session) => session.id === target || session.metadata?.[KEY]?.taskPath === target)
  if (exact.length === 1) return exact[0]
  const suffix = target.startsWith("/") ? target : `/root/${target}`
  const relative = sessions.filter((session) => session.metadata?.[KEY]?.rootID === rootID && session.metadata?.[KEY]?.taskPath === suffix)
  if (relative.length === 1) return relative[0]
  throw new Error(exact.length + relative.length > 1 ? `ambiguous target: ${target}` : `unknown target: ${target}`)
}

export const SetForgeAgentCoordinator: Plugin = async ({ client, directory, serverUrl }) => {
  const locks = new Map<string, Promise<any>>()
  const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

  const serial = async <T>(id: string, fn: () => Promise<T>): Promise<T> => {
    const prior = locks.get(id) ?? Promise.resolve()
    let release!: () => void
    const gate = new Promise<void>((resolve) => (release = resolve))
    const current = prior.then(() => gate)
    locks.set(id, current)
    await prior
    try {
      return await fn()
    } finally {
      release()
      if (locks.get(id) === current) locks.delete(id)
    }
  }

  const getSession = async (id: string, dir = directory) => unwrap<any>(await client.session.get({ path: { id }, query: { directory: dir } }))
  const statusMap = async (dir = directory) => unwrap<Record<string, any>>(await client.session.status({ query: { directory: dir } })) ?? {}
  const messages = async (id: string, dir = directory) => unwrap<any[]>(await client.session.messages({ path: { id }, query: { directory: dir } })) ?? []
  const awaitOperation = async (id: string, operation: string, dir: string, expectedText: string, timeout = 5000) => {
    const end = Date.now() + timeout
    while (Date.now() < end) {
      const found = (await messages(id, dir)).find((message) =>
        message.info?.role === "user" && operationID(message) === operation && partsText(message) === expectedText,
      )
      if (found) return found
      await sleep(25)
    }
    throw new Error(`message ${operation} was not durably accepted`)
  }
  const authHeaders = () => {
    const env = (globalThis as any).process?.env ?? {}
    const password = env.OPENCODE_SERVER_PASSWORD
    if (!password) return {} as Record<string, string>
    const username = env.OPENCODE_SERVER_USERNAME || "opencode"
    return { authorization: `Basic ${btoa(`${username}:${password}`)}` }
  }

  const setMeta = async (session: any, meta: CoordinatorMeta, dir = session.directory ?? directory) => {
    const merged = { ...(session.metadata ?? {}), [KEY]: meta }
    return unwrap<any>(await client.session.update({ path: { id: session.id }, query: { directory: dir }, body: { metadata: merged } } as any))
  }

  const ensureRoot = async (rootID: string) => {
    const root = await getSession(rootID)
    const existing = root.metadata?.[KEY] as CoordinatorMeta | undefined
    if (existing?.kind === "root") return root
    await setMeta(root, {
      version: 1,
      kind: "root",
      coordinatorDirectory: directory,
      rootID,
      notifications: [],
      children: [],
      generation: 0,
    })
    return await getSession(rootID)
  }

  const childSessions = async (rootID: string) => {
    const root = await ensureRoot(rootID)
    const rootMeta = root.metadata?.[KEY] as CoordinatorMeta
    const refs = rootMeta.children ?? []
    const children: any[] = []
    for (const ref of refs) {
      try {
        const child = await getSession(ref.id, ref.directory)
        const meta = child.metadata?.[KEY] as CoordinatorMeta | undefined
        if (meta?.kind === "child" && meta.rootID === rootID && meta.coordinatorDirectory === directory) children.push(child)
      } catch {}
    }
    return children
  }

  const terminalResponseFor = (all: any[], envelope: Envelope, queue: Envelope[]) => {
    const operations = new Set([
      envelope.id,
      ...queue.filter((item) => item.kind === "message" && item.generation === envelope.generation).map((item) => item.id),
    ])
    const parents = new Set(all.filter((message) => message.info?.role === "user" && operations.has(operationID(message) ?? "")).map((message) => message.info.id))
    return all.findLast((message) =>
      message.info?.role === "assistant"
      && parents.has(message.info?.parentID)
    && message.info?.time?.completed
    && !["tool-calls", "unknown"].includes(message.info?.finish),
    )
  }

  const activeChild = async (child: any) => {
    const meta = child.metadata?.[KEY] as CoordinatorMeta
    if (meta.interrupted) return false
    if ((meta.queue ?? []).some((item) => ["queued", "dispatching", "accepted"].includes(item.state))) return true
    return (await statusMap(child.directory))[child.id]?.type === "busy"
  }

  const reserveChild = async (rootID: string, taskPath: string) => serial(rootID, async () => {
    const root = await ensureRoot(rootID)
    const meta = root.metadata[KEY] as CoordinatorMeta
    const reservations = [...(meta.reservations ?? [])]
    if ((meta.children ?? []).some((item) => item.taskPath === taskPath) || reservations.some((item) => item.taskPath === taskPath)) {
      throw new Error(`task already exists: ${taskPath}`)
    }
    const children = await childSessions(rootID)
    let active = 0
    for (const child of children) if (await activeChild(child)) active += 1
    if (active + reservations.length >= MAX_CHILDREN) throw new Error(`active child limit ${MAX_CHILDREN} reached`)
    reservations.push({ taskPath, created: Date.now() })
    await setMeta(root, { ...meta, reservations })
  })

  const finishChild = async (rootID: string, child: any, taskPath: string, childDirectory: string) => serial(rootID, async () => {
    const root = await ensureRoot(rootID)
    const meta = root.metadata[KEY] as CoordinatorMeta
    const children = [...(meta.children ?? [])]
    if (!children.some((item) => item.id === child.id)) children.push({ id: child.id, taskPath, directory: childDirectory })
    await setMeta(root, { ...meta, children, reservations: (meta.reservations ?? []).filter((item) => item.taskPath !== taskPath) })
  })

  const releaseChild = async (rootID: string, taskPath: string, childID?: string) => serial(rootID, async () => {
    const root = await ensureRoot(rootID)
    const meta = root.metadata[KEY] as CoordinatorMeta
    await setMeta(root, {
      ...meta,
      children: (meta.children ?? []).filter((item) => item.id !== childID),
      reservations: (meta.reservations ?? []).filter((item) => item.taskPath !== taskPath),
    })
  })

  const reserveActivation = async (child: any) => serial(child.metadata[KEY].rootID, async () => {
    const childMeta = child.metadata[KEY] as CoordinatorMeta
    const root = await ensureRoot(childMeta.rootID)
    const meta = root.metadata[KEY] as CoordinatorMeta
    if ((meta.reservations ?? []).some((item) => item.taskPath === childMeta.taskPath)) {
      throw new Error(`agent activation already in progress: ${childMeta.taskPath}`)
    }
    child = await getSession(child.id, child.directory)
    if (await activeChild(child)) return false
    const children = await childSessions(childMeta.rootID)
    let active = 0
    for (const item of children) if (await activeChild(item)) active += 1
    if (active + (meta.reservations ?? []).length >= MAX_CHILDREN) throw new Error(`active child limit ${MAX_CHILDREN} reached`)
    await setMeta(root, { ...meta, reservations: [...(meta.reservations ?? []), { taskPath: childMeta.taskPath!, created: Date.now() }] })
    return true
  })

  const releaseActivation = async (child: any) => serial(child.metadata[KEY].rootID, async () => {
    const childMeta = child.metadata[KEY] as CoordinatorMeta
    const root = await ensureRoot(childMeta.rootID)
    const meta = root.metadata[KEY] as CoordinatorMeta
    await setMeta(root, { ...meta, reservations: (meta.reservations ?? []).filter((item) => item.taskPath !== childMeta.taskPath) })
  })

  const recordNotification = async (child: any, envelope: Envelope) => {
    const childMeta = child.metadata?.[KEY] as CoordinatorMeta
    const rootDirectory = childMeta.coordinatorDirectory
    await serial(childMeta.rootID, async () => {
      const root = await getSession(childMeta.rootID, rootDirectory)
      const meta = root.metadata?.[KEY] as CoordinatorMeta
      const id = `notification-${child.id}-${envelope.generation}`
      if ((meta.notifications ?? []).some((item) => item.id === id)) return
      const notification: Envelope = {
        id,
        kind: "notification",
        text: `<agent_notification>\nAgent ${childMeta.taskPath} completed generation ${envelope.generation}.\n${envelope.result ?? ""}\n</agent_notification>`,
        state: "queued",
        generation: envelope.generation,
        created: Date.now(),
      }
      await setMeta(root, { ...meta, notifications: [...(meta.notifications ?? []), notification] }, rootDirectory)
    })
  }

  const deliverNotifications = async (rootID: string, rootDirectory = directory) => serial(rootID, async () => {
    let root = await getSession(rootID, rootDirectory)
    let meta = root.metadata?.[KEY] as CoordinatorMeta
    if (!meta || meta.kind !== "root") return
    const all = await messages(rootID, rootDirectory)
    const statuses = await statusMap(rootDirectory)
    const busy = statuses[rootID]?.type === "busy"
    let notifications = [...(meta.notifications ?? [])]
    let changed = false
    for (const notification of notifications) {
      if (!["dispatching", "accepted"].includes(notification.state)) continue
      const user = all.find((message) => message.info?.role === "user" && operationID(message) === notification.id)
      if (user) {
        notification.state = "completed"
        notification.messageID = user.info.id
        changed = true
      } else if (!busy) {
        notification.state = "interrupted"
        changed = true
      }
    }
    if (changed) {
      await setMeta(root, { ...meta, notifications }, rootDirectory)
      root = await getSession(rootID, rootDirectory)
      meta = root.metadata[KEY] as CoordinatorMeta
      notifications = [...(meta.notifications ?? [])]
    }
    if (busy) return
    const next = notifications.find((item) => item.state === "queued")
    if (!next) return
    next.state = "dispatching"
    await setMeta(root, { ...meta, notifications }, rootDirectory)
    const response = await client.session.promptAsync({
      path: { id: rootID }, query: { directory: rootDirectory },
      body: { noReply: true, parts: [{ type: "text", text: next.text, synthetic: true, metadata: { setforge_operation_id: next.id } }] },
    })
    if (response.error) return
    await awaitOperation(rootID, next.id, rootDirectory, next.text)
    root = await getSession(rootID, rootDirectory)
    meta = root.metadata[KEY] as CoordinatorMeta
    notifications = [...(meta.notifications ?? [])]
    const accepted = notifications.find((item) => item.id === next.id)
    if (accepted) accepted.state = "completed"
    await setMeta(root, { ...meta, notifications }, rootDirectory)
    queueMicrotask(() => void deliverNotifications(rootID, rootDirectory))
  })

  const reconcileChild = async (session: any): Promise<any> => serial(session.id, async () => {
    session = await getSession(session.id, session.directory)
    const meta = session.metadata?.[KEY] as CoordinatorMeta
    if (!meta || meta.kind !== "child") return session
    const queue = [...(meta.queue ?? [])]
    const all = await messages(session.id, session.directory)
    const statuses = await statusMap(session.directory)
    const busy = statuses[session.id]?.type === "busy"
    let changed = false
    for (const envelope of queue) {
      if (!["dispatching", "accepted"].includes(envelope.state)) continue
      const user = all.find((message) => message.info?.role === "user" && operationID(message) === envelope.id)
      if (user && (envelope.state === "dispatching" || !envelope.messageID)) {
        if (envelope.state === "dispatching") envelope.state = envelope.kind === "message" ? "completed" : "accepted"
        envelope.messageID = user.info.id
        if (envelope.kind === "message") envelope.result = "delivered"
        changed = true
      }
      if (envelope.kind === "message") continue
      if (!user) {
        if (!busy) {
          envelope.state = "interrupted"
          meta.interrupted = true
          changed = true
        }
        continue
      }
      const answer = terminalResponseFor(all, envelope, queue)
      if (answer) {
        const failed = Boolean(answer.info.error) || ["abort", "cancelled", "error"].includes(answer.info.finish)
        envelope.state = failed ? "interrupted" : "completed"
        envelope.result = partsText(answer)
        if (failed) meta.interrupted = true
        else meta.generation = Math.max(meta.generation ?? 0, envelope.generation)
        changed = true
      } else if (!busy) {
        envelope.state = "interrupted"
        meta.interrupted = true
        changed = true
      }
    }
    if (changed) await setMeta(session, { ...meta, queue }, session.directory)
    session = await getSession(session.id, session.directory)
    for (const envelope of (session.metadata?.[KEY]?.queue ?? []) as Envelope[]) {
      if (envelope.kind !== "message" && envelope.state === "completed") await recordNotification(session, envelope)
    }
    return session
  })

  const dispatchNext = async (session: any) => serial(session.id, async () => {
    session = await getSession(session.id, session.directory)
    let meta = session.metadata?.[KEY] as CoordinatorMeta
    if (!meta || meta.kind !== "child") return
    const statuses = await statusMap(session.directory)
    if (statuses[session.id]?.type === "busy") return
    const queue = [...(meta.queue ?? [])]
    const envelope = queue.find((item) => item.state === "queued")
    if (!envelope) return
    envelope.state = "dispatching"
    await setMeta(session, { ...meta, queue }, session.directory)
    const body: any = {
      agent: ROLE_AGENT[meta.role ?? "default"],
      model: meta.model,
      variant: meta.variant,
      parts: [{ type: "text", text: envelope.text, metadata: { setforge_operation_id: envelope.id } }],
    }
    const response = await client.session.promptAsync({ path: { id: session.id }, query: { directory: session.directory }, body })
    if (response.error) return
    await awaitOperation(session.id, envelope.id, session.directory, envelope.text)
    session = await getSession(session.id, session.directory)
    meta = session.metadata?.[KEY] as CoordinatorMeta
    const updated = [...(meta.queue ?? [])]
    const accepted = updated.find((item) => item.id === envelope.id)
    if (accepted?.state === "dispatching") accepted.state = "accepted"
    await setMeta(session, { ...meta, queue: updated }, session.directory)
  })

  const reconcileAndDispatch = async (session: any) => {
    const reconciled = await reconcileChild(session)
    await dispatchNext(reconciled)
    return await reconcileChild(reconciled)
  }

  const addEnvelope = async (session: any, text: string, kind: Envelope["kind"]) => serial(session.id, async () => {
    session = await getSession(session.id, session.directory)
    const meta = session.metadata?.[KEY] as CoordinatorMeta
    if (meta.interrupted && kind !== "followup") throw new Error(`agent ${meta.taskPath} is interrupted; inspect it before a new request`)
    const generation = Math.max(meta.generation ?? 0, ...(meta.queue ?? []).map((item) => item.generation)) + 1
    const envelope: Envelope = { id: nowID(kind), kind, text, state: "queued", generation, created: Date.now() }
    await setMeta(session, { ...meta, interrupted: kind === "followup" ? false : meta.interrupted, queue: [...(meta.queue ?? []), envelope] }, session.directory)
    return envelope
  })

  const addMessage = async (session: any, text: string) => serial(session.id, async () => {
    session = await getSession(session.id, session.directory)
    const meta = session.metadata?.[KEY] as CoordinatorMeta
    if (meta.interrupted) throw new Error(`agent ${meta.taskPath} is interrupted; inspect it before a new message`)
    const active = (meta.queue ?? []).findLast((item) => item.kind !== "message" && ["dispatching", "accepted"].includes(item.state))
    const envelope: Envelope = { id: nowID("message"), kind: "message", text, state: "dispatching", generation: active?.generation ?? 0, created: Date.now() }
    await setMeta(session, { ...meta, queue: [...(meta.queue ?? []), envelope] }, session.directory)
    const response = await client.session.promptAsync({
      path: { id: session.id }, query: { directory: session.directory },
      body: {
        noReply: true,
        agent: ROLE_AGENT[meta.role ?? "default"],
        model: meta.model,
        variant: meta.variant,
        parts: [{ type: "text", text, metadata: { setforge_operation_id: envelope.id } }],
      },
    })
    if (response.error) return envelope
    await awaitOperation(session.id, envelope.id, session.directory, text)
    session = await getSession(session.id, session.directory)
    const nextMeta = session.metadata[KEY] as CoordinatorMeta
    const queue = [...(nextMeta.queue ?? [])]
    const accepted = queue.find((item) => item.id === envelope.id)
    if (accepted) { accepted.state = "completed"; accepted.result = "delivered" }
    await setMeta(session, { ...nextMeta, queue }, session.directory)
    return envelope
  })

  const awaitGeneration = async (session: any, generation: number, timeout: number) => {
    const end = Date.now() + timeout
    while (Date.now() < end) {
      session = await reconcileAndDispatch(session)
      const meta = session.metadata?.[KEY] as CoordinatorMeta
      const envelope = (meta.queue ?? []).find((item) => item.generation === generation)
      if (envelope?.state === "completed") return { session, envelope }
      if (envelope?.state === "interrupted") throw new Error(`agent ${meta.taskPath} was interrupted during generation ${generation}`)
      await sleep(40)
    }
    throw new Error(`timeout waiting for generation ${generation}`)
  }

  const renderHistory = async (rootID: string, count?: number) => {
    const all = await messages(rootID)
    const selected = count === undefined ? all : all.slice(-count)
    return selected.map((message) => `${message.info.role.toUpperCase()}:\n${JSON.stringify(message.parts ?? [])}`).join("\n\n")
  }

  const createWorktree = async (taskName: string) => {
    const controller = new AbortController()
    const events = await client.global.event({ signal: controller.signal } as any)
    let info: any
    try {
      const response = await fetch(new URL(`/experimental/worktree?directory=${encodeURIComponent(directory)}`, serverUrl), {
        method: "POST",
        headers: { "content-type": "application/json", ...authHeaders() },
        body: JSON.stringify({ name: `setforge-${taskName}` }),
      })
      if (!response.ok) throw new Error(`worktree create failed: HTTP ${response.status}`)
      const payload: any = await response.json()
      info = payload.data ?? payload
      if (!info?.directory || !info?.name) throw new Error("worktree create returned incomplete information")
      const ready = (async () => {
        for await (const event of events.stream) {
          if (event?.directory !== info.directory) continue
          const payload = event.payload
          if (payload?.type === "worktree.ready" && payload.properties?.name === info.name) return
          if (payload?.type === "worktree.failed") throw new Error("worktree bootstrap failed")
        }
        throw new Error("worktree event stream ended before readiness")
      })()
      let timer: ReturnType<typeof setTimeout> | undefined
      await Promise.race([
        ready,
        new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("worktree readiness timed out")), 30_000) }),
      ]).finally(() => { if (timer) clearTimeout(timer) })
      return info
    } catch (error) {
      if (info?.directory) await removeWorktree(info.directory).catch(() => undefined)
      throw new Error(`worktree readiness failed: ${error instanceof Error ? error.message : String(error)}`)
    } finally {
      controller.abort()
    }
  }

  const removeWorktree = async (worktreeDirectory: string) => {
    const response = await fetch(new URL(`/experimental/worktree?directory=${encodeURIComponent(directory)}`, serverUrl), {
      method: "DELETE",
      headers: { "content-type": "application/json", ...authHeaders() },
      body: JSON.stringify({ directory: worktreeDirectory }),
    })
    if (!response.ok) throw new Error(`worktree cleanup failed: HTTP ${response.status}`)
  }

  const tools = {
    spawn_agent: tool({
      description: "Spawn a persistent child coding agent.",
      args: {
        task_name: tool.schema.string().regex(/^[a-z0-9_]+$/),
        message: tool.schema.string().min(1),
        agent_type: tool.schema.string().optional(),
        model: tool.schema.string().optional(),
        reasoning_effort: tool.schema.string().optional(),
        fork_turns: tool.schema.union([tool.schema.literal("none"), tool.schema.literal("all"), tool.schema.string().regex(/^[1-9][0-9]*$/)]).optional(),
        isolation: tool.schema.boolean().optional(),
      },
      async execute(args, context) {
        const root = await ensureRoot(context.sessionID)
        const role = args.agent_type ?? "default"
        if (!VALID_ROLES.has(role)) throw new Error(`invalid agent_type: ${role}`)
        const taskPath = `/root/${args.task_name}`
        const inherited = root.model ? { providerID: root.model.providerID, modelID: root.model.id } : undefined
        const requested = args.model ? (() => {
          const split = args.model!.indexOf("/")
          if (split < 1 || split === args.model!.length - 1) throw new Error(`invalid model: ${args.model}`)
          return { providerID: args.model!.slice(0, split), modelID: args.model!.slice(split + 1) }
        })() : undefined
        const pin = ROLE_PIN[role]
        if (pin && requested && (requested.providerID !== pin.providerID || requested.modelID !== pin.modelID)) throw new Error(`role ${role} requires ${pin.providerID}/${pin.modelID}`)
        if (pin && args.reasoning_effort && args.reasoning_effort !== pin.variant) throw new Error(`role ${role} requires effort ${pin.variant}`)
        const model = pin ? { providerID: pin.providerID, modelID: pin.modelID } : requested ?? inherited
        const variant = pin?.variant ?? args.reasoning_effort ?? root.model?.variant
        if (!model) throw new Error("root model unavailable")
        if (!pin && (requested || args.reasoning_effort)) {
          const catalog = unwrap<any>(await client.provider.list({ query: { directory } }))
          const provider = (catalog?.all ?? []).find((item: any) => item.id === model.providerID)
          const found = provider?.models?.[model.modelID] ?? provider?.models?.[`${model.providerID}/${model.modelID}`]
            ?? Object.values(provider?.models ?? {}).find((item: any) => item?.id === model.modelID || item?.id === `${model.providerID}/${model.modelID}`)
          if (!found) throw new Error(`unknown model: ${model.providerID}/${model.modelID}`)
          if (args.reasoning_effort && !found.variants?.[args.reasoning_effort]) throw new Error(`unsupported effort ${args.reasoning_effort} for ${model.providerID}/${model.modelID}`)
        }
        await reserveChild(context.sessionID, taskPath)
        let childDirectory = directory
        let worktree: CoordinatorMeta["worktree"]
        let child: any
        try {
          if (args.isolation) {
            const info = await serial("__worktree_create__", () => createWorktree(args.task_name))
            childDirectory = info.directory
            worktree = { directory: info.directory, branch: info.branch, state: "ready" }
          }
          if ((args.fork_turns ?? "none") === "all" && !args.isolation) {
            child = unwrap<any>(await client.session.fork({ path: { id: context.sessionID }, query: { directory: childDirectory }, body: { messageID: context.messageID } }))
          } else {
            child = unwrap<any>(await client.session.create({ query: { directory: childDirectory }, body: { parentID: args.isolation ? undefined : context.sessionID, title: `setforge-agent:${taskPath}`, agent: ROLE_AGENT[role], model: { providerID: model.providerID, id: model.modelID } } } as any))
          }
          const envelope: Envelope = { id: nowID("initial"), kind: "initial", text: args.message, state: "queued", generation: 1, created: Date.now() }
          const childMeta: CoordinatorMeta = {
            version: 1, kind: "child", coordinatorDirectory: directory, rootID: context.sessionID,
            taskPath, role, model, variant, worktree, generation: 0, queue: [envelope], interrupted: false,
          }
          await setMeta(child, childMeta, childDirectory)
          await finishChild(context.sessionID, child, taskPath, childDirectory)
          child = await getSession(child.id, childDirectory)
          const seedCount = args.isolation && (args.fork_turns ?? "none") === "all"
            ? undefined
            : (/^[1-9]/.test(args.fork_turns ?? "") ? Number(args.fork_turns) : null)
          if (seedCount !== null) {
            const history = await renderHistory(context.sessionID, seedCount)
            const seed = `CONTEXT FROM PARENT:\n${history}`
            const seedID = nowID("context")
            unwrap(await client.session.promptAsync({
              path: { id: child.id }, query: { directory: childDirectory },
              body: {
                noReply: true, agent: ROLE_AGENT[role], model, variant,
                parts: [{ type: "text", text: seed, metadata: { setforge_operation_id: seedID } }],
              },
            } as any))
            await awaitOperation(child.id, seedID, childDirectory, seed)
          }
          await dispatchNext(child)
          return JSON.stringify({ id: child.id, task_path: taskPath, generation: envelope.generation, directory: childDirectory, worktree: worktree ?? null })
        } catch (error) {
          await releaseChild(context.sessionID, taskPath, child?.id).catch(() => undefined)
          if (child?.id) await client.session.delete({ path: { id: child.id }, query: { directory: childDirectory } }).catch(() => undefined)
          if (worktree?.directory) await removeWorktree(worktree.directory).catch(() => undefined)
          throw error
        }
      },
    }),
    list_agents: tool({
      description: "List persistent child agents and states.",
      args: { path_prefix: tool.schema.string().optional() },
      async execute(args, context) {
        await ensureRoot(context.sessionID)
        const children = await childSessions(context.sessionID)
        const result = []
        for (let child of children) {
          child = await reconcileAndDispatch(child)
          const meta = child.metadata[KEY] as CoordinatorMeta
          if (args.path_prefix && !meta.taskPath?.startsWith(args.path_prefix)) continue
          const statuses = await statusMap(child.directory)
          result.push({ id: child.id, task_path: meta.taskPath, role: meta.role, model: meta.model, effort: meta.variant, state: meta.interrupted ? "interrupted" : statuses[child.id]?.type ?? "idle", generation: meta.generation ?? 0, directory: child.directory, worktree: meta.worktree ?? null })
        }
        return JSON.stringify(result)
      },
    }),
    send_message: tool({
      description: "Append a durable no-reply message to a child.",
      args: { target: tool.schema.string(), message: tool.schema.string().min(1) },
      async execute(args, context) {
        const child = resolveTarget(args.target, await childSessions(context.sessionID), context.sessionID)
        const envelope = await addMessage(child, args.message)
        return JSON.stringify({ id: envelope.id, delivered: true })
      },
    }),
    followup_task: tool({
      description: "Queue a child follow-up and run it when idle.",
      args: { target: tool.schema.string(), message: tool.schema.string().min(1) },
      async execute(args, context) {
        let child = resolveTarget(args.target, await childSessions(context.sessionID), context.sessionID)
        child = await reconcileChild(child)
        const reserved = await reserveActivation(child)
        try {
          const envelope = await addEnvelope(child, args.message, "followup")
          await dispatchNext(child)
          return JSON.stringify({ id: envelope.id, generation: envelope.generation, queued: true })
        } finally {
          if (reserved) await releaseActivation(child)
        }
      },
    }),
    interrupt_agent: tool({
      description: "Interrupt a child and clear undispatched follow-ups.",
      args: { target: tool.schema.string() },
      async execute(args, context) {
        let child = resolveTarget(args.target, await childSessions(context.sessionID), context.sessionID)
        return await serial(child.id, async () => {
          child = await getSession(child.id, child.directory)
          const meta = child.metadata[KEY] as CoordinatorMeta
          const previous = meta.interrupted ? "interrupted" : (await statusMap(child.directory))[child.id]?.type ?? "idle"
          const queue = (meta.queue ?? []).map((item) => ["queued", "dispatching", "accepted"].includes(item.state) ? { ...item, state: "interrupted" as const } : item)
          await setMeta(child, { ...meta, queue, interrupted: true }, child.directory)
          unwrap(await client.session.abort({ path: { id: child.id }, query: { directory: child.directory } }))
          return JSON.stringify({ id: child.id, interrupted: true, previous_state: previous })
        })
      },
    }),
    wait_agent: tool({
      description: "Wait for one or more child generations.",
      args: {
        targets: tool.schema.array(tool.schema.string()).optional(),
        after_generation: tool.schema.number().int().min(0).optional(),
        timeout_ms: tool.schema.number().int().min(1).max(60000).optional(),
      },
      async execute(args, context) {
        const all = await childSessions(context.sessionID)
        const selected = args.targets?.length ? args.targets.map((target) => resolveTarget(target, all, context.sessionID)) : all
        if (!selected.length) throw new Error("no matching agents")
        const end = Date.now() + (args.timeout_ms ?? 60000)
        while (Date.now() < end) {
          for (let child of selected) {
            child = await reconcileAndDispatch(child)
            const meta = child.metadata[KEY] as CoordinatorMeta
            const after = args.after_generation ?? 0
            const completed = (meta.queue ?? []).find((item) =>
              ["initial", "followup"].includes(item.kind) && item.state === "completed" && item.generation > after,
            )
            if (completed) {
              return JSON.stringify({ id: child.id, task_path: meta.taskPath, generation: completed.generation, output: completed.result })
            }
            if (meta.interrupted) throw new Error(`agent ${meta.taskPath} is interrupted`)
          }
          await sleep(40)
        }
        return JSON.stringify({ timeout: true })
      },
    }),
  }

  const recoverStartup = async () => {
    const listed = unwrap<any[]>(await client.session.list({ query: { directory, scope: "project", limit: 1000 } } as any)) ?? []
    const roots = listed.filter((session) => {
      const meta = session.metadata?.[KEY] as CoordinatorMeta | undefined
      return meta?.kind === "root" && meta.coordinatorDirectory === directory && meta.rootID === session.id
    })
    for (let root of roots) {
      await serial(root.id, async () => {
        root = await getSession(root.id, directory)
        const meta = root.metadata?.[KEY] as CoordinatorMeta
        if (meta.reservations?.length) await setMeta(root, { ...meta, reservations: [] }, directory)
      })
      for (const child of await childSessions(root.id)) await reconcileAndDispatch(child)
      await deliverNotifications(root.id, directory)
    }
  }

  const startupTimer = setTimeout(() => {
    void recoverStartup().catch(() => console.warn("SetForge agent coordinator startup recovery failed"))
  }, 0)

  return {
    dispose: async () => clearTimeout(startupTimer),
    tool: tools,
    event: async ({ event }: any) => {
      if (event?.type !== "session.status" || event?.properties?.status?.type !== "idle") return
      const sessionID = event.properties.sessionID
      try {
        const session = await getSession(sessionID)
        const meta = session.metadata?.[KEY] as CoordinatorMeta | undefined
        if (meta?.kind === "root") {
          await deliverNotifications(sessionID, directory)
          return
        }
        if (meta?.kind === "child") {
          await reconcileAndDispatch(session)
          await deliverNotifications(meta.rootID, meta.coordinatorDirectory)
        }
      } catch {}
    },
  }
}

export default SetForgeAgentCoordinator
