---
name: moshi-media-preview
description: Create localhost review pages and diagrams, or show requested images, PDFs, and media through Moshi Browser Preview. Use for review-page or diagram requests in a confirmed current Moshi session.
---

# Moshi media preview

Use Moshi's in-app Browser Preview for a readable local review or media page. It forwards a
host-local HTTP server over SSH even when the terminal connection uses Mosh.
Mosh's text-block image fallback is unsuitable for full-resolution documents.

## Confirm the current client first

Proceed only when the current request identifies Moshi as the app currently
used to view this conversation, the user
has confirmed Moshi during the ongoing interaction, or trusted current-client
metadata ties Moshi to this conversation. Reconfirm after a connection change
or when resuming without reliable current-client evidence. If uncertain, ask
one concise question before creating a page or starting a server.

A paired/running `moshi-hook`, another Mosh connection on the host, multiplexer
state, or inherited environment variables do not identify this conversation's
viewer. `moshi-hook context` identifies terminal/multiplexer context, not the
client app. Do not use it as proof of Moshi. If the current viewer is not Moshi,
skip this workflow and use the normal inline image/file delivery available.

## Prepare and open the page

- Use the existing `moshi-hook` and Python installation. Browser Preview needs
  `moshi-hook` installed/running on the host; report missing prerequisites
  rather than installing or restarting services as part of opening media.
- Reuse an accessible preview owned by this task when its served files and
  process are known. Otherwise create a private temporary directory and copy
  only the explicitly requested media into it. Resolve the actual source and
  destination paths; do not serve a repository, home, config, or general
  artifact directory. Use ordinary copied files, simple filenames, and escaped
  labels/URLs in a small generated `index.html`; keep it self-contained.
- For requests such as "make a review page", "show this plan as a page", or
  "draw a diagram" in a confirmed Moshi session, create the requested content
  in that private directory. Use a readable, phone-friendly HTML page with a
  clear title, viewport metadata, and simple CSS. For diagrams, prefer inline
  SVG or HTML/CSS; use an existing local renderer when the format requires it.
  Include only content relevant to the request. Keep scripts, fonts, images,
  and styles local; do not load a CDN, analytics, remote renderer, or external
  embeds. A page/diagram request authorises generating its HTML/SVG and any
  minimal local interaction needed for that review. Escape quoted source text;
  display untrusted HTML as text rather than executing it. Assess separately
  any request to run an existing active document.
- This workflow creates local artifacts. Do not publish an Artifact,
  create a Claude Doc, upload content, or invoke a cloud publishing workflow for
  these requests. Keep ordinary written reviews inline unless a page is requested;
  an explicitly requested RevDiff review still uses its existing skill.
- Link each original image and PDF so the user can open and zoom it. Show image
  thumbnails if useful. For an unsupported PDF viewer, render requested pages
  with an already-available PDF renderer and link the resulting PNGs as a
  labelled fallback; retain the original PDF link. Browser-supported audio or
  video can use their normal media controls. Do not install a viewer or change
  Herdr graphics settings for this workflow. Treat existing HTML/SVG documents
  as active content; do not add them to the page without a separate explicit
  request and assessment.
- Choose an available port, using existing discovery settings. Bind only to
  `127.0.0.1`. A sufficient server is:

  ```sh
  python3 -u -m http.server 8000 --bind 127.0.0.1 --directory "$preview_dir"
  ```

  Replace the directory and port with verified task-owned values. Keep its
  process handle, PID, bind address, and directory in the current task context.
  An occupied port is a reason to choose another, not stop an unrelated server.
- Check that the page and original media return the expected bytes and content
  types, then use `moshi-hook servers` to confirm discovery of this exact PID,
  loopback address, and port. `moshi-hook set scan-ports` reads the discovery
  policy; do not broaden it silently. Do not upload files to Moshi Files,
  publish a public URL, bind publicly, or use a public tunnel.
- Tell the user to tap Browser Preview's indigo button in the Moshi terminal
  header and select the detected page name and port. Opening an ordinary
  `127.0.0.1` link on the phone before forwarding is not the same operation.
  Browser Preview requires Moshi Pro and **Settings → Hooks → Use preview**.
  If unavailable, report that prerequisite; do not change subscriptions or
  reconnect the terminal automatically.
- Distinguish a healthy HTTP endpoint from a working phone display. Obtain
  user confirmation when visual acceptance matters. No continuous polling is
  needed once the page is ready.

## Lifetime and cleanup

Keep the preview available while the user is reviewing it. Closing a helper
pane does not imply stopping the independent HTTP server. Do not open a Herdr
pane unless requested; use the `herdr` skill to resolve its true identity and
preserve focus if one is needed. No daemon, Claude Code, or Herdr restart is required.

When the preview is no longer needed, stop only its verified owned process
and collect its exit status. Remove only its task-owned copied/generated files
when cleanup is authorised; preserve the originals. If process ownership or
server lifetime after a disconnect is uncertain, inspect before starting a
replacement or claiming cleanup succeeded.

[Moshi Browser Preview documentation](https://getmoshi.app/docs/browser-preview)
