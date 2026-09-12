# Technical checkpoints

The primary owns technical design, including material architecture, component
boundaries, public interfaces, data flow, security boundaries, credentials,
migrations, destructive data operations, and compatibility. Assign an additional
read-only design specialist only for a concrete expertise or risk gap. Honor
configured roles and explicit model choices rather than selecting an author by
the primary model's name. Give an assigned author the complete relevant request,
decisions, repository evidence, constraints, and spike results; prohibit edits.
Send material revisions back to the same author with complete current evidence.
Authors never count as independent reviewers of their own work. Review-only
escalation does not require a design author.

Judge materiality from the proposed change and its consequences, not keywords,
file names, or the topic alone. A review or validation requirement does not by
itself require recovery, persistence, retry, or coordination software when
existing mechanisms or a bounded procedure satisfy the safety contract.

Require a focused independent `review_correctness` checkpoint before a
consequential action in those material risk classes. Provide the complete
evidence, proposed action, and exact question, and require a fresh verdict. A
current phase gate may satisfy the checkpoint only when it covers the same
risk, action, and complete current evidence.

Ordinary source revisions, the relevant diff, and relevant command evidence are
sufficient when they show the reviewed behavior. The checkpoint itself does not
require new bundles, manifests, or recovery tooling; require them only when the
task or its safety contract requires them. Identical evidence that was only
renamed or repackaged, and routine launcher corrections that cannot affect the
reviewed action or risk, do not require another review. Changed evidence
relevant to the action or risk still requires a fresh verdict.

Before a third implementation correction for the same unresolved issue after
two unsuccessful corrections, the primary reassesses the evidence and approach.
Require an independent `review_correctness` checkpoint when material or critical
uncertainty remains. After an inconclusive material spike, require an independent
checkpoint before selecting the next attempt. A phase gate may satisfy either
checkpoint only when it covers the same risk, action, and complete current evidence.

Route validated implementation corrections to the current owner: the primary
for its own work or the persistent worker for delegated work. The primary owns
routine gate validation. A reviewer cannot waive the spike rule: a revised
critical path must pass its stated runnable proof before production edits. If a
required reviewer or capability is unavailable or validated findings remain
unresolved, block the dependent work.
