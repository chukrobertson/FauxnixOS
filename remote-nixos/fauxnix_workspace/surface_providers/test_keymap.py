"""Print X11 keymap for an Xwayland provider."""

import time
import subprocess
from Xlib import display
from fauxnix_workspace.surface_providers.xwayland_per_app import XwaylandPerApp


def main():
    p = XwaylandPerApp(argv=["xterm"], width=400, height=300)
    p.start()
    time.sleep(3)

    dpy = display.Display(f":{p._display_num}")
    min_kc = dpy.display.info.min_keycode
    max_kc = dpy.display.info.max_keycode

    # Print keymap before and after explicit setxkbmap.
    for label, do_set in [("before", False), ("after", True)]:
        if do_set:
            subprocess.run(
                ["setxkbmap", "-display", f":{p._display_num}", "us"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(1)
        mapping = dpy.get_keyboard_mapping(min_kc, max_kc - min_kc + 1)
        print(f"=== {label} setxkbmap ===")
        for i, keysyms in enumerate(mapping):
            kc = min_kc + i
            if 30 <= kc <= 70:
                syms = [k for k in keysyms if k != 0]
                chars = []
                for ks in syms:
                    try:
                        ch = dpy.keysym_to_string(ks)
                    except Exception:
                        ch = None
                    if ch is None:
                        try:
                            ch = chr(ks) if 32 <= ks < 127 else None
                        except Exception:
                            ch = None
                    chars.append(ch or f"0x{ks:x}")
                if chars:
                    print(f"kc={kc:3d} syms={chars}")

    dpy.close()
    p.stop()


if __name__ == "__main__":
    main()
