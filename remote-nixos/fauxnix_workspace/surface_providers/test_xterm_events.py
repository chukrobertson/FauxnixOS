"""Inspect xterm event mask and try sending events."""

import os
import time
from Xlib import X, display
from Xlib.ext import xtest
from Xlib.protocol import event as XEvent
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
        print("No app window found")
        dpy.close()
        p.stop()
        return

    attrs = app_win.get_attributes()
    print("event_mask:", hex(attrs.your_event_mask), "all_event_masks:", hex(attrs.all_event_masks))

    # Capture before
    p.poll()
    frame_before = p.get_frame()
    print(f"frame before: {frame_before is not None}")

    # Set focus and warp pointer
    app_win.set_input_focus(X.RevertToParent, X.CurrentTime)
    root.warp_pointer(50, 50)
    dpy.sync()

    # Try XTEST key 'h' (kc 43)
    xtest.fake_input(dpy, X.KeyPress, 43)
    xtest.fake_input(dpy, X.KeyRelease, 43)
    dpy.sync()
    print("XTEST h sent")

    # Try XSendEvent KeyPress for 't' (kc 28)
    press = XEvent.KeyPress(
        time=X.CurrentTime,
        root=root,
        window=app_win,
        same_screen=1,
        child=X.NONE,
        root_x=50, root_y=50, event_x=50, event_y=50,
        state=0,
        detail=28,
    )
    app_win.send_event(press, propagate=True, event_mask=X.KeyPressMask)
    dpy.sync()
    print("XSendEvent t sent")

    # Try XTEST Return (kc 36) to execute if text was typed
    xtest.fake_input(dpy, X.KeyPress, 36)
    xtest.fake_input(dpy, X.KeyRelease, 36)
    dpy.sync()
    print("XTEST Return sent")

    time.sleep(2)

    # Capture after
    p.poll()
    frame_after = p.get_frame()
    print(f"frame after: {frame_after is not None}")
    if frame_before and frame_after:
        print(f"frames identical: {frame_before[0] == frame_after[0]}")

    dpy.close()
    p.stop()


if __name__ == "__main__":
    main()
