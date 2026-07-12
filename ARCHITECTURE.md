# FauxnixOS Architecture

## Overview

FauxnixOS is a NixOS-based Linux desktop distribution with AI as a core system service — not an afterthought. Two applications share a common tooling library and work together:

```
┌──────────────────────────────────────────────────────────────┐
│                      FAUXNIX OS                              │
│                                                               │
│  ┌─────────────────────┐    ┌─────────────────────────────┐ │
│  │      MEMBRIE          │    │        ARCHIVIST             │ │
│  │  "What are you doing?" │    │  "Where is everything?"     │ │
│  │                       │    │                             │ │
│  │  • Session tracking   │    │  • Intelligent file mgr     │ │
│  │  • Activity timeline  │    │  • Face detection           │ │
│  │  • Session summaries  │    │  • Object detection         │ │
│  │  • Workspace creation │    │  • Media translation        │ │
│  │  • Drift detection    │    │  • Smart organization       │ │
│  │  • Memory companion   │    │  • LLM-driven decisions     │ │
│  │  • OTG mobile web     │    │  • Unified search           │ │
│  └──────────┬────────────┘    └─────────────┬───────────────┘ │
│             │                               │                 │
│             └───────────┬───────────────────┘                 │
│                         │                                     │
│              ┌──────────▼──────────┐                         │
│              │   FAUXNIX-TOOLS     │                         │
│              │   (shared library)  │                         │
│              │                     │                         │
│              │  • File extraction  │                         │
│              │  • Face detection   │                         │
│              │  • Vision analysis  │                         │
│              │  • Media processing │                         │
│              │  • LLM routing      │                         │
│              │  • File indexing    │                         │
│              │  • Auto-tagging     │                         │
│              │  • Snapshots        │                         │
│              └─────────────────────┘                         │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │                   SYSTEM LAYER                        │    │
│  │                                                       │    │
│  │  ollama.service  │  fauxnix-tools  │  membrie.service  │   │
│  │  whisper         │  ffmpeg         │  tesseract        │   │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
fauxnix-core/
├── flake.nix                 # Root Nix flake (aggregator)
├── ARCHITECTURE.md           # This file
├── modules/                  # NixOS system modules
│   ├── fauxnix-tools.nix     # Shared tooling system module
│   ├── membrie.nix           # Membrie systemd user service
│   └── archivist.nix         # Archivist systemd user service
├── packages/
│   ├── fauxnix-tools/        # Shared Python library
│   │   ├── pyproject.toml
│   │   ├── default.nix       # Nix derivation
│   │   └── fauxnix_tools/
│   │       ├── config.py     # XDG-compliant configuration
│   │       ├── db/           # SQLite + ChromaDB utilities
│   │       ├── files/        # Extraction, indexing, tagging, snapshots
│   │       ├── vision/       # Face detection, image analysis, object detection
│   │       ├── media/        # Video probing, storyboard, transcription
│   │       ├── llm/          # Model routing, embeddings, chat
│   │       ├── utils/        # Hashing, MIME, file categories
│   │       ├── context/      # Context source discovery
│   │       └── enrichment/   # Document enrichment pipeline
│   ├── membrie/              # Membrie app (Linux-native)
│   │   ├── pyproject.toml    # depends on fauxnix-tools
│   │   └── membrie/
│   │       ├── session/      # Session lifecycle, timelines, summaries
│   │       ├── awareness/   # Process detection (D-Bus/GNOME), drift
│   │       ├── chat/         # Chat orchestration, memory, persona
│   │       ├── ui/           # GTK system tray, PyQt6 window
│   │       └── web/          # OTG FastAPI server
│   └── archivist/            # Archivist app (new)
│       ├── pyproject.toml    # depends on fauxnix-tools
│       └── archivist/
│           ├── file_manager/ # File browsing + management UI
│           ├── smart_actions/ # LLM-driven file decisions
│           ├── translation/  # Media translation tools
│           ├── organizer/    # Smart file organization
│           └── search/       # Unified cross-source search
```

## Key Design Decisions

### 1. Shared Library (`fauxnix-tools`)
- All filesystem I/O, vision processing, media handling, and LLM routing lives here
- XDG-compliant: respects `XDG_DATA_HOME`, `XDG_CACHE_HOME`, `XDG_CONFIG_HOME`
- No GUI code — pure logic and data layer
- Designed to be importable by both Membrie and Archivist

### 2. Membrie — The Watcher
- **What it does:** Tracks user activity, builds session timelines, generates LLM summaries, detects drift from stated intentions, maintains a memory store
- **Process awareness:** Uses D-Bus + GNOME Shell Extension or `xdotool`/`wmctrl` (not Win32 APIs)
- **Unique features:** Session management, workspace-from-session export, OTG mobile web interface

### 3. Archivist — The Organizer
- **What it does:** Intelligent file manager with AI-powered search, face recognition, object detection, media translation, and automated organization
- **Process awareness:** None needed — it's a file manager, not a tracker
- **Unique features:** Object detection, media translation, smart organization decisions by local LLM

### 4. System Integration (NixOS)
- **ollama.service:** System-wide Ollama server (one per machine)
- **membrie-daemon.service:** User service, starts with graphical session
- **membrie-otg.service:** User service for mobile web interface (port 8920)
- **archivist-daemon.service:** User service for file monitoring/indexing
- All configured via `fauxnix.{membrie,archivist,tools}` NixOS options

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `FAUXNIX_DATA_DIR` | `~/.local/share/fauxnix` | All data, DB, vectors |
| `FAUXNIX_CHAT_MODEL` | `qwen2.5:7b` | Main chat/instruction model |
| `FAUXNIX_EMBED_MODEL` | `nomic-embed-text` | Text embeddings |
| `FAUXNIX_VISION_MODEL` | `qwen3-vl:8b` | Vision/image analysis |
| `FAUXNIX_SUMMARY_MODEL` | `qwen2.5:1.5b` | Summarization (small model) |
| `FAUXNIX_WHISPER_MODEL` | `base` | Speech-to-text model |
| `FAUXNIX_TESSERACT_CMD` | `tesseract` | OCR binary path |
| `FAUXNIX_FFMPEG_BIN` | `ffmpeg` | FFmpeg binary |
| `FAUXNIX_FACE_SCAN_IMAGES` | `true` | Auto-detect faces in images |
| `FAUXNIX_FACE_SCAN_VIDEOS` | `true` | Auto-detect faces in videos |

## Migration Phases

### Phase 1 — Shared Library (COMPLETED)
- Extracted all shared tooling from Membrie into `fauxnix-tools`
- Created Nix flake + derivation
- Linux paths, XDG compliance, D-Bus ready

### Phase 2 — Linux-port Membrie (IN PROGRESS)
- Replace Win32 process hooks with D-Bus/GNOME APIs
- System tray via GTK/PyQt6 (StatusNotifierItem)
- Build session management (timeline, summaries, workspaces)
- Wire to `fauxnix-tools`
- Package as Nix flake

### Phase 3 — Build Archivist (PLANNED)
- File manager UI on `fauxnix-tools`
- Object detection in `fauxnix-tools` (YOLO / OWL-ViT)
- Smart file decisions powered by local LLM
- Media translation pipeline
- Package as Nix flake

### Phase 4 — FauxnixOS System Integration (PLANNED)
- systemd user services for both daemons
- OTG on WiFaux kiosk display
- GNOME Shell extension for Membrie status
- Full `configuration.nix` module options

### Phase 5 — Workspace System (NEW)
- Container-based workspace isolation (systemd-nspawn + btrfs)
- Fork and merge workspaces like git branches
- AI-driven context awareness and drift detection
- Windows 11 and macOS desktop feel profiles
- Assistant-powered workspace suggestions
- Full docs: [docs/workspace-system/](./docs/workspace-system/)

## Model Sizing Strategy

- **Heavy tasks (8-9B):** Vision analysis, video understanding, complex reasoning
  - Use: `qwen3-vl:8b`, `qwen2.5:7b`
- **Medium tasks (3-7B):** Chat, memory search, file decisions
  - Use: `qwen2.5:7b`, `llama3.2:3b`
- **Light tasks (0.5-1.5B):** Summarization, simple classification, quick chat
  - Use: `qwen2.5:1.5b`, `qwen2.5:0.5b`
