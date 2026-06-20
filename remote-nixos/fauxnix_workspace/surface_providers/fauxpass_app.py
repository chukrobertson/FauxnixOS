"""Surface provider bridge for faux-pass app sources.

This provider is a launch/control bridge today. It gives the generic Display
card a stable provider descriptor for faux-pass apps while the true remote
framebuffer/RDP/VM stream providers are built behind the same interface.
"""

from __future__ import annotations

import json
import subprocess
import time
from typing import Any

from .base import InputEvent, SurfaceProvider


class FauxPassAppProvider(SurfaceProvider):
    """Launch a faux-pass app and expose lifecycle/status to a Display card."""

    def __init__(self, app: str, provider_id: str = "", width: int = 800, height: int = 600):
        self._app = app
        self._provider_id = provider_id
        self._width = max(1, int(width))
        self._height = max(1, int(height))
        self._running = False
        self._launch_result: dict[str, Any] = {}
        self._last_error = ""
        self._last_frame: tuple[bytes, int, int] | None = None
        self._last_input: dict[str, Any] = {}
        self._started_at: float | None = None

    def start(self) -> None:
        if self._running:
            return
        cmd = ["faux-pass", "--json", "run", self._app]
        try:
            result = subprocess.run(
                cmd,
                check=False,
                timeout=8,
                capture_output=True,
                text=True,
            )
            payload = json.loads(result.stdout or "{}")
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            payload = {"ok": False, "error": str(exc)}

        self._launch_result = payload
        self._running = bool(payload.get("ok"))
        self._last_error = "" if self._running else str(payload.get("error", "launch failed"))
        self._started_at = time.time()
        self._last_frame = self._make_frame()

    def stop(self) -> None:
        self._running = False
        self._last_frame = self._make_frame()

    def is_running(self) -> bool:
        return self._running

    def poll(self) -> None:
        self._last_frame = self._make_frame()

    def get_frame(self) -> tuple[bytes, int, int] | None:
        if self._last_frame is None:
            self._last_frame = self._make_frame()
        return self._last_frame

    def resize(self, width: int, height: int) -> None:
        self._width = max(1, int(width))
        self._height = max(1, int(height))
        self._last_frame = self._make_frame()

    def send_input(self, event: InputEvent) -> None:
        self._last_input = {
            "type": event.type,
            "x": event.x,
            "y": event.y,
            "button": event.button,
            "key": event.key,
            "delta_x": event.delta_x,
            "delta_y": event.delta_y,
        }

    def focus(self) -> None:
        return None

    def minimize(self) -> None:
        return None

    def close(self) -> None:
        self.stop()

    def metadata(self) -> dict:
        return {
            "source_kind": "fauxpass-app",
            "source_name": self._app,
            "provider_kind": "fauxpass-app",
            "app": self._app,
            "fauxpass_provider": self._provider_id,
            "frame_kind": "launch-status",
        }

    def status(self) -> dict:
        return {
            "running": self._running,
            "app": self._app,
            "fauxpass_provider": self._provider_id,
            "launch_result": self._launch_result,
            "last_error": self._last_error,
            "last_input": self._last_input,
            "started_at": self._started_at,
            "width": self._width,
            "height": self._height,
        }

    def _make_frame(self) -> tuple[bytes, int, int]:
        w = self._width
        h = self._height
        data = bytearray(w * h * 4)
        if self._running:
            base = (18, 70, 56)
            accent = (0, 200, 255)
        elif self._last_error:
            base = (78, 28, 36)
            accent = (255, 120, 80)
        else:
            base = (18, 24, 36)
            accent = (120, 132, 160)

        border = max(2, min(w, h) // 32)
        for y in range(h):
            for x in range(w):
                i = (y * w + x) * 4
                edge = x < border or y < border or x >= w - border or y >= h - border
                stripe = (x + y) % 23 == 0
                r, g, b = accent if edge or stripe else base
                data[i] = r
                data[i + 1] = g
                data[i + 2] = b
                data[i + 3] = 255
        return bytes(data), w, h
