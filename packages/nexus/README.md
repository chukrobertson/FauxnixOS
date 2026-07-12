# Nexus — FauxnixOS Host Daemon

The host-level daemon that orchestrates threads, aggregates context, runs the ML pipeline, and generates suggestions.

## Services

| Service | Interval | Function |
|---------|----------|----------|
| `ContextAggregator` | 5s | Dispatch socket at `/run/nexus/dispatch.sock` — receives JSONL events from all Fennix instances |
| `ThreadSupervisor` | 30s | Tracks running threads via `machinectl list` |
| `PipelineRunner` | 60s | Textify events → embed (nomic-embed-text, 768-dim) → cluster threads → detect drift → queue suggestions |
| `SnapshotService` | 3600s | Hourly btrfs snapshots of all running threads via `wsctl snapshot` |
| `ThreadHealthMonitor` | 30s | Tracks uptime, CPU/mem, crash count per thread |

## Running

```bash
# Start the daemon
sudo mkdir -p /run/nexus
PYTHONPATH=/path/to/fauxnix-core/packages/nexus python3 -m nexus

# Or as a systemd service (planned)
systemctl start nexus
```

## Database

SQLite at `~/.local/share/fauxnix/nexus/nexus.db`. Tables:

| Table | Purpose |
|-------|---------|
| `thread_context` | All received events (thread_name, source, event_data, created_at) |
| `thread_vectors` | Embedding vectors (packed 768-dim float arrays) |
| `suggestions` | Pending/accepted/dismissed suggestions (merge, drift, workload) |
| `drift_events` | Historical drift detection records |
| `thread_health` | Per-thread health status, CPU/mem, crash count |

## Dependencies

- `fauxnix-tools` — LLM routing, DB utilities
- Ollama — for embedding model (nomic-embed-text)
- systemd-nspawn — for machinectl thread tracking
