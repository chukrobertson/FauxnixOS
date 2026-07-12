# FauxnixOS Thread System

> **Note:** These documents are the original design specifications. The implementation evolved significantly — see [ARCHITECTURE.md](../../ARCHITECTURE.md) and [README](../../README.md) for current state.

Container-based threads of continuity with AI-driven context awareness, fork/join operations, and dual desktop feels.

## Concept

Threads are isolated NixOS containers (systemd-nspawn + btrfs) that can be forked, merged, snapshotted, and restored. Two AI assistants operate at different layers:

```
┌──────────────────────────────────────────────────────────┐
│                  Immutable NixOS Base                     │
│  ┌────────────┐  ┌──────────┐  ┌──────────────────────┐ │
│  │   NEXUS    │  │ Snapper  │  │ Container Runtime    │ │
│  │ (host      │  │ (btrfs)  │  │ (systemd-nspawn)     │ │
│  │  daemon)   │  │          │  │                      │ │
│  │            │  │          │  │                      │ │
│  │ Ollama     │  │          │  │                      │ │
│  └─────┬──────┘  └────┬─────┘  └──────────┬───────────┘ │
│        │              │                   │              │
│  read-only /nix/store, tmpfs root overlay                │
└────────┼──────────────┼───────────────────┼──────────────┘
         │              │                   │
  ┌──────▼──────┐ ┌─────▼─────┐      ┌──────▼──────┐
  │  Thread A    │ │ Thread B  │      │ Thread C    │
  │  (nspawn)    │ │ (nspawn)  │      │ (nspawn)    │
  │             │ │            │      │             │
  │ win11 feel  │ │ macos feel │      │ headless    │
  │ btrfs subvol│ │ btrfs subvol│     │ dev shell   │
  │ Nix closure │ │ Nix closure│      │             │
  │             │ │            │      │             │
  │ ┌─────────┐ │ │ ┌────────┐ │      │ ┌─────────┐ │
  │ │ FENNIX   │ │ │ │FENNIX  │ │      │ │ FENNIX   │ │
  │ │(in-thread│ │ │ │        │ │      │ │          │ │
  │ │assistant)│ │ │ │        │ │      │ │          │ │
  │ └────┬────┘ │ │ └───┬────┘ │      │ └────┬────┘ │
  │      │      │ │     │      │      │      │      │
  └──────┼──────┘ └─────┼──────┘      └──────┼──────┘
         │              │                     │
    context stream  context stream      context stream
         │              │                     │
  ┌──────▼──────────────▼─────────────────────▼──────┐
  │          ML Pipeline (Nexus-hosted)              │
  │  embeddings → clustering → drift → suggestions   │
  └──────────────────────────────────────────────────┘
```

## Thread Lifecycle

### Spin (Fork)
"Start a new thread from this content"
- Snapshot current thread (safety)
- Create writable btrfs snapshot as new thread
- New thread inherits parent's Nix closure
- Parent thread unchanged
- Nexus detects topic drift → suggests spin

### Join (Merge)
"Merge this thread into thread X"
- Snapshot both threads (always — undo is free)
- Union their Nix closures (packages + services)
- Copy relevant files to shared directory
- Archive source thread (soft-delete, snapshots preserved)
- Nexus detects 87% topic overlap → suggests join

### Suggest
Nexus detects patterns and recommends:
- "You drifted from topic A into topic B — spin?"
- "Thread X and Y are 87% similar — join?"
- "You need a thread for [detected task] — create?"

## Nexus vs Fennix

| | Nexus (Host) | Fennix (In-Thread) |
|---|---|---|
| **Scope** | All threads | Single thread |
| **Runs** | Immutable base system | Inside each thread container |
| **Manages** | Thread lifecycle, ML pipeline, security | User activity monitoring, context collection |
| **Data** | Aggregates from all Fennix instances | Streams context to Nexus |
| **UI** | systemd service (headless) | Qt6 desktop shell (tray, quickbar, panels) |
| **LLM** | Coordinates Ollama (single server) | Uses Ollama via Nexus proxy |
| **Security** | Intrusion detection, audit (future) | Threat reports to Nexus (future) |

## Desktop Feel Profiles

Each thread can adopt one of two desktop feels:

### Windows 11 Profile
- Bottom taskbar with centered launcher
- System tray right-aligned
- Rounded window corners, acrylic/blur effects
- Implementation: labwc compositor + Fennix Qt6 panel (win11 layout + QSS theme)

### macOS Profile
- Top menu bar (global)
- Bottom dock with magnifying icons
- Spotlight-style quick launcher
- Implementation: labwc compositor + Fennix Qt6 panel (macos layout + QSS theme)

## ML Pipeline

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Thread A    │     │ Thread B    │     │ Thread C    │
│ Fennix      │     │ Fennix      │     │ Fennix      │
│ activity ───┼─────┼──activity ──┼─────┼──activity ──┤
│   .jsonl    │     │   .jsonl    │     │   .jsonl    │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       └───────────────────┼───────────────────┘
                           │
                    ┌──────▼──────┐
                    │    Nexus    │
                    │  Aggregator │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Textify    │
                    │  Embed      │
                    │  Cluster    │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Drift      │
                    │  Detection  │
                    │  Overlap    │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  Suggestion │
                    │  Engine     │
                    │  (spin/join)│
                    └─────────────┘
```

## Data Flow (Fennix + Archivist → Nexus)

1. Fennix (in-thread) collects: window titles, file changes, browser domains, terminal history, git activity, idle state
2. Archivist (in-thread) feeds: OCR text, object detection results, face tags, file classifications
3. Combined context writes to `activity.jsonl` + streams via unix socket
4. Nexus aggregator reads all thread sockets
4. Textifies → embeds → clusters → detects drift/overlap
5. Suggestions queued → delivered via libnotify or Fennix tray

## Relationship to Existing Components

| Component | Role in Thread System |
|-----------|----------------------|
| `fauxnix-tools` | Shared DB, LLM routing, file indexing |
| `fennix` | In-thread assistant: context collection, desktop shell, Qt6 UI |
| `nexus` (planned) | Host daemon: thread orchestration, ML pipeline, security |
| `archivist` | Default file manager (base + threads) — OCR, face/object detection, media transcription; feeds ML results to Fennix (in-thread) and Nexus (host) |
| `membrie` | Superseded — app-level continuity succeeded by the OS-level thread system |
| `wsctl` | Thread management CLI |

## Phases

| # | Phase | Dependencies |
|---|-------|-------------|
| 1 | [Immutable Base + btrfs + nspawn](./01-base-system.md) | None |
| 2 | [Fork/Merge CLI (wsctl)](./02-fork-merge-cli.md) | Phase 1 |
| 3 | [Per-Thread Context Agent (Fennix)](./03-context-agent.md) | Phase 1 |
| 4 | [Embedding Pipeline + Clustering (Nexus ML)](./04-embeddings-clustering.md) | Phase 3 |
| 5 | [Assistant Daemon + Suggestion Engine (Nexus)](./05-assistant-daemon.md) | Phase 4 |
| 6 | [UI Layer + Desktop Feels + Polish (Fennix Shell)](./06-ui-polish.md) | Phase 5 |

## Glossary

- **Thread**: A containerized workspace. Short for "thread of continuity."
- **Nexus**: Host-level daemon — manages threads, ML pipeline, security.
- **Fennix**: In-thread assistant — monitors activity, assists the user.
- **Archivist**: Default file manager — OCR, object/face detection, media transcription. Feeds ML results to Nexus and Fennix.
- **Membrie**: Superseded. App-level continuity experiment — succeeded by the OS-level thread system.
- **Base System**: The immutable NixOS host — read-only, boots clean every time.
- **Spin**: Fork a new thread from an existing one.
- **Join**: Merge two threads into one.
- **Drift**: When thread activity diverges from its known topic vector.
- **Feel Profile**: The desktop layout/theme applied to a thread (win11 or macos).
