# FauxnixOS Core

**AI-powered desktop companion tools for NixOS.**

Three integrated applications that work together to bring true AI assistance to the Linux desktop:

| Component | Purpose | Requires |
|---|---|---|
| [fauxnix-tools](./packages/fauxnix-tools/) | Shared library — file ops, vision, media, LLM | Python 3.10+, Ollama |
| [membrie](./packages/membrie/) | Session tracker & memory companion | fauxnix-tools |
| [archivist](./packages/archivist/) | Intelligent file manager | fauxnix-tools |

## Quick Start

```bash
# 1. Install Ollama and pull models
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
ollama pull qwen2.5:1.5b

# 2. Install system dependencies (on NixOS)
# Add to configuration.nix:
#   environment.systemPackages = [ pkgs.tesseract pkgs.ffmpeg pkgs.xdotool ];

# 3. Install fauxnix-tools
cd packages/fauxnix-tools
pip install -e .

# 4. Extract text from any file
python -c "from fauxnix_tools.files import extract_text; print(extract_text('document.pdf'))"

# 5. Run Membrie
cd ../membrie
pip install -e .
python -m membrie

# 6. Run Archivist
cd ../archivist
pip install -e .
python -m archivist
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
  imports = [ inputs.fauxnix-core.nixosModules.fauxnix-tools
              inputs.fauxnix-core.nixosModules.membrie
              inputs.fauxnix-core.nixosModules.archivist ];

  fauxnix.tools.enable = true;
  fauxnix.membrie.enable = true;
  fauxnix.archivist.enable = true;
}
```

## Architecture

```
┌──────────────────────────────────────────────────┐
│                    FAUXNIX OS                     │
│                                                   │
│   ┌──────────┐           ┌──────────────────┐    │
│   │ MEMBRIE   │           │    ARCHIVIST      │    │
│   │ watcher   │           │    organizer      │    │
│   └─────┬─────┘           └────────┬─────────┘    │
│         │                          │              │
│         └──────────┬───────────────┘              │
│                    │                              │
│         ┌──────────▼──────────┐                   │
│         │   FAUXNIX-TOOLS     │                   │
│         │   shared library    │                   │
│         └──────────┬──────────┘                   │
│                    │                              │
│    ┌───────────────┼───────────────┐              │
│    │               │               │              │
│  Ollama      SQLite/Chroma     ffmpeg/tess        │
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
| `MEMBRIE_OTG_PORT` | `8920` | Mobile web interface port |

## Documentation

- [ARCHITECTURE.md](./ARCHITECTURE.md) — Full system design
- [AGENTS.md](./AGENTS.md) — For AI coding assistants
- [fake-tools README](./packages/fauxnix-tools/README.md) — Library API reference
- [membrie README](./packages/membrie/README.md) — Membrie user guide
- [archivist README](./packages/archivist/README.md) — Archivist user guide
- [CONTRIBUTING.md](./CONTRIBUTING.md) — Development guide
- [Workspace System](./docs/workspace-system/) — Container workspaces with fork/merge, context awareness, and desktop feels

## Requirements

- **Python** 3.10+
- **Ollama** running locally (at least one chat model + embedding model)
- **System tools**: tesseract (OCR), ffmpeg (media), xdotool (process awareness)
- **Optional**: PyQt6 (GUI), Nix/NixOS (system integration)
