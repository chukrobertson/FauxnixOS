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
│  │  context ────┼───┼───────┼──────┼───┼───context    │           │
│  │  collection  │   │       │      │   │              │           │
│  └──────┬───────┘   └───────┼──────┘   └──────────────┘           │
│         │                   │                                      │
│         └───────────────────┘                                      │
│                   │                                                │
│         ┌─────────▼─────────┐                                      │
│         │   ML PIPELINE     │                                      │
│         │   (Nexus ↔ Fennix)│                                      │
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
│  │  SQLite + ChromaDB (persistent AI state)                      │ │
│  └───────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

## Component Roles

### Nexus — The Host Guard
- **Runs on:** Immutable NixOS base system
- **Scope:** Host-wide, cross-thread
- **Responsibilities:**
  - Thread lifecycle (wsctl backend — create, fork, merge, snapshot, restore, delete)
  - Security monitoring, intrusion detection (future phases)
  - ML pipeline orchestration (aggregates context from all Fennix instances)
  - Cross-thread suggestions ("thread A and B are 87% similar — merge?")
  - Ollama daemon management (single LLM server for all threads)

### Fennix — The In-Thread Assistant
- **Runs on:** Inside each thread container
- **Scope:** Single thread
- **Responsibilities:**
  - User activity monitoring (window titles, file changes, browser activity, git, terminal)
  - Context collection (feeds data to Nexus ML pipeline)
  - On-demand component installation (nix-shell, nix profile)
  - In-thread chat and assistance
  - Desktop shell (Qt6 panels, tray, quickbar)

### Threads — Continuity Containers
- **What:** Container-based workspaces (systemd-nspawn + btrfs subvolume)
- **Properties:**
  - Isolated OS (NixOS container closure with `boot.isContainer`)
  - Persistent or disposable
  - Forkable (snapshot + new manifest)
  - Mergeable (union Nix closures + file copy)
  - Desktop feel profiles: win11 or macos (labwc compositor + Fennix Qt6 panels)
- **Naming:** Threads of continuity. The CLI still uses `wsctl` for workspace control.

### ML Pipeline
- **Embedding model:** all-MiniLM-L6-v2 (CPU) or nomic-embed-text (Ollama)
- **Data flow:** Fennix (in-thread) → activity JSONL → Nexus aggregator → embeddings → clustering
- **Shared state:** SQLite DB on host, accessible by both Nexus and Fennix components

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
│   ├── membrie/                  # Session tracker (legacy, being absorbed)
│   ├── archivist/                # File manager (legacy, being absorbed)
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
