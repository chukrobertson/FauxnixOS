# Archivist File Manager Card

## Feature Summary

The Archivist File Manager card is a Fauxnix desktop feature for surfacing files
that matter to the user's current work. It is not a generic file browser. Its
purpose is to connect files, previews, notes, and thread continuity so Fennix can
help the user pick up work with evidence instead of guessing from chat history.

The card starts as a compact desktop widget and expands into a larger file
manager view when selected.

## Product Intent

Fauxnix treats the desktop as a continuity map. Files should appear as evidence
attached to threads, projects, notes, and recent actions. The Archivist File
Manager card is the first desktop bridge between the filesystem and that
continuity system.

Primary goals:

- Show recently relevant files without making the user browse folders first.
- Connect files to active threads and workspace memory.
- Keep previews and source paths visible so summaries stay grounded.
- Support quick open/copy/attach actions with read-only defaults.
- Become the local file surface that Fennix can reason about and act through.

Non-goals for v0:

- Replacing a full graphical file manager.
- Bulk destructive file operations.
- Automatic reorganization without explicit approval.
- Large recursive indexing of the whole home directory.

## Desktop Card

The compact card should be dense, calm, and immediately useful.

```text
Archivist
Watching: Downloads - Threads - Cowriter

[ Recent ] [ Thread ] [ Pinned ]

* README.md        Fauxnix / edited 4m ago
* screenshot.png   Pictures / 12m ago
* notes.md         Cowriter / today

Index healthy - 248 files
```

Card content:

- Header: `Archivist`
- Subtitle: watched roots or active scope
- Tabs: Recent, Thread, Pinned
- File rows: name, source, recency, lightweight status
- Footer: index health, file count, last scan time

Visual direction:

- Dark glass card consistent with Fauxshell.
- Orange title/accent.
- Cyan selection or active-thread glow.
- Small file-type chips where useful.
- No decorative folder art.
- Text must stay compact and readable at dashboard scale.

## Expanded View

Clicking the card opens an Archivist Files view.

Layout:

- Left rail: Recent, Downloads, Threads, Cowriter, Fauxnix, Pinned, Search
  Results.
- Center list: files with name, type, modified time, size, git/thread status.
- Right preview/details: preview, source path, summary, actions, linked thread
  memory.

Expected actions:

- Open
- Reveal
- Copy Path
- Attach to Active Thread
- Send to Cowriter
- Promote to Memory
- Pin

Risky actions such as delete, move, rename, bulk copy, and recursive changes must
stay out of v0 or require explicit confirmation gates later.

## Watched Roots

Initial watched roots should be narrow and useful:

- `~/Downloads`
- `~/Pictures`
- `~/Fauxnix/Threads`
- `~/Fauxnix/Cowriter`
- `~/Fauxnix/Repos`
- Active thread directories

The card should not scan all of `/home` by default. New roots should be added by
explicit user action or system settings.

## File Intelligence

Each file row can carry:

- Path
- Display name
- File type
- Modified time
- Size
- Source root
- Git status when inside a repo
- Attached thread id when known
- Pinned flag
- Short summary when available

Summaries must be evidence-backed. If a summary is inferred, label it as such.

## Fennix Integration

Fennix should be able to answer and act through the card:

- "Show recent files."
- "Open that screenshot."
- "Attach this file to the Fauxnix thread."
- "Send this note to Cowriter."
- "What files changed in this thread?"
- "Pin this as evidence."

Fennix defaults:

- Read-only inspection first.
- Open/reveal/copy path are low-risk actions.
- Attach/promote/pin are allowed local metadata actions.
- Destructive or filesystem-moving actions require explicit confirmation.

## Relationship To Continuity

The file manager card feeds the continuity constellation.

Continuity links may connect:

- Thread cards
- Chat messages
- Cowriter notes
- Clipboard captures
- Files
- Git snapshots
- Fennix memory entries

The user should be able to see files not as isolated objects, but as evidence in
the map of their work.

## Implementation Plan

### v0: Desktop Card

- Add an Archivist card to the Fauxshell desktop map.
- Read recent files from narrow watched roots.
- Show name, root, modified time, and file type.
- Keep actions read-only.

Status: implemented as the first read-only pass.

- Backend: `fauxd` exposes `GET /api/files/recent?limit=5`.
- Summary: `GET /api/summary` includes a `files` object for dashboard polling.
- Desktop: Fauxshell renders an `Archivist Files` card with scan health and
  recent file evidence rows.
- Scanner guardrails: bounded watched roots, no symlink traversal, hidden/cache
  directory skips, and per-root scan caps.

### v1: Expanded Files View

- Add click-to-open expanded Archivist Files view.
- Add left rail, file list, and preview/details pane.
- Support Open, Reveal, Copy Path, Pin.

Status: implemented as a read-only expanded view.

- Launch: the desktop `Archivist Files` card has an `Open Files` control that
  starts `fauxshell-host --files`.
- Backend: `GET /api/files/recent?limit=<n>&root=<root>` supports root-filtered
  file lists.
- Backend: `GET /api/files/preview?path=<path>` returns bounded metadata/text
  previews for regular files inside watched roots.
- UI: the expanded GTK view has a root rail, recent evidence list, and
  preview/details pane.
- Guardrails: preview is read-only, path-scoped to watched roots, symlink-safe,
  and capped to a small text preview.

### v2: Thread Attachments

- Add file-to-thread metadata.
- Show files attached to the active thread.
- Add "Attach to Active Thread" and "Promote to Memory".

Status: implemented and runtime-smoked.

- Backend: `POST /api/files/attach` records file evidence in
  `~/Fauxnix/Threads/<thread>/attachments.json`.
- Backend: `GET /api/files/attachments?thread=<thread>` lists attached file
  evidence for a thread.
- Backend: `POST /api/files/promote` creates a Fennix note from selected file
  metadata and a bounded text preview when available.
- UI: the expanded `Archivist Files` view has an `Attached` root, a thread
  selector, and `Attach` / `Promote` controls.
- Guardrails: attachment and promotion only accept regular files inside watched
  roots; the UI does not move, rename, or delete files.
- Verification note: after reboot, the live `fauxd` health check, thread
  attachment read-back, attach action, and promote action completed
  successfully.

### v3: Search And Preview

- Add filename search over watched roots.
- Add text search for text-like files.
- Add markdown/text/image previews.
- Add lightweight summaries for supported file types.

Status: implemented and runtime-smoked.

- Backend: `GET /api/files/search?q=<query>&root=<root>&content=1`
  searches watched roots with bounded scans. Filename/path matching is on by
  default; content matching is limited to previewable text files.
- Backend: previews now classify markdown, text, image, PDF metadata, and
  generic metadata.
- UI: the expanded `Archivist Files` view has a search row with Enter/Search,
  Clear, and a `Text` toggle for content search.
- UI: selected images render as a scaled preview above the text/metadata pane.
- Verification note: after rebuild and daemon refresh, `/api/files/search`
  returned README matches and `/api/files/preview` returned a markdown preview
  for `/home/chvk/Fauxnix/Repos/admin/README.md`.

### v4: Archivist-Style Indexing

- Add bounded background indexing.
- Add evidence labels and source confidence.
- Feed continuity constellation links.
- Expose file context to Fauxdex and Fennix planning.

Status: first pass implemented and runtime-smoked.

- Backend: `GET /api/files/index?rebuild=1` writes a bounded snapshot to
  `~/.local/state/fauxd/files-index.json`.
- Backend: file payloads now include `evidence_label` and
  `source_confidence`.
- Backend: recent file evidence now feeds the continuity constellation as
  `source=file` bubbles.
- UI: the expanded `Archivist Files` view has an `Index` action that refreshes
  the bounded snapshot and reports the indexed/scanned counts.
- UI: the Files window uses a translucent, frosted-glass style under current
  Sway. True background blur needs compositor support; `swayfx` is available in
  this Nixpkgs channel and can be tested as a later window-manager pass.
- Verification note: after rebuild and daemon refresh,
  `/api/files/index?rebuild=1` indexed 28 watched files and continuity returned
  2 file evidence bubbles.

### v5: Pinned Evidence

- Add durable user-pinned file evidence.
- Show pinned files as a first-class root in the expanded Files view.
- Let pinned evidence feed continuity.
- Keep pin/unpin non-destructive and scoped to watched roots.

Status: implemented and runtime-smoked.

- Backend: `GET /api/files/pins` lists pinned file evidence from
  `~/.local/share/fennix/file-pins.json`.
- Backend: `POST /api/files/pin` safely pins a selected watched file.
- Backend: `POST /api/files/unpin` removes the pin entry without touching the
  underlying file.
- Backend: pinned evidence contributes `source=file`, `kind=pinned evidence`
  continuity bubbles.
- UI: the expanded `Archivist Files` view has a `Pinned` root and `Pin` /
  `Unpin` actions.
- Verification note: after rebuild and daemon refresh, pinning
  `/home/chvk/Fauxnix/Repos/admin/README.md` succeeded, `/api/files/pins`
  returned one pinned file, and continuity returned one pinned evidence bubble.

### v6: Evidence Utility Actions

- Add small non-destructive actions that help evidence move into other
  workflows.
- Keep actions explicit and visible in the preview pane.

Status: implemented in code, runtime smoke pending.

- UI: `Copy Path` copies the selected file path to the system clipboard.
- Guardrail: the action only copies the already-selected safe watched-root path;
  it does not move, rename, delete, or open arbitrary files.

### v7: Basic Open And Reveal Actions

- Add low-risk file opening actions to the expanded Files view.
- Keep these actions scoped to the selected watched-root path.
- Prefer desktop/portal open behavior over shell-built command strings.

Status: implemented in code, runtime smoke pending.

- UI: `Open` asks the desktop to open the selected file URI.
- UI: `Reveal` asks the desktop to open the selected file's containing folder.
- Guardrail: actions use the already-selected file from the safe preview/list
  path; no move, rename, delete, or broad filesystem browsing is introduced.

## Guardrails

- Prefer bounded watched roots over broad home scans.
- Prefer previews and source links over narrative-only summaries.
- Keep file evidence candidate-labeled when uncertain.
- Do not hide status telemetry in the name of simplifying the UI.
- Do not add destructive file operations without permission gates.
- Keep the compact card useful even before the expanded view exists.

## Open Questions

- Should pinned files live in the Fennix SQLite database, thread metadata files,
  or both?
- Should thread attachments be portable markdown manifests under
  `~/Fauxnix/Threads/<thread>/`?
- Should the expanded view be implemented in Fauxshell C/GTK first, or in a
  separate GTK app shared by future Fennix surfaces?
- Should previews be served by `fauxd`, rendered directly in GTK, or split by
  file type?
