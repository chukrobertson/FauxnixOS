from __future__ import annotations

import signal
import sys
import time

from nexus.db import init_db, event_counts
from nexus.engine import ContextAggregator, ThreadSupervisor, SuggestionEngine
from nexus.services import ServicesManager


def main() -> None:
    init_db()

    manager = ServicesManager()
    aggregator = ContextAggregator()
    manager.add(aggregator)
    manager.add(ThreadSupervisor())
    manager.add(SuggestionEngine())

    manager.start_all()
    print(f"[nexus] listening on /run/nexus/")

    running = True

    def _shutdown(signum: int, frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    last_total = 0
    while running:
        time.sleep(10)
        counts = event_counts()
        total = sum(counts.values())
        if total != last_total:
            parts = [f"{n}={c}" for n, c in sorted(counts.items())]
            print(f"[nexus] events: {total} total ({', '.join(parts)})")
            last_total = total

    print("[nexus] shutting down...")
    manager.stop_all()
    sys.exit(0)


if __name__ == "__main__":
    main()
