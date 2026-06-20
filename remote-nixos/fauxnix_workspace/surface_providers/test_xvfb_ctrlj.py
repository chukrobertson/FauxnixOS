"""Test XTEST Ctrl+J as line terminator in Xvfb xterm."""

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


def main():
    marker = "/tmp/fauxnix-xvfb-ctrlj-marker"
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
    xterm = subprocess.Popen(["xterm", "-ls"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)

    dpy = display.Display(disp_str)
    subprocess.run(["setxkbmap", "-display", disp_str, "us"], check=False, timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        xvfb.terminate()
        return

    root.warp_pointer(50, 50)
    app_win.set_input_focus(X.RevertToParent, X.CurrentTime)
    dpy.sync()
    time.sleep(0.2)

    KEYCODES = {
        "t": 28, "o": 32, "u": 30, "c": 54, "h": 43,
        "a": 38, "space": 65, "slash": 61, "j": 44,
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

    # Ctrl+J (linefeed) instead of Return
    xtest.fake_input(dpy, X.KeyPress, 37)  # Control_L
    dpy.sync()
    time.sleep(0.02)
    xtest.fake_input(dpy, X.KeyPress, KEYCODES["j"])
    dpy.sync()
    time.sleep(0.02)
    xtest.fake_input(dpy, X.KeyRelease, KEYCODES["j"])
    dpy.sync()
    time.sleep(0.02)
    xtest.fake_input(dpy, X.KeyRelease, 37)
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
        print("SUCCESS - Ctrl+J marker created")
    else:
        print("FAILURE - Ctrl+J marker not created")


if __name__ == "__main__":
    main()
