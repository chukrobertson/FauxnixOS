# AGENTS.md — FauxnixOS Core

This file provides AI coding agents (Claude, Codex, Cursor, etc.) with the context needed to work on this project effectively.

## Project Identity

FauxnixOS is a NixOS-based operating system with containerized **threads of continuity** (workspaces) and two AI assistant layers:

- **fauxnix-tools** — shared Python library (file ops, vision, media, LLM)
- **fennix** — in-thread assistant (context collection, desktop shell, user assistance)
- **nexus** — host-level daemon (thread orchestration, security, ML pipeline) — PLANNED
- **membrie** — session tracker (legacy, being absorbed into fennix/nexus)
- **archivist** — intelligent file manager (legacy, being absorbed into fennix/nexus)
- **wsctl** — thread management CLI (create, fork, merge, snapshot, restore)

## Thread Terminology

| Term | Definition |
|------|-----------|
| **Thread** | A containerized workspace (systemd-nspawn + btrfs subvolume). "Thread of continuity." |
| **Spin** | Fork a new thread from an existing one |
| **Join** | Merge two threads together |
| **Snapshot** | btrfs read-only snapshot of a thread's state |
| **Nexus** | Host-level daemon — manages threads, security, cross-thread ML |
| **Fennix** | In-thread assistant — monitors activity, assists user, desktop shell |

The CLI tool (`wsctl`) uses `fork`/`merge` terminology. Internally, code and docs use `spin`/`join` or `fork`/`merge` interchangeably.

## Repository Layout

```
fauxnix-core/
├── flake.nix                     # Root Nix flake
├── modules/                      # NixOS system modules
│   ├── fauxnix-tools.nix
│   ├── membrie.nix
│   ├── archivist.nix
│   ├── fennix.nix
│   └── nexus.nix                 # (future)
├── packages/
│   ├── fauxnix-tools/            # No deps on membrie/archivist/fennix/nexus
│   │   ├── pyproject.toml
│   │   ├── default.nix
│   │   └── fauxnix_tools/
│   ├── fennix/                   # In-thread assistant (depends on fauxnix-tools)
│   │   ├── pyproject.toml
│   │   ├── default.nix
│   │   └── fennix/
│   ├── nexus/                    # Host daemon (PLANNED — depends on fauxnix-tools)
│   │   └── nexus/
│   ├── membrie/                  # Legacy (being absorbed)
│   ├── archivist/                # Legacy (being absorbed)
│   └── wsctl/                    # Thread management CLI
│       ├── pyproject.toml
│       └── wsctl/
├── containers/                   # Thread NixOS container configs
│   └── minimal.nix
├── docs/
│   └── workspace-system/         # Thread system design
├── ARCHITECTURE.md
├── AGENTS.md
└── README.md
```

## Dependency Rules (CRITICAL)

1. `fauxnix-tools` MUST NOT import from any other package
2. `fennix` depends on `fauxnix-tools` only
3. `nexus` depends on `fauxnix-tools` only (future)
4. `membrie` and `archivist` depend on `fauxnix-tools` only
5. No cross-dependencies between fennix, nexus, membrie, archivist
6. Imports use the package prefix: `from fauxnix_tools.X import Y`

**Before adding any import, verify it doesn't violate these rules.**

## Python Coding Conventions

- `from __future__ import annotations` at top of every file
- Type hints on all function signatures (use `str | None` not `Optional[str]`)
- No docstrings on functions (docstrings are for modules only)
- No comments in code unless mathematically non-obvious
- All filesystem paths use `pathlib.Path`, never `os.path` or strings
- Environment variables use the app prefix: `FAUXNIX_*`, `FENNIX_*`, `NEXUS_*`
- Config goes through `config.py` in each package, never `os.getenv()` inline
- Database access via `get_conn()` from `fauxnix_tools.db`
- Lazy imports for heavy dependencies (PyQt6, OpenCV, fastapi, etc.)

## Path Conventions

| Purpose | Path |
|---|---|
| All data | `$XDG_DATA_HOME/fauxnix/` |
| Cache | `$XDG_CACHE_HOME/fauxnix/` |
| Config | `$XDG_CONFIG_HOME/fauxnix/` |
| SQLite DB | `~/.local/share/fauxnix/data/fauxnix.db` |
| ChromaDB vectors | `~/.local/share/fauxnix/data/chroma/` |
| Thread roots | `/var/lib/workspaces/` |
| Thread shared | `/var/lib/workspaces-shared/` |
| Thread snapshots | `/var/lib/workspaces/.snapshots/` |
| Thread template | `/var/lib/workspaces/.template/` |

## ML Pipeline Conventions

- Fennix (in-thread) collects context → writes to `activity.jsonl`
- Nexus (host) aggregates all thread activity via unix sockets
- Embedding pipeline runs on host (CPU, all-MiniLM-L6-v2 or Ollama nomic-embed-text)
- Results stored in SQLite with `sqlite-vec` for vector similarity search
- Suggestions (fork/merge) originate from Nexus, delivered via libnotify

## Build / Test Commands

```bash
# Syntax check all Python files:
python3 -c "
import py_compile, os
for dp,_,fs in os.walk('packages'):
    for f in fs:
        if f.endswith('.py'):
            py_compile.compile(os.path.join(dp,f), doraise=True)
print('OK')
"

# Build packages:
nix build .#fauxnix-tools
nix build .#fennix
nix build .#membrie
nix build .#archivist

# Test wsctl:
PYTHONPATH=packages/wsctl python3 -m wsctl list

# Build thread container system closure:
nix-build '<nixpkgs/nixos>' -A config.system.build.toplevel \
  -I nixos-config=containers/minimal.nix
```

## Adding New Features

1. **New shared tool** → add to `fauxnix-tools`, update `__init__.py` exports
2. **New Fennix feature** → add to `fennix/`, depends on fauxnix-tools only
3. **New Nexus feature** → add to `nexus/`, depends on fauxnix-tools only
4. **New wsctl command** → add to `wsctl/`, no deps
5. **New DB table** → add to the correct `db.py`, add indexes, update init function
6. **New env var** → add to correct `config.py`, use FAUXNIX_/FENNIX_/NEXUS_ prefix
7. **New NixOS option** → add to correct module in `modules/`
8. **New Python dep** → add to correct `pyproject.toml` AND `default.nix`

## Common Pitfalls

- Don't use `os.path` — use `pathlib.Path` everywhere
- Don't hardcode paths — use the config object
- Don't add circular imports between packages
- Don't assume Windows — no Win32 APIs, no `C:\` paths, no `.exe` suffixes
- Don't assume GPU — InsightFace uses CPU, whisper uses CPU by default
- Lazy-import heavy deps (PyQt6, PyMuPDF, cv2, insightface)
- Thread roots live on btrfs subvolumes — use sudo for all filesystem ops
- The OTG server binds `0.0.0.0` — ensure firewall is configured
