# FauxnixOS Architecture

## Overview

FauxnixOS is a NixOS-based operating system built around containerized **threads of continuity** — isolated workspaces that can be forked, merged, snapshotted, and restored. Two AI assistants operate at different layers, sharing a common ML pipeline.

```
┌──────────────────────────────────────────────────────────────────┐
│                    FAUXNIX OS                                     │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                 NEXUS (Host-Level Daemon)                     │ │
│  │  "The orchestrator and guardian of the base system"          │ │
│  │                                                               │ │
│  │  • Thread lifecycle management (create, fork, merge, snap)   │ │
│  │  • Cross-thread ML pipeline (embeddings, clustering, drift)  │ │
│  │  • Security audit and intrusion detection (future)           │ │
│  │  • Ollama coordination (one LLM server, all threads)         │ │
│  │  • fs orchestration: btrfs subvolumes, snapshots, shared dir │ │
│  └────────────────────────┬────────────────────────────────────┘ │
│                           │                                       │
│  ┌────────────────────────┼────────────────────────────────────┐ │
│  │              IMMUTABLE NIXOS BASE                            │ │
│  │  Read-only /nix/store, tmpfs root overlay, btrfs root       │ │
│  │  systemd-nspawn, snapper, ollama.service, nexus.service      │ │
│  └────────────────────────┼────────────────────────────────────┘ │
│                           │                                       │
│         ┌─────────────────┼─────────────────┐                    │
│         │                 │                 │                    │
│  ┌──────▼──────┐   ┌──────▼──────┐   ┌──────▼──────┐           │
│  │  Thread A    │   │  Thread B    │   │  Thread C    │           │
│  │  (nspawn)    │   │  (nspawn)    │   │  (nspawn)    │           │
│  │              │   │              │   │              │           │
│  │ ┌──────────┐ │   │ ┌──────────┐ │   │ ┌──────────┐ │           │
│  │ │  FENNIX   │ │   │ │  FENNIX   │ │   │ │  FENNIX   │ │           │
│  │ │ in-thread │ │   │ │ in-thread │ │   │ │ in-thread │ │           │
│  │ │ assistant │ │   │ │ assistant │ │   │ │ assistant │ │           │
│  │ └─────┬────┘ │   │ └─────┬────┘ │   │ └─────┬────┘ │           │
│  │       │      │   │       │      │   │       │      │           │
│  │ ┌─────▼────┐ │   │ ┌─────▼────┐ │   │ ┌─────▼────┐ │           │
│  │ │ARCHIVIST │ │   │ │ARCHIVIST │ │   │ │ARCHIVIST │ │           │
│  │ │file mgr  │ │   │ │file mgr  │ │   │ │file mgr  │ │           │
│  │ │OCR/ML    │ │   │ │OCR/ML    │ │   │ │OCR/ML    │ │           │
│  │ └─────┬────┘ │   │ └─────┬────┘ │   │ └─────┬────┘ │           │
│  │       │      │   │       │      │   │       │      │           │
│  │  context ────┼───┼───────┼──────┼───┼───context    │           │
│  │  + ML meta   │   │       │      │   │  + ML meta   │           │
│  └──────┬───────┘   └───────┼──────┘   └──────────────┘           │
│         │                   │                                      │
│         └───────────────────┘                                      │
│                   │                                                │
│         ┌─────────▼─────────┐                                      │
│         │   ML PIPELINE     │                                      │
│         │   (Nexus-hosted)  │                                      │
│         │                    │                                      │
│         │ • Embedding model  │                                      │
│         │ • Topic clustering │                                      │
│         │ • Drift detection  │                                      │
│         │ • Thread similarity│                                      │
│         │ • Suggestion engine│                                      │
│         └─────────┬─────────┘                                      │
│                   │                                                │
│  ┌────────────────▼─────────────────────────────────────────────┐ │
│  │                   SHARED DATA LAYER                           │ │
│  │                                                               │ │
│  │  /shared (btrfs, bind-mounted into all threads)               │ │
│  │  fauxnix-tools (shared Python library)                        │ │
│  │  Archivist ML metadata (OCR, faces, objects, transcripts)     │ │
│  │  SQLite + ChromaDB (persistent AI state)                      │ │
│  └───────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

## Component Roles

### Nexus — The Host Daemon
- **Runs on:** Immutable NixOS base system
- **Scope:** Host-wide, cross-thread
- **Stability contract:** Must not modify the host system. All changes happen inside threads. Nexus reads data, manages containers, and coordinates — never installs packages or modifies `/nix/store`.
- **Responsibilities:**
  - **Thread lifecycle** — create threads based on user workload requests ("I need to work on PDFs" → Nexus spins up a thread with Zathura, Pandoc, LaTeX). Backs `wsctl` commands.
  - **Context aggregation** — Receives activity streams from all Fennix instances via unix sockets. Aggregates into a shared SQLite DB.
  - **ML pipeline** — Textify → embed → cluster → detect drift and thread overlap.
  - **Suggestion engine** — "Thread A and B are 87% similar — merge?" "You drifted from coding into writing — fork?"
  - **Ollama coordination** — Single LLM server for all threads. Routes requests from Fennix instances.
  - **Security monitoring** — Intrusion detection, audit logging (future).

### Fennix — The In-Thread Assistant
- **Runs on:** Inside each thread container (one per thread)
- **Scope:** Single thread
- **Responsibilities:**
  - **Context collection** — Window titles, file changes, browser domains, terminal history, git activity, idle state. Already implemented via `fennix.context.*` and `fennix.services.*`.
  - **Context streaming** — Feeds activity data to Nexus via unix socket. Aggregated context + file metadata + ML results from Archivist.
  - **Software installation** — `nix-shell -p`, `nix profile install`, `nix-env -iA`. Install components the user needs for the current task.
  - **Thread adaptation** — Modify the thread environment to better suit the task (install missing tools, adjust config).
  - **Desktop shell** — Qt6 panels, system tray, quickbar overlay. Windows 11 or macOS feel profiles via QSS themes.
  - **User assistance** — In-thread chat, recall, file search via `fennix.recall` and `fennix.ingestion`.
  - **Nexus collaboration** — Sends activity context to Nexus, receives merge/fork suggestions, presents them to user.

### Nexus ↔ Fennix Communication

```
┌──────────────────────────────────────────────┐
│                  HOST SYSTEM                  │
│                                               │
│  ┌─────────┐         ┌──────────────────┐    │
│  │  Nexus   │◄────────│ /run/nexus/      │    │
│  │          │ unix    │   thread-A.sock  │    │
│  │  context │ sockets │   thread-B.sock  │    │
│  │  engine  │         │   thread-C.sock  │    │
│  └────┬─────┘         └───┬──────────────┘    │
│       │                   │                    │
│       │ suggestions       │ activity stream    │
│       │ (libnotify or     │ (JSONL over unix   │
│       │  Fennix tray)     │  socket)           │
│       │                   │                    │
│  ┌────┴───────────────────┴─────────────────┐ │
│  │           SHARED SQLITE DB               │ │
│  │  (workspace_vectors, suggestions,        │ │
│  │   thread_context, drift_events)          │ │
│  └──────────────────────────────────────────┘ │
│                                               │
│  ┌──────────────────────────────────────────┐ │
│  │         IMMUTABLE NIXOS BASE             │ │
│  │  nexus.service  │  ollama.service        │ │
│  └──────────────────────────────────────────┘ │
└──────────────┬───────────────┬────────────────┘
               │               │
    ┌──────────▼───┐   ┌───────▼──────────┐
    │  Thread A     │   │  Thread B         │
    │  ┌─────────┐  │   │  ┌─────────┐     │
    │  │ Fennix   │  │   │  │ Fennix   │     │
    │  │          ├──┼───┼──┤          │     │
    │  │ context  │  │   │  │ context  │     │
    │  │ stream   │  │   │  │ stream   │     │
    │  └─────────┘  │   │  └─────────┘     │
    └───────────────┘   └──────────────────┘
```

**Activity stream protocol (Fennix → Nexus):**
```json
{"ts":"2026-07-12T00:50:00Z","thread":"ml-paper","src":"window",
 "data":{"app":"zathura","title":"attention.pdf"},"dur":null}
{"ts":"2026-07-12T00:50:01Z","thread":"ml-paper","src":"file",
 "data":{"path":"/shared/notes/attention.md","action":"modify"}}
{"ts":"2026-07-12T00:50:02Z","thread":"ml-paper","src":"git",
 "data":{"repo":"/shared/transformers","branch":"experiment","msg":"Add attention","action":"commit"}}
{"ts":"2026-07-12T00:50:03Z","thread":"ml-paper","src":"browser",
 "data":{"domain":"arxiv.org","title":"Attention Is All You Need"}}
{"ts":"2026-07-12T00:50:04Z","thread":"ml-paper","src":"idle",
 "data":{"state":"active","seconds":45}}
```

**Suggestion protocol (Nexus → Fennix):**
```json
{"type":"fork_suggest","thread":"ml-paper","confidence":0.78,
 "title":"Fork new thread for Rust development?",
 "body":"Your recent activity in 'ml-paper' has shifted from ML to Rust programming.",
 "action":"wsctl fork ml-paper rust-dev --interactive"}
{"type":"merge_suggest","thread_a":"ml-paper","thread_b":"transformers",
 "confidence":0.89,"title":"Merge 'ml-paper' and 'transformers'?",
 "body":"These threads are 89% similar in topic. Consider merging.",
 "action":"wsctl merge ml-paper transformers"}
```

### Threads — Continuity Containers
- **What:** Container-based workspaces (systemd-nspawn + btrfs subvolume)
- **Properties:**
  - Isolated OS (NixOS container closure with `boot.isContainer`)
  - Persistent or disposable
  - Forkable (snapshot + new manifest)
  - Mergeable (union Nix closures + file copy)
  - Desktop feel profiles: win11 or macos (labwc compositor + Fennix Qt6 panels)
- **Naming:** Threads of continuity. The CLI still uses `wsctl` for workspace control.

### Archivist — The File Manager & Data Feeder
- **What:** Default file manager for both the base system and thread containers
- **Runs on:** Base system and inside each thread
- **Capabilities:**
  - OCR (Tesseract) — extract text from images and scanned documents
  - Object detection (YOLO / OWL-ViT) — identify objects in images and video
  - Face detection and recognition (InsightFace) — tag people in photo libraries
  - Media transcription (Whisper) — transcribe audio and video content
  - Smart organization — LLM-driven file classification, tagging, and renaming
  - Unified search — cross-source search across all indexed content
- **Data flow:**
  - Archivist (in-thread) → enriches files with ML metadata → feeds results to **Fennix**
  - Archivist (base) → enriches shared files with ML metadata → feeds results to **Nexus**
  - Both paths feed into the ML pipeline for cross-thread awareness

### Membrie — Superseded
- **What was:** App-level session tracker and memory companion
- **Status:** Superseded by Nexus (host-level orchestration) and Fennix (OS-level context awareness). The application-layer approach to continuity was a stepping stone — the thread system now provides continuity at the OS level rather than per-application. Code kept for reference.

### ML Pipeline
- **Embedding model:** all-MiniLM-L6-v2 (CPU) or nomic-embed-text (Ollama)
- **Data flow:** Fennix (in-thread) + Archivist → activity JSONL + file metadata → Nexus aggregator → embeddings → clustering
- **Shared state:** SQLite DB on host, accessible by all Nexus, Fennix, and Archivist components

## Directory Structure

```
fauxnix-core/
├── flake.nix                     # Root Nix flake
├── modules/                      # NixOS system modules
│   ├── fauxnix-tools.nix
│   ├── membrie.nix
│   ├── archivist.nix
│   ├── fennix.nix                # In-thread assistant module
│   └── nexus.nix                 # Host daemon module (future)
├── packages/
│   ├── fauxnix-tools/            # Shared Python library
│   │   └── fauxnix_tools/
│   │       ├── config.py
│   │       ├── db/
│   │       ├── files/
│   │       ├── vision/
│   │       ├── media/
│   │       ├── llm/
│   │       ├── utils/
│   │       └── enrichment/
│   ├── fennix/                   # In-thread assistant
│   │   └── fennix/
│   │       ├── ui/               # Qt6 desktop shell
│   │       ├── context/          # Activity collection
│   │       ├── ingestion/        # File/context pipeline
│   │       ├── recall/           # Memory search
│   │       └── services/         # Background service manager
│   ├── nexus/                    # Host daemon (planned)
│   │   └── nexus/
│   │       ├── threads/          # Thread lifecycle ops
│   │       ├── security/         # Intrusion detection
│   │       ├── pipeline/         # ML orchestration
│   │       └── services/
│   ├── archivist/                # Default file manager — OCR, face/object detection, media transcription
│   ├── membrie/                  # Superseded — app-level session tracker
│   └── wsctl/                    # Thread management CLI
│       └── wsctl/
│           ├── btrfs.py
│           ├── nspawn.py
│           ├── manifest.py
│           └── operations.py
├── containers/                   # Thread NixOS configs
│   └── minimal.nix               # Base thread config
├── docs/
│   └── workspace-system/         # Thread system design docs
├── ARCHITECTURE.md
├── AGENTS.md
└── README.md
```

## System Layers

```
Layer 0: Immutable NixOS Base
  - Read-only /nix/store
  - tmpfs root overlay
  - btrfs root filesystem with subvolumes
  - ollama.service (single LLM server)
  - systemd-nspawn / systemd-machined

Layer 1: Nexus (Host Daemon)
  - Thread management
  - Security monitoring
  - ML pipeline aggregation
  - Snapper/btrfs orchestration

Layer 2: Threads (Container Workspaces)
  - NixOS container with boot.isContainer
  - btrfs subvolume-backed root
  - Bind-mounted /shared directory
  - Bind-mounted /nix/store (read-only, shared with host)

Layer 3: Fennix (In-Thread Assistant)
  - Context collection agent
  - Desktop shell (Qt6 panels, themes)
  - Component installation
  - User assistance

Layer 4: User Applications
  - Any desktop app, terminal, browser
  - Compositor (labwc with win11/macos profile)
```

## Thread Lifecycle

```
create ──► start ──► active ──► stop ──► stopped
             │          │                    │
             │          ├─ snapshot ──► restore
             │          │
             │          ├─ fork ──► new thread
             │          │
             │          └─ merge ──► combined thread
             │
             └─ destroy

Every mutating operation snapshots first. Undo is always possible.
```

## ML Data Flow

```
┌──────────────────────────────────────────────────┐
│  Thread A (Fennix)                                │
│  activity.jsonl ──► unix socket ──┐              │
└────────────────────────────────────┼──────────────┘
                                     │
┌────────────────────────────────────┼──────────────┐
│  Thread B (Fennix)                │               │
│  activity.jsonl ──► unix socket ──┤              │
└────────────────────────────────────┼──────────────┘
                                     │
                              ┌──────▼──────┐
                              │    Nexus    │
                              │  Aggregator │
                              └──────┬──────┘
                                     │
                              ┌──────▼──────┐
                              │  Textify +  │
                              │  Embed      │
                              └──────┬──────┘
                                     │
                              ┌──────▼──────┐
                              │  Cluster +  │
                              │  Drift      │
                              │  Detection  │
                              └──────┬──────┘
                                     │
                              ┌──────▼──────┐
                              │  Suggestion │
                              │  Engine     │
                              │  (fork/     │
                              │   merge)    │
                              └─────────────┘
```

## Model Sizing Strategy

- **Heavy tasks (8-9B):** Vision analysis, video understanding, complex reasoning
  - Use: `qwen3-vl:8b`, `qwen2.5:7b`
- **Medium tasks (3-7B):** Chat, memory search, thread decisions
  - Use: `qwen2.5:7b`, `llama3.2:3b`
- **Light tasks (0.5-1.5B):** Summarization, classification, embedding
  - Use: `qwen2.5:1.5b`, `nomic-embed-text`

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `FAUXNIX_CHAT_MODEL` | `qwen2.5:7b` | Main chat/instruction model |
| `FAUXNIX_EMBED_MODEL` | `nomic-embed-text` | Text embeddings |
| `FAUXNIX_VISION_MODEL` | `qwen3-vl:8b` | Vision/image analysis |
| `FAUXNIX_SUMMARY_MODEL` | `qwen2.5:1.5b` | Summarization (small model) |
| `FENNIX_*` | (see fennix config) | In-thread assistant settings |
| `NEXUS_*` | (future) | Host daemon settings |
