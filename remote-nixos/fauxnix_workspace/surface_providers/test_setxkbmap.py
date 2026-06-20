"""Debug setxkbmap in Xwayland provider."""

import time
import subprocess
from fauxnix_workspace.surface_providers.xwayland_per_app import XwaylandPerApp


def main():
    p = XwaylandPerApp(argv=["xterm"], width=400, height=300)
    p.start()
    time.sleep(2)
    print("display:", p._display_num)

    result = subprocess.run(
        ["setxkbmap", "-display", f":{p._display_num}", "us"],
        capture_output=True,
        text=True,
    )
    print("setxkbmap exit:", result.returncode)
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)

    time.sleep(1)
    result2 = subprocess.run(
        ["setxkbmap", "-display", f":{p._display_num}", "-v", "10", "us"],
        capture_output=True,
        text=True,
    )
    print("setxkbmap verbose exit:", result2.returncode)
    print("stdout:", result2.stdout[:2000])

    p.stop()


if __name__ == "__main__":
    main()
