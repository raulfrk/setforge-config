import { spawn, type ChildProcess } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import {
  access,
  chmod,
  lstat,
  mkdtemp,
  open,
  readFile,
  readdir,
  realpath,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { constants as fsConstants } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { dirname, isAbsolute, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";

type Review =
  | { kind: "clean" }
  | { kind: "annotations"; annotations: string }
  | { kind: "failure"; error: string; evidenceDir: string }
  | { kind: "abort"; evidenceDir: string };

type FileIdentity = {
  dev: string;
  ino: string;
  mode: string;
  nlink: string;
  uid: string;
  gid: string;
  size: string;
  mtimeNs: string;
  ctimeNs: string;
};

type PinnedPlan = {
  candidate: string;
  lexicalPath: string;
  lexical: FileIdentity;
  realPath: string;
  target: FileIdentity;
  digest: string;
  bytes: string;
  title: string;
};

const extensionPath = fileURLToPath(import.meta.url);
const helperPath = fileURLToPath(
  new URL("../skills/herdr/scripts/omp_plan_mode_handoff.py", import.meta.url),
);
const launcherPath = fileURLToPath(new URL("../scripts/launch-plan-review.sh", import.meta.url));
const WORKFLOW_TOOLS = ["plan_enter", "revdiff_plan"];
const REVIEW_ENTRY = "setforge-plan-review";

function textResult(value: unknown, isError = false) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(value) }],
    details: value,
    ...(isError ? { isError: true } : {}),
  };
}

function isRoot(ctx: ExtensionContext): boolean {
  return !ctx.sessionManager.getBranch().some((entry: any) => entry?.type === "session_init");
}

function latestMode(ctx: ExtensionContext): { mode: string; planFilePath?: string } {
  for (const entry of [...ctx.sessionManager.getBranch()].reverse() as any[]) {
    if (entry?.type !== "mode_change") continue;
    const mode = entry.mode === "plan" ? "plan" : "build";
    const value = entry?.data?.planFilePath;
    return { mode, ...(mode === "plan" && typeof value === "string" ? { planFilePath: value } : {}) };
  }
  return { mode: "build" };
}

function exactProposalTarget(input: any): boolean {
  const raw = typeof input?.file_path === "string" ? input.file_path : input?.path;
  if (typeof raw !== "string") return false;
  let target = raw.trimEnd();
  const wrapped = /^\[([^#\]\n]+)(?:#[0-9A-Fa-f]{4})?\]$/.exec(target);
  if (wrapped) target = wrapped[1];
  const selector = /:(raw|conflicts)$/i.exec(target);
  if (selector) target = target.slice(0, selector.index);
  return target.slice(0, 5).toLowerCase() === "xd://" && target.slice(5) === "propose";
}

function normalizeLocal(value: string): string {
  return value.startsWith("local:") ? `local://${value.replace(/^local:\/{1,2}/, "")}` : value;
}

function localRoot(ctx: ExtensionContext): string {
  const artifacts = ctx.localProtocolOptions?.getArtifactsDir?.();
  if (artifacts) return resolve(artifacts, "local");
  const raw = ctx.localProtocolOptions?.getSessionId?.() ?? ctx.sessionManager.getSessionId?.() ?? "session";
  const safe = String(raw).replace(/[^a-zA-Z0-9_.-]/g, "_") || "session";
  return join(tmpdir(), "omp-local", safe);
}

function within(path: string, root: string): boolean {
  return path === root || path.startsWith(`${root}${sep}`);
}

function localCandidatePath(candidate: string, ctx: ExtensionContext): string {
  const root = localRoot(ctx);
  const encoded = normalizeLocal(candidate).slice("local://".length);
  const relative = decodeURIComponent(encoded);
  const target = resolve(root, relative);
  if (!relative || !within(target, root)) throw new Error(`unsafe local Plan path: ${candidate}`);
  return target;
}

function stateCandidatePath(candidate: string, ctx: ExtensionContext): string {
  if (candidate.startsWith("local:")) return localCandidatePath(candidate, ctx);
  let value = candidate;
  if (value === "~" || value.startsWith(`~${sep}`)) value = join(homedir(), value.slice(2));
  if (/^\/+$/u.test(value)) return ctx.cwd;
  return isAbsolute(value) ? value : resolve(ctx.cwd, value);
}

function identity(value: any): FileIdentity {
  return {
    dev: String(value.dev),
    ino: String(value.ino),
    mode: String(value.mode),
    nlink: String(value.nlink),
    uid: String(value.uid),
    gid: String(value.gid),
    size: String(value.size),
    mtimeNs: String(value.mtimeNs),
    ctimeNs: String(value.ctimeNs),
  };
}

function normalizedTitle(value: unknown): string | undefined {
  if (typeof value !== "string" || !value.trim()) return undefined;
  const trimmed = value.trim();
  if (trimmed.includes("/") || trimmed.includes("\\") || trimmed.includes("..")) return undefined;
  const title = trimmed
    .replace(/\.md$/i, "")
    .replace(/\s+/g, "-")
    .replace(/[^A-Za-z0-9_-]/g, "")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "");
  return title || undefined;
}

function resolvedTitle(supplied: unknown, content: string, candidate: string): string {
  const direct = normalizedTitle(supplied);
  if (direct) return direct;
  const heading = /^[ \t]*#[ \t]+(.+?)[ \t]*$/m.exec(content);
  const headingTitle = normalizedTitle(heading?.[1]);
  if (headingTitle) return headingTitle;
  const path = candidate.replace(/^local:\/+/, "");
  const stem = (path.split(/[\\/]/).pop() ?? "").replace(/\.md$/i, "");
  return normalizedTitle(stem) ?? "plan";
}

async function pinPlan(candidate: string, supplied: unknown, ctx: ExtensionContext): Promise<PinnedPlan | null> {
  const lexicalPath = stateCandidatePath(candidate, ctx);
  let lexicalStat: any;
  try {
    lexicalStat = await lstat(lexicalPath, { bigint: true });
  } catch (error: any) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
  if (!lexicalStat.isFile() && !lexicalStat.isSymbolicLink()) {
    throw new Error(`Plan candidate is not a regular file or stable symlink: ${candidate}`);
  }
  const resolvedPath = await realpath(lexicalPath);
  const targetStat: any = await stat(resolvedPath, { bigint: true });
  if (!targetStat.isFile()) throw new Error(`Plan candidate does not resolve to a regular file: ${candidate}`);
  if (candidate.startsWith("local:")) {
    const rootPath = localRoot(ctx);
    const realRoot = await realpath(rootPath);
    if (!within(resolvedPath, realRoot)) throw new Error(`local Plan candidate escapes its canonical root: ${candidate}`);
  }
  await access(resolvedPath, fsConstants.R_OK);
  const bytes = await readFile(resolvedPath);
  const lexicalAfter: any = await lstat(lexicalPath, { bigint: true });
  const realAfter = await realpath(lexicalPath);
  const targetAfter: any = await stat(realAfter, { bigint: true });
  if (
    realAfter !== resolvedPath ||
    JSON.stringify(identity(lexicalAfter)) !== JSON.stringify(identity(lexicalStat)) ||
    JSON.stringify(identity(targetAfter)) !== JSON.stringify(identity(targetStat))
  ) {
    throw new Error(`Plan candidate changed while it was read: ${candidate}`);
  }
  const content = bytes.toString("utf8");
  return {
    candidate: normalizeLocal(candidate),
    lexicalPath,
    lexical: identity(lexicalStat),
    realPath: resolvedPath,
    target: identity(targetStat),
    digest: createHash("sha256").update(bytes).digest("hex"),
    bytes: bytes.toString("base64"),
    title: resolvedTitle(supplied, content, candidate),
  };
}

async function listNativePlans(ctx: ExtensionContext): Promise<string[]> {
  const root = localRoot(ctx);
  let entries: any[];
  try {
    entries = await readdir(root, { withFileTypes: true });
  } catch {
    return [];
  }
  const plans = await Promise.all(
    entries
      .filter(entry => entry.isFile() && /plan\.md$/i.test(entry.name))
      .map(async entry => {
        const path = join(root, entry.name);
        const metadata = await stat(path).catch(() => null);
        return { candidate: `local://${entry.name}`, mtime: metadata?.mtimeMs ?? 0 };
      }),
  );
  return plans.sort((a, b) => b.mtime - a.mtime).map(value => value.candidate);
}

async function resolveNativePlan(supplied: unknown, ctx: ExtensionContext): Promise<PinnedPlan> {
  const statePath = latestMode(ctx).planFilePath;
  if (!statePath) throw new Error("native Plan has no recorded plan file path");
  const ordered: string[] = [];
  const consider = (candidate?: string) => {
    if (candidate && !ordered.some(value => normalizeLocal(value) === normalizeLocal(candidate))) ordered.push(candidate);
  };
  const normalized = normalizedTitle(supplied);
  if (normalized) {
    const slug = normalized.replace(/-plan$/i, "") || normalized;
    consider(`local://${slug}-plan.md`);
  }
  const listed = await listNativePlans(ctx);
  const canonicalListed = new Set(listed.map(normalizeLocal));
  if (!canonicalListed.has(normalizeLocal(statePath))) consider(statePath);
  for (const candidate of listed) consider(candidate);
  consider(statePath);
  for (const candidate of ordered) {
    const pinned = await pinPlan(candidate, supplied, ctx);
    if (pinned) return pinned;
  }
  throw new Error(`Plan file not found at ${ordered[0] ?? statePath}`);
}

async function privateDirectory(prefix: string): Promise<string> {
  const root = process.env.XDG_RUNTIME_DIR || tmpdir();
  const directory = await mkdtemp(join(root, prefix));
  await chmod(directory, 0o700);
  return directory;
}

function collect(child: ChildProcess): Promise<{ code: number | null; stdout: string; stderr: string }> {
  return new Promise((resolveChild, reject) => {
    const stdout: Buffer[] = [];
    const stderr: Buffer[] = [];
    child.stdout?.on("data", chunk => stdout.push(Buffer.from(chunk)));
    child.stderr?.on("data", chunk => stderr.push(Buffer.from(chunk)));
    child.once("error", reject);
    child.once("close", code =>
      resolveChild({ code, stdout: Buffer.concat(stdout).toString("utf8"), stderr: Buffer.concat(stderr).toString("utf8") }),
    );
  });
}

async function reviewInUi(
  current: string,
  previous: string | undefined,
  description: string,
  ctx: ExtensionContext,
): Promise<Review> {
  const directory = await privateDirectory("omp-plan-review-");
  const currentPath = join(directory, "plan.md");
  await writeFile(currentPath, current, { mode: 0o600 });
  let previousPath: string | undefined;
  if (previous !== undefined) {
    previousPath = join(directory, "previous.md");
    await writeFile(previousPath, previous, { mode: 0o600 });
  }
  if (ctx.mode !== "tui" || !ctx.hasUI || ctx.hasPendingMessages()) {
    return { kind: "failure", error: "RevDiff plan approval requires an idle interactive OMP TUI.", evidenceDir: directory };
  }
  let child: ChildProcess | undefined;
  try {
    const result = await ctx.ui.custom<Review>((_tui, theme, keys, done) => {
      const args = [currentPath];
      if (previousPath) args.push(previousPath);
      args.push(`--description=${description}`);
      child = spawn(launcherPath, args, { stdio: ["ignore", "pipe", "pipe"], env: { ...process.env } });
      collect(child).then(
        value => {
          const annotations = value.stdout.trimEnd();
          if (value.code === 0 && !annotations) done({ kind: "clean" });
          else if (value.code === 10 && annotations) done({ kind: "annotations", annotations });
          else done({ kind: "failure", error: `review launcher failed with exit ${value.code}`, evidenceDir: directory });
        },
        error => done({ kind: "failure", error: String(error), evidenceDir: directory }),
      );
      return {
        render: () => [theme.fg("accent", "RevDiff plan review is open in Herdr")],
        invalidate() {},
        handleInput(data: string) {
          if (keys.matches(data, "tui.select.cancel")) {
            child?.kill();
            done({ kind: "abort", evidenceDir: directory });
          }
        },
        dispose() {
          if (child && child.exitCode === null) child.kill();
        },
      };
    });
    if (result.kind === "clean") {
      try {
        await rm(directory, { recursive: true });
      } catch (error) {
        ctx.ui.notify(`Review passed; cleanup retained ${directory}: ${String(error)}`, "warning");
      }
    }
    return result;
  } catch (error) {
    child?.kill();
    return { kind: "failure", error: String(error), evidenceDir: directory };
  }
}

function latestAssistant(ctx: ExtensionContext): string | undefined {
  for (const entry of [...ctx.sessionManager.getBranch()].reverse() as any[]) {
    const message = entry?.type === "message" ? entry.message : undefined;
    if (message?.role !== "assistant" || !Array.isArray(message.content)) continue;
    const text = message.content
      .filter((part: any) => part?.type === "text" && typeof part.text === "string")
      .map((part: any) => part.text)
      .join("");
    if (text) return text;
  }
  return undefined;
}

function previousReviewedPlan(ctx: ExtensionContext): string | undefined {
  for (const entry of [...ctx.sessionManager.getBranch()].reverse() as any[]) {
    if (entry?.type !== "custom" || entry.customType !== REVIEW_ENTRY) continue;
    const encoded = entry?.data?.plan;
    return typeof encoded === "string" ? Buffer.from(encoded, "base64").toString("utf8") : undefined;
  }
  return undefined;
}

function formatBlocked(review: Exclude<Review, { kind: "clean" }>): string {
  if (review.kind === "annotations") return review.annotations;
  if (review.kind === "abort") return `RevDiff review aborted. Evidence retained at ${review.evidenceDir}`;
  return `${review.error} Evidence retained at ${review.evidenceDir}`;
}

export default function setforgePlanWorkflow(pi: ExtensionAPI) {
  const z = pi.zod;

  pi.registerTool({
    name: "plan_enter",
    label: "Enter native Plan",
    description:
      "Arm a verified Herdr handoff into OMP native Plan for substantial work. It must be the only tool in this response; then emit only its marker.",
    parameters: z.object({ reason: z.string().min(1), continuation: z.string().min(1) }),
    defaultInactive: true,
    loadMode: "essential",
    approval: "read",
    renderCall(args: any, _options: any, theme: any) {
      return { render: () => [theme.fg("dim", `Enter native Plan: ${args.reason}`)], invalidate() {} };
    },
    async execute(_id, params, signal, _update, ctx) {
      if (!isRoot(ctx)) return textResult({ status: "unavailable", reason: "plan_enter is root-only" }, true);
      if (ctx.mode !== "tui" || !ctx.hasUI || ctx.hasPendingMessages()) {
        return textResult({ status: "unavailable", reason: "Type /plan in an idle interactive OMP TUI." }, true);
      }
      const socket = process.env.HERDR_SOCKET_PATH;
      const workspace = process.env.HERDR_WORKSPACE_ID;
      const tab = process.env.HERDR_TAB_ID;
      const pane = process.env.HERDR_PANE_ID;
      if (process.env.HERDR_ENV !== "1" || !socket || !workspace || !tab || !pane) {
        return textResult({ status: "unavailable", reason: "Outside Herdr, type /plan and continue the request." }, true);
      }
      const mode = latestMode(ctx).mode;
      if (mode !== "build" && mode !== "plan") throw new Error("plan_enter requires Build or native Plan");
      if (signal?.aborted) throw new Error("plan handoff was cancelled before arming");
      const session = ctx.sessionManager.getSessionFile();
      if (!session) throw new Error("OMP session path is unavailable");
      const directory = await privateDirectory("omp-plan-handoff-");
      const marker = `OMP_PLAN_HANDOFF_${randomUUID().replaceAll("-", "")}`;
      const continuationFile = join(directory, "continuation");
      await writeFile(continuationFile, params.continuation, { mode: 0o600 });
      await writeFile(
        join(directory, "state.json"),
        JSON.stringify({
          socket,
          workspace,
          tab,
          pane,
          session,
          marker,
          continuation_file: continuationFile,
          deadline: Date.now() / 1000 + 120,
        }),
        { mode: 0o600 },
      );
      const log = await open(join(directory, "helper.log"), "a", 0o600);
      const child = spawn(helperPath, [directory], {
        detached: true,
        stdio: ["ignore", log.fd, log.fd],
        env: { ...process.env },
      });
      child.unref();
      await log.close();
      const readyDeadline = Date.now() + 5000;
      while (Date.now() < readyDeadline) {
        if (signal?.aborted) throw new Error(`plan handoff cancelled; secured evidence retained at ${directory}`);
        try {
          const pid = Number((await readFile(join(directory, "READY"), "utf8")).trim());
          if (!Number.isSafeInteger(pid) || pid <= 1) throw new Error("helper READY PID is invalid");
          process.kill(pid, 0);
          return textResult({ status: "armed", marker, evidenceDir: directory });
        } catch (error: any) {
          if (error?.code !== "ENOENT" && error?.code !== "ESRCH") throw error;
        }
        await new Promise(resolveDelay => setTimeout(resolveDelay, 25));
      }
      let reason = "helper did not become ready";
      try {
        reason = (await readFile(join(directory, "FAILURE"), "utf8")).trim() || reason;
      } catch {}
      throw new Error(`${reason}; secured evidence retained at ${directory}`);
    },
  });

  pi.registerTool({
    name: "revdiff_plan",
    label: "Review plan in RevDiff",
    description: "Review an explicit plan, the current native Plan artifact, or the latest assistant response.",
    parameters: z.object({ plan: z.string().min(1).optional(), previous_plan: z.string().optional() }),
    defaultInactive: true,
    loadMode: "essential",
    approval: "read",
    async execute(_id, params, _signal, _update, ctx) {
      if (!isRoot(ctx)) return textResult({ status: "unavailable", reason: "revdiff_plan is root-only" }, true);
      let current = params.plan;
      if (!current && latestMode(ctx).mode === "plan") {
        current = Buffer.from((await resolveNativePlan(undefined, ctx)).bytes, "base64").toString("utf8");
      }
      current ??= latestAssistant(ctx);
      if (!current) return textResult({ status: "failure", error: "No plan or assistant response is available." }, true);
      const previous = params.previous_plan ?? previousReviewedPlan(ctx);
      const review = await reviewInUi(current, previous, "Review the OMP plan or response", ctx);
      if (review.kind === "annotations") pi.appendEntry(REVIEW_ENTRY, { plan: Buffer.from(current).toString("base64") });
      else if (review.kind === "clean") pi.appendEntry(REVIEW_ENTRY, { status: "clean" });
      return textResult(review, review.kind === "failure" || review.kind === "abort");
    },
  });

  pi.registerCommand("revdiff-plan", {
    description: "Review the current native Plan artifact or latest assistant response in RevDiff",
    handler: async (args, ctx) => {
      const explicit = args.trim() || undefined;
      let current = explicit;
      if (!current && latestMode(ctx).mode === "plan") {
        current = Buffer.from((await resolveNativePlan(undefined, ctx)).bytes, "base64").toString("utf8");
      }
      current ??= latestAssistant(ctx);
      if (!current) {
        ctx.ui.notify("No plan or assistant response is available.", "error");
        return;
      }
      const review = await reviewInUi(current, previousReviewedPlan(ctx), "Review the OMP plan or response", ctx);
      if (review.kind === "annotations") {
        pi.appendEntry(REVIEW_ENTRY, { plan: Buffer.from(current).toString("base64") });
        pi.sendUserMessage(
          `Revise the current response using every exact RevDiff annotation below, then present the complete replacement.\n\n${review.annotations}`,
          { deliverAs: "followUp" },
        );
      } else if (review.kind === "clean") {
        pi.appendEntry(REVIEW_ENTRY, { status: "clean" });
        ctx.ui.notify("RevDiff review completed cleanly.", "info");
      } else {
        ctx.ui.notify(formatBlocked(review), "error");
      }
    },
  });

  pi.on("tool_call", async (event: any, ctx) => {
    if (!exactProposalTarget(event?.input) || event?.toolName !== "write") return;
    if (!isRoot(ctx) || latestMode(ctx).mode !== "plan") return;
    if (ctx.mode !== "tui" || !ctx.hasUI || ctx.hasPendingMessages()) {
      return { block: true, reason: "RevDiff plan approval requires an idle interactive OMP TUI." };
    }
    const supplied = event.input?.content;
    const pinned = await resolveNativePlan(supplied, ctx);
    const current = Buffer.from(pinned.bytes, "base64").toString("utf8");
    const review = await reviewInUi(current, previousReviewedPlan(ctx), `Review the OMP implementation plan: ${pinned.title}`, ctx);
    if (review.kind !== "clean") {
      if (review.kind === "annotations") pi.appendEntry(REVIEW_ENTRY, { plan: pinned.bytes, digest: pinned.digest });
      return { block: true, reason: formatBlocked(review) };
    }
    if (ctx.hasPendingMessages()) {
      return { block: true, reason: "Queued user input arrived during review; submit the proposal again." };
    }
    const after = await resolveNativePlan(supplied, ctx);
    if (JSON.stringify(after) !== JSON.stringify(pinned)) {
      return { block: true, reason: "The selected native Plan artifact changed during review; submit it again." };
    }
    pi.appendEntry(REVIEW_ENTRY, { status: "clean", digest: pinned.digest });
    return undefined;
  });

  async function activate(ctx: ExtensionContext) {
    const active = pi.getActiveTools().filter(name => !WORKFLOW_TOOLS.includes(name));
    if (isRoot(ctx)) active.push(...WORKFLOW_TOOLS);
    await pi.setActiveTools([...new Set(active)]);
  }
  pi.on("session_start", async (_event, ctx) => activate(ctx));
  pi.on("session_tree", async (_event, ctx) => activate(ctx));
  pi.on("session_branch", async (_event, ctx) => activate(ctx));
}

export {
  exactProposalTarget,
  isRoot,
  latestMode,
  normalizeLocal,
  normalizedTitle,
  resolveNativePlan,
  resolvedTitle,
};
