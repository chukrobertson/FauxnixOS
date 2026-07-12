from __future__ import annotations

import signal
import sys
import time

from nexus.db import init_db
from nexus.engine import ContextAggregator, ThreadSupervisor, SuggestionEngine
from nexus.services import ServicesManager


def main() -> None:
    init_db()

    manager = ServicesManager()
    manager.add(ContextAggregator())
    manager.add(ThreadSupervisor())
    manager.add(SuggestionEngine())

    manager.start_all()

    running = True

    def _shutdown(signum: int, frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while running:
        status = manager.status()
        time.sleep(10)

    manager.stop_all()
    sys.exit(0)


if __name__ == "__main__":
    main()
