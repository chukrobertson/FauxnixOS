"""Send Return to an empty xterm prompt and capture frame."""

import time
from Xlib import X, display
from Xlib.ext import xtest
from fauxnix_workspace.surface_providers.xwayland_per_app import XwaylandPerApp


def main():
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
    time.sleep(0.5)

    p.poll()
    before = p.get_frame()

    # Send Return key
    xtest.fake_input(dpy, X.KeyPress, 36)
    xtest.fake_input(dpy, X.KeyRelease, 36)
    dpy.sync()
    print("Sent Return")
    time.sleep(1.0)

    p.poll()
    after = p.get_frame()
    if after:
        w, h = after[1], after[2]
        ppm = "/tmp/fauxnix-return.ppm"
        with open(ppm, "wb") as f:
            f.write(b"P6\n%d %d\n255\n" % (w, h))
            for i in range(0, len(after[0]), 4):
                f.write(bytes([after[0][i], after[0][i + 1], after[0][i + 2]]))
        print(f"saved frame to {ppm}")
    if before and after:
        print(f"frames identical: {before[0] == after[0]}")

    dpy.close()
    p.stop()


if __name__ == "__main__":
    main()
