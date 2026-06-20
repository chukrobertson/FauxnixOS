"""Test XTEST to xterm child under rootful Xwayland with host focus."""

import os
import time
import subprocess
from Xlib import X, display
from Xlib.ext import xtest
from fauxnix_workspace.surface_providers.xwayland_per_app import XwaylandPerApp


def deepest(win):
    try:
        attrs = win.get_attributes()
        if attrs.map_state != X.IsViewable or attrs.override_redirect:
            return None
        children = win.query_tree().children
        for child in reversed(children):
            leaf = deepest(child)
            if leaf is not None:
                return leaf
        return win
    except Exception:
        return None


def main():
    marker = "/tmp/fauxnix-xtest-xwayland-child-marker"
    if os.path.exists(marker):
        os.remove(marker)

    p = XwaylandPerApp(argv=["xterm", "-geometry", "80x24", "-ls"], width=800, height=600)
    p.start()
    time.sleep(4)

    dpy = display.Display(f":{p._display_num}")
    root = dpy.screen().root
    app_win = deepest(root)
    print(f"app win: {app_win}")

    if app_win is None:
        print("No app window")
        dpy.close()
        p.stop()
        return

    root.warp_pointer(100, 100)
    app_win.set_input_focus(X.RevertToParent, X.CurrentTime)
    dpy.sync()
    time.sleep(0.2)

    # Focus provider Xwayland on host.
    env = os.environ.copy()
    env["WAYLAND_DISPLAY"] = "wayland-1"
    subprocess.run(["wlrctl", "toplevel", "focus", "org.freedesktop.Xwayland"], env=env, check=False)
    time.sleep(0.5)

    KEYCODES = {
        "t": 28, "o": 32, "u": 30, "c": 54, "h": 43,
        "a": 38, "space": 65, "slash": 61, "return": 36,
    }
    text = f"touch {marker}"
    for ch in text:
        lookup = ch if ch not in (" ", "/") else ("space" if ch == " " else "slash")
        kc = KEYCODES.get(lookup)
        if kc is None:
            continue
        xtest.fake_input(dpy, X.KeyPress, kc)
        dpy.sync()
        time.sleep(0.02)
        xtest.fake_input(dpy, X.KeyRelease, kc)
        dpy.sync()
        time.sleep(0.05)

    time.sleep(0.1)
    xtest.fake_input(dpy, X.KeyPress, KEYCODES["return"])
    dpy.sync()
    time.sleep(0.02)
    xtest.fake_input(dpy, X.KeyRelease, KEYCODES["return"])
    dpy.sync()
    time.sleep(2.0)

    dpy.close()
    p.stop()

    if os.path.exists(marker):
        print("SUCCESS - XTEST Xwayland child marker created")
    else:
        print("FAILURE - XTEST Xwayland child marker not created")


if __name__ == "__main__":
    main()
