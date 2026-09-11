---
name: usage-check
description: Inspect current Codex account allowance and estimate token-based standard credits for the current session tree. Use at substantial work boundaries, before a costly phase when fresh usage could change the approach, on explicit usage requests, or after a native usage warning.
---

# Usage check

Run the bounded read-only helper, passing a root thread ID only when
`CODEX_THREAD_ID` does not already identify the current root:

```bash
python ~/.codex/skills/usage-check/scripts/check_usage.py
```

The optional `--thread-id ID` overrides `CODEX_THREAD_ID` when checking a known
root session tree.

The compact JSON separates account allowance from estimated session-tree
credits. Account buckets are shared with concurrent sessions on other projects;
never attribute their change to this tree or convert an estimate into quota.
Token estimates use the bundled standard credit rates dated in the output, not
subscription deductions. Treat `unpriced` agents and incomplete coverage as
unknown usage rather than zero.

Reuse a sufficiently current snapshot. Show a short summary and compact agent
table. Compare estimated-credit changes with a previous-context snapshot only
when the root thread, pricing date, and coverage are comparable, and pair the
delta or rate with verified progress. Include time until the actual account
reset and remember that concurrent sessions share the remaining capacity. Keep
the comparison in context; do not create a persistent usage database.

At the first real phase boundary, record in the existing progress update whether
the check answered a usage question or informed a concrete decision. Report
later changes only when decision-relevant. If repeated checks are not useful,
recommend narrower triggers without automatically changing policy or creating a
tracker.

Usage is advisory. Choose a cheaper sufficient approach when useful while
preserving requested scope, required checks, explicit model choices, and safety
contracts. Unavailable usage does not block work, justify fabricated estimates
or caps, or authorize automatic model, scope, test, or review reductions.
