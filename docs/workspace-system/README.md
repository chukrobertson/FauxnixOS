# FauxnixOS Workspace System

Container-based workspace management with AI-driven context awareness, fork/merge operations, and dual desktop feels.

## Concept

```
┌──────────────────────────────────────────────────────────┐
│                  Immutable NixOS Base                     │
│  ┌────────────┐  ┌──────────┐  ┌──────────────────────┐ │
│  │  Fennix    │  │ Snapper  │  │ Container Runtime    │ │
│  │ (assistant)│  │ (btrfs)  │  │ (systemd-nspawn)     │ │
│  │            │  │          │  │ or Podman            │ │
│  │ Ollama     │  │          │  │                      │ │
│  └─────┬──────┘  └────┬─────┘  └──────────┬───────────┘ │
│        │              │                   │              │
│  read-only /nix/store, tmpfs root overlay                │
└────────┼──────────────┼───────────────────┼──────────────┘
         │              │                   │
  ┌──────▼──────┐ ┌─────▼─────┐      ┌──────▼──────┐
  │ Workspace A │ │ Workspace B│      │ Workspace C │
  │ (nspawn)    │ │ (nspawn)   │      │ (nspawn)    │
  │             │ │            │      │             │
  │ win11 feel  │ │ macos feel │      │ headless    │
  │ btrfs subvol│ │ btrfs subvol│     │ dev shell   │
  │ git repo    │ │ git repo   │      │             │
  │ Nix closure │ │ Nix closure│      │             │
  │ Fennix agent│ │ Fennix agent│     │             │
  └──────┬──────┘ └─────┬──────┘      └─────────────┘
         │              │
  ┌──────▼──────────────▼──────┐
  │    Shared Files            │
  │    /@shared (btrfs)        │
  │    bind-mounted to all ws  │
  └────────────────────────────┘
```

## Core Operations

### Fork
"Start a new workspace from this content"
- Snapshot current workspace (safety)
- Create writable btrfs snapshot as new workspace
- Present file/app picker for what to carry over
- New workspace inherits parent's Nix closure
- Parent workspace unchanged

### Merge
"Merge this workspace into workspace X"
- Snapshot both workspaces (always — undo is free)
- Union their Nix closures (packages + services)
- Copy relevant files to shared directory
- Show diff summary
- Archive source workspace (soft-delete, snapshots preserved)

### Suggest
Fennix assistant detects drift/overlap and recommends:
- "You drifted from topic A into topic B — fork?"
- "Workspace X and Y are 87% similar — merge?"
- "You need a workspace for [detected task] — create?"

## Desktop Feel Profiles

Each workspace can adopt one of two desktop feels. These are compostor + theme templates, not separate codebases.

### Windows 11 Profile
- Bottom taskbar with centered launcher
- System tray right-aligned
- Rounded window corners, acrylic/blur effects
- Snap layout for window tiling
- Implementation: Labwc compositor + Fennix Qt6 panel (win11 layout)

### macOS Profile
- Top menu bar (global)
- Bottom dock with magnifying icons
- Spotlight-style quick launcher
- Mission Control-like workspace overview
- Implementation: Labwc compositor + Fennix Qt6 panel (macos layout)

Fennix's existing Qt6 UI layer (`fennix.ui.quickbar`, `fennix.ui.tray`, `fennix.ui.window`) provides the panel/dock/launcher for both profiles. The compositor underneath is the same (labwc/wayfire) — only the panel layout and QSS theme differ.

## Relationship to Existing FauxnixOS Components

| Component | Role in Workspace System |
|-----------|-------------------------|
| `fauxnix-tools` | Shared DB, LLM routing, file indexing |
| `fennix` | Assistant daemon, context collection, UI (tray/quickbar/window) |
| `membrie` | Session tracking per workspace (drift detection source) |
| `archivist` | File organization across shared files |

## Phases

| # | Phase | Dependencies |
|---|-------|-------------|
| 1 | [Immutable Base + btrfs + nspawn](./01-base-system.md) | None |
| 2 | [Fork/Merge CLI (wsctl)](./02-fork-merge-cli.md) | Phase 1 |
| 3 | [Per-Workspace Context Agent](./03-context-agent.md) | Phase 1 |
| 4 | [Embedding Pipeline + Clustering](./04-embeddings-clustering.md) | Phase 3 |
| 5 | [Assistant Daemon + Suggestion Engine](./05-assistant-daemon.md) | Phase 4 |
| 6 | [UI Layer + Desktop Feels + Polish](./06-ui-polish.md) | Phase 5 |

## Glossary

- **Workspace**: An isolated container (systemd-nspawn) with its own Nix closure, btrfs subvolume, and git repo
- **Base System**: The immutable NixOS host — read-only, boots clean every time, runs Fennix + Ollama + container runtime
- **Fork**: Create a new workspace from a snapshot of an existing one
- **Merge**: Combine two workspaces' closures and files into one, archiving the source
- **Drift**: When workspace activity diverges from its known topic vector
- **Feel Profile**: The desktop layout/theme applied to a workspace (win11 or macos)
