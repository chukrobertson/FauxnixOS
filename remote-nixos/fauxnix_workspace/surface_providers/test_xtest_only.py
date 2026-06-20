"""Test only XTEST events to xterm."""

import time
from Xlib import X, display
from Xlib.ext import xtest
from fauxnix_workspace.surface_providers.xwayland_per_app import XwaylandPerApp


def main():
    p = XwaylandPerApp(argv=["xterm"], width=400, height=300)
    p.start()
    time.sleep(4)

    dpy = display.Display(f":{p._display_num}")
    root = dpy.screen().root
    app_win = None
    for c in root.query_tree().children:
        attrs = c.get_attributes()
        if attrs.map_state == X.IsViewable and not attrs.override_redirect:
            app_win = c
            break

    if app_win is None:
        print("No app window")
        dpy.close()
        p.stop()
        return

    # Focus and warp
    root.warp_pointer(50, 50)
    app_win.set_input_focus(X.RevertToParent, X.CurrentTime)
    dpy.sync()

    # Capture before
    p.poll()
    before = p.get_frame()

    # Send h and Return via XTEST only
    xtest.fake_input(dpy, X.KeyPress, 43)
    xtest.fake_input(dpy, X.KeyRelease, 43)
    xtest.fake_input(dpy, X.KeyPress, 36)
    xtest.fake_input(dpy, X.KeyRelease, 36)
    dpy.sync()
    print("XTEST h + Return sent")

    time.sleep(2)
    p.poll()
    after = p.get_frame()
    print(f"frames identical: {before[0] == after[0] if before and after else 'N/A'}")

    dpy.close()
    p.stop()


if __name__ == "__main__":
    main()
