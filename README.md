# FauxnixOS Core

**AI-powered NixOS with containerized threads of continuity.**

FauxnixOS layers two AI assistants (Nexus on the host, Fennix in each thread) over an immutable NixOS base with btrfs-snapshotted container workspaces.

## Components

| Component | Layer | Purpose |
|---|---|---|
| [fauxnix-tools](./packages/fauxnix-tools/) | Shared | file ops, vision, media, LLM routing |
| [fennix](./packages/fennix/) | In-thread | context collection, desktop shell, user assistance |
| [wsctl](./packages/wsctl/) | Host | thread management CLI (create, fork, merge, snapshot) |
| nexus | Host (planned) | thread orchestration, ML pipeline, security |
| [membrie](./packages/membrie/) | Legacy | session tracker (being absorbed into fennix) |
| [archivist](./packages/archivist/) | Legacy | file manager (being absorbed into fennix) |

## Quick Start

### Thread (Container Workspace)

```bash
# Create and start a thread
wsctl create my-thread --profile headless
wsctl start my-thread

# Fork a thread
wsctl fork my-thread my-thread-dev

# Snapshot and restore
wsctl snapshot my-thread --label pre-experiment
wsctl restore my-thread my-thread-pre-experiment

# List all threads
wsctl list
```

See [Thread System docs](./docs/workspace-system/) for architecture and phases.

### AI Tools

```bash
# Install Ollama and pull models
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
ollama pull qwen2.5:1.5b

# Install fauxnix-tools
cd packages/fauxnix-tools
pip install -e .

# Run Fennix (in-thread assistant)
cd ../fennix
pip install -e .
python -m fennix
```

### Nix Flake

```nix
# flake.nix
{
  inputs.fauxnix-core.url = "path:/path/to/fauxnix-core";
  # ...
}
```

```nix
# configuration.nix
{
  imports = [
    inputs.fauxnix-core.nixosModules.fauxnix-tools
    inputs.fauxnix-core.nixosModules.fennix
  ];

  fauxnix.tools.enable = true;
  fauxnix.fennix.enable = true;
}
```

## Architecture

```
┌──────────────────────────────────────────────────┐
│                FAUXNIX OS                         │
│                                                   │
│  ┌─────────────────────────────────────────────┐ │
│  │              NEXUS (host daemon)             │ │
│  │  thread mgmt  │  ML pipeline  │  security   │ │
│  └──────────────────┬──────────────────────────┘ │
│                     │                             │
│  ┌──────────────────▼──────────────────────────┐ │
│  │         IMMUTABLE NIXOS BASE                │ │
│  │  btrfs  │  nspawn  │  snapper  │  ollama    │ │
│  └──────────────────┬──────────────────────────┘ │
│                     │                             │
│       ┌─────────────┼─────────────┐              │
│  ┌────▼────┐   ┌────▼────┐   ┌────▼────┐        │
│  │ Thread A│   │ Thread B│   │ Thread C│        │
│  │ FENNIX  │   │ FENNIX  │   │ FENNIX  │        │
│  └────┬────┘   └────┬────┘   └────┬────┘        │
│       └──────────────┼──────────────┘             │
│                ┌─────▼─────┐                      │
│                │  /shared  │                      │
│                └───────────┘                      │
└──────────────────────────────────────────────────┘
```

## Environment Variables

See each package's documentation for full details. Key variables:

| Variable | Default | Purpose |
|---|---|---|
| `FAUXNIX_CHAT_MODEL` | `qwen2.5:7b` | Main chat model |
| `FAUXNIX_EMBED_MODEL` | `nomic-embed-text` | Text embeddings |
| `FAUXNIX_VISION_MODEL` | `qwen3-vl:8b` | Vision/image analysis |
| `FAUXNIX_SUMMARY_MODEL` | `qwen2.5:1.5b` | Summaries and quick tasks |
| `FENNIX_INGEST_DIRS` | `~/Documents:~/Projects:~/Downloads` | Fennix watched directories |
| `FENNIX_CLIPBOARD_WATCH` | `true` | Monitor clipboard context |
| `NEXUS_*` | (future) | Host daemon settings |

## Documentation

- [ARCHITECTURE.md](./ARCHITECTURE.md) — Full system design (Nexus, Fennix, threads, ML pipeline)
- [AGENTS.md](./AGENTS.md) — For AI coding assistants
- [Thread System](./docs/workspace-system/) — Thread lifecycle, fork/join, context awareness, desktop feels
- [fauxnix-tools README](./packages/fauxnix-tools/README.md) — Library API reference
- [fennix README](./packages/fennix/README.md) — In-thread assistant guide
- [membrie README](./packages/membrie/README.md) — Legacy session tracker
- [archivist README](./packages/archivist/README.md) — Legacy file manager
- [CONTRIBUTING.md](./CONTRIBUTING.md) — Development guide

## Requirements

- **Python** 3.10+
- **Ollama** running locally (at least one chat model + embedding model)
- **System tools**: tesseract (OCR), ffmpeg (media), xdotool (process awareness)
- **Optional**: PyQt6 (GUI), Nix/NixOS (system integration)
