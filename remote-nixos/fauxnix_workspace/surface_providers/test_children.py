"""List Xwayland provider windows."""

import time
from Xlib import X, display
from fauxnix_workspace.surface_providers.xwayland_per_app import XwaylandPerApp


def main():
    p = XwaylandPerApp(argv=["xterm"], width=400, height=300)
    p.start()
    time.sleep(4)

    dpy = display.Display(f":{p._display_num}")
    root = dpy.screen().root
    print("root children:")
    for c in root.query_tree().children:
        try:
            attrs = c.get_attributes()
            geom = c.get_geometry()
            name = c.get_wm_name() or ""
            cls = c.get_wm_class() or ()
            print(f"  id={c.id} {geom.width}x{geom.height}+{geom.x}+{geom.y} map={attrs.map_state} or={attrs.override_redirect} name={name!r} class={cls}")
        except Exception as e:
            print(f"  id={c.id} error={e}")

    dpy.close()
    p.stop()


if __name__ == "__main__":
    main()
