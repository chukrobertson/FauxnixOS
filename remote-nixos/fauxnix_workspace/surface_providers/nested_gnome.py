"""Nested GNOME Desktop display source.

Runs GNOME Shell inside a Cage compositor session on a private X display,
then captures the framebuffer via Xlib (same pattern as XwaylandPerApp).

The provider launches:
    cage -s gnome-session -- Xwayland :<N> -geometry WxH

And captures frames from the Xwayland root window using XGetImage.
Input is forwarded via XTEST into the private X display.

This reuses the same capture-and-input pattern from xwayland_per_app.py
but wraps a full GNOME desktop session instead of a single app.
"""

from __future__ import annotations

import os
import subprocess
import time
import signal
from .base import SurfaceProvider, InputEvent


class NestedGnomeProvider(SurfaceProvider):
    """Display source for a full nested GNOME desktop session."""

    def __init__(self, width: int = 1280, height: int = 720, xdisplay: str = ":2"):
        self._width = width
        self._height = height
        self._xdisplay = xdisplay
        self._process: subprocess.Popen | None = None
        self._running = False
        self._x_display_obj = None

    # ── Lifecycle ───────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        env = os.environ.copy()
        env["DISPLAY"] = self._xdisplay
        env["GDK_BACKEND"] = "x11"
        env["QT_QPA_PLATFORM"] = "xcb"
        cmd = [
            "cage", "-s", "gnome-session",
            "--", "Xwayland", self._xdisplay,
            "-geometry", f"{self._width}x{self._height}",
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
        time.sleep(3)
        self._running = True

    def stop(self) -> None:
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=10)
            except Exception:
                self._process.kill()
            self._process = None
        self._running = False

    def is_running(self) -> bool:
        if self._process is None:
            return False
        if self._process.poll() is not None:
            self._running = False
            return False
        return self._running

    # ── Frame capture (stub) ────────────────────────────────────────────

    def get_frame(self) -> tuple[bytes, int, int] | None:
        return None

    def poll(self) -> None:
        pass

    # ── Input (stub) ────────────────────────────────────────────────────

    def send_input(self, event: InputEvent) -> None:
        pass

    # ── Window lifecycle (pass-through: fullscreen nested session) ───

    def resize(self, width: int, height: int) -> None:
        self._width = max(320, width)
        self._height = max(240, height)

    def focus(self) -> None:
        pass

    def minimize(self) -> None:
        pass

    def close(self) -> None:
        self.stop()
