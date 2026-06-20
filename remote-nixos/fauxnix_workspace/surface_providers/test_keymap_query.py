"""Query the XKB keymap of an XwaylandPerApp provider."""

import time
from Xlib import display, X
from fauxnix_workspace.surface_providers.xwayland_per_app import XwaylandPerApp


def main():
    p = XwaylandPerApp(argv=["xterm"], width=400, height=300)
    p.start()
    time.sleep(3)

    dpy = display.Display(f":{p._display_num}")
    # Get keycodes -> keysyms mapping.
    keymap = dpy.get_input_focus()
    print("focus:", keymap)
    # Query keymap for keycodes 28,32,30,54,43,38,36,65
    min_kc = dpy.display.info.min_keycode
    max_kc = dpy.display.info.max_keycode
    print(f"keycode range {min_kc}-{max_kc}")
    for kc in [24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 38, 39, 40, 41, 42, 43, 44, 45, 46, 52, 53, 54, 55, 56, 57, 58]:
        syms = dpy.get_keyboard_mapping(kc, 1)
        print(f"kc {kc}: {syms}")

    dpy.close()
    p.stop()


if __name__ == "__main__":
    main()
