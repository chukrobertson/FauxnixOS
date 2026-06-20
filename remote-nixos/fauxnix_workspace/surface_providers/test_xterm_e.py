"""Test that xterm -e executes commands in provider display."""

import os
import time
from fauxnix_workspace.surface_providers.xwayland_per_app import XwaylandPerApp


def main():
    marker = "/tmp/xterm_e_marker"
    if os.path.exists(marker):
        os.remove(marker)

    p = XwaylandPerApp(
        argv=["xterm", "-e", "touch", marker],
        width=400,
        height=300,
    )
    p.start()
    time.sleep(4)
    p.stop()

    if os.path.exists(marker):
        print("SUCCESS - xterm -e executed")
    else:
        print("FAILURE - xterm -e did not create marker")


if __name__ == "__main__":
    main()
