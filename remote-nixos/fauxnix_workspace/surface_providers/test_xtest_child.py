"""Test XTEST input targeting xterm's deepest child window."""

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
    marker = "/tmp/fauxnix-xtest-child-marker"
    if os.path.exists(marker):
        os.remove(marker)

    disp = find_free_display()
    disp_str = f":{disp}"

    xvfb = subprocess.Popen(
        ["Xvfb", disp_str, "-screen", "0", "400x300x24", "-ac", "-noreset"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)

    env = os.environ.copy()
    env["DISPLAY"] = disp_str
    env.pop("WAYLAND_DISPLAY", None)
    xterm = subprocess.Popen(["xterm", "-geometry", "80x24", "-e", "bash", "-c", "stty icrnl; exec bash -i"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)

    dpy = display.Display(disp_str)
    subprocess.run(["setxkbmap", "-display", disp_str, "us"], check=False, timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    root = dpy.screen().root
    app_win = deepest(root)
    print(f"app win: {app_win}")

    if app_win is None:
        print("No app window")
        dpy.close()
        xvfb.terminate()
        return

    root.warp_pointer(50, 50)
    app_win.set_input_focus(X.RevertToParent, X.CurrentTime)
    dpy.sync()
    time.sleep(0.2)

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
    time.sleep(1.0)

    dpy.close()
    xterm.terminate()
    xvfb.terminate()
    try:
        xterm.wait(timeout=2)
    except subprocess.TimeoutExpired:
        xterm.kill()
    try:
        xvfb.wait(timeout=2)
    except subprocess.TimeoutExpired:
        xvfb.kill()

    if os.path.exists(marker):
        print("SUCCESS - XTEST child marker created")
    else:
        print("FAILURE - XTEST child marker not created")


if __name__ == "__main__":
    main()
