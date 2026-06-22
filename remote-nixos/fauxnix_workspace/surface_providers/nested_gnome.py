"""Nested GNOME Desktop display source.

Runs GNOME Shell inside a Cage compositor session with a private Xwayland
server. Frames are captured from the Xwayland root window (same pattern as
XwaylandPerApp). Input is forwarded via XTEST into the private X display.

Architecture:

    Fauxnix canvas (host Wayfire)
         │
         ├── Cage compositor (Wayland, nested)
         │    └── gnome-session
         │         ├── GNOME Shell (Wayland client of Cage)
         │         └── X11 apps ← Xwayland :<N>
         │
         └── NestedGnomeProvider
              ├── Xlib connection to Xwayland :<N>
              ├── get_image() → capture root window → card
              └── xtest.fake_input() → forward input → Xwayland
"""

from __future__ import annotations

import glob
import os
import subprocess
import time
from pathlib import Path

from Xlib import X, display
from Xlib.ext import xtest
from Xlib.protocol import event

from .base import SurfaceProvider, InputEvent


def _find_free_display() -> int:
    for n in range(10, 200):
        if not os.path.exists(f"/tmp/.X11-unix/X{n}") and not glob.glob(f"/tmp/.X{n}-lock"):
            return n
    raise RuntimeError("No free X display")


def _wait_for_x_socket(display_num: int, timeout: float = 15.0) -> bool:
    path = f"/tmp/.X11-unix/X{display_num}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path):
            return True
        time.sleep(0.05)
    return False


class NestedGnomeProvider(SurfaceProvider):
    """Display source for a full nested GNOME desktop session."""

    def __init__(self, width: int = 1280, height: int = 720, xdisplay: str = ""):
        self._width = max(320, width)
        self._height = max(240, height)
        self._requested_display = xdisplay

        self._display_num: int | None = None
        self._process: subprocess.Popen | None = None
        self._dpy: display.Display | None = None
        self._running = False
        self._last_frame: tuple[bytes, int, int] | None = None

    # ── Lifecycle ───────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return

        if self._requested_display:
            parts = self._requested_display.lstrip(":")
            self._display_num = int(parts) if parts.isdigit() else _find_free_display()
        else:
            self._display_num = _find_free_display()

        display_str = f":{self._display_num}"

        # Start Cage + gnome-session with a private Xwayland.
        env = os.environ.copy()
        env.pop("WAYLAND_DISPLAY", None)
        cmd = [
            "cage", "-s", "gnome-session",
            "--", "Xwayland",
            display_str,
            "-geometry", f"{self._width}x{self._height}",
            "-noreset", "-ac",
        ]

        try:
            self._process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            raise RuntimeError("cage not found — install cage compositor")

        # Wait for X socket
        if not _wait_for_x_socket(self._display_num, timeout=15.0):
            self.stop()
            raise RuntimeError(f"Cage Xwayland did not appear on display {display_str}")

        time.sleep(0.3)
        try:
            self._dpy = display.Display(display_str)
            self._load_keymap()
            self._load_resources()
        except Exception as e:
            self.stop()
            raise RuntimeError(f"Failed to connect to {display_str}: {e}")

        self._running = True

    def stop(self) -> None:
        self._running = False
        if self._dpy:
            try:
                self._dpy.close()
            except Exception:
                pass
            self._dpy = None
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                    self._process.wait(timeout=3)
                except Exception:
                    pass
            self._process = None

    def is_running(self) -> bool:
        if self._process is None:
            return False
        if self._process.poll() is not None:
            self._running = False
            return False
        return self._running

    # ── Frame capture via Xlib ──────────────────────────────────────────

    def get_frame(self) -> tuple[bytes, int, int] | None:
        return self._last_frame

    def poll(self) -> None:
        if not self._running:
            return
        frame = self._capture_root()
        if frame is not None:
            self._last_frame = frame

    def _capture_root(self) -> tuple[bytes, int, int] | None:
        if self._dpy is None:
            return None
        try:
            root = self._dpy.screen().root
            geom = root.get_geometry()
            w, h = geom.width, geom.height
            if w <= 0 or h <= 0:
                return None
            raw = root.get_image(0, 0, w, h, X.ZPixmap, 0xFFFFFFFF)
            data = raw.data
            expected = w * h * 4
            if len(data) != expected:
                return None
            rgba = bytearray(expected)
            for i in range(0, expected, 4):
                rgba[i] = data[i + 2]
                rgba[i + 1] = data[i + 1]
                rgba[i + 2] = data[i]
                rgba[i + 3] = data[i + 3]
            return bytes(rgba), w, h
        except Exception:
            return None

    # ── Input forwarding via XTEST ──────────────────────────────────────

    def send_input(self, event: InputEvent) -> None:
        if self._dpy is None:
            return
        try:
            x, y = int(event.x), int(event.y)
            if event.type in ("pointer_move", "button_press", "button_release", "axis"):
                self._dpy.screen().root.warp_pointer(x, y)
            if event.type == "pointer_move":
                xtest.fake_input(self._dpy, X.MotionNotify, 0, x, y)
            elif event.type == "button_press":
                self.focus()
                xtest.fake_input(self._dpy, X.ButtonPress, event.button, x, y)
            elif event.type == "button_release":
                xtest.fake_input(self._dpy, X.ButtonRelease, event.button, x, y)
            elif event.type == "key_press":
                self._send_key(event.key, press=True)
            elif event.type == "key_release":
                self._send_key(event.key, press=False)
            elif event.type == "axis":
                btn = 4 if (event.delta_y or 0) > 0 else 5
                for _ in range(min(abs(int(event.delta_y or 0)) // 15 + 1, 10)):
                    xtest.fake_input(self._dpy, X.ButtonPress, btn, x, y)
                    xtest.fake_input(self._dpy, X.ButtonRelease, btn, x, y)
            self._dpy.sync()
        except Exception:
            pass

    def _send_key(self, keycode: int, press: bool) -> None:
        if keycode is None:
            return
        try:
            win = self._deepest_window()
            root = self._dpy.screen().root
            if win is not None and win != root:
                cls = event.KeyPress if press else event.KeyRelease
                ev = cls(
                    window=win,
                    root=root,
                    child=X.NONE,
                    time=X.CurrentTime,
                    root_x=0, root_y=0,
                    event_x=0, event_y=0,
                    state=0,
                    detail=int(keycode),
                    same_screen=1,
                )
                win.send_event(ev, event_mask=X.KeyPressMask | X.KeyReleaseMask)
            else:
                xtest.fake_input(
                    self._dpy,
                    X.KeyPress if press else X.KeyRelease,
                    int(keycode),
                )
        except Exception:
            pass

    def _deepest_window(self):
        if self._dpy is None:
            return None

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

        try:
            return deepest(self._dpy.screen().root)
        except Exception:
            return None

    # ── Window lifecycle ────────────────────────────────────────────────

    def resize(self, width: int, height: int) -> None:
        self._width = max(320, width)
        self._height = max(240, height)
        if self._dpy:
            try:
                root = self._dpy.screen().root
                root.configure(width=self._width, height=self._height)
                self._dpy.sync()
            except Exception:
                pass

    def focus(self) -> None:
        if self._dpy is None:
            return
        try:
            win = self._deepest_window()
            if win is not None:
                win.set_input_focus(X.RevertToParent, X.CurrentTime)
                self._dpy.sync()
        except Exception:
            pass

    def minimize(self) -> None:
        pass

    def close(self) -> None:
        self.stop()

    # ── X11 helpers ─────────────────────────────────────────────────────

    def _load_keymap(self) -> None:
        if self._display_num is None:
            return
        try:
            subprocess.run(
                ["setxkbmap", "-display", f":{self._display_num}", "us"],
                check=False, timeout=5,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    def _load_resources(self) -> None:
        if self._display_num is None:
            return
        try:
            subprocess.run(
                ["xrdb", "-display", f":{self._display_num}", "-"],
                input=b"*allowSendEvents: true\n",
                check=False, timeout=5,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass
