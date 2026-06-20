"""Type a command into xterm and check marker while process is alive."""

import os
import time
from Xlib import X, display
from Xlib.ext import xtest
from fauxnix_workspace.surface_providers.xwayland_per_app import XwaylandPerApp

KEYCODES = {
    "t": 28, "o": 32, "u": 30, "c": 54, "h": 43,
    "a": 38, "space": 65, "slash": 61, "return": 36,
}


def send_keycode(dpy, kc):
    xtest.fake_input(dpy, X.KeyPress, kc)
    xtest.fake_input(dpy, X.KeyRelease, kc)
    dpy.sync()


def send_text(dpy, text, delay=0.05):
    for ch in text:
        kc = KEYCODES.get(ch)
        if kc is None:
            continue
        send_keycode(dpy, kc)
        time.sleep(delay)


def main():
    marker = "/tmp/fauxnix-live-marker"
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

    if app_win is None:
        print("No app window")
        dpy.close()
        p.stop()
        return

    root.warp_pointer(50, 50)
    app_win.set_input_focus(X.RevertToParent, X.CurrentTime)
    dpy.sync()
    time.sleep(0.5)

    send_text(dpy, f"touch {marker}", delay=0.05)
    time.sleep(0.2)
    send_keycode(dpy, KEYCODES["return"])

    for i in range(10):
        time.sleep(0.5)
        exists = os.path.exists(marker)
        print(f"after {0.5*(i+1)}s marker exists: {exists}", flush=True)
        if exists:
            break

    dpy.close()
    p.stop()


if __name__ == "__main__":
    main()
