---
name: usage-check
description: Inspect OpenCode token and cost statistics for the current project or local session history, and clearly separate them from provider account allowance.
---

# Usage check

Use OpenCode's public statistics command:

```bash
opencode stats --models --project "$PWD"
```

Use `opencode stats --models` only when the user asks for all local projects.
Report the command's time range, token counts, and recorded cost concisely.
These are local OpenCode session statistics; they are not subscription credits
or provider account allowance.

OpenCode 1.18.21 exposes no provider-account allowance endpoint. If the user
asks for remaining account allowance, say that it is unavailable through this
profile rather than scraping credentials, provider internals, or another
coding harness. Do not infer quota from local cost or token totals.

Usage is advisory. It does not authorize changing requested scope, required
checks, explicit models, or review requirements.
