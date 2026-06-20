"""Inspect xterm window tree under Xvfb."""

import time
import glob
import os
import subprocess
from Xlib import X, display


def find_free_display():
    for n in range(10, 1000):
        if not os.path.exists(f"/tmp/.X11-unix/X{n}") and not glob.glob(f"/tmp/.X{n}-lock"):
            return n
    raise RuntimeError("no free display")


def dump_tree(win, indent=0):
    try:
        attrs = win.get_attributes()
        geom = win.get_geometry()
        print(" " * indent + f"id={win.id} or={attrs.override_redirect} map={attrs.map_state} geom={geom.width}x{geom.height}+{geom.x}+{geom.y}")
        for c in win.query_tree().children:
            dump_tree(c, indent + 2)
    except Exception as e:
        print(" " * indent + f"error: {e}")


def main():
    disp = find_free_display()
    disp_str = f":{disp}"
    xvfb = subprocess.Popen(["Xvfb", disp_str, "-screen", "0", "400x300x24", "-ac", "-noreset"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    env = os.environ.copy()
    env["DISPLAY"] = disp_str
    env.pop("WAYLAND_DISPLAY", None)
    xterm = subprocess.Popen(["xterm", "-ls"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)

    dpy = display.Display(disp_str)
    root = dpy.screen().root
    print("Window tree:")
    dump_tree(root)
    dpy.close()
    xterm.terminate()
    xvfb.terminate()


if __name__ == "__main__":
    main()
