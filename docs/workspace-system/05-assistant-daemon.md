# Phase 5: Assistant Daemon + Suggestion Engine

## Objective

An intelligent daemon on the base system that consumes context from Phase 4, detects patterns, and proactively suggests workspace operations. Extends Fennix's existing assistant capabilities.

## Deliverables

- `fennix.assistant` module — suggestion engine
- Integration with existing `fennix.services.ServicesManager`
- Local LLM reasoning for workspace operations (via Ollama)
- Suggestion queue with user-facing notification
- Natural language interface for workspace queries

## Architecture

```
┌───────────────────────────────────────────────────────┐
│                  Base System                           │
│                                                        │
│  ┌────────────────────────────────────────────────┐   │
│  │  Fennix ServicesManager                         │   │
│  │                                                 │   │
│  │  ┌───────────┐  ┌───────────┐  ┌────────────┐  │   │
│  │  │ Context   │  │ Embedding │  │ Assistant  │  │   │
│  │  │ Aggregator│  │ Pipeline  │  │ Engine     │  │   │
│  │  │ (Phase 3) │  │ (Phase 4)  │  │ (Phase 5)  │  │   │
│  │  └─────┬─────┘  └─────┬─────┘  └─────┬──────┘  │   │
│  │        │              │              │          │   │
│  │        └──────────────┼──────────────┘          │   │
│  │                       │                         │   │
│  │           ┌───────────▼──────────┐              │   │
│  │           │   Suggestion Queue   │              │   │
│  │           │   (SQLite table)     │              │   │
│  │           └───────────┬──────────┘              │   │
│  │                       │                         │   │
│  │           ┌───────────▼──────────┐              │   │
│  │           │  Notification Layer  │              │   │
│  │           │  (libnotify + UI)    │              │   │
│  │           └──────────────────────┘              │   │
│  └─────────────────────────────────────────────────┘  │
│                                                        │
│  Ollama (local LLM)                                    │
│  - Reasoning: qwen2.5:7b or llama3.2:3b               │
└───────────────────────────────────────────────────────┘
```

## Tasks

### 5.1 Assistant Service

Extends `fennix.services.BaseService`:

```python
from fennix.services import BaseService

class AssistantEngine(BaseService):
    name = "assistant"
    interval_s = 300  # check every 5 minutes

    def start(self):
        self._timer = threading.Timer(self.interval_s, self._tick)
        self._timer.start()

    def _tick(self):
        self._check_drifts()
        self._check_overlaps()
        self._check_idle_patterns()
        self._timer = threading.Timer(self.interval_s, self._tick)
        self._timer.start()

    def stop(self):
        if self._timer:
            self._timer.cancel()
```

### 5.2 Suggestion Triggers

| Trigger | Condition | Action |
|---------|-----------|--------|
| Topic drift | Recent vectors < 0.5 sim to EMA | Determine if forking or switching makes sense |
| Workspace overlap | Two workspaces > 0.75 sim | Suggest merge |
| Frequent switching | User switches workspace > 10x/hour | Suggest combined workspace |
| New project detected | New file tree + git init in /shared | Suggest dedicated workspace |
| Idle anomaly | Workspace unused > 7 days | Suggest archive |
| Template match | Activity matches a known template | Suggest creating from template |

### 5.3 Suggestion Queue

SQLite table (persisted across reboots):

```sql
CREATE TABLE suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT,
    suggestion_type TEXT NOT NULL,  -- fork, merge, create, archive, template
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    action_json TEXT NOT NULL,      -- wsctl command to execute
    confidence REAL NOT NULL,       -- 0.0-1.0
    trigger_data TEXT,              -- JSON: what triggered this
    status TEXT DEFAULT 'pending',  -- pending, accepted, dismissed, executed
    created_at TEXT,
    dismissed_at TEXT,
    executed_at TEXT
);
```

Example suggestion:

```json
{
  "workspace_id": "ws-ml-paper",
  "suggestion_type": "fork",
  "title": "Fork new workspace for Rust development?",
  "body": "Your recent activity in 'ml-paper' has shifted from ML research (transformers) to Rust programming (cargo, rustc). Creating a dedicated Rust workspace would help keep contexts separate.",
  "action_json": "{\"cmd\": \"wsctl fork ml-paper rust-dev --interactive\"}",
  "confidence": 0.78,
  "trigger_data": "{\"trigger\": \"drift\", \"drift_similarity\": 0.42, \"nearest_ws\": null}",
  "status": "pending"
}
```

### 5.4 LLM-Enhanced Reasoning

For complex decisions, query the local LLM (Ollama) to reason about workspace operations:

```python
from fauxnix_tools.llm.embeddings import chat_messages

def reason_about_drift(workspace_id: str, drift: DriftResult) -> DriftDecision:
    context = build_drift_prompt_context(workspace_id, drift)
    response = chat_messages(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ],
        task="summary",
    )
    return parse_llm_decision(response)

SYSTEM_PROMPT = """You are a workspace management assistant for FauxnixOS.
Given a user's workspace activity history and detected topic drift,
recommend whether the user should:
1. FORK: Create a new workspace for the new topic
2. SWITCH: Move to an existing workspace that matches the new topic
3. IGNORE: The drift is temporary and not significant

Respond in JSON: {"action": "fork|switch|ignore", "reasoning": "...", "confidence": 0.X}"""
```

LLM is called infrequently:
- Only for drift events (not every overlap check)
- Results are cached (same workspace + similar drift → reuse cached decision)
- Falls back to heuristic if Ollama is unavailable

### 5.5 Natural Language Interface

`wsctl ask "<natural language query>"`:

```
$ wsctl ask "set up a workspace for training a vision transformer"

Fennix: Analyzing request...
  → Detected intent: CREATE WORKSPACE
  → Recommended packages: pytorch, torchvision, jupyter, matplotlib
  → Recommended template: ml-python
  → Suggested name: vit-training

Execute? [Y/n]: y

Creating workspace 'vit-training' with profile 'win11' using template 'ml-python'...
Workspace started. Connect with: wsctl attach vit-training
```

```
$ wsctl ask "where should I work on the attention paper?"

Fennix: Searching workspaces...
  → ml-paper: 94% match (transformer research, paper writing)
  → vit-training: 62% match (vision models, pytorch)
  → research-notes: 41% match (general research)

Best match: ml-paper
Switch now? [Y/n]:
```

Implementation: Uses `fauxnix_tools.llm.embeddings.chat_messages()` with `task="summary"` (lightweight model) to:
1. Parse the user's intent (create, find, compare, status)
2. Extract keywords for workspace search
3. Find best-matching workspace via vector similarity
4. Generate recommended configuration

### 5.6 Integration with Existing ServicesManager

Fennix's `ServicesManager` (from `fennix.services`) already manages a list of `BaseService` instances. The assistant is added as a new service:

```python
# In fennix/services.py or __main__.py
from fennix.assistant.engine import AssistantEngine

manager = ServicesManager()
manager.add_service(AssistantEngine())
manager.add_service(EmbeddingPipeline())  # Phase 4
manager.add_service(ContextAggregator())   # Phase 3
manager.start()
```

### 5.7 Notifications

When a suggestion is queued, send a desktop notification:

```python
import subprocess

def notify_suggestion(suggestion: dict):
    subprocess.run([
        "notify-send",
        "-a", "Fennix",
        "-i", "fauxnix",
        suggestion["title"],
        suggestion["body"],
        "--action=accept=Accept",
        "--action=dismiss=Dismiss",
        "--hint=int:transient:1",
    ])
```

Notification actions feed back into the suggestion queue (accept → execute `action_json`, dismiss → mark dismissed).

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Reasoning model | qwen2.5:7b (chat) or 1.5b (summary) | Already configured, no new model pull |
| Check interval | 5 minutes | Frequent enough for timely suggestions, not too aggressive on CPU |
| LLM for drift reasoning | Yes, but cached | LLM adds nuance (is this real drift or a one-off?), caching avoids thrashing |
| LLM for overlap reasoning | No, purely heuristic | Cosine similarity > threshold is unambiguous |
| Suggestion persistence | SQLite | Survives reboots, user can review history |
| Max pending suggestions | 5 | Avoid notification fatigue |

## Success Criteria

- [ ] AssistantEngine starts as a Fennix service
- [ ] Drift detection triggers a suggestion within 10 minutes of sustained topic shift
- [ ] Overlap detection triggers merge suggestion when two workspaces converge
- [ ] `wsctl ask` correctly interprets create/find/status intents
- [ ] Suggestions are persisted and survive reboot
- [ ] Desktop notifications fire for new suggestions
- [ ] Accept/dismiss actions work end-to-end
- [ ] LLM fallback to heuristic works when Ollama is unavailable
