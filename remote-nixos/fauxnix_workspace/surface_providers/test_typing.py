"""Test typing into xterm via XTEST with delays and verify output."""

import os
import time
from Xlib import X, display
from Xlib.ext import xtest
from fauxnix_workspace.surface_providers.xwayland_per_app import XwaylandPerApp

KEYCODES = {
    "t": 28, "o": 32, "u": 30, "c": 54, "h": 43,
    "a": 38, "space": 65, "slash": 61, "return": 36,
    "b": 56, "e": 26, "n": 57, "d": 40, "i": 31, "l": 46,
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
    marker = "/tmp/fauxnix-typed-marker"
    if os.path.exists(marker):
        os.remove(marker)

    p = XwaylandPerApp(argv=["xterm", "-geometry", "80x24"], width=400, height=300)
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
    time.sleep(0.2)

    send_text(dpy, f"touch {marker}", delay=0.05)
    time.sleep(0.2)
    root.warp_pointer(50, 50)
    app_win.set_input_focus(X.RevertToParent, X.CurrentTime)
    dpy.sync()
    send_keycode(dpy, KEYCODES["return"])
    time.sleep(0.2)
    app_win.set_input_focus(X.RevertToParent, X.CurrentTime)
    dpy.sync()
    send_keycode(dpy, 104)  # KP_Enter
    time.sleep(1.0)

    p.poll()
    after = p.get_frame()
    if after:
        w, h = after[1], after[2]
        # Save raw RGBA as PPM for visual inspection.
        ppm = "/tmp/fauxnix-typed.ppm"
        with open(ppm, "wb") as f:
            f.write(b"P6\n%d %d\n255\n" % (w, h))
            for i in range(0, len(after[0]), 4):
                f.write(bytes([after[0][i], after[0][i + 1], after[0][i + 2]]))
        print(f"saved frame to {ppm}")

    dpy.close()
    p.stop()

    if os.path.exists(marker):
        print("SUCCESS - marker created")
    else:
        print("FAILURE - marker not created")


if __name__ == "__main__":
    main()
