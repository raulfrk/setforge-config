---
name: revdiff-plan
description: Review an OMP response or proposed plan with inline RevDiff annotations in a dedicated Herdr tab. Use for "revdiff-plan", "review plan with revdiff", "annotate plan", or "review last response".
---

# RevDiff Plan Review

Use the profile's `revdiff_plan` tool for an explicit review of the current plan
or last assistant response. Pass the complete canonical Markdown in `plan`; pass
`previous_plan` only when the user is reviewing a revision against its immediate
predecessor.

The tool remains pending until RevDiff closes. Do not background it or end the
turn before collecting its result. It opens the same responsive Herdr review
used by the automatic Plan gate, maps projected line numbers back to canonical
Markdown, and returns either the accepted plan or exact annotations.

If annotations return, interpret the comment and referenced context together.
Answer questions directly and apply concrete requested changes within the
existing authorization. Clarify only material ambiguity. Produce the complete
replacement, then call `revdiff_plan` again with that replacement and the
immediate prior plan. Continue until the tool reports a clean review.

OMP's root native Plan agent does not need this manual flow for a normal
proposal. A write to `xd://propose` is held while the profile reviews the exact
pinned native Plan artifact. Annotations block that write and return exact
feedback to the same Plan agent; a clean review alone allows OMP to open its
native approval surface.
