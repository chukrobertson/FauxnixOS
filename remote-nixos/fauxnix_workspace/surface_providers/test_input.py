"""Test input forwarding into an Xwayland surface provider (xterm)."""

import os
import time

from fauxnix_workspace.surface_providers.xwayland_per_app import XwaylandPerApp
from fauxnix_workspace.surface_providers.base import InputEvent


KEYCODES = {
    "t": 28,
    "o": 32,
    "u": 30,
    "c": 54,
    "h": 43,
    "a": 38,
    "space": 65,
    "slash": 61,
    "return": 36,
}


def send_key(provider, keycode):
    print(f"DEBUG send_key: kc={keycode}", flush=True)
    provider.send_input(InputEvent(type="key_press", key=keycode))
    provider.send_input(InputEvent(type="key_release", key=keycode))


def send_text(provider, text):
    for ch in text:
        lookup = ch if ch not in (" ", "/") else ("space" if ch == " " else "slash")
        keycode = KEYCODES.get(lookup)
        if keycode is None:
            continue
        send_key(provider, keycode)
        time.sleep(0.05)


def main():
    marker = "/tmp/a"
    if os.path.exists(marker):
        os.remove(marker)

    provider = XwaylandPerApp(
        argv=["xterm"],
        width=400,
        height=300,
    )
    provider.start()

    time.sleep(4)
    provider.poll()
    frame_before = provider.get_frame()
    print(f"DEBUG: before frame={frame_before is not None}", flush=True)

    print("DEBUG: sending input events", flush=True)
    print(f"DEBUG: provider type {type(provider)} send_input {provider.send_input}", flush=True)
    provider.focus()
    time.sleep(0.2)

    send_text(provider, "touch /tmp/a")
    time.sleep(0.1)
    send_key(provider, KEYCODES["return"])

    print("DEBUG: events sent", flush=True)

    time.sleep(3)
    provider.poll()
    frame_after = provider.get_frame()
    print(f"DEBUG: after frame={frame_after is not None}", flush=True)
    if frame_before and frame_after:
        same = frame_before[0] == frame_after[0]
        print(f"DEBUG: frames identical={same}", flush=True)

    provider.stop()

    if os.path.exists(marker):
        print("DEBUG: SUCCESS - marker file created", flush=True)
    else:
        print("DEBUG: FAILURE - marker file not created", flush=True)


if __name__ == "__main__":
    main()
