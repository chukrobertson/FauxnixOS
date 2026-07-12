from __future__ import annotations

import os
import signal
import sys
import time

from fennix.db import init_fennix_db


def main():
    init_fennix_db()

    if not os.getenv("DISPLAY") and not os.getenv("WAYLAND_DISPLAY"):
        _run_headless()
        return

    from fennix.ui.tray import run_tray
    run_tray()


def _run_headless():
    from fennix.services import ServicesManager

    manager = ServicesManager()
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
