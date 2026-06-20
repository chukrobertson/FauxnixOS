"""Window manager integration for Fauxnix Workspace.

Provides a lightweight interface to discover and control toplevel windows
under Wayfire using wlrctl (foreign-toplevel) and, as a fallback, X11 tools.
"""

import json
import os
import shutil
import subprocess
import re
from pathlib import Path
from dataclasses import dataclass


@dataclass
class ToplevelWindow:
    app_id: str
    title: str
    maximized: bool = False
    minimized: bool = False
    fullscreen: bool = False
    focused: bool = False


class WindowManager:
    """Talk to the compositor to list and control toplevel windows."""

    def __init__(self):
        self._wlrctl = shutil.which("wlrctl")
        self._xprop = shutil.which("xprop")
        self._WAYLAND_DISPLAY = os.environ.get("WAYLAND_DISPLAY", "wayland-1")
        self._DISPLAY = os.environ.get("DISPLAY", ":1")

    # ──────────────────────────────────────────────────────────────────────
    # wlrctl (foreign-toplevel) backend
    # ──────────────────────────────────────────────────────────────────────

    def _run_wlrctl(self, *args: str, timeout: float = 5.0) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["WAYLAND_DISPLAY"] = self._WAYLAND_DISPLAY
        if self._DISPLAY:
            env["DISPLAY"] = self._DISPLAY
        return subprocess.run(
            [self._wlrctl, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )

    def wlrctl_available(self) -> bool:
        return self._wlrctl is not None

    def list_windows(self) -> list[ToplevelWindow]:
        """Return a list of toplevel windows."""
        if self.wlrctl_available():
            return self._list_wlrctl()
        return self._list_x11()

    # Titles/app-ids that should never show up in user-facing window lists
    # because controlling them (minimize/close) can crash the session.
    _BLOCKLIST = {"Fauxnix Workspace"}

    def _list_wlrctl(self) -> list[ToplevelWindow]:
        try:
            result = self._run_wlrctl("toplevel", "list")
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return []

        windows = []
        # wlrctl toplevel list output is one window per line, format:
        #   app_id: "title"
        # Focused window is prefixed with '*'
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            focused = line.startswith("*")
            if focused:
                line = line[1:].strip()
            # Parse app_id: "title"  (title may contain colons/quotes)
            m = re.match(r'^([^"]+?):\s*"(.*)"$', line)
            if not m:
                # Some versions may output differently; try simple split
                if ":" in line:
                    app_id, title = line.split(":", 1)
                    app_id = app_id.strip()
                    title = title.strip().strip('"')
                else:
                    app_id = line
                    title = line
            else:
                app_id = m.group(1).strip()
                title = m.group(2)
            if app_id in self._BLOCKLIST or title in self._BLOCKLIST:
                continue
            windows.append(ToplevelWindow(
                app_id=app_id,
                title=title,
                focused=focused,
            ))
        return windows

    # ──────────────────────────────────────────────────────────────────────
    # X11 fallback for XWayland windows
    # ──────────────────────────────────────────────────────────────────────

    def _list_x11(self) -> list[ToplevelWindow]:
        if not self._xprop:
            return []
        try:
            result = subprocess.run(
                [self._xprop, "-root", "_NET_CLIENT_LIST"],
                capture_output=True,
                text=True,
                timeout=5.0,
                env={**os.environ, "DISPLAY": self._DISPLAY},
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return []

        windows = []
        ids = re.findall(r"0x[0-9a-fA-F]+", result.stdout)
        for wid in ids:
            try:
                props = subprocess.run(
                    [self._xprop, "-id", wid, "WM_CLASS", "_NET_WM_NAME", "WM_NAME"],
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                    env={**os.environ, "DISPLAY": self._DISPLAY},
                )
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                continue

            app_id = ""
            title = ""
            for line in props.stdout.splitlines():
                if line.startswith("WM_CLASS"):
                    parts = re.findall(r'"([^"]*)"', line)
                    if len(parts) >= 2:
                        app_id = parts[1]
                elif line.startswith("_NET_WM_NAME") or line.startswith("WM_NAME"):
                    m = re.search(r'"([^"]*)"', line)
                    if m:
                        title = m.group(1)
            if app_id or title:
                windows.append(ToplevelWindow(app_id=app_id or title, title=title or app_id))
        return windows

    # ──────────────────────────────────────────────────────────────────────
    # Actions
    # ──────────────────────────────────────────────────────────────────────

    def focus(self, title: str) -> bool:
        if self.wlrctl_available():
            try:
                result = self._run_wlrctl("toplevel", "focus", f"title:{title}")
                return result.returncode == 0
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                pass
        return False

    def close(self, title: str) -> bool:
        if self.wlrctl_available():
            try:
                result = self._run_wlrctl("toplevel", "close", f"title:{title}")
                return result.returncode == 0
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                pass
        return False

    def maximize(self, title: str) -> bool:
        if self.wlrctl_available():
            try:
                result = self._run_wlrctl("toplevel", "maximize", f"title:{title}")
                return result.returncode == 0
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                pass
        return False

    def minimize(self, title: str) -> bool:
        if self.wlrctl_available():
            try:
                result = self._run_wlrctl("toplevel", "minimize", f"title:{title}")
                return result.returncode == 0
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                pass
        return False

    def fullscreen(self, title: str) -> bool:
        if self.wlrctl_available():
            try:
                result = self._run_wlrctl("toplevel", "fullscreen", f"title:{title}")
                return result.returncode == 0
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                pass
        return False

    def find_by_app_id(self, app_id: str) -> ToplevelWindow | None:
        """Return the first toplevel matching the given app_id."""
        for win in self.list_windows():
            if win.app_id.lower() == app_id.lower():
                return win
        return None

    def is_desktop_window(self, title: str) -> bool:
        return title in self._BLOCKLIST


# Singleton for the workspace process
_window_manager: WindowManager | None = None


def get_window_manager() -> WindowManager:
    global _window_manager
    if _window_manager is None:
        _window_manager = WindowManager()
    return _window_manager
