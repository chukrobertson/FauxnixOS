"""Surface provider that runs one app inside its own rootful Xwayland instance.

This avoids the fragility of reparenting arbitrary app windows. The app renders
into a private X11 display served by Xwayland; we capture Xwayland's root window
and forward input events directly to that display.
"""

from __future__ import annotations

import os
import glob
import shutil
import time
import subprocess
from typing import Callable

from Xlib import X, display
from Xlib.ext import xtest
from Xlib.protocol import event

from .base import SurfaceProvider, InputEvent


def _find_free_display() -> int:
    """Return a free X display number (>=10) by checking lock files."""
    for n in range(10, 1000):
        if not os.path.exists(f"/tmp/.X11-unix/X{n}") and not glob.glob(f"/tmp/.X{n}-lock"):
            return n
    raise RuntimeError("No free X display")


def _wait_for_x_socket(display_num: int, timeout: float = 10.0) -> bool:
    path = f"/tmp/.X11-unix/X{display_num}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path):
            return True
        time.sleep(0.05)
    return False


class XwaylandPerApp(SurfaceProvider):
    """Run a single app inside a rootful Xwayland and capture its root window."""

    def __init__(self, argv: list[str], env: dict[str, str] | None = None,
                 width: int = 800, height: int = 600,
                 on_frame: Callable[[], None] | None = None,
                 source_kind: str = "xwayland-per-app",
                 source_name: str = ""):
        self._argv = argv
        self._extra_env = env or {}
        self._width = width
        self._height = height
        self._on_frame = on_frame
        self._source_kind = source_kind
        self._source_name = source_name

        self._display_num: int | None = None
        self._xwayland_proc: subprocess.Popen | None = None
        self._app_proc: subprocess.Popen | None = None
        self._last_frame: tuple[bytes, int, int] | None = None
        self._dpy: display.Display | None = None
        self._app_win = None
        self._host_focused = False
        self._host_hidden = False
        self._last_host_focus = 0.0
        self._last_host_hide = 0.0
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self._display_num = _find_free_display()
        display_str = f":{self._display_num}"

        # Start rootful Xwayland. -noreset keeps it alive after the app exits;
        # -ac disables access control so we can XGrab/capture freely.
        self._xwayland_proc = subprocess.Popen(
            [
                "Xwayland",
                "-noreset",
                "-ac",
                "-listen", "tcp",
                "-geometry", f"{self._width}x{self._height}",
                display_str,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        if not _wait_for_x_socket(self._display_num, timeout=10.0):
            self.stop()
            raise RuntimeError("Xwayland did not start")

        # Give Xwayland a moment to finish setup, then resize the root window
        # to the desired provider size so captures match the card body.
        time.sleep(0.2)
        self._dpy = display.Display(f":{self._display_num}")
        self._load_keymap()
        self._load_resources()
        self.resize(self._width, self._height)
        self._hide_host_surface(force=True)

        # Launch the app inside the Xwayland display.
        env = os.environ.copy()
        env["DISPLAY"] = display_str
        # Force the app onto X11. If it sees the host Wayland socket it may try
        # to use it and fail to show up on the provider's X display.
        env.pop("WAYLAND_DISPLAY", None)
        env.update(self._extra_env)
        self._app_proc = subprocess.Popen(
            self._argv,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        self._running = True
        self._hide_host_surface(force=True)

    def stop(self) -> None:
        self._running = False
        if self._app_proc and self._app_proc.poll() is None:
            self._app_proc.terminate()
            try:
                self._app_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._app_proc.kill()
            self._app_proc = None
        if self._xwayland_proc and self._xwayland_proc.poll() is None:
            self._xwayland_proc.terminate()
            try:
                self._xwayland_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._xwayland_proc.kill()
            self._xwayland_proc = None
        if self._dpy is not None:
            try:
                self._dpy.close()
            except Exception:
                pass
            self._dpy = None
        self._app_win = None
        self._display_num = None
        self._host_focused = False
        self._host_hidden = False
        self._last_host_focus = 0.0
        self._last_host_hide = 0.0

    def is_running(self) -> bool:
        return self._running and self._xwayland_proc is not None and self._xwayland_proc.poll() is None

    def poll(self) -> None:
        """Capture a new frame. Must be called on the main thread."""
        if not self._running:
            return
        self._hide_host_surface()
        frame = self._capture_root()
        if frame is not None:
            self._last_frame = frame
            if self._on_frame:
                try:
                    self._on_frame()
                except Exception:
                    pass

    def get_frame(self) -> tuple[bytes, int, int] | None:
        return self._last_frame

    def metadata(self) -> dict:
        return {
            "source_kind": self._source_kind,
            "source_name": self._source_name,
            "provider_kind": "xwayland-per-app",
            "argv": list(self._argv),
        }

    def status(self) -> dict:
        return {
            "running": self.is_running(),
            "display": f":{self._display_num}" if self._display_num is not None else None,
            "width": self._width,
            "height": self._height,
            "host_focused": self._host_focused,
            "host_hidden": self._host_hidden,
        }

    def _load_keymap(self) -> None:
        """Load a default US keymap so key events produce characters."""
        if self._display_num is None:
            return
        try:
            subprocess.run(
                ["setxkbmap", "-display", f":{self._display_num}", "us"],
                check=False,
                timeout=5,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    def _load_resources(self) -> None:
        """Load X resources that make clients accept synthetic input events."""
        if self._display_num is None:
            return
        try:
            subprocess.run(
                ["xrdb", "-display", f":{self._display_num}", "-"],
                input=b"*allowSendEvents: true\n",
                check=False,
                timeout=5,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    def resize(self, width: int, height: int) -> None:
        """Resize the Xwayland root window and record the desired size."""
        self._width = width
        self._height = height
        if self._dpy is None:
            return
        try:
            root = self._dpy.screen().root
            root.configure(width=width, height=height)
            self._dpy.sync()
        except Exception:
            pass

    def _app_window(self):
        """Return the deepest viewable non-override-redirect app window."""
        if self._dpy is None:
            return None
        if self._app_win is not None:
            try:
                attrs = self._app_win.get_attributes()
                if attrs.map_state == X.IsViewable:
                    return self._app_win
            except Exception:
                self._app_win = None

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

        root = self._dpy.screen().root
        try:
            self._app_win = deepest(root)
        except Exception:
            pass
        if self._app_win is not None:
            return self._app_win
        return root

    def send_input(self, event: InputEvent) -> None:
        """Forward an input event into the Xwayland display."""
        if self._dpy is None:
            return
        try:
            x = int(event.x)
            y = int(event.y)
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
                self._send_key_event(event.key, press=True)
            elif event.type == "key_release":
                self._send_key_event(event.key, press=False)
            elif event.type == "axis":
                btn = 4 if event.delta_y > 0 else 5
                xtest.fake_input(self._dpy, X.ButtonPress, btn, x, y)
                xtest.fake_input(self._dpy, X.ButtonRelease, btn, x, y)
            self._dpy.sync()
        except Exception:
            pass

    def _send_key_event(self, keycode: int, press: bool) -> None:
        """Send a synthetic key event directly to the app window.

        XTEST key events are routed through the host Wayland compositor's
        keymap, which drops or remaps keys when the provider Xwayland surface
        does not have focus.  Synthetic events bypass the seat and are accepted
        by clients that enable synthetic-event reception (e.g. xterm with
        ``allowSendEvents:true``).
        """
        if keycode is None:
            return
        if self._host_focused:
            xtest.fake_input(
                self._dpy,
                X.KeyPress if press else X.KeyRelease,
                int(keycode),
            )
            return

        win = self._app_window()
        root = self._dpy.screen().root
        if win is None or win == root:
            return
        cls = event.KeyPress if press else event.KeyRelease
        ev = cls(
            window=win,
            root=root,
            child=X.NONE,
            time=X.CurrentTime,
            root_x=0,
            root_y=0,
            event_x=0,
            event_y=0,
            state=0,
            detail=keycode,
            same_screen=1,
        )
        win.send_event(ev, event_mask=X.KeyPressMask | X.KeyReleaseMask)

    def _host_surface_title(self) -> str | None:
        if self._display_num is None:
            return None
        return f"Xwayland on :{self._display_num}"

    def _run_host_toplevel(self, action: str) -> bool:
        title = self._host_surface_title()
        if title is None:
            return False

        wlrctl = shutil.which("wlrctl")
        if not wlrctl:
            return False

        env = os.environ.copy()
        if os.environ.get("WAYLAND_DISPLAY"):
            env["WAYLAND_DISPLAY"] = os.environ["WAYLAND_DISPLAY"]
        if os.environ.get("DISPLAY"):
            env["DISPLAY"] = os.environ["DISPLAY"]
        cmd = [wlrctl, "toplevel", action, f"title:{title}"]
        try:
            result = subprocess.run(
                cmd,
                env=env,
                check=False,
                timeout=1.0,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _hide_host_surface(self, force: bool = False) -> bool:
        """Keep the provider's rootful Xwayland toplevel out of the desktop."""
        now = time.time()
        if not force and now - self._last_host_hide < 1.0:
            return self._host_hidden
        self._last_host_hide = now

        ok = self._run_host_toplevel("minimize")
        self._host_hidden = ok
        if ok:
            self._host_focused = False
        return ok

    def _focus_host_surface(self) -> bool:
        """Ask Wayfire to focus this rootful Xwayland surface if explicitly needed."""
        now = time.time()
        if now - self._last_host_focus < 0.5:
            return self._host_focused
        self._last_host_focus = now

        commands = ["focus", "activate"]
        for cmd in commands:
            if self._run_host_toplevel(cmd):
                self._host_focused = True
                self._host_hidden = False
                return True

        self._host_focused = False
        return False

    def focus(self) -> None:
        """Set X input focus inside the private provider display."""
        if self._dpy is None:
            return
        try:
            win = self._app_window()
            if win is not None:
                geom = win.get_geometry()
                cx = geom.x + geom.width // 2
                cy = geom.y + geom.height // 2
                self._dpy.screen().root.warp_pointer(cx, cy)
                win.set_input_focus(X.RevertToParent, X.CurrentTime)
                self._dpy.sync()
            self._hide_host_surface()
        except Exception:
            pass

    def minimize(self) -> None:
        """Hide the rootful-Xwayland host window from the compositor."""
        self._hide_host_surface(force=True)

    def close(self) -> None:
        self.stop()

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

            expected_len = w * h * 4
            if len(data) != expected_len:
                return None

            # Convert BGRA → RGBA.
            rgba = bytearray(len(data))
            for i in range(0, len(data), 4):
                rgba[i] = data[i + 2]
                rgba[i + 1] = data[i + 1]
                rgba[i + 2] = data[i]
                rgba[i + 3] = data[i + 3]
            return bytes(rgba), w, h
        except Exception:
            return None
