"""Type text + Return into a shell read and check the captured line."""

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
    time.sleep(0.05)
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
    out = "/tmp/fauxnix-read-line.txt"
    if os.path.exists(out):
        os.remove(out)

    p = XwaylandPerApp(
        argv=["xterm", "-e", "sh", "-c", f'read line; echo "$line" > {out}'],
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

    # Focus the provider Xwayland window on the host compositor so it has a seat.
    subprocess.run(
        ["wlrctl", "toplevel", "activate", "title", f"Xwayland on :{p._display_num}"],
        check=False,
    )
    time.sleep(0.5)

    send_text(dpy, "abc", delay=0.5)
    time.sleep(0.2)
    send_keycode(dpy, KEYCODES["return"])
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
