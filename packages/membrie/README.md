# Membrie

**AI-powered session tracker and memory companion for FauxnixOS.**

Membrie watches your desktop activity, builds session timelines, generates LLM summaries, detects when you drift from your intentions, and creates searchable workspaces from your research sessions. It also provides a persistent AI companion that remembers past conversations.

## What Membrie Tracks

- **Foreground application** — what app and window title is active, with duration
- **Idle time** — keyboard/mouse inactivity (active / idle / away / locked)
- **Drift detection** — are you working on what you said you would?
- **Focus sessions** — sustained productive periods (10+ min)
- **Clipboard** — text clips (optional)
- **File indexing** — periodic re-indexing of watched directories

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `MEMBRIE_OTG_PORT` | `8920` | Mobile web interface port |
| `MEMBRIE_KIOSK_REFRESH` | `30` | Kiosk dashboard refresh interval (seconds) |

## How It Works

### 1. Process Awareness

Membrie detects the foreground application using a multi-tier fallback:

1. `xdotool getactivewindow getwindowpid getwindowname`
2. Python-Xlib (`_NET_ACTIVE_WINDOW`, `_NET_WM_PID`, `WM_CLASS`)
3. `/proc/*/cmdline` and `/proc/*/comm`

Idle time detection:
1. `xprintidle`
2. X11 ScreenSaver extension

Screen lock detection:
1. `loginctl show-session`
2. `dbus-send org.gnome.ScreenSaver`
3. `qdbus org.kde.screensaver`
4. `qdbus org.freedesktop.ScreenSaver`

### 2. Drift Detection

You set an intention ("Working on the Q4 report"), and Membrie checks if your active window matches:

| State | Meaning |
|---|---|
| `on_track` | Active app matches your intention keywords |
| `drifted` | You're in entertainment/browsing and not matching intention |
| `neutral` | Communication app (meetings aren't drift) |
| `away` | No input for 15+ minutes |
| `locked` | Screen is locked |
| `idle` | No intention set |

### 3. Focus Sessions

When you stay `on_track` in work/utilities apps for 10+ minutes, Membrie enters "focus mode" and tracks your focus streak. Daily focus totals are computed by subtracting entertainment/browsing time from total active time.

### 4. Session Management

Sessions have a lifecycle:

```
start_session() → records start time + intention
  ↓ (background: process_log entries accumulate)
end_session() → computes:
  • Total active time
  • Focus time (on_track periods)
  • Drift count
  • Top apps by duration
  • Auto-generated summary
```

### 5. Workspace Creation

From any session, create a workspace:

```python
from membrie.session.workspace import create_workspace_from_session
create_workspace_from_session(session_id, name="Q4 Research")

# Creates:
# ~/.local/share/fauxnix/data/workspaces/q4_research/
# ├── manifest.json   # Full activity log, top apps, summary
# └── README.md       # Human-readable summary
```

### 6. Memory System

Membrie captures two types of memories:

**Observed** — automatically detected personal statements:
- "I am a software engineer"
- "My family lives in Boston"
- "I prefer dark mode in all my apps"

**Explicit** — when you tell Membrie to remember:
- "Remember that the Q4 deadline is December 15th"
- "Note to self: John prefers email over Slack"

Memories are stored in SQLite and indexed in ChromaDB for semantic search.

## API Reference

```python
from membrie import (
    # Process awareness
    get_foreground_process, get_idle_seconds, get_idle_state,
    get_active_process_context, WindowHook,

    # Drift & focus
    check_drift, set_intention, clear_intention, get_intention,
    get_drift_status, get_focus_state, get_drift_history,

    # Sessions
    start_session, end_session, get_active_session,
    list_sessions, get_session_timeline,

    # Workspaces
    create_workspace_from_session, browse_workspaces,
    export_workspace, search_in_workspaces,

    # Chat
    answer_query, get_conversation, list_conversations,

    # Memory
    create_memory, search_memories, list_memories,

    # Services
    ServicesManager,

    # UI
    run_tray, MembrieTray, MembrieWindow, run_otg_server, create_otg_app,
)
```

### Chat

```python
from membrie.chat import answer_query, get_conversation, list_conversations

# Send a message (creates a conversation if none active):
result = answer_query("What was I working on this morning?")
# → {"conversation_id": "conv-abc123", "user": "...", "reply": "..."}

# The reply includes context:
# - Your system persona
# - Current desktop activity
# - Relevant memories from vector search
# - Recent conversation history (last 20 messages)

# Get conversation history:
conv = get_conversation("conv-abc123")
# → {"id": "...", "title": "...", "messages": [{role, content}, ...]}

# List recent conversations:
convs = list_conversations(limit=10)
```

### Memory

```python
from membrie.chat.memory import create_memory, search_memories, list_memories

# Create a memory:
create_memory("User prefers dark mode", kind="observed", confidence=0.7)

# Search by keyword:
memories = search_memories("dark mode")
# → [{"id": "mem-ab12", "content": "User prefers dark mode", "confidence": 0.7}, ...]

# List all memories:
all_memories = list_memories(limit=50, kind="observed")
```

### Background Services

```python
from membrie.services import ServicesManager

manager = ServicesManager()

# Start all 6 services:
manager.start()

# Check status:
status = manager.status()
# → {"running": 6, "services": ["process_watcher", "clipboard_monitor", ...]}

# Toggle a service:
manager.toggle_service("clipboard_monitor", enabled=False)

# Stop everything:
manager.stop()
```

Services:
| Service | Interval | Purpose |
|---|---|---|
| `process_watcher` | Event-driven | Instant foreground window tracking |
| `clipboard_monitor` | 3s | New clipboard text capture |
| `idle_detector` | 30s | User presence state transitions |
| `drift_detector` | 120s | Intention vs. activity comparison |
| `focus_tracker` | 60s | Focus session state updates |
| `file_index_checker` | 3600s | Re-index oldest watched directory |

## GUI

### Desktop Window

The PyQt6 window has 4 tabs:

- **Activity** — current drift status, intention setter, recent activity timeline, focus stats
- **Chat** — chat with Membrie, conversation history selector
- **Sessions** — past sessions list, detail viewer, "Create Workspace" button
- **Settings** — toggle individual services on/off

### System Tray

The green "M" icon provides:
- **Open Membrie** — show/hide the desktop window
- **Start/Stop OTG Server** — toggle mobile web interface
- **Status** — shows current drift state, category, focus streak
- **Quit** — graceful shutdown of all services

### OTG Mobile Web

Mobile-friendly dark-themed dashboard accessible at `http://<hostname>:8920`:

- **Status badge** — on_track (green), drifted (red), neutral (yellow)
- **Chat** — text box + send button
- **Intention setter** — quick text input
- **Memory search** — search your stored memories
- **Session list** — browse past sessions

## Persona Customization

Membrie reads its personality from `~/.config/fauxnix/persona.md`. Create this file to customize:

```markdown
You are Membrie — a personal research assistant for a PhD student.
You excel at literature review organization and citation tracking.
Respond in a formal academic tone. Always suggest related papers.
```

## Running

```bash
# With GUI (PyQt6):
python -m membrie

# Headless (daemon + OTG only):
python -c "from membrie.db import init_membrie_db; from membrie.services import ServicesManager; init_membrie_db(); ServicesManager().start()"

# OTG server only:
python -m membrie.web.otg_server
```
