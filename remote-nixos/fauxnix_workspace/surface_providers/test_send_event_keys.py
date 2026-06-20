"""Test sending synthetic key events directly to xterm window."""

import os
import time
from Xlib import X, display
from Xlib.protocol import event
from fauxnix_workspace.surface_providers.xwayland_per_app import XwaylandPerApp

KEYCODES = {
    "t": 28, "o": 32, "u": 30, "c": 54, "h": 43,
    "a": 38, "space": 65, "slash": 61, "return": 36,
}


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
    win.send_event(release)
    dpy.sync()


def send_text(dpy, win, root, text, delay=0.05):
    for ch in text:
        lookup = ch if ch not in (" ", "/") else ("space" if ch == " " else "slash")
        kc = KEYCODES.get(lookup)
        if kc is None:
            continue
        send_keycode(dpy, win, root, kc)
        time.sleep(delay)


def main():
    marker = "/tmp/fauxnix-sendevent-marker"
    if os.path.exists(marker):
        os.remove(marker)

    p = XwaylandPerApp(argv=["xterm", "-xrm", "*allowSendEvents:true", "-e", "bash", "-i"], width=400, height=300)
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
    time.sleep(0.5)

    p.poll()
    before = p.get_frame()
    send_text(dpy, app_win, root, f"touch {marker}", delay=0.05)
    time.sleep(0.1)
    send_keycode(dpy, app_win, root, KEYCODES["return"])
    time.sleep(1.0)
    p.poll()
    after = p.get_frame()

    def save_ppm(frame, path):
        w, h = frame[1], frame[2]
        with open(path, "wb") as f:
            f.write(b"P6\n%d %d\n255\n" % (w, h))
            for i in range(0, len(frame[0]), 4):
                f.write(bytes([frame[0][i], frame[0][i + 1], frame[0][i + 2]]))

    if before:
        save_ppm(before, "/tmp/fauxnix-sendevent-before.ppm")
        print("saved before frame")
    if after:
        save_ppm(after, "/tmp/fauxnix-sendevent-after.ppm")
        print("saved after frame")
    if before and after:
        print(f"frames identical: {before[0] == after[0]}")

    dpy.close()
    p.stop()

    if os.path.exists(marker):
        print("SUCCESS - send_event keys worked")
    else:
        print("FAILURE - send_event keys did not create marker")


if __name__ == "__main__":
    main()
