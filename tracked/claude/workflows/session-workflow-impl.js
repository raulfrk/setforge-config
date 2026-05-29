export const meta = {
  name: 'session-workflow-impl',
  description: 'Parameterized implementation harness — anticipatory pitfall research, planning, gated build pipeline, diff-audit, and capped worst-of-N review/fix against a spec.',
  whenToUse: 'When the user has an approved spec and wants it implemented end-to-end with built-in risk research and review gating. Pass args as an object {specPath, bdId, basePath}; specPath and bdId are required. The harness anticipates smells/bugs per risk dimension, builds step-by-step with per-step verification, audits the diff against the merged checklist, then loops worst-of-N review until PASS or the cap.',
  phases: [{"title":"Research","detail":"Parallel inline per-dimension research prompt modeled on the pitfall-researcher agent, one per risk dimension; merge + dedup into one checklist"},{"title":"Plan","detail":"Single agent consumes spec + merged checklist, emits an ordered build plan"},{"title":"Build","detail":"Pipeline over plan steps: build agent then verify agent; verify gates progression"},{"title":"Diff-audit","detail":"Agent audits the produced diff against the merged checklist, marking each item present/verified"},{"title":"Review/Fix","detail":"Capped worst-of-N review loop; compute worst verdict in code; dispatch fix agent until PASS or cap"}],
}

// session-workflow-impl: Research → Plan → pipeline(Build → Verify) → Diff-audit → capped Review/Fix
// args is an object: { specPath, bdId, basePath }. specPath + bdId required.
// Gate is computed in code (not by model judgment): merge only when worst-of-N === PASS
// AND zero checklist items are present-but-unverified.

const MAX_REVIEW_ROUNDS = 3
const MAX_REVIEWERS = 8

// Host-local specialist reviewers available as agentType. The review planner
// maps changed files onto these; for any review dimension none of them cover
// (JS/workflow scripts, YAML/config, shell, Dockerfiles, lockfiles, ...) it
// synthesizes an ad-hoc reviewer so coverage of the diff is always complete.
const REVIEWER_REGISTRY = [
  { agentType: "python-spec-reviewer", when: "python sources, pyproject.toml, CI workflows, pre-commit config (spec/contract conformance)" },
  { agentType: "python-substance-reviewer", when: "python sources (design, error model, security)" },
  { agentType: "python-specifics-reviewer", when: "python sources (conventions, type hints, test quality)" },
  { agentType: "python-prose-reviewer", when: "python docstrings / prose" },
  { agentType: "claude-md-spec-reviewer", when: "tracked/claude markdown: CLAUDE.md, skills, agents, workflow docs (spec conformance)" },
  { agentType: "claude-md-form-reviewer", when: "tracked/claude markdown (structure, headers, links)" },
  { agentType: "claude-md-substance-reviewer", when: "tracked/claude markdown (coherence, contradictions)" },
  { agentType: "claude-md-specifics-reviewer", when: "tracked/claude markdown (project conventions)" },
  { agentType: "claude-md-prose-reviewer", when: "tracked/claude markdown (prose quality)" },
  { agentType: "markdown-prose-reviewer", when: "generic markdown outside tracked/claude (READMEs, docs, CHANGELOG)" },
]
const REGISTERED_TYPES = new Set(REVIEWER_REGISTRY.map(r => r.agentType))

const RISK_DIMENSIONS = [
  { key: "concurrency", label: "concurrency/async", focus: "race conditions, unhandled rejections, floating promises, unbounded parallelism, missing timeout propagation" },
  { key: "error-model", label: "error model", focus: "swallowed errors, silent failures, missing re-throw, partial-result loss on fail-fast, error-path coverage" },
  { key: "security", label: "security/injection", focus: "command/template injection, untrusted input flowing into exec/eval, unvalidated config or agent output" },
  { key: "resource-leak", label: "resource leak", focus: "unreleased handles/listeners, uncleared timers, missing cleanup in finally, unbounded caches/loops" },
  { key: "api-misuse", label: "API misuse", focus: "wrong primitive choice, contract mismatches, type/shape assumptions, out-of-order result mapping" },
]

// ─── Schemas ───
const CHECKLIST_ITEM_SCHEMA = {
  type: "object", required: ["id", "dimension", "kind", "statement", "detect"],
  properties: {
    id: { type: "string" },
    dimension: { type: "string" },
    kind: { enum: ["smell", "bug"] },
    statement: { type: "string" },
    detect: { type: "string" },
    severity: { enum: ["high", "medium", "low"] },
  },
}
const RESEARCH_SCHEMA = {
  type: "object", required: ["dimension", "items"],
  properties: {
    dimension: { type: "string" },
    summary: { type: "string" },
    items: { type: "array", maxItems: 8, items: CHECKLIST_ITEM_SCHEMA },
  },
}
const PLAN_SCHEMA = {
  type: "object", required: ["steps", "strategy"],
  properties: {
    strategy: { type: "string" },
    steps: { type: "array", minItems: 1, maxItems: 12, items: {
      type: "object", required: ["id", "title", "instruction"],
      properties: {
        id: { type: "string" },
        title: { type: "string" },
        instruction: { type: "string" },
        verify: { type: "string" },
        relevantChecklist: { type: "array", items: { type: "string" } },
      },
    }},
  },
}
const BUILD_STEP_SCHEMA = {
  type: "object", required: ["stepId", "status", "summary"],
  properties: {
    stepId: { type: "string" },
    status: { enum: ["done", "blocked", "skipped"] },
    summary: { type: "string" },
    filesTouched: { type: "array", items: { type: "string" } },
    notes: { type: "string" },
  },
}
const VERIFY_STEP_SCHEMA = {
  type: "object", required: ["stepId", "passed", "evidence"],
  properties: {
    stepId: { type: "string" },
    passed: { type: "boolean" },
    evidence: { type: "string" },
    failures: { type: "array", items: { type: "string" } },
  },
}
const AUDIT_SCHEMA = {
  type: "object", required: ["items"],
  properties: {
    summary: { type: "string" },
    items: { type: "array", items: {
      type: "object", required: ["id", "present", "verified"],
      properties: {
        id: { type: "string" },
        present: { type: "boolean" },
        verified: { type: "boolean" },
        evidence: { type: "string" },
      },
    }},
  },
}
const REVIEW_VERDICT_SCHEMA = {
  type: "object", required: ["verdict", "checklist"],
  properties: {
    verdict: { enum: ["PASS", "CONCERNS", "BLOCK"] },
    rationale: { type: "string" },
    checklist: { type: "array", items: {
      type: "object", required: ["id", "present", "verified"],
      properties: {
        id: { type: "string" },
        present: { type: "boolean" },
        verified: { type: "boolean" },
        note: { type: "string" },
      },
    }},
    findings: { type: "array", items: {
      type: "object", required: ["severity", "detail"],
      properties: {
        severity: { enum: ["high", "medium", "low"] },
        detail: { type: "string" },
      },
    }},
  },
}
const FIX_SCHEMA = {
  type: "object", required: ["status", "summary"],
  properties: {
    status: { enum: ["fixed", "partial", "blocked"] },
    summary: { type: "string" },
    addressed: { type: "array", items: { type: "string" } },
    filesTouched: { type: "array", items: { type: "string" } },
  },
}
const REVIEW_PLAN_SCHEMA = {
  type: "object", required: ["assigned", "adhoc"],
  properties: {
    assigned: { type: "array", items: {
      type: "object", required: ["agentType", "reason"],
      properties: { agentType: { type: "string" }, reason: { type: "string" } },
    }},
    adhoc: { type: "array", items: {
      type: "object", required: ["aspect", "focus"],
      properties: { aspect: { type: "string" }, focus: { type: "string" } },
    }},
  },
}

// ─── Args guard ───
phase("Research")
const ARGS = (args && typeof args === "object") ? args : {}
const SPEC_PATH = (typeof ARGS.specPath === "string" && ARGS.specPath.trim()) || ""
const BD_ID = (typeof ARGS.bdId === "string" && ARGS.bdId.trim()) || ""
const BASE_PATH = (typeof ARGS.basePath === "string" && ARGS.basePath.trim()) || ""
if (!SPEC_PATH || !BD_ID) {
  return { error: "session-workflow-impl requires args {specPath, bdId, basePath}; specPath and bdId are mandatory. Pass them via Workflow({name: 'session-workflow-impl', args: {specPath, bdId, basePath}})." }
}

// ─── Rank objects (computed in code, not by model) ───
const verdictRank = { PASS: 0, CONCERNS: 1, BLOCK: 2 }
const verdictName = ["PASS", "CONCERNS", "BLOCK"]
const sevRank = { high: 0, medium: 1, low: 2 }

// ─── Prompts ───
const RESEARCH_PROMPT = (dim) =>
  "## Pitfall Researcher: " + dim.label + "\n\n" +
  "Spec under implementation: " + SPEC_PATH + "\n" +
  (BASE_PATH ? "Codebase base path: " + BASE_PATH + "\n" : "") +
  "\n## Your dimension\n**" + dim.label + "** — anticipate failure modes in: " + dim.focus + "\n\n" +
  "## Task\n" +
  "Read the spec. Anticipate the smells and bugs an implementation is LIKELY to introduce along THIS dimension only. " +
  "Do not review existing code for other dimensions. Produce a checklist of concrete, checkable items.\n" +
  "Each item must have:\n" +
  "- a stable id (lowercase-dashes, prefixed with the dimension key \"" + dim.key + "-\")\n" +
  "- kind: smell or bug\n" +
  "- a one-sentence statement of the risk\n" +
  "- a detect clause: exactly how to find it in a diff (search pattern, structural check, or property to verify)\n" +
  "- a severity\n\n" +
  "Be specific to this spec, not generic. Structured output only."

const PLAN_PROMPT = (checklistBlock) =>
  "## Build Planner\n\n" +
  "Spec to implement: " + SPEC_PATH + "\n" +
  (BASE_PATH ? "Codebase base path: " + BASE_PATH + "\n" : "") +
  "\n## Anticipated-risk checklist (carry these constraints into every step)\n" + checklistBlock + "\n\n" +
  "## Task\n" +
  "Read the spec. Produce an ORDERED build plan: a sequence of independently-verifiable steps. " +
  "Each step must be small enough to build and verify on its own.\n" +
  "For each step provide:\n" +
  "- a stable id\n" +
  "- a short title\n" +
  "- a concrete build instruction (which files, what behavior)\n" +
  "- a verify clause (the command or observable property that proves the step is done correctly)\n" +
  "- relevantChecklist: the ids of checklist items this step must not violate\n\n" +
  "Order steps so each depends only on earlier ones. Structured output only."

const BUILD_PROMPT = (step, checklistBlock) =>
  "## Builder: " + step.title + "\n\n" +
  "Spec: " + SPEC_PATH + "\n" +
  (BASE_PATH ? "Codebase base path: " + BASE_PATH + "\n" : "") +
  "\n## Step\n" + step.instruction + "\n\n" +
  "## Risk checklist you must not violate\n" + checklistBlock + "\n\n" +
  "## Task\n" +
  "Implement EXACTLY this step against the spec — no more, no less. Honor the checklist constraints. " +
  "Report status, a one-line summary, and the files you touched. Structured output only."

const VERIFY_PROMPT = (step) =>
  "## Step Verifier: " + step.title + "\n\n" +
  "Spec: " + SPEC_PATH + "\n" +
  (BASE_PATH ? "Codebase base path: " + BASE_PATH + "\n" : "") +
  "\n## Step that was just built\n" + step.instruction + "\n\n" +
  "## How to verify\n" + (step.verify || "Inspect the change against the spec for this step.") + "\n\n" +
  "## Task\n" +
  "Verify ONLY this step. Run the verify clause if it is a command; otherwise inspect. " +
  "Return passed=true only with concrete evidence (command output or specific inspection). " +
  "List any failures. Default passed=false if uncertain. Structured output only."

const AUDIT_PROMPT = (checklistBlock) =>
  "## Diff Auditor\n\n" +
  "Spec: " + SPEC_PATH + "\n" +
  (BASE_PATH ? "Codebase base path: " + BASE_PATH + "\n" : "") +
  "\n## Task\n" +
  "Audit the produced diff against EVERY item in the merged risk checklist below. " +
  "For each item, report:\n" +
  "- present: true if the smell/bug pattern the item describes is FOUND in the diff\n" +
  "- verified: true if you confirmed the item is either absent from the diff OR present-but-explicitly-safe\n" +
  "- evidence: the specific diff location or reasoning\n\n" +
  "An item that is present must be either verified-safe (verified=true) or flagged (verified=false). " +
  "Do not skip items — emit one audit entry per checklist id.\n\n" +
  "## Merged risk checklist\n" + checklistBlock + "\n\nStructured output only."

const REVIEW_PLAN_PROMPT = (registryBlock) =>
  "## Review Coverage Planner\n\n" +
  "Spec: " + SPEC_PATH + "\n" +
  (BASE_PATH ? "Codebase base path: " + BASE_PATH + "\n" : "") +
  "\n## Task\n" +
  "Inspect the produced diff — run `git -C " + (BASE_PATH || ".") + " diff --name-only`, then look at the changes. " +
  "Plan a review that covers EVERY changed artifact type.\n" +
  "1. From the registry of available specialist reviewers below, choose the ones whose 'when' matches the changed files. Use each agentType at most once; do not assign a reviewer for an artifact type absent from the diff.\n" +
  "2. For any changed artifact type the registry does NOT cover (e.g. JS / workflow scripts, YAML / config, shell, Dockerfiles, lockfiles), SYNTHESIZE an ad-hoc reviewer: name the aspect and write a focus clause telling a generalist reviewer exactly what to scrutinize for that artifact.\n" +
  "Return `assigned` (registry agentTypes + reason) and `adhoc` (aspect + focus). Together they must cover the whole diff.\n\n" +
  "## Registry of available specialist reviewers\n" + registryBlock + "\n\nStructured output only."

const REVIEW_PROMPT = (task, changedBlock, checklistBlock, round) =>
  "## Implementation Reviewer — " + task.label + " (round " + round + ")\n\n" +
  "Spec: " + SPEC_PATH + "\n" +
  (BASE_PATH ? "Codebase base path: " + BASE_PATH + "\n" : "") +
  (task.kind === "adhoc"
    ? "\n## Your aspect (no dedicated agent exists for this — you are the synthesized reviewer)\n" + task.focus + "\n"
    : "") +
  "\n## Changed files\n" + changedBlock + "\n" +
  "\n## Task\n" +
  "Review the produced diff for spec-conformance AND for every risk-checklist item below. Be skeptical.\n" +
  "Return a verdict: PASS | CONCERNS | BLOCK.\n" +
  "- PASS only if the diff matches the spec AND every checklist item is either absent or verified-safe.\n" +
  "- CONCERNS for non-blocking issues.\n" +
  "- BLOCK for spec violations or any present-but-unverified checklist item.\n" +
  "For each checklist id, report present (found in diff) and verified (confirmed absent or safe).\n" +
  "Default to BLOCK if uncertain.\n\n" +
  "## Merged risk checklist\n" + checklistBlock + "\n\nStructured output only."

const FIX_PROMPT = (issuesBlock, checklistBlock) =>
  "## Fixer\n\n" +
  "Spec: " + SPEC_PATH + "\n" +
  (BASE_PATH ? "Codebase base path: " + BASE_PATH + "\n" : "") +
  "\n## Issues to resolve (from worst-of-N review)\n" + issuesBlock + "\n\n" +
  "## Risk checklist you must not violate\n" + checklistBlock + "\n\n" +
  "## Task\n" +
  "Resolve the issues above against the spec. Touch only what is needed. " +
  "Report status, a summary, the issue ids you addressed, and files touched. Structured output only."

// ─── Phase: Research (anticipatory, parallel per dimension) ───
const researchResults = (await parallel(
  RISK_DIMENSIONS.map(dim => () =>
    agent(RESEARCH_PROMPT(dim), {
      label: "research:" + dim.key,
      phase: "Research",
      schema: RESEARCH_SCHEMA,
    }).then(r => {
      if (!r) return null
      log("research " + dim.key + ": " + r.items.length + " items")
      return r
    })
  )
)).filter(Boolean)

// Merge per-dimension checklists into one, dedup in code by a normalized key.
const normKey = s => String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim()
const checklistById = new Map()
const checklistByContent = new Set()
let droppedDupes = 0
for (const r of researchResults) {
  for (const item of r.items) {
    const contentKey = normKey(item.dimension) + "|" + normKey(item.statement)
    if (checklistByContent.has(contentKey) || checklistById.has(item.id)) {
      droppedDupes++
      continue
    }
    checklistByContent.add(contentKey)
    checklistById.set(item.id, item)
  }
}
const checklist = [...checklistById.values()]
log("merged checklist: " + checklist.length + " items (" + droppedDupes + " dupes dropped) from " + researchResults.length + "/" + RISK_DIMENSIONS.length + " dimensions")

if (checklist.length === 0) {
  return { error: "Research produced an empty checklist — all dimension researchers returned null or no items. Cannot gate the build.", specPath: SPEC_PATH }
}

const renderChecklist = items =>
  items.map(c =>
    "- [" + c.id + "] (" + c.dimension + " / " + c.kind + (c.severity ? " / " + c.severity : "") + ") " + c.statement +
    "\n    detect: " + c.detect
  ).join("\n")
const checklistBlock = renderChecklist(checklist)

// ─── Phase: Plan ───
phase("Plan")
const plan = await agent(PLAN_PROMPT(checklistBlock), { label: "plan", phase: "Plan", schema: PLAN_SCHEMA })
if (!plan) {
  return { error: "Plan agent returned no result — cannot derive build steps.", specPath: SPEC_PATH, checklistItems: checklist.length }
}
log("plan: " + plan.steps.length + " steps")

// ─── Phase: Build (pipeline — per step: build then verify; verify gates progression) ───
phase("Build")
const buildOutcomes = await pipeline(
  plan.steps,

  step => agent(BUILD_PROMPT(step, checklistBlock), {
    label: "build:" + step.id,
    phase: "Build",
    schema: BUILD_STEP_SCHEMA,
  }).then(b => {
    if (!b) {
      log("build " + step.id + ": no result (skipped)")
      return { step, build: null }
    }
    log("build " + step.id + ": " + b.status + " — " + b.summary)
    return { step, build: b }
  }),

  built => {
    if (!built.build) return { stepId: built.step.id, built: null, verify: null, gated: false }
    return agent(VERIFY_PROMPT(built.step), {
      label: "verify:" + built.step.id,
      phase: "Build",
      schema: VERIFY_STEP_SCHEMA,
    }).then(v => {
      if (!v) {
        log("verify " + built.step.id + ": no result — treating as not-passed")
        return { stepId: built.step.id, built: built.build, verify: null, gated: false }
      }
      log("verify " + built.step.id + ": " + (v.passed ? "PASS" : "FAIL") + " — " + v.evidence)
      return { stepId: built.step.id, built: built.build, verify: v, gated: v.passed === true }
    }).catch(e => {
      log("verify " + built.step.id + " errored: " + (e.message || e))
      return { stepId: built.step.id, built: built.build, verify: null, gated: false }
    })
  }
)

const stepResults = buildOutcomes.filter(Boolean)
const failedSteps = stepResults.filter(s => !s.gated)
log("build done: " + stepResults.length + " steps, " + (stepResults.length - failedSteps.length) + " verified, " + failedSteps.length + " unverified")

// ─── Phase: Diff-audit (audit produced diff against merged checklist) ───
phase("Diff-audit")
const audit = await agent(AUDIT_PROMPT(checklistBlock), { label: "diff-audit", phase: "Diff-audit", schema: AUDIT_SCHEMA })
const auditById = new Map()
if (audit && Array.isArray(audit.items)) {
  for (const it of audit.items) auditById.set(it.id, it)
}
// Any checklist item the auditor failed to address counts as present-but-unverified
// (conservative: a missing audit entry is NOT a pass).
const auditUnverified = checklist.filter(c => {
  const a = auditById.get(c.id)
  if (!a) return true
  return a.present === true && a.verified !== true
})
log("diff-audit: " + (audit ? auditById.size : 0) + "/" + checklist.length + " items addressed, " + auditUnverified.length + " present-but-unverified")

// ─── Phase: Review/Fix (planned reviewer set; capped worst-of-N loop; verdict in code) ───
phase("Review/Fix")

// Plan the reviewer set: map changed files onto registered specialist reviewers,
// and synthesize ad-hoc reviewers for any dimension none of them cover.
const registryBlock = REVIEWER_REGISTRY.map(r => "- " + r.agentType + " — " + r.when).join("\n")
const reviewPlan = await agent(REVIEW_PLAN_PROMPT(registryBlock), { label: "review-plan", phase: "Review/Fix", schema: REVIEW_PLAN_SCHEMA })
const reviewerTasks = []
const usedTypes = new Set()
for (const a of ((reviewPlan && reviewPlan.assigned) || [])) {
  if (REGISTERED_TYPES.has(a.agentType) && !usedTypes.has(a.agentType)) {
    usedTypes.add(a.agentType)
    reviewerTasks.push({ kind: "named", agentType: a.agentType, label: a.agentType })
  }
}
for (const a of ((reviewPlan && reviewPlan.adhoc) || [])) {
  reviewerTasks.push({ kind: "adhoc", focus: a.focus, label: "adhoc:" + (normKey(a.aspect).replace(/ /g, "-") || "aspect") })
}
// Always keep at least one reviewer; cap the total to avoid fan-out blowup.
if (reviewerTasks.length === 0) reviewerTasks.push({ kind: "adhoc", focus: "General spec-conformance and correctness review of the entire diff.", label: "adhoc:general" })
const cappedTasks = reviewerTasks.slice(0, MAX_REVIEWERS)
if (reviewerTasks.length > MAX_REVIEWERS) log("review plan: " + reviewerTasks.length + " reviewers capped to " + MAX_REVIEWERS)
log("review plan: " + cappedTasks.map(t => t.label).join(", "))
const changedBlock = "Inspect via `git -C " + (BASE_PATH || ".") + " diff`."

let round = 0
let worstVerdict = "BLOCK"
let unverifiedItems = checklist.slice()
let lastFindings = []
let gatePassed = false

while (round < MAX_REVIEW_ROUNDS) {
  round++
  const reviews = (await parallel(
    cappedTasks.map(task => () =>
      agent(REVIEW_PROMPT(task, changedBlock, checklistBlock, round),
        task.kind === "named"
          ? { agentType: task.agentType, label: "review:r" + round + ":" + task.label, phase: "Review/Fix", schema: REVIEW_VERDICT_SCHEMA }
          : { label: "review:r" + round + ":" + task.label, phase: "Review/Fix", schema: REVIEW_VERDICT_SCHEMA })
    )
  )).filter(Boolean)

  if (reviews.length === 0) {
    // No reviewer adjudicated — cannot pass the gate this round.
    worstVerdict = "BLOCK"
    log("round " + round + ": no reviewer returned — verdict BLOCK")
    continue
  }

  // Worst-of-N verdict, computed in code (max rank wins).
  const worstRank = reviews.reduce((acc, r) => Math.max(acc, verdictRank[r.verdict] ?? verdictRank.BLOCK), 0)
  worstVerdict = verdictName[worstRank]

  // Merge reviewer checklist verdicts: an item is unverified if ANY reviewer
  // marks it present-but-unverified, OR no reviewer confirms it verified-safe.
  const verifiedSafe = new Set()
  const flaggedPresent = new Set()
  for (const r of reviews) {
    for (const c of (r.checklist || [])) {
      if (c.verified === true && c.present !== true) verifiedSafe.add(c.id)
      else if (c.verified === true && c.present === true) verifiedSafe.add(c.id)
      if (c.present === true && c.verified !== true) flaggedPresent.add(c.id)
    }
  }
  // Fold the diff-audit's present-but-unverified items in too.
  for (const c of auditUnverified) flaggedPresent.add(c.id)
  unverifiedItems = checklist.filter(c => flaggedPresent.has(c.id) || !verifiedSafe.has(c.id))

  lastFindings = reviews.flatMap(r => (r.findings || []))
    .sort((a, b) => (sevRank[a.severity] ?? 9) - (sevRank[b.severity] ?? 9))

  // HARD GATE (both conditions, computed in code — the model does not decide):
  const verdictPass = worstVerdict === "PASS"
  const checklistClean = unverifiedItems.length === 0
  gatePassed = verdictPass && checklistClean
  log("round " + round + ": worst-of-" + reviews.length + " = " + worstVerdict +
    " · unverified checklist items = " + unverifiedItems.length +
    " · gate " + (gatePassed ? "PASS" : "HELD"))

  if (gatePassed) break

  if (round >= MAX_REVIEW_ROUNDS) break

  // Dispatch a fix agent for the next round.
  const issuesBlock =
    "Worst-of-N verdict: " + worstVerdict + "\n\n" +
    "Present-but-unverified checklist items:\n" +
    (unverifiedItems.length ? renderChecklist(unverifiedItems) : "(none)") + "\n\n" +
    "Reviewer findings:\n" +
    (lastFindings.length ? lastFindings.map(f => "- (" + f.severity + ") " + f.detail).join("\n") : "(none)")
  const fix = await agent(FIX_PROMPT(issuesBlock, checklistBlock), {
    label: "fix:r" + round,
    phase: "Review/Fix",
    schema: FIX_SCHEMA,
  })
  if (!fix) {
    log("round " + round + ": fix agent returned no result")
  } else {
    log("round " + round + ": fix " + fix.status + " — " + fix.summary)
  }
}

// Cap reached without passing: log unresolved items, do not loop forever.
if (!gatePassed) {
  log("REVIEW CAP REACHED (" + MAX_REVIEW_ROUNDS + " rounds) without PASS. worst verdict=" + worstVerdict +
    ", unresolved checklist items=" + unverifiedItems.length)
  for (const c of unverifiedItems) {
    log("  unresolved [" + c.id + "] " + c.statement)
  }
}

return {
  specPath: SPEC_PATH,
  merged: gatePassed,
  verdict: worstVerdict,
  iterations: round,
  gate: {
    verdictPass: worstVerdict === "PASS",
    checklistClean: unverifiedItems.length === 0,
    passed: gatePassed,
  },
  unresolvedChecklist: unverifiedItems.map(c => ({ id: c.id, dimension: c.dimension, kind: c.kind, statement: c.statement })),
  findings: lastFindings,
  stats: {
    dimensionsResearched: researchResults.length,
    dimensionsTotal: RISK_DIMENSIONS.length,
    checklistItems: checklist.length,
    checklistDupesDropped: droppedDupes,
    planSteps: plan.steps.length,
    stepsVerified: stepResults.length - failedSteps.length,
    stepsUnverified: failedSteps.length,
    auditItemsAddressed: audit ? auditById.size : 0,
    auditUnverified: auditUnverified.length,
    reviewRounds: round,
    reviewersPlanned: cappedTasks.length,
    reviewersNamed: cappedTasks.filter(t => t.kind === "named").length,
    reviewersAdhoc: cappedTasks.filter(t => t.kind === "adhoc").length,
    unresolved: unverifiedItems.length,
  },
}
