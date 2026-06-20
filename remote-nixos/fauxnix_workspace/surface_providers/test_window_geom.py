"""Inspect xterm window geometry inside provider display."""

import time
from Xlib import X, display
from fauxnix_workspace.surface_providers.xwayland_per_app import XwaylandPerApp


def main():
    p = XwaylandPerApp(argv=["xterm"], width=400, height=300)
    p.start()
    time.sleep(4)

    dpy = display.Display(f":{p._display_num}")
    root = dpy.screen().root
    print(f"root geometry: {root.get_geometry()}")
    for c in root.query_tree().children:
        attrs = c.get_attributes()
        name = c.get_wm_name()
        geom = c.get_geometry()
        print(f"child id={c.id} or={attrs.override_redirect} map={attrs.map_state} geom={geom} name={name}")

    dpy.close()
    p.stop()


if __name__ == "__main__":
    main()
