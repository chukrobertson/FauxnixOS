"""Create a simple X11 window on a provider display and print received events."""

import time
import subprocess
from Xlib import X, display
from Xlib.ext import xtest
from fauxnix_workspace.surface_providers.xwayland_per_app import XwaylandPerApp


def main():
    p = XwaylandPerApp(argv=["sleep", "10"], width=400, height=300)
    p.start()
    time.sleep(2)

    dpy = display.Display(f":{p._display_num}")
    root = dpy.screen().root

    win = root.create_window(
        0, 0, 400, 300,
        0,
        dpy.screen().root_depth,
        X.InputOutput,
        X.CopyFromParent,
        background_pixel=dpy.screen().white_pixel,
        event_mask=(X.ExposureMask | X.KeyPressMask | X.KeyReleaseMask |
                    X.ButtonPressMask | X.ButtonReleaseMask | X.PointerMotionMask),
    )
    win.set_input_focus(X.RevertToParent, X.CurrentTime)
    win.map()
    dpy.sync()

    print("Window created. Sending XTEST events...")
    xtest.fake_input(dpy, X.MotionNotify, 0, 50, 50)
    xtest.fake_input(dpy, X.ButtonPress, 1, 50, 50)
    xtest.fake_input(dpy, X.ButtonRelease, 1, 50, 50)
    xtest.fake_input(dpy, X.KeyPress, 43, 0, 0)
    xtest.fake_input(dpy, X.KeyRelease, 43, 0, 0)
    dpy.sync()
    print("XTEST events sent.")

    print("Waiting for events...")
    deadline = time.time() + 3
    received = []
    while time.time() < deadline:
        while dpy.pending_events() > 0:
            ev = dpy.next_event()
            received.append(ev.type)
            print("event:", ev.type)
        time.sleep(0.05)

    print(f"Received {len(received)} events")

    dpy.close()
    p.stop()


if __name__ == "__main__":
    main()
