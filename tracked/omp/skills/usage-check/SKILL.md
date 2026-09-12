---
name: usage-check
description: Inspect redacted OMP provider allowance when authenticated and OMP-local activity, keeping their scope explicit.
---

# Usage check

Run only with provider key, OAuth, token, and auth-broker variables removed
from the command environment:

```bash
omp usage --json --provider openai-codex --redact
omp stats --json
```

Report provider allowance as shared account data and `stats` as OMP-local
activity. An unauthenticated allowance result is unavailable, not zero. Never
copy, inspect, or infer credentials to make the command succeed.

OMP cannot reconstruct Codex rollout-tree topology or token-based standard
credit estimates. Do not infer those values from OMP-local cost or tokens. Do
not add a parser for authenticated allowance output until a representative
sample has been captured on the target platform.

Usage is advisory. It does not authorize changing requested scope, required
checks, explicit models, or review requirements.
