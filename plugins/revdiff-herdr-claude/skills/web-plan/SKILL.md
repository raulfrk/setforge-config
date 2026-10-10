---
name: web-plan
description: Choose the plan format in Plan Mode. When the one attached Herdr viewer is Raul's phone in Moshi, write the plan as an HTML page for review there instead of Markdown. Use whenever you are in Plan Mode and about to write the plan file, and for explicit "web plan" requests.
allowed-tools: [Bash, Read, Edit, Write]
---

# Web plan

On Moshi, write the Plan Mode plan as an HTML page so Raul can review it on his
phone and comment per block. Everywhere else, write Markdown as usual.

## Choose the format

Once per plan, before writing the plan file:

```bash
SCRIPT_DIR="${CLAUDE_SKILL_DIR}/scripts"
python3 "$SCRIPT_DIR/viewer-check.py"
```

- `unsure`: write the plan in Markdown as usual and stop reading this skill.
- `moshi`: write the plan as HTML, as below.

Keep the chosen format across revisions, even if the device changes. If Raul
asks for a particular format, follow him whatever the check said.

## Mark the file

The plan file's first line must be `<!-- web-plan -->`. After a review returns
comments, the hook asks for a `<!-- previous revision: PATH -->` line first;
then put the mark on the line directly after it.

## Content rules

- Plain HTML only. No `<script>`, no `<style>`, no inline event handlers, no
  remote resources (images, fonts, links to load), no classes except the SVG
  ones below. The review page supplies layout and styling.
- Start with exactly one `<h1>` title; it becomes the page name Raul picks in
  Moshi. Optionally follow it directly with ONE short `<p>` summary line, shown
  under the title. Then `<section>`s, each starting with an `<h2>` (a small
  heading on a card).
- How the page shows elements:
  - `<ol>`: steps as a numbered timeline. `<ul>`: bullets.
  - `<table>`: rows; the first column is monospace, good for file paths.
  - `<aside>`: a highlighted note. Use it for a question or decision that is Raul's.
  - `<mark>`: a small green status chip. Use sparingly, for a short status such
    as "Low risk" or "Done".
  - `<figure>` + `<figcaption>`: a framed diagram with a caption. `pre`/`code`
    and `blockquote` as usual.
- One idea per block. Start every commentable block (heading, paragraph, list
  item, table row, figure, `pre`, `blockquote`, `aside`) on its own line. Raul
  comments per block, and comments are tied to the line a block starts on.
- Write for a phone: answer first, plain words, little text, no decoration.
  The plan must still hold everything needed to carry it out: files, steps,
  and verification.

### Diagrams

Include at least one inline SVG diagram wherever the plan has a flow, a
structure, or a before/after; skip it only when there is truly nothing to draw.
- `viewBox` about 330 wide so text stays readable on a phone. No fixed
  `width`/`height`. Text at least 10.5px. Always `role="img"` and `aria-label`.
- Inside `<svg>` only, use these class names; the page styles them for light and
  dark mode, so set no fill or stroke colours on elements that carry them:
  `node` (a box: `<rect>` with rx about 9), `dot` (circle behind an icon), `ic`
  (icon strokes), `lbl` (label text), `sub` (small grey text), `wire` (a
  connector or arrow path), `loop` (added to a wire to dot it), `pill` +
  `pilltxt` (a small tag such as "up to 3×").
- Draw wires before nodes, so boxes cover the line ends.

```html
<!-- web-plan -->
<h1>Add retry to the uploader</h1>
<p>Retry failed uploads three times, then report.</p>
<section>
<h2>How it flows</h2>
<figure>
<svg viewBox="0 0 330 100" role="img" aria-label="Upload, on failure wait and retry up to three times, then report">
<path class="wire loop" d="M165 40 C165 6 53 6 53 34"/>
<path class="wire" d="M48 27 L53 36 L59 27"/>
<path class="wire" d="M97 64 H121 M116 59 L122 64 L116 69 M209 64 H233 M228 59 L234 64 L228 69"/>
<rect class="pill" x="78" y="3" width="62" height="21" rx="10.5"/>
<text class="pilltxt" x="109" y="17.5" text-anchor="middle">up to 3×</text>
<rect class="node" x="9" y="40" width="88" height="48" rx="9"/>
<rect class="node" x="121" y="40" width="88" height="48" rx="9"/>
<rect class="node" x="233" y="40" width="88" height="48" rx="9"/>
<text class="lbl" x="53" y="68" text-anchor="middle">Upload</text>
<text class="lbl" x="165" y="68" text-anchor="middle">Wait, retry</text>
<text class="lbl" x="277" y="68" text-anchor="middle">Report</text>
</svg>
<figcaption>The dotted line is the retry loop</figcaption>
</figure>
<aside>Should the pauses be configurable? Default: no.</aside>
</section>
```

## Review

Calling ExitPlanMode opens the review automatically. Right before calling it,
tell Raul in one short line to tap the indigo Browser Preview button in Moshi
and pick the page with the plan's title.

His comments come back like RevDiff annotations (a line, a quote, the comment).
Address every one, then call ExitPlanMode again with the full revised plan. A
failed or interrupted review is never approval.

## Limits

The page is served on this server's loopback address for one review. Never
publish a plan anywhere: no Artifact, no Claude Docs, no external host.

The review page always uses port 47821 on this server, so only one web plan
review can be open at a time. A second one fails as "not reviewed"; retry it
after the first is finished.

The check proves only that the single attached Herdr client was opened by Moshi
with its `MOSHI_CLIENT` setting on. Several attached devices, or the setting
off, give `unsure`. If the review ends with "moshi-hook servers did not list
port", Moshi could not see the page; one known cause is a non-default `TMPDIR`
in the session.
