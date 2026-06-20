"""Test interactive bash inside xterm in provider display."""

import os
import time
from fauxnix_workspace.surface_providers.xwayland_per_app import XwaylandPerApp


def main():
    marker = "/tmp/bash_interactive_marker"
    if os.path.exists(marker):
        os.remove(marker)

    p = XwaylandPerApp(
        argv=["xterm", "-e", "bash", "-i", "-c", f"touch {marker}; sleep 2"],
        width=400,
        height=300,
    )
    p.start()
    time.sleep(4)
    p.stop()

    if os.path.exists(marker):
        print("SUCCESS - interactive bash executed")
    else:
        print("FAILURE - interactive bash did not create marker")


if __name__ == "__main__":
    main()
