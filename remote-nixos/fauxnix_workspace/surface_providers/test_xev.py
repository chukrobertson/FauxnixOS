"""Run xev inside an XwaylandPerApp provider and print key events via XTEST."""

import os
import time
from Xlib import X, display
from Xlib.ext import xtest
from fauxnix_workspace.surface_providers.xwayland_per_app import XwaylandPerApp


def main():
    log = "/tmp/fauxnix-xev.log"
    if os.path.exists(log):
        os.remove(log)

    p = XwaylandPerApp(
        argv=["xterm", "-e", "sh", "-c", f"xev > {log}"],
        width=400,
        height=300,
    )
    p.start()
    time.sleep(4)

    dpy = display.Display(f":{p._display_num}")
    root = dpy.screen().root
    app_win = None
    for _ in range(50):
        for c in root.query_tree().children:
            attrs = c.get_attributes()
            if attrs.map_state == X.IsViewable and not attrs.override_redirect:
                app_win = c
                break
        if app_win is not None:
            break
        time.sleep(0.2)

    if app_win is None:
        print("No app window")
        dpy.close()
        p.stop()
        return

    root.warp_pointer(50, 50)
    app_win.set_input_focus(X.RevertToParent, X.CurrentTime)
    dpy.sync()
    time.sleep(0.2)

    # Send 'h' key
    xtest.fake_input(dpy, X.KeyPress, 43)
    xtest.fake_input(dpy, X.KeyRelease, 43)
    dpy.sync()
    print("Sent h keycode")
    time.sleep(1)

    # Send Return
    xtest.fake_input(dpy, X.KeyPress, 36)
    xtest.fake_input(dpy, X.KeyRelease, 36)
    dpy.sync()
    print("Sent Return keycode")
    time.sleep(1)

    dpy.close()
    p.stop()

    print("--- xev log ---")
    if os.path.exists(log):
        with open(log) as f:
            print(f.read()[-2000:])
    else:
        print("no xev log")


if __name__ == "__main__":
    main()
