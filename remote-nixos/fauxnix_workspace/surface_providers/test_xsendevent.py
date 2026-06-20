"""Test XSendEvent input forwarding into Xwayland xterm."""

import os
import time

from Xlib import X, display
from Xlib.protocol import event as XEvent
from fauxnix_workspace.surface_providers.xwayland_per_app import XwaylandPerApp


KEYCODES = {
    "t": 28,
    "o": 32,
    "u": 30,
    "c": 54,
    "h": 43,
    "space": 65,
    "slash": 61,
    "return": 36,
}


def send_key(dpy, win, keycode):
    root = dpy.screen().root
    press = XEvent.KeyPress(
        time=X.CurrentTime,
        root=root,
        window=win,
        same_screen=1,
        child=X.NONE,
        root_x=0, root_y=0, event_x=0, event_y=0,
        state=0,
        detail=keycode,
    )
    release = XEvent.KeyRelease(
        time=X.CurrentTime,
        root=root,
        window=win,
        same_screen=1,
        child=X.NONE,
        root_x=0, root_y=0, event_x=0, event_y=0,
        state=0,
        detail=keycode,
    )
    win.send_event(press, propagate=True, event_mask=X.KeyPressMask)
    win.send_event(release, propagate=True, event_mask=X.KeyReleaseMask)
    dpy.sync()


def send_text(dpy, win, text):
    for ch in text:
        kc = KEYCODES.get(ch)
        if kc is not None:
            send_key(dpy, win, kc)


def main():
    marker = "/tmp/fauxnix-xsendevent-ok"
    if os.path.exists(marker):
        os.remove(marker)

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

    print("app_win:", app_win)
    if app_win:
        app_win.set_input_focus(X.RevertToParent, X.CurrentTime)
        dpy.sync()
        print("focus:", dpy.get_input_focus().focus)

        # Click to focus
        click = XEvent.ButtonPress(
            time=X.CurrentTime,
            root=root,
            window=app_win,
            same_screen=1,
            child=X.NONE,
            root_x=50, root_y=50, event_x=50, event_y=50,
            state=0,
            detail=1,
        )
        app_win.send_event(click, propagate=True, event_mask=X.ButtonPressMask)
        dpy.sync()

        send_text(dpy, app_win, "touch /tmp/fauxnix-xsendevent-ok")
        send_key(dpy, app_win, KEYCODES["return"])
        print("sent text")

    dpy.close()
    time.sleep(2)
    p.stop()

    if os.path.exists(marker):
        print("SUCCESS: marker created")
    else:
        print("FAILURE: marker not created")


if __name__ == "__main__":
    main()
