"""Test XTEST typing with host compositor focus on provider Xwayland."""

import os
import time
import subprocess
from Xlib import X, display
from Xlib.ext import xtest
from fauxnix_workspace.surface_providers.xwayland_per_app import XwaylandPerApp

KEYCODES = {
    "t": 28, "o": 32, "u": 30, "c": 54, "h": 43,
    "a": 38, "space": 65, "slash": 61, "return": 36,
}


def send_keycode(dpy, kc):
    xtest.fake_input(dpy, X.KeyPress, kc)
    dpy.sync()
    time.sleep(0.02)
    xtest.fake_input(dpy, X.KeyRelease, kc)
    dpy.sync()


def send_text(dpy, text, delay=0.05):
    for ch in text:
        lookup = ch if ch not in (" ", "/") else ("space" if ch == " " else "slash")
        kc = KEYCODES.get(lookup)
        if kc is None:
            continue
        send_keycode(dpy, kc)
        time.sleep(delay)


def main():
    marker = "/tmp/fauxnix-xtest-focused-marker"
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
    time.sleep(0.2)

    # Focus provider Xwayland on host compositor.
    env = os.environ.copy()
    env["WAYLAND_DISPLAY"] = "wayland-1"
    subprocess.run(
        ["wlrctl", "toplevel", "focus", "org.freedesktop.Xwayland"],
        env=env,
        check=False,
    )
    time.sleep(0.5)

    p.poll()
    before = p.get_frame()
    send_text(dpy, f"touch {marker}", delay=0.05)
    time.sleep(0.1)
    send_keycode(dpy, KEYCODES["return"])
    time.sleep(1.0)
    p.poll()
    after = p.get_frame()
    def save_ppm(frame, path):
        data, w, h = frame
        with open(path, "wb") as f:
            f.write(b"P6\n%d %d\n255\n" % (w, h))
            for i in range(0, len(data), 4):
                f.write(bytes([data[i], data[i + 1], data[i + 2]]))

    if after:
        save_ppm(after, "/tmp/fauxnix-xtest-focused.ppm")
        print("saved after frame")
    if before and after:
        print(f"frames identical: {before[0] == after[0]}")

    dpy.close()
    p.stop()

    if os.path.exists(marker):
        print("SUCCESS - XTEST focused marker created")
    else:
        print("FAILURE - XTEST focused marker not created")


if __name__ == "__main__":
    main()
