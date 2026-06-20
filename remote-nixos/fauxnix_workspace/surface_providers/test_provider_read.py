"""Test provider send_input with read line."""

import os
import time
from fauxnix_workspace.surface_providers.xwayland_per_app import XwaylandPerApp
from fauxnix_workspace.surface_providers.base import InputEvent


KEYCODES = {
    "a": 38, "b": 56, "c": 54, "d": 40, "e": 26, "f": 41,
    "g": 42, "h": 43, "i": 31, "j": 44, "k": 45, "l": 46,
    "m": 58, "n": 57, "o": 32, "p": 33, "q": 24, "r": 27,
    "s": 39, "t": 28, "u": 30, "v": 55, "w": 25, "x": 53,
    "y": 29, "z": 52, "space": 65, "return": 36,
}


def send_key(provider, keycode):
    provider.send_input(InputEvent(type="key_press", key=keycode))
    time.sleep(0.05)
    provider.send_input(InputEvent(type="key_release", key=keycode))


def send_text(provider, text):
    for ch in text:
        kc = KEYCODES.get(ch)
        if kc is None:
            continue
        send_key(provider, kc)
        time.sleep(0.05)


def main():
    out = "/tmp/fauxnix-provider-read.txt"
    if os.path.exists(out):
        os.remove(out)

    p = XwaylandPerApp(
        argv=["xterm", "-e", "sh", "-c", f'read line; echo "$line" > {out}'],
        width=400,
        height=300,
    )
    p.start()
    time.sleep(4)
    p.poll()
    print(f"before frame={p.get_frame() is not None}")

    p.focus()
    send_text(p, "a b")
    send_key(p, KEYCODES["return"])

    time.sleep(2)
    p.poll()
    print(f"after frame={p.get_frame() is not None}")
    p.stop()

    if os.path.exists(out):
        with open(out) as f:
            content = f.read().strip()
        print(f"SUCCESS: {repr(content)}")
    else:
        print("FAILURE: no output file")


if __name__ == "__main__":
    main()
