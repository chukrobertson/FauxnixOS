"""Inspect process tree of XwaylandPerApp provider."""

import os
import time
import subprocess
from fauxnix_workspace.surface_providers.xwayland_per_app import XwaylandPerApp


def main():
    p = XwaylandPerApp(argv=["xterm"], width=400, height=300)
    p.start()
    time.sleep(4)

    app_pid = p._app_proc.pid if p._app_proc else None
    print(f"app pid: {app_pid}")
    if app_pid:
        subprocess.run(["ps", "-ef", "--forest"], check=False)
        print(f"--- /proc/{app_pid}/cmdline ---")
        try:
            with open(f"/proc/{app_pid}/cmdline", "rb") as f:
                print(f.read().replace(b"\x00", b" "))
        except Exception as e:
            print(e)
        print(f"--- /proc/{app_pid}/status ---")
        try:
            with open(f"/proc/{app_pid}/status") as f:
                for line in f:
                    if line.startswith("State:") or line.startswith("PPid:"):
                        print(line.strip())
        except Exception as e:
            print(e)

    input("Press Enter to stop...")
    p.stop()


if __name__ == "__main__":
    main()
