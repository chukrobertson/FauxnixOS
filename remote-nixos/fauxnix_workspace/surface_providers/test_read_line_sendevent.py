"""Send synthetic key events to xterm and read line."""

import os
import time
from Xlib import X, display
from Xlib.protocol import event
from fauxnix_workspace.surface_providers.xwayland_per_app import XwaylandPerApp

KEYCODES = {"a": 38, "b": 56, "c": 54, "space": 65, "return": 36}


def send_keycode(dpy, win, root, kc):
    press = event.KeyPress(
        window=win,
        root=root,
        child=X.NONE,
        time=X.CurrentTime,
        root_x=50,
        root_y=50,
        event_x=50,
        event_y=50,
        state=0,
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
        state=0,
        detail=kc,
        same_screen=1,
    )
    win.send_event(press)
    dpy.sync()
    time.sleep(0.05)
    win.send_event(release)
    dpy.sync()


def send_text(dpy, win, root, text, delay=0.2):
    for ch in text:
        kc = KEYCODES.get(ch if ch != " " else "space")
        send_keycode(dpy, win, root, kc)
        time.sleep(delay)


def main():
    out = "/tmp/fauxnix-read-line-se.txt"
    if os.path.exists(out):
        os.remove(out)

    p = XwaylandPerApp(
        argv=["xterm", "-xrm", "*allowSendEvents:true", "-e", "sh", "-c", f'read line; echo "$line" > {out}'],
        width=400,
        height=300,
    )
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

    send_text(dpy, app_win, root, "a b", delay=0.2)
    time.sleep(0.2)
    send_keycode(dpy, app_win, root, KEYCODES["return"])
    time.sleep(2.0)

    dpy.close()
    p.stop()

    if os.path.exists(out):
        with open(out) as f:
            content = f.read().strip()
        print(f"SUCCESS - read line: {repr(content)}")
    else:
        print("FAILURE - no output file")


if __name__ == "__main__":
    main()
