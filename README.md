# FauxnixOS Core

**AI-native NixOS with containerized threads of continuity.**

FauxnixOS layers two AI assistants over an immutable NixOS base with btrfs-snapshotted container workspaces. Every thread of work gets its own isolated OS, auto-indexed files, continuous git history, and cross-thread context awareness.

## Quick Start

```bash
# Add wsctl to your PATH (one-time)
export PATH="$HOME/.local/bin:$PATH"

# Create and boot a thread
wsctl ask "coding work" --profile win11 --name my-coder
# → Creates thread, boots container, starts Fennix + Archivist automatically

# See all threads
wsctl list

# Check one thread's health
wsctl status my-coder

# Attach to a running thread
wsctl attach my-coder

# Search across all threads
wsctl search "attention"

# Live dashboard
wsctl dashboard

# Manage snapshots
wsctl snapshot my-coder --label before-experiment
wsctl restore my-coder my-coder-before-experiment
wsctl snapshots prune
```

## Architecture

```
┌──────────────────────────────────────────────────┐
│                FAUXNIX OS                         │
│                                                   │
│  ┌─────────────────────────────────────────────┐ │
│  │           NEXUS (host daemon)                │ │
│  │  context aggregator · pipeline · health      │ │
│  │  snapshot service · suggestion engine        │ │
│  └──────────────────┬──────────────────────────┘ │
│                     │                             │
│  ┌──────────────────▼──────────────────────────┐ │
│  │         IMMUTABLE NIXOS BASE                │ │
│  │  btrfs  │  nspawn  │  ollama  │  systemd    │ │
│  └──────────────────┬──────────────────────────┘ │
│                     │                             │
│       ┌─────────────┼─────────────┐              │
│  ┌────▼────┐   ┌────▼────┐   ┌────▼────┐        │
│  │ Thread A│   │ Thread B│   │ Thread C│        │
│  │ FENNIX  │   │ FENNIX  │   │ FENNIX  │        │
│  │ARCHIVIST│   │ARCHIVIST│   │ARCHIVIST│        │
│  └────┬────┘   └────┬────┘   └────┬────┘        │
│       └──────────────┼──────────────┘             │
│                ┌─────▼─────┐                      │
│                │  /shared  │                      │
│                └───────────┘                      │
└──────────────────────────────────────────────────┘
```

## Components

| Component | Layer | Status | Description |
|-----------|-------|--------|-------------|
| [fauxnix-tools](./packages/fauxnix-tools/) | Shared | Stable | File ops, vision, media, LLM routing |
| [fennix](./packages/fennix/) | In-thread | Stable | Context collection, desktop shell, 11 services |
| [nexus](./packages/nexus/) | Host | Stable | Thread orchestration, ML pipeline, 5 services |
| [wsctl](./packages/wsctl/) | Host | Stable | Thread management CLI — 18 commands |
| [archivist](./packages/archivist/) | Base + Threads | Stable | Default file manager — OCR, face/object detection |
| [membrie](./packages/membrie/) | Reference | Superseded | Original app-level continuity experiment |

## Thread Lifecycle

```
wsctl ask "coding work"        wsctl snapshot my-thread
        │                              │
        ▼                              ▼
   create → start → ● running → stop → snapshot → restore
                │       │                         │
                │       ├─ fork → new thread      │
                │       │                         │
                │       ├─ merge → combined        │
                │       │                         │
                │       └─ attach → shell          │
                │                                  │
                └─ delete ← pre-delete snapshot ──┘
```

Every lifecycle operation auto-snapshots. Undo is always possible.

## wsctl Commands

```
create     start      stop       fork       merge      snapshot  
restore    delete     list       log        commit     diff       
attach     setup      ask        profiles   dashboard  status     
search     clip       snapshots
```

## Nexus Services (Host)

| Service | Interval | Function |
|---------|----------|----------|
| ContextAggregator | 5s | Dispatch socket for Fennix event streams |
| ThreadSupervisor | 30s | Tracks running threads via machinectl |
| PipelineRunner | 60s | Embed → cluster → drift detect → suggestions |
| SnapshotService | 3600s | Hourly snapshots of all running threads |
| ThreadHealthMonitor | 30s | Uptime, CPU/mem, crash count per thread |

## Fennix Services (In-Thread)

| Service | Interval | Function |
|---------|----------|----------|
| ContextStreamService | 5s | Streams activity events to Nexus |
| ClipboardContextWatcher | 2s | Clipboard history |
| OpenFilesTracker | 10s | Foreground process + open files |
| SystemStateLogger | 300s | CPU/mem snapshots |
| AutoIngestionScanner | 600s | Auto-index directories |
| FileChangeReconciler | 120s | Detect file changes |
| GitActivityWatcher | 15s | Watch repos for commits |
| TerminalHistoryWatcher | 10s | Track shell commands |
| BrowserActivityWatcher | 10s | Detect browser domains |
| ClipboardBridge | 3s | Shared clipboard across threads |
| GitAutoCommitService | 300s | Auto-commit workspace changes |

## Thread Templates

| Template | Packages |
|----------|----------|
| `ml-python` | PyTorch, Jupyter, NumPy, Pandas, Scikit-learn |
| `coding` | Python, Rust, Go, Node.js, C, git, neovim, tmux |
| `rust-dev` | cargo, rustc, rust-analyzer, clippy |
| `web-dev` | Node.js, TypeScript, VS Code |
| `writing` | Pandoc, Zathura, LaTeX, spellcheck |
| `documents` | LibreOffice, Pandoc, LaTeX, Calibre, PDF tools |
| `research` | Firefox, Obsidian, Zotero, clipboard, notes |
| `audio` | Ardour, Audacity, LMMS, FFmpeg, SoX |
| `image-video` | GIMP, Inkscape, Blender, Kdenlive, OBS |
| `gaming` | Steam, Lutris, Wine, GameMode, MangoHud |

## Desktop Feel Profiles

```
wsctl ask "coding work" --profile win11    # Windows 11: bottom taskbar, acrylic blur
wsctl ask "design work" --profile macos    # macOS: top bar, bottom dock, frosted glass
```

QSS themes (3.5-3.9KB each), labwc compositor configs, auto-applied by Fennix on boot.

## Documentation

- [ARCHITECTURE.md](./ARCHITECTURE.md) — Full system design with diagrams
- [AGENTS.md](./AGENTS.md) — For AI coding assistants
- [CONTRIBUTING.md](./CONTRIBUTING.md) — Development guide
- [docs/workspace-system/](./docs/workspace-system/) — Original phase design documents (historic reference)
- Package READMEs in each `packages/*/`

## Requirements

- **NixOS** with btrfs root filesystem
- **Python** 3.10+
- **Ollama** running locally (at least one chat model + nomic-embed-text)
- **systemd-nspawn** (included with systemd)
- **btrfs-progs** for subvolume management
