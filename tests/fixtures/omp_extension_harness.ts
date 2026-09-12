import assert from "node:assert/strict";
import { chmod, mkdtemp, mkdir, readFile, symlink, utimes, writeFile } from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";

import workflow, {
  exactProposalTarget,
  isRoot,
  latestMode,
  normalizeLocal,
  normalizedTitle,
  resolveNativePlan,
  resolvedTitle,
} from "../../tracked/omp/extensions/setforge-plan-workflow.ts";

const field = () => ({
  min() { return this; },
  optional() { return this; },
});

const tools = new Map<string, any>();
const commands = new Map<string, any>();
const events = new Map<string, Array<(event: any, ctx: any) => Promise<any>>>();
let activeTools = ["read", "plan_enter"];
const entries: any[] = [];
const messages: any[] = [];
const pi = {
  zod: { string: field, object: (shape: any) => ({ shape }) },
  registerTool(definition: any) { tools.set(definition.name, definition); },
  registerCommand(name: string, definition: any) { commands.set(name, definition); },
  on(name: string, callback: any) {
    const current = events.get(name) ?? [];
    current.push(callback);
    events.set(name, current);
  },
  getActiveTools() { return [...activeTools]; },
  async setActiveTools(names: string[]) { activeTools = [...names]; },
  appendEntry(customType: string, data: any) { entries.push({ customType, data }); },
  sendUserMessage(text: string, options: any) { messages.push({ text, options }); },
};
workflow(pi as any);

assert.deepEqual([...tools.keys()], ["plan_enter", "revdiff_plan"]);
assert.equal(tools.get("plan_enter").defaultInactive, true);
assert.equal(tools.get("revdiff_plan").defaultInactive, true);
assert.equal(tools.get("plan_enter").approval, "read");
assert.equal(commands.has("revdiff-plan"), true);
assert.equal(events.has("session_stop"), false);
assert.equal(events.has("shutdown"), false);

function context(branch: any[], cwd: string, artifacts: string): any {
  return {
    cwd,
    mode: "tui",
    hasUI: true,
    hasPendingMessages: () => false,
    localProtocolOptions: {
      getArtifactsDir: () => artifacts,
      getSessionId: () => "session-test",
    },
    sessionManager: {
      getBranch: () => branch,
      getSessionId: () => "session-test",
      getSessionFile: () => join(artifacts, "session.jsonl"),
    },
  };
}

const rootCtx = context([], process.cwd(), tmpdir());
assert.equal(isRoot(rootCtx), true);
assert.deepEqual(latestMode(rootCtx), { mode: "build" });
for (const callback of events.get("session_start") ?? []) await callback({}, rootCtx);
assert.deepEqual(activeTools, ["read", "plan_enter", "revdiff_plan"]);

const childCtx = context([{ type: "session_init" }], process.cwd(), tmpdir());
assert.equal(isRoot(childCtx), false);
for (const eventName of ["session_start", "session_tree", "session_branch"]) {
  for (const callback of events.get(eventName) ?? []) await callback({}, childCtx);
  assert.deepEqual(activeTools, ["read"]);
  activeTools = ["read", "plan_enter", "revdiff_plan"];
}

for (const value of [
  { path: "xd://propose" },
  { file_path: "xd://propose" },
  { path: "xd://propose:raw" },
  { path: "xd://propose:CONFLICTS" },
  { path: "[xd://propose#A10f]" },
  { path: "xd://propose\n\t" },
  { path: "XD://propose" },
]) assert.equal(exactProposalTarget(value), true, JSON.stringify(value));
for (const value of [
  {},
  { path: "xd://PROPOSE" },
  { path: " xd://propose" },
  { path: "xd://proposal" },
  { path: "[xd://propose#wrong]" },
  { path: "ssh://host/xd://propose" },
]) assert.equal(exactProposalTarget(value), false, JSON.stringify(value));

assert.equal(normalizeLocal("local:/PLAN.md"), "local://PLAN.md");
assert.equal(normalizeLocal("local://PLAN.md"), "local://PLAN.md");
assert.equal(normalizedTitle(" Auth feature plan.md "), "Auth-feature-plan");
assert.equal(normalizedTitle("../escape"), undefined);
assert.equal(resolvedTitle(undefined, "# First heading\n\nBody", "local://PLAN.md"), "First-heading");
assert.equal(resolvedTitle(undefined, "  # Desired title", "local://PLAN.md"), "Desired-title");
assert.equal(resolvedTitle(undefined, "# ../invalid\n# Other title", "local://named-plan.md"), "named-plan");
assert.equal(resolvedTitle(undefined, "Body", "local://named-plan.md"), "named-plan");
assert.equal(resolvedTitle(undefined, "Body", "local://.md"), "plan");

const root = await mkdtemp(join(tmpdir(), "omp-extension-harness-"));
const artifacts = join(root, "artifacts");
const local = join(artifacts, "local");
const cwd = join(root, "cwd");
await mkdir(homedir(), { recursive: true });
await mkdir(local, { recursive: true });
await mkdir(cwd);

const mode = (planFilePath: string) => [{ type: "mode_change", mode: "plan", data: { planFilePath } }];
await writeFile(join(local, "auth-plan.md"), "# Auth heading\n\nChosen by supplied title.\n");
await writeFile(join(local, "PLAN.md"), "# Default\n");
let pinned = await resolveNativePlan("auth", context(mode("local://PLAN.md"), cwd, artifacts));
assert.equal(pinned.candidate, "local://auth-plan.md");
assert.equal(pinned.title, "auth");
assert.equal(Buffer.from(pinned.bytes, "base64").toString(), "# Auth heading\n\nChosen by supplied title.\n");
assert.match(pinned.digest, /^[a-f0-9]{64}$/);

await writeFile(join(cwd, "chosen.md"), "# Cwd chosen\n");
pinned = await resolveNativePlan(undefined, context(mode("chosen.md"), cwd, artifacts));
assert.equal(pinned.realPath, join(cwd, "chosen.md"));
assert.equal(pinned.title, "Cwd-chosen");

const absolute = join(root, "absolute.md");
await writeFile(absolute, "absolute body\n");
pinned = await resolveNativePlan(undefined, context(mode(absolute), cwd, artifacts));
assert.equal(pinned.realPath, absolute);
assert.equal(pinned.title, "absolute");

const homePlan = join(homedir(), `omp-harness-${process.pid}.md`);
await writeFile(homePlan, "# Home plan\n");
pinned = await resolveNativePlan(undefined, context(mode(`~/omp-harness-${process.pid}.md`), cwd, artifacts));
assert.equal(pinned.realPath, homePlan);

const symlinkTarget = join(root, "symlink-target.md");
const stableLink = join(cwd, "stable.md");
await writeFile(symlinkTarget, "# Stable link\n");
await symlink(symlinkTarget, stableLink);
pinned = await resolveNativePlan(undefined, context(mode("stable.md"), cwd, artifacts));
assert.equal(pinned.lexicalPath, stableLink);
assert.equal(pinned.realPath, symlinkTarget);

const older = new Date(Date.now() - 10_000);
const newer = new Date();
await utimes(join(local, "PLAN.md"), older, older);
await writeFile(join(local, "newest-plan.md"), "# Newest\n");
await utimes(join(local, "newest-plan.md"), newer, newer);
pinned = await resolveNativePlan(undefined, context(mode("local:/PLAN.md"), cwd, artifacts));
assert.equal(pinned.candidate, "local://newest-plan.md");

const outside = join(root, "outside.md");
await writeFile(outside, "outside\n");
await symlink(outside, join(local, "escape-plan.md"));
await assert.rejects(
  resolveNativePlan("escape", context(mode("local://escape-plan.md"), cwd, artifacts)),
  /escapes its canonical root/,
);
await assert.rejects(
  resolveNativePlan(undefined, context(mode("local://..%2Foutside.md"), cwd, artifacts)),
  /unsafe local Plan path/,
);
await mkdir(join(cwd, "directory.md"));
await assert.rejects(
  resolveNativePlan(undefined, context(mode("directory.md"), cwd, artifacts)),
  /not a regular file or stable symlink/,
);
await symlink(join(root, "missing.md"), join(cwd, "dangling.md"));
await assert.rejects(resolveNativePlan(undefined, context(mode("dangling.md"), cwd, artifacts)), /ENOENT/);

let toolResult = await tools.get("plan_enter").execute(
  "child-plan-enter",
  { reason: "test", continuation: "test" },
  undefined,
  undefined,
  childCtx,
);
assert.equal(toolResult.details.status, "unavailable");
toolResult = await tools.get("revdiff_plan").execute(
  "child-revdiff",
  { plan: "test" },
  undefined,
  undefined,
  childCtx,
);
assert.equal(toolResult.details.status, "unavailable");

const toolCallHook = (events.get("tool_call") ?? [])[0];
assert(toolCallHook);
assert.equal(await toolCallHook({ toolName: "write", input: { path: "xd://propose", content: "auth" } }, rootCtx), undefined);
assert.equal(await toolCallHook({ toolName: "write", input: { path: "xd://propose", content: "auth" } }, childCtx), undefined);
const headlessCtx = context(mode("local://auth-plan.md"), cwd, artifacts);
headlessCtx.mode = "rpc";
headlessCtx.hasUI = false;
assert.match(
  (await toolCallHook({ toolName: "write", input: { path: "xd://propose", content: "auth" } }, headlessCtx)).reason,
  /idle interactive OMP TUI/,
);

const fakeBin = join(root, "fake-bin");
await mkdir(fakeBin);
await writeFile(
  join(fakeBin, "tmux"),
  `#!/bin/sh
if [ "\${1:-}" = "-V" ]; then echo 'tmux 3.4'; exit 0; fi
while [ "$#" -gt 0 ]; do
  if [ "$1" = "sh" ]; then exec "$@"; fi
  shift
done
exit 2
`,
);
await writeFile(
  join(fakeBin, "revdiff"),
  `#!/bin/sh
output=
input=
for arg in "$@"; do
  case "$arg" in
    --output=*) output=\${arg#--output=} ;;
    --only=*) input=\${arg#--only=} ;;
    --compare-new=*) input=\${arg#--compare-new=} ;;
  esac
done
if [ -n "\${OMP_REVIEW_CAPTURE:-}" ] && [ -n "$input" ]; then cp "$input" "$OMP_REVIEW_CAPTURE"; fi
if [ -n "\${OMP_REVIEW_ARGS:-}" ]; then printf '%s\n' "$@" > "$OMP_REVIEW_ARGS"; fi
case "\${OMP_REVIEW_MODE:-clean}" in
  annotations) printf 'line 2: revise this\n' > "$output"; exit 10 ;;
  failure) exit 3 ;;
  mutate) printf '\nchanged after review\n' >> "$OMP_REVIEW_MUTATE"; : > "$output"; exit 0 ;;
  *) : > "$output"; exit 0 ;;
esac
`,
);
await chmod(join(fakeBin, "tmux"), 0o755);
await chmod(join(fakeBin, "revdiff"), 0o755);
await mkdir(join(root, "review-tmp"));
process.env.PATH = `${fakeBin}:${process.env.PATH}`;
for (const name of [
  "HERDR_ENV",
  "HERDR_SOCKET_PATH",
  "HERDR_WORKSPACE_ID",
  "HERDR_TAB_ID",
  "HERDR_PANE_ID",
  "AGTERM_SESSION_ID",
  "ZELLIJ",
  "ZELLIJ_PANE_ID",
  "KITTY_LISTEN_ON",
  "WEZTERM_PANE",
  "CMUX_SURFACE_ID",
  "GHOSTTY_RESOURCES_DIR",
  "GHOSTTY_BIN_DIR",
  "ITERM_SESSION_ID",
  "INSIDE_EMACS",
]) delete process.env[name];
process.env.TMUX = "probe";
process.env.TMPDIR = join(root, "review-tmp");
process.env.XDG_RUNTIME_DIR = join(root, "review-tmp");

const notices: any[] = [];
function interactiveContext(branch: any[], options: { abort?: boolean; pendingAfter?: boolean } = {}): any {
  const ctx = context(branch, cwd, artifacts);
  let pending = false;
  ctx.hasPendingMessages = () => pending;
  ctx.ui = {
    notify(message: string, level: string) { notices.push({ message, level }); },
    custom(factory: any) {
      return new Promise(resolveReview => {
        let resolved = false;
        const done = (value: any) => {
          if (resolved) return;
          resolved = true;
          if (options.pendingAfter) pending = true;
          resolveReview(value);
        };
        const component = factory(
          {},
          { fg: (_color: string, value: string) => value },
          { matches: (data: string, action: string) => data === "cancel" && action === "tui.select.cancel" },
          done,
        );
        if (options.abort) component.handleInput("cancel");
      });
    },
  };
  return ctx;
}

const capture = join(root, "review-capture");
process.env.OMP_REVIEW_CAPTURE = capture;
process.env.OMP_REVIEW_MODE = "clean";
toolResult = await tools.get("revdiff_plan").execute(
  "manual-explicit",
  { plan: "EXPLICIT PLAN" },
  undefined,
  undefined,
  interactiveContext([]),
);
assert.equal(toolResult.details.kind, "clean");
assert.equal(await readFile(capture, "utf8"), "EXPLICIT PLAN");
assert.deepEqual(entries.at(-1).data, { status: "clean" });

process.env.OMP_REVIEW_MODE = "annotations";
toolResult = await tools.get("revdiff_plan").execute(
  "manual-annotations",
  { plan: "ANNOTATED PLAN" },
  undefined,
  undefined,
  interactiveContext([]),
);
assert.deepEqual(toolResult.details, { kind: "annotations", annotations: "line 2: revise this" });
assert.equal(Buffer.from(entries.at(-1).data.plan, "base64").toString(), "ANNOTATED PLAN");

process.env.OMP_REVIEW_MODE = "failure";
toolResult = await tools.get("revdiff_plan").execute(
  "manual-failure",
  { plan: "FAILURE PLAN" },
  undefined,
  undefined,
  interactiveContext([]),
);
assert.equal(toolResult.details.kind, "failure");
assert.equal(toolResult.isError, true);

process.env.OMP_REVIEW_MODE = "clean";
toolResult = await tools.get("revdiff_plan").execute(
  "manual-abort",
  { plan: "ABORT PLAN" },
  undefined,
  undefined,
  interactiveContext([], { abort: true }),
);
assert.equal(toolResult.details.kind, "abort");
assert.equal(toolResult.isError, true);

process.env.OMP_REVIEW_MODE = "clean";
toolResult = await tools.get("revdiff_plan").execute(
  "manual-native",
  {},
  undefined,
  undefined,
  interactiveContext(mode("local://auth-plan.md")),
);
assert.equal(toolResult.details.kind, "clean");
assert.equal(await readFile(capture, "utf8"), "# Newest\n");

toolResult = await tools.get("revdiff_plan").execute(
  "manual-latest",
  {},
  undefined,
  undefined,
  interactiveContext([{
    type: "message",
    message: { role: "assistant", content: [{ type: "text", text: "LATEST ASSISTANT" }] },
  }]),
);
assert.equal(toolResult.details.kind, "clean");
assert.equal(await readFile(capture, "utf8"), "LATEST ASSISTANT");

await writeFile(join(local, "auth-plan.md"), "# Auth heading\n\nChosen by supplied title.\n");
process.env.OMP_REVIEW_MODE = "clean";
let hookResult = await toolCallHook(
  { toolName: "write", input: { path: "xd://propose", content: "auth" } },
  interactiveContext(mode("local://auth-plan.md")),
);
assert.equal(hookResult, undefined);
assert.equal(entries.at(-1).data.status, "clean");
assert.match(entries.at(-1).data.digest, /^[a-f0-9]{64}$/);

process.env.OMP_REVIEW_MODE = "annotations";
hookResult = await toolCallHook(
  { toolName: "write", input: { path: "xd://propose", content: "auth" } },
  interactiveContext(mode("local://auth-plan.md")),
);
assert.equal(hookResult.block, true);
assert.equal(hookResult.reason, "line 2: revise this");

process.env.OMP_REVIEW_MODE = "clean";
hookResult = await toolCallHook(
  { toolName: "write", input: { path: "xd://propose", content: "auth" } },
  interactiveContext(mode("local://auth-plan.md"), { pendingAfter: true }),
);
assert.equal(hookResult.block, true);
assert.match(hookResult.reason, /Queued user input/);

await writeFile(join(local, "auth-plan.md"), "# Auth heading\n\nChosen by supplied title.\n");
process.env.OMP_REVIEW_MODE = "mutate";
process.env.OMP_REVIEW_MUTATE = join(local, "auth-plan.md");
hookResult = await toolCallHook(
  { toolName: "write", input: { path: "xd://propose", content: "auth" } },
  interactiveContext(mode("local://auth-plan.md")),
);
assert.equal(hookResult.block, true);
assert.match(hookResult.reason, /changed during review/);

console.log(JSON.stringify({
  activation: "passed",
  proposal_paths: "passed",
  resolver: "passed",
  review_ordering: "passed",
  registered_tools: [...tools.keys()],
  registered_commands: [...commands.keys()],
}));
