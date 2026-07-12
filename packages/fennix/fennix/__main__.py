from __future__ import annotations

import os
import signal
import sys
import time

from fennix.db import init_fennix_db


def main():
    init_fennix_db()

    thread_name = os.getenv("FENNIX_THREAD_NAME", "workspace")

    if not os.getenv("DISPLAY") and not os.getenv("WAYLAND_DISPLAY"):
        _run_headless(thread_name)
        return

    from fennix.ui.tray import run_tray
    run_tray(thread_name)


def _run_headless(thread_name: str):
    from fennix.services import ServicesManager

    manager = ServicesManager(thread_name)
    manager.start()

    running = True

    def _shutdown(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while running:
        time.sleep(1)

    manager.stop()
    sys.exit(0)


if __name__ == "__main__":
    main()
