# RevDiff returns

`O` exports annotations without quitting; automatic reflow does not complete a
review. Act on annotations returned by a completed review or on a verified
export the user explicitly asks to process. An export alone is not acceptance
or completion.

Interpret returned annotations in context. Answer questions directly, apply
concrete requested edits within scope, and clarify material ambiguity. Punctuation
or a keyword alone does not turn a question into an edit or authorize a new
review loop. Preserve the current review's exact revision provenance.

Do not inspect or incorporate annotation contents before they are returned. Do not
discard or defer later actionable feedback after it returns; route every validated
implementation correction to its existing owner. If a known fixture or path represents later feedback, defer reading its contents
until the initial gate is complete, and explicitly tell every initial reviewer
not to inspect that path. Merely saying that feedback will be applied later is
not sufficient because reviewers can inspect the shared workspace themselves.

If returned annotations change a plan, build the complete replacement. If they
change files, apply the same justified-check policy used above. In either case,
reselect specialists from the changed risk surface and apply the same current
revision review, targeted specialist rerun, retained-verdict, thread-reuse, and
fresh-completion rules above. Resolve findings until clean before presenting a
replacement plan or offering RevDiff again.
