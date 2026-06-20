"""Create a simple X11 window and print received events."""

import time
from Xlib import X, display


def main():
    dpy = display.Display(":1")
    root = dpy.screen().root

    win = root.create_window(
        100, 100, 400, 300,
        0,
        dpy.screen().root_depth,
        X.InputOutput,
        X.CopyFromParent,
        background_pixel=dpy.screen().black_pixel,
        event_mask=(X.ExposureMask | X.KeyPressMask | X.KeyReleaseMask |
                    X.ButtonPressMask | X.ButtonReleaseMask | X.PointerMotionMask),
    )
    win.map()
    dpy.sync()

    print("Window created. Send events to it.")
    deadline = time.time() + 10
    while time.time() < deadline:
        while dpy.pending_events() > 0:
            ev = dpy.next_event()
            print("event:", ev.type, ev)
        time.sleep(0.1)

    dpy.close()


if __name__ == "__main__":
    main()
