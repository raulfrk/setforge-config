import { chmod, mkdtemp, rm, stat, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fileURLToPath } from "node:url"
import { tool, type Plugin } from "@opencode-ai/plugin"

type Model = { providerID: string; modelID: string }
type Request = { agent?: string; model?: Model; variant?: string }
type ReviewResult = { status: "clean" } | { status: "annotations"; annotations: string }

const requests = new Map<string, Request>()
const guardedSessions = new Set<string>()
const transitioning = new Map<string, string>()
const launcher = fileURLToPath(new URL("../scripts/launch-plan-review.sh", import.meta.url))

function unwrap<T = any>(response: any): T {
  if (response?.error) throw new Error(typeof response.error === "string" ? response.error : JSON.stringify(response.error))
  return response?.data as T
}

function exactPlan(text: string): string {
  const matches = [...text.matchAll(/<proposed_plan>[\s\S]*?<\/proposed_plan>/g)]
  if (matches.length !== 1 || matches[0][0].trim() !== text.trim()) {
    throw new Error("expected exactly one complete proposed_plan block with no surrounding text")
  }
  return matches[0][0]
}

async function snapshot(text: string): Promise<{ directory: string; path: string }> {
  const directory = await mkdtemp(join(tmpdir(), "opencode-plan-review-"))
  await chmod(directory, 0o700)
  const path = join(directory, "plan.md")
  await writeFile(path, text, { mode: 0o600 })
  if ((await stat(path)).mode % 0o1000 !== 0o600) throw new Error("plan snapshot mode is not 0600")
  return { directory, path }
}

async function review(current: string, previous?: string): Promise<ReviewResult> {
  const args = [launcher, current]
  if (previous) args.push(previous)
  args.push("--description=Review the OpenCode implementation plan")
  const child = Bun.spawn(args, { stdout: "pipe", stderr: "pipe", env: { ...Bun.env } })
  const [stdout, stderr, code] = await Promise.all([
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
    child.exited,
  ])
  if (code === 0 && !stdout.trim()) return { status: "clean" }
  if (code === 10 && stdout.trim()) return { status: "annotations", annotations: stdout }
  if (code === 0) throw new Error("review launcher returned annotations with a clean exit")
  if (code === 10) throw new Error("review launcher reported annotations but returned none")
  throw new Error(`review launcher failed with exit ${code}`)
}

function modelFromSession(session: any): Model | undefined {
  if (!session?.model?.providerID || !session?.model?.id) return undefined
  return { providerID: session.model.providerID, modelID: session.model.id }
}

export default (async ({ client, directory }) => {
  const sessionInfo = async (sessionID: string, targetDirectory = directory) =>
    unwrap<any>(await client.session.get({ path: { id: sessionID }, query: { directory: targetDirectory } }))

  const currentRequest = async (sessionID: string, targetDirectory = directory): Promise<Request> => {
    const remembered = requests.get(sessionID)
    if (remembered?.model) return remembered
    const session = await sessionInfo(sessionID, targetDirectory)
    return { agent: session.agent, model: modelFromSession(session), variant: session.model?.variant }
  }

  const revise = async (sessionID: string, targetDirectory: string, current: string, annotations: string, request: Request) => {
    if (!request.model) throw new Error("the root model is unavailable for plan revision")
    const created = unwrap<any>(await client.session.create({
      query: { directory: targetDirectory },
      body: { parentID: sessionID, title: "guarded plan revision", agent: "plan_reviser", model: { providerID: request.model.providerID, id: request.model.modelID } },
    } as any))
    if (!created?.id) throw new Error("plan revision child creation returned no session ID")
    guardedSessions.add(created.id)
    try {
      const prompt = [
        "Revise the complete plan using every exact annotation below.",
        "Return exactly one complete <proposed_plan>...</proposed_plan> block and no surrounding prose.",
        "",
        "FULL PRIOR PLAN:",
        current,
        "",
        "EXACT ANNOTATIONS:",
        annotations,
      ].join("\n")
      const response = unwrap<any>(await client.session.prompt({
        path: { id: created.id }, query: { directory: targetDirectory },
        body: {
          model: request.model,
          agent: "plan_reviser",
          variant: request.variant,
          tools: {
            bash: false, read: false, glob: false, grep: false, edit: false, write: false,
            apply_patch: false, task: false, webfetch: false, websearch: false,
            todowrite: false, question: false, skill: false, plan_enter: false, plan_exit: false,
            setforge_plan_enter: false, setforge_plan_exit: false,
            spawn_agent: false, list_agents: false, send_message: false,
            followup_task: false, interrupt_agent: false, wait_agent: false,
          },
          parts: [{ type: "text", text: prompt }],
        },
      } as any))
      const text = (response?.parts ?? []).filter((part: any) => part.type === "text").map((part: any) => part.text ?? "").join("")
      return exactPlan(text)
    } finally {
      guardedSessions.delete(created.id)
      const deleted = await client.session.delete({ path: { id: created.id }, query: { directory: targetDirectory } })
      if (deleted.error) console.warn(`SetForge Plan workflow could not delete revision session ${created.id}`)
    }
  }

  const runReviewLoop = async (sessionID: string, targetDirectory: string, initial: string, previous: string | undefined, request: Request) => {
    let current = exactPlan(initial)
    let previousPath: string | undefined
    const cleanup: string[] = []
    let accepted = false
    try {
      if (previous) {
        const prior = await snapshot(exactPlan(previous))
        previousPath = prior.path
        cleanup.push(prior.directory)
      }
      while (true) {
        const currentSnapshot = await snapshot(current)
        cleanup.push(currentSnapshot.directory)
        const verdict = await review(currentSnapshot.path, previousPath)
        if (verdict.status === "clean") {
          accepted = true
          return current
        }
        const revised = await revise(sessionID, targetDirectory, current, verdict.annotations, request)
        previousPath = currentSnapshot.path
        current = revised
      }
    } finally {
      if (!accepted) {
        for (const path of cleanup) console.warn(`SetForge Plan workflow retained secured review snapshot ${path}`)
      } else {
        for (const path of cleanup) {
          try {
            await rm(path, { recursive: true })
          } catch (error) {
            console.warn(`SetForge Plan workflow retained secured review snapshot ${path}: ${error instanceof Error ? error.message : String(error)}`)
          }
        }
      }
    }
  }

  const runManualReview = async (current: string, previous?: string) => {
    const cleanup: string[] = []
    let completed = false
    try {
      const currentSnapshot = await snapshot(current)
      cleanup.push(currentSnapshot.directory)
      let previousPath: string | undefined
      if (previous !== undefined) {
        const previousSnapshot = await snapshot(previous)
        cleanup.push(previousSnapshot.directory)
        previousPath = previousSnapshot.path
      }
      const verdict = await review(currentSnapshot.path, previousPath)
      completed = true
      return verdict
    } finally {
      if (!completed) {
        for (const path of cleanup) console.warn(`SetForge Plan workflow retained secured review snapshot ${path}`)
      } else {
        for (const path of cleanup) {
          try {
            await rm(path, { recursive: true })
          } catch (error) {
            console.warn(`SetForge Plan workflow retained secured review snapshot ${path}: ${error instanceof Error ? error.message : String(error)}`)
          }
        }
      }
    }
  }

  return {
    tool: {
      setforge_plan_enter: tool({
        description: "Enter the native Plan agent for a substantial request.",
        args: {},
        async execute(_args, context) {
          const request = await currentRequest(context.sessionID, context.directory)
          if (request.agent !== "build" || !request.model) throw new Error("setforge_plan_enter requires an active Build request with a model")
          transitioning.set(context.sessionID, context.messageID)
          const response = await client.session.promptAsync({
            path: { id: context.sessionID }, query: { directory: context.directory },
            body: {
              model: request.model, agent: "plan", variant: request.variant, noReply: true,
              parts: [{ type: "text", text: "Continue this same request in native Plan mode. Research the repository and return the complete plan only." }],
            },
          } as any)
          if (response.error) {
            transitioning.delete(context.sessionID)
            throw new Error(`native Plan transition failed: ${JSON.stringify(response.error)}`)
          }
          return "Native Plan is active. Continue the same request under the Plan agent."
        },
      }),
      setforge_plan_exit: tool({
        description: "Request approval to return from native Plan to Build.",
        args: {},
        async execute(_args, context) {
          const request = await currentRequest(context.sessionID, context.directory)
          if (request.agent !== "plan" || !request.model) throw new Error("setforge_plan_exit requires an active Plan request with a model")
          await context.ask({ permission: "setforge_plan_exit", patterns: ["*"], always: [], metadata: { sessionID: context.sessionID } })
          transitioning.set(context.sessionID, context.messageID)
          const response = await client.session.promptAsync({
            path: { id: context.sessionID }, query: { directory: context.directory },
            body: {
              model: request.model, agent: "build", variant: request.variant, noReply: true,
              parts: [{ type: "text", text: "The reviewed plan is approved. Continue this same request in native Build mode." }],
            },
          } as any)
          if (response.error) {
            transitioning.delete(context.sessionID)
            throw new Error(`native Build transition failed: ${JSON.stringify(response.error)}`)
          }
          return "Native Build is active. Continue the approved request."
        },
      }),
      revdiff_plan: tool({
        description: "Review complete canonical plan Markdown in RevDiff and return the clean accepted revision.",
        args: {
          plan: tool.schema.string().min(1),
          previous_plan: tool.schema.string().optional(),
        },
        async execute(args, context) {
          const verdict = await runManualReview(args.plan, args.previous_plan)
          return JSON.stringify(verdict)
        },
      }),
    },
    "chat.message": async (input: any) => {
      requests.set(input.sessionID, { agent: input.agent, model: input.model, variant: input.variant })
    },
    "tool.execute.before": async (input: any) => {
      const transitionMessage = transitioning.get(input.sessionID)
      if (transitionMessage) throw new Error("a mode transition must be the only tool call in its response")
    },
    "experimental.text.complete": async (input: any, output: { text: string }) => {
      if (guardedSessions.has(input.sessionID) || !output.text.includes("<proposed_plan>")) return
      try {
        const session = await sessionInfo(input.sessionID)
        const request = await currentRequest(input.sessionID)
        if (session.parentID || session.metadata?.setforgeCoordinator?.kind === "child" || request.agent !== "plan") return
        output.text = await runReviewLoop(input.sessionID, session.directory, output.text, undefined, request)
      } catch {
        output.text = "<proposed_plan>\nPlan review failed closed. Inspect the retained secured review evidence and fix the review environment before implementation.\n</proposed_plan>"
      }
    },
    event: async ({ event }: any) => {
      if (event?.type !== "message.updated") return
      const info = event.properties?.info
      if (info?.role === "assistant" && info?.time?.completed && transitioning.get(info.sessionID) === info.id) {
        transitioning.delete(info.sessionID)
      }
    },
  }
}) satisfies Plugin
