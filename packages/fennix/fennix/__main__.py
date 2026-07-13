from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

from fennix.db import init_fennix_db


def _install_template_packages() -> None:
    for manifest_path in [
        Path("/var/lib/workspaces") / os.getenv("FENNIX_THREAD_NAME", ""),
        Path("/var/lib/workspaces") / os.uname().nodename,
    ]:
        mf = manifest_path / "ws-manifest.json" if manifest_path.name else None
        if not mf or not mf.exists():
            continue
        try:
            manifest = json.loads(mf.read_text())
            template = manifest.get("nix", {}).get("template")
            if template:
                from fennix.install import install_template
                installed = install_template(template)
                if installed:
                    print(f"[fennix] installed {len(installed)} packages for template '{template}'")
        except Exception:
            pass
        break


def main():
    init_fennix_db()
    _install_template_packages()

    thread_name = os.getenv("FENNIX_THREAD_NAME", "workspace")

    from fennix.resume import show_resume
    show_resume(thread_name)

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
