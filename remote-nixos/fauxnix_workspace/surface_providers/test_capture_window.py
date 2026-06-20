"""Capture xterm window directly (not root) and type a command."""

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


def capture(win):
    geom = win.get_geometry()
    raw = win.get_image(0, 0, geom.width, geom.height, X.ZPixmap, 0xFFFFFFFF)
    data = raw.data
    expected = geom.width * geom.height * 4
    if len(data) != expected:
        return None
    rgba = bytearray(len(data))
    for i in range(0, len(data), 4):
        rgba[i] = data[i + 2]
        rgba[i + 1] = data[i + 1]
        rgba[i + 2] = data[i]
        rgba[i + 3] = data[i + 3]
    return bytes(rgba), geom.width, geom.height


def save_ppm(frame, path):
    data, w, h = frame
    with open(path, "wb") as f:
        f.write(b"P6\n%d %d\n255\n" % (w, h))
        for i in range(0, len(data), 4):
            f.write(bytes([data[i], data[i + 1], data[i + 2]]))


def main():
    marker = "/tmp/fauxnix-win-marker"
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

    print(f"app win geom: {app_win.get_geometry()}")
    before = capture(app_win)
    if before:
        save_ppm(before, "/tmp/fauxnix-win-before.ppm")
        print("saved before")

    root.warp_pointer(50, 50)
    app_win.set_input_focus(X.RevertToParent, X.CurrentTime)
    dpy.sync()
    time.sleep(0.5)

    send_text(dpy, f"touch {marker}", delay=0.05)
    time.sleep(0.2)
    send_keycode(dpy, KEYCODES["return"])
    time.sleep(1.0)

    after = capture(app_win)
    if after:
        save_ppm(after, "/tmp/fauxnix-win-after.ppm")
        print("saved after")
    if before and after:
        print(f"frames identical: {before[0] == after[0]}")

    dpy.close()
    p.stop()

    if os.path.exists(marker):
        print("SUCCESS")
    else:
        print("FAILURE")


if __name__ == "__main__":
    main()
