"""Test XTEST read line under Xvfb."""

import os
import time
import glob
import subprocess
from Xlib import X, display
from Xlib.ext import xtest


def find_free_display():
    for n in range(10, 1000):
        if not os.path.exists(f"/tmp/.X11-unix/X{n}") and not glob.glob(f"/tmp/.X{n}-lock"):
            return n
    raise RuntimeError("no free display")


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
    out = "/tmp/fauxnix-xvfb-read.txt"
    if os.path.exists(out):
        os.remove(out)

    disp = find_free_display()
    disp_str = f":{disp}"

    xvfb = subprocess.Popen(["Xvfb", disp_str, "-screen", "0", "400x300x24", "-ac", "-noreset"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    env = os.environ.copy()
    env["DISPLAY"] = disp_str
    env.pop("WAYLAND_DISPLAY", None)
    xterm = subprocess.Popen(["xterm", "-ls", "-e", "sh", "-c", f'read line; printf "%q\\n" "$line" > {out}'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)

    dpy = display.Display(disp_str)
    subprocess.run(["setxkbmap", "-display", disp_str, "us"], check=False, timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    root = dpy.screen().root
    app_win = deepest(root)

    if app_win is None:
        print("No app window")
        dpy.close()
        xvfb.terminate()
        return

    root.warp_pointer(50, 50)
    app_win.set_input_focus(X.RevertToParent, X.CurrentTime)
    dpy.sync()
    time.sleep(0.2)

    KEYCODES = {"a": 38, "b": 56, "c": 54, "space": 65, "return": 36}
    for ch in "a b c":
        lookup = ch if ch != " " else "space"
        kc = KEYCODES[lookup]
        xtest.fake_input(dpy, X.KeyPress, kc)
        dpy.sync()
        time.sleep(0.02)
        xtest.fake_input(dpy, X.KeyRelease, kc)
        dpy.sync()
        time.sleep(0.1)

    time.sleep(0.2)
    xtest.fake_input(dpy, X.KeyPress, KEYCODES["return"])
    dpy.sync()
    time.sleep(0.02)
    xtest.fake_input(dpy, X.KeyRelease, KEYCODES["return"])
    dpy.sync()
    time.sleep(1.0)

    dpy.close()
    xterm.terminate()
    xvfb.terminate()

    if os.path.exists(out):
        print(f"read: {open(out).read().strip()!r}")
    else:
        print("no output")


if __name__ == "__main__":
    main()
