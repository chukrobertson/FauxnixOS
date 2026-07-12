# Phase 3: Per-Workspace Context Collection Agent

## Objective

A lightweight agent inside each workspace that observes user activity and streams context events to the base system. Extends Fennix's existing context monitoring (`fennix.context.*`) for workspace-specific awareness.

## Deliverables

- `fennix-context-agent` — systemd user service per workspace
- Activity event stream (JSONL file + unix socket)
- Collection sources: windows, files, browser, terminal, git, idle
- Privacy controls (per-source toggles, exclusion lists)

## Architecture

```
┌─────────────────────────────────────────────┐
│              Base System                     │
│                                              │
│  ┌──────────────────────────────────────┐   │
│  │  Fennix Context Aggregator           │   │
│  │  Reads from all workspace sockets    │   │
│  │  Feeds Phase 4 embedding pipeline    │   │
│  └──────────┬───────────────┬───────────┘   │
│             │               │               │
└─────────────┼───────────────┼───────────────┘
              │               │
    ┌─────────▼─────┐  ┌──────▼────────┐
    │ Workspace A    │  │ Workspace B   │
    │                │  │               │
    │ ┌────────────┐ │  │ ┌───────────┐ │
    │ │ ctx-agent  │ │  │ │ ctx-agent │ │
    │ │            │ │  │ │           │ │
    │ │ inotify    │ │  │ │ inotify   │ │
    │ │ xdotool    │ │  │ │ xdotool   │ │
    │ │ browser ext│ │  │ │ ...       │ │
    │ └─────┬──────┘ │  │ └─────┬─────┘ │
    │       │        │  │       │       │
    │  activity.jsonl│  │ activity.jsonl│
    │       │        │  │       │       │
    └───────┼────────┘  └───────┼───────┘
            │                   │
            ▼                   ▼
       /workspaces/A/     /workspaces/B/
       var/log/ctx/       var/log/ctx/
```

## Context Collection Sources

### 3.1 Window/App Tracking

```
Source: xdotool / wlrctl / swaymsg
Method: Poll every 2s, emit event on change
Data:
  - Application name (WM_CLASS)
  - Window title
  - Workspace/desktop tag
  - Duration (from previous event's timestamp)

Event format:
{"ts":"...","ws":"ws-ml-paper","src":"window",
 "data":{"app":"zathura","title":"attention_is_all_you_need.pdf","desktop":1},
 "dur":null}

{"ts":"...","ws":"ws-ml-paper","src":"window",
 "data":{"app":"zathura","title":"attention_is_all_you_need.pdf","desktop":1},
 "dur":3600}
```

### 3.2 File Activity

```
Source: inotify on /shared + user home dirs
Method: inotify watcher, batched (every 5s)
Data:
  - File path
  - Action (create, modify, delete, move)
  - File extension
  - Size delta

Event format:
{"ts":"...","ws":"ws-ml-paper","src":"file",
 "data":{"path":"/shared/notes/attention.md","action":"modify","ext":".md"}}
```

### 3.3 Browser Activity

```
Source: Browser extension → local JSONL file
Method: WebExtension writes to ~/.local/share/fennix/browser-activity.jsonl
        Agent tails this file
Data:
  - URL (domain only for privacy, or full URL if enabled)
  - Tab title
  - Tab active/inactive
  - Duration on page

Event format:
{"ts":"...","ws":"ws-ml-paper","src":"browser",
 "data":{"domain":"arxiv.org","title":"Attention Is All You Need","active":true},
 "dur":null}
```

### 3.4 Terminal History

```
Source: Shell preexec hook via HISTFILE
Method: Tail $HISTFILE, diff on each poll
Data:
  - Command
  - Working directory
  - Exit code (if available)

Event format:
{"ts":"...","ws":"ws-ml-paper","src":"terminal",
 "data":{"cmd":"python train.py --epochs 100","cwd":"/shared/projects/transformer","exit":0}}
```

### 3.5 Git Activity

```
Source: inotify on .git directories + periodic git log
Method: Watch .git/HEAD and .git/logs/HEAD for changes
Data:
  - Repo path
  - Branch name
  - Commit message (first line)
  - Action (commit, checkout, merge, rebase)

Event format:
{"ts":"...","ws":"ws-ml-paper","src":"git",
 "data":{"repo":"/shared/projects/transformer","branch":"experiment-1",
         "msg":"Add multi-head attention","action":"commit"}}
```

### 3.6 Idle Detection

```
Source: xprintidle / loginctl
Method: Poll every 30s
Data:
  - Idle seconds
  - Lock state

States: "active" (<300s), "idle" (<900s), "away" (>=900s), "locked"

Event format:
{"ts":"...","ws":"ws-ml-paper","src":"idle",
 "data":{"state":"active","seconds":45}}
```

## Agent Implementation

### 3.7 Inherits from Fennix Service Pattern

Extends `fennix.services.BaseService`:

```python
from fennix.services import BaseService

class ContextAgent(BaseService):
    name = "context-agent"
    sources: dict[str, ContextSource]

    def start(self):
        for src in [WindowSource, FileSource, BrowserSource,
                     TerminalSource, GitSource, IdleSource]:
            if src.enabled_in_config():
                source = src(self.config)
                source.start()
                self.sources[src.name] = source

    def stop(self):
        for src in self.sources.values():
            src.stop()

    def status(self) -> dict:
        return {
            "running": self._running,
            "sources": {name: s.status() for name, s in self.sources.items()},
            "events_logged": self._event_count,
        }
```

### 3.8 Event Output

Two output channels:
1. **JSONL file**: `/var/log/fennix/workspace-activity.jsonl` — persistent, append-only
2. **Unix socket**: `/run/fennix/ws-activity.sock` — real-time stream to base system

The base system's Fennix daemon connects to each workspace's socket and aggregates events.

### 3.9 Configuration

`~/.config/fennix/workspace-context.toml`:

```toml
[context]
enabled = true
event_log_path = "/var/log/fennix/workspace-activity.jsonl"

[sources.window]
enabled = true
poll_interval_s = 2
exclude_apps = []             # Apps to ignore

[sources.file]
enabled = true
watch_paths = ["/shared", "/home/user/Documents"]
exclude_patterns = [".git/", "__pycache__/", "*.pyc"]
batch_interval_s = 5

[sources.browser]
enabled = true
log_full_urls = false         # Domain only for privacy
exclude_domains = []          # Domains to ignore

[sources.terminal]
enabled = true
exclude_commands = ["ls", "cd", "pwd", "clear"]

[sources.git]
enabled = true
watch_repos = []              # Empty = auto-discover from /shared

[sources.idle]
enabled = true
poll_interval_s = 30
```

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Agent location | Inside workspace | Richer context than external observation |
| Browser context | Browser extension → local file | Can't read browser state from outside container |
| Output format | JSONL | Append-friendly, no parsing overhead, good for streaming |
| Communication | Unix socket + JSONL file | Socket for real-time, file for durability/persistence |
| Framework | Extends `fennix.services.BaseService` | Consistent with existing `fennix` architecture |

## Success Criteria

- [ ] Context agent starts as systemd user service inside workspace
- [ ] Window/app titles captured with correct timestamps
- [ ] File modifications detected within 5s of change
- [ ] Browser domains captured (with full-URL toggle)
- [ ] Terminal commands captured (with exclusions)
- [ ] Git branch/commit activity detected
- [ ] Idle state transitions captured
- [ ] Events stream via unix socket readable from base system
- [ ] Per-source disable/enable works at runtime
- [ ] No events logged for excluded paths/domains/commands
