# Design authors

The primary owns technical design, including material architecture, component
boundaries, public interfaces, data flow, security boundaries, credentials,
migrations, destructive data operations, and compatibility. Assign an additional
read-only design specialist only for a concrete expertise or risk gap. Give an
assigned author the complete relevant request, decisions, repository evidence,
constraints, and spike results; prohibit edits. Send material revisions back
to the same author with complete current evidence. Authors never count as
independent reviewers of their own work. Review-only escalation does not
require a design author.

Judge materiality from the proposed change and its consequences, not keywords,
file names, or the topic alone. A review or validation requirement does not by
itself require recovery, persistence, retry, or coordination software when
existing mechanisms or a bounded procedure satisfy the safety contract.
