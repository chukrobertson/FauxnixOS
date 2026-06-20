"""Check XTEST extension availability."""

import time
from Xlib import display
from fauxnix_workspace.surface_providers.xwayland_per_app import XwaylandPerApp


def main():
    p = XwaylandPerApp(argv=["xterm"], width=400, height=300)
    p.start()
    time.sleep(3)
    dpy = display.Display(f":{p._display_num}")
    ext = dpy.query_extension("XTEST")
    print(f"XTEST present: {ext is not None}")
    print(f"XTEST info: {ext}")
    dpy.close()
    p.stop()


if __name__ == "__main__":
    main()
