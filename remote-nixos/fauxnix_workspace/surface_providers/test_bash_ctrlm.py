"""Test synthetic Ctrl+M in interactive bash."""

import os
import time
from Xlib import X, display
from Xlib.protocol import event
from fauxnix_workspace.surface_providers.xwayland_per_app import XwaylandPerApp


def send_key(dpy, win, root, kc, state=0):
    press = event.KeyPress(
        window=win,
        root=root,
        child=X.NONE,
        time=X.CurrentTime,
        root_x=50,
        root_y=50,
        event_x=50,
        event_y=50,
        state=state,
        detail=kc,
        same_screen=1,
    )
    release = event.KeyRelease(
        window=win,
        root=root,
        child=X.NONE,
        time=X.CurrentTime,
        root_x=50,
        root_y=50,
        event_x=50,
        event_y=50,
        state=state,
        detail=kc,
        same_screen=1,
    )
    win.send_event(press)
    dpy.sync()
    time.sleep(0.05)
    win.send_event(release)
    dpy.sync()


def main():
    marker = "/tmp/fauxnix-ctrlm-marker"
    if os.path.exists(marker):
        os.remove(marker)

    p = XwaylandPerApp(argv=["xterm", "-xrm", "*allowSendEvents:true", "-e", "bash", "-i"], width=400, height=300)
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

    root.warp_pointer(50, 50)
    app_win.set_input_focus(X.RevertToParent, X.CurrentTime)
    dpy.sync()
    time.sleep(0.5)

    # Type "touch marker" then Ctrl+M
    text = f"touch {marker}"
    KEYCODES = {
        "t": 28, "o": 32, "u": 30, "c": 54, "h": 43,
        "a": 38, "space": 65, "m": 50,
    }
    for ch in text:
        lookup = ch if ch != " " else "space"
        kc = KEYCODES.get(lookup)
        if kc is None:
            continue
        send_key(dpy, app_win, root, kc)
        time.sleep(0.05)

    time.sleep(0.1)
    send_key(dpy, app_win, root, KEYCODES["m"], state=X.ControlMask)
    time.sleep(1.0)

    dpy.close()
    p.stop()

    if os.path.exists(marker):
        print("SUCCESS - Ctrl+M executed command")
    else:
        print("FAILURE - marker not created")


if __name__ == "__main__":
    main()
