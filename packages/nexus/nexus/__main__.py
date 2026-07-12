from __future__ import annotations

import atexit
import os
import signal
import sys
import time

from nexus.db import init_db, event_counts
from nexus.engine import ContextAggregator, ThreadSupervisor, PipelineRunner, SnapshotService, ThreadHealthMonitor
from nexus.services import ServicesManager

PID_FILE = "/tmp/nexus.pid"


def _acquire_lock() -> bool:
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE) as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)
            print(f"[nexus] already running (PID {old_pid})", file=sys.stderr)
            return False
        except (OSError, ValueError):
            pass

    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    return True


def _release_lock() -> None:
    try:
        os.unlink(PID_FILE)
    except FileNotFoundError:
        pass


def main() -> None:
    if not _acquire_lock():
        sys.exit(1)

    atexit.register(_release_lock)

    init_db()

    manager = ServicesManager()
    manager.add(ContextAggregator())
    manager.add(ThreadSupervisor())
    manager.add(PipelineRunner())
    manager.add(SnapshotService())
    manager.add(ThreadHealthMonitor())

    manager.start_all()
    print(f"[nexus] listening on /run/nexus/")

    running = True

    def _shutdown(signum: int, frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    last_total = 0
    last_suggestions = 0
    while running:
        time.sleep(10)
        counts = event_counts()
        total = sum(counts.values())
        if total != last_total:
            parts = [f"{n}={c}" for n, c in sorted(counts.items())]
            print(f"[nexus] events: {total} total ({', '.join(parts)})")
            last_total = total

        from nexus.db import get_conn
        conn = get_conn()
        pending = conn.execute(
            "SELECT count(*) as cnt FROM suggestions WHERE status = 'pending'"
        ).fetchone()
        conn.close()
        pc = pending["cnt"] if pending else 0
        if pc != last_suggestions:
            print(f"[nexus] suggestions pending: {pc}")
            last_suggestions = pc

    print("[nexus] shutting down...")
    _release_lock()
    manager.stop_all()
    sys.exit(0)


if __name__ == "__main__":
    main()
