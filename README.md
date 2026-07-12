# FauxnixOS Core

**AI-native NixOS with containerized threads of continuity.**

FauxnixOS layers two AI assistants over an immutable NixOS base with btrfs-snapshotted container workspaces. Every thread of work gets its own isolated OS, auto-indexed files, continuous git history, and cross-thread context awareness.

## Quick Start

```bash
export PATH="$HOME/.local/bin:$PATH"

# Create and boot a thread — one command
wsctl ask "coding work" --profile win11 --name my-coder
# → Creates thread, boots container, starts Fennix + Archivist

# See all threads
wsctl list

# Detailed health
wsctl status my-coder

# Live dashboard
wsctl dashboard

# Search everything
wsctl search "attention"
```

## Architecture

```
┌──────────────────────────────────────────────────┐
│              GNOME DESKTOP (base)                 │
│  ┌────────────────────────────────────────────┐  │
│  │ [Fennix ext] 🔍 search │ ⏰  📶  🔊  🔲 3  │  │
│  │  ┌───────────────────────────────────────┐ │  │
│  │  │         NEXUS (host daemon)            │ │  │
│  │  │  context · pipeline · health · snap    │ │  │
│  │  └───────────────┬───────────────────────┘ │  │
│  │                  │                          │  │
│  │   IMMUTABLE BASE (tmpfs root)               │  │
│  │   btrfs · nspawn · ollama · ollama         │  │
│  └──────────────────┬───────────────────────┘  │
│                     │                          │
│       ┌─────────────┼─────────────┐           │
│  ┌────▼────┐   ┌────▼────┐   ┌────▼────┐     │
│  │ Thread A│   │ Thread B│   │ Thread C│     │
│  │ FENNIX  │   │ FENNIX  │   │ FENNIX  │     │
│  │ARCHIVIST│   │ARCHIVIST│   │ARCHIVIST│     │
│  │ wayvnc  │   │ wayvnc  │   │ wayvnc  │     │
│  └─────────┘   └─────────┘   └─────────┘     │
│       │              │              │          │
│    VNC:5901       VNC:5902      VNC:5903     │
└──────────────────────────────────────────────┘
```

## Components

| Component | Layer | Description |
|-----------|-------|-------------|
| [fauxnix-tools](./packages/fauxnix-tools/) | Shared | File ops, vision, media, LLM routing |
| [fennix](./packages/fennix/) | In-thread | Context collection, desktop shell, 11 services |
| [nexus](./packages/nexus/) | Host | Thread orchestration, ML pipeline, 5 services |
| [wsctl](./packages/wsctl/) | Host | Thread management CLI — 20 commands |
| [archivist](./packages/archivist/) | Threads | File manager — OCR, face/object detection |
| [membrie](./packages/membrie/) | Reference | Superseded — original continuity experiment |

## wsctl Commands (20)

```
create     start      stop       fork       merge      snapshot  
restore    delete     list       log        commit     diff       
attach     setup      ask        profiles   dashboard  status     
search     clip       snapshots  (prune)
```

## Nexus Services (5, runs on host)

| Service | Interval | Function |
|---------|----------|----------|
| ContextAggregator | 5s | Dispatch socket for Fennix event streams |
| ThreadSupervisor | 30s | Tracks threads via machinectl |
| PipelineRunner | 60s | Embed (nomic-embed-text, 768-dim) → cluster → drift |
| SnapshotService | 3600s | Hourly btrfs snapshots |
| ThreadHealthMonitor | 30s | Uptime, CPU/mem, crash count |

## Fennix Services (11, runs per-thread)

| Service | Interval | Function |
|---------|----------|----------|
| ContextStreamService | 5s | Streams events to Nexus |
| ClipboardContextWatcher | 2s | Clipboard history |
| OpenFilesTracker | 10s | Foreground process + files |
| SystemStateLogger | 300s | CPU/mem snapshots |
| AutoIngestionScanner | 600s | Auto-index directories |
| FileChangeReconciler | 120s | Detect file changes |
| GitActivityWatcher | 15s | Watch for commits |
| TerminalHistoryWatcher | 10s | Track shell commands |
| BrowserActivityWatcher | 10s | Chrome/Firefox/Brave/Edge |
| ClipboardBridge | 3s | Shared clipboard |
| GitAutoCommitService | 300s | Auto-commit every 5 min |

## Thread Templates (11)

| Template | Packages |
|----------|----------|
| `ml-python` | PyTorch, Jupyter, NumPy, Pandas |
| `coding` | Python, Rust, Go, Node.js, C, git, neovim |
| `rust-dev` | cargo, rustc, rust-analyzer |
| `web-dev` | Node.js, TypeScript, VS Code |
| `writing` | Pandoc, Zathura, LaTeX |
| `documents` | LibreOffice, Pandoc, LaTeX, Calibre |
| `research` | Chrome, Firefox, Obsidian, Zotero |
| `audio` | Ardour, Audacity, LMMS, FFmpeg |
| `image-video` | GIMP, Inkscape, Blender, Kdenlive |
| `gaming` | Steam, Lutris, Wine, GameMode |
| `minimal` | git, neovim, curl (base thread) |

## Desktop Feels

```
wsctl ask "coding" --profile win11     # Windows 11: bottom taskbar, acrylic blur
wsctl ask "design" --profile macos     # macOS: top bar, dock, frosted glass
```

QSS themes (3.5KB each) applied by Fennix on boot. Wayvnc VNC server auto-assigned (ports 5901-5920).

## Vision

| Model | Size | Function |
|-------|------|----------|
| OpenCV Haar (faces) | 0MB | Face detection — 2 faces found on test photo |
| llava-phi3:3.8b (objects) | 2.9GB | Object + scene detection via Ollama |
| nomic-embed-text (embeddings) | 274MB | 768-dim vectors for clustering |
| qwen2.5:1.5b (LLM ask) | 986MB | Template matching from natural language |

## GNOME Base

The immutable base runs GNOME with a Fennix extension:
- **Top bar indicator** — live thread count, updates every 10s
- **Quick-create menu** — any template in one click
- **Running thread list** — click to attach
- **Wallpaper + lockscreen** — Fauxnix branding
- **Runs only essential services** — Nexus, Ollama, SSH

## Status

**31 commits, 87 Python files, all features proven working.** Threads boot with Fennix + Archivist, events stream to Nexus, pipeline clusters + suggests, face/object detection runs automatically.

## Documentation

- [ARCHITECTURE.md](./ARCHITECTURE.md) — Full system design
- [ROADMAP.md](./ROADMAP.md) — Upcoming features
- [AGENTS.md](./AGENTS.md) — For AI coding assistants
- [docs/immutable-base.md](./docs/immutable-base.md) — Deployment guide
- [docs/workspace-system/](./docs/workspace-system/) — Original design docs (historic)
