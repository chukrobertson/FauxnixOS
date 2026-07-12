# Fennix — FauxnixOS In-Thread Assistant

The AI assistant that runs inside each thread container. Monitors user activity, streams context to Nexus, manages the desktop shell, and auto-installs software.

## Services (11 total)

| Service | Interval | Function |
|---------|----------|----------|
| `ContextStreamService` | 5s | Streams window/file/git/terminal/browser events to Nexus dispatch socket |
| `ClipboardContextWatcher` | 2s | Tracks clipboard history |
| `OpenFilesTracker` | 10s | Foreground process detection + open file enumeration |
| `SystemStateLogger` | 300s | CPU/mem snapshots via psutil |
| `AutoIngestionScanner` | 600s | Auto-indexes files in configured directories |
| `FileChangeReconciler` | 120s | Detects modified files and re-ingests |
| `GitActivityWatcher` | 15s | Watches .git repos for new commits |
| `TerminalHistoryWatcher` | 10s | Tails shell history for new commands |
| `BrowserActivityWatcher` | 10s | Detects browser domains from window titles |
| `ClipboardBridge` | 3s | Shares clipboard across threads via /shared/.clipboard/ |
| `GitAutoCommitService` | 300s | Auto-commits workspace changes every 5 minutes |

## Running

```bash
# Headless (inside thread container)
FENNIX_THREAD_NAME=my-thread python3 -m fennix

# Graphical (with Qt6 desktop shell)
FENNIX_THREAD_NAME=my-thread python3 -m fennix
# → auto-applies QSS theme from manifest profile
```

## Desktop Profiles

Fennix reads the thread's `ws-manifest.json` to determine the profile:

| Profile | QSS Theme | Compositor | Description |
|---------|-----------|------------|-------------|
| `win11` | `win11.qss` (3.5KB) | labwc-win11.xml | Dark acrylic, bottom taskbar |
| `macos` | `macos.qss` (3.9KB) | labwc-macos.xml | Light frosted glass, top bar + dock |
| `headless` | none | none | SSH access only |

## Context Streaming

Fennix streams activity events to Nexus via `/run/nexus/dispatch.sock`:

```json
{"ts":"...","thread":"my-thread","src":"window","data":{"app":"zathura","title":"paper.pdf"}}
{"ts":"...","thread":"my-thread","src":"git","data":{"repo":"/shared/proj","branch":"main","msg":"Add attention","action":"commit"}}
{"ts":"...","thread":"my-thread","src":"terminal","data":{"cmd":"python train.py","cwd":"/shared"}}
```

## Software Installation

```python
from fennix.install import install_template, install_for_workload

# Install all packages for a template
install_template("ml-python")  # → PyTorch, Jupyter, NumPy, Pandas

# Install packages for a specific workload
install_for_workload("documents")  # → Pandoc, LaTeX, LibreOffice
```

## Dependencies

- `fauxnix-tools` — LLM routing, file indexing, vision, DB
- PyQt6 — desktop shell (optional, falls back to headless)
- psutil — system resource monitoring
- pyperclip — clipboard bridge (optional)
- Ollama — LLM queries (via fauxnix-tools)
