"""Base interface for display sources.

A display source is anything that can produce a framebuffer for a Fauxnix
Display card and accept input events. Sources may represent:

- a nested-compositor app (LocalAppSource, XwaylandPerApp, CagePerApp)
- a VM framebuffer (LookingGlassVM)
- a remote/desktop stream (Fauxpass, MoonlightClient, SpiceClient)
- a fallback thumbnail/capture of a native window

Historically this interface was named SurfaceProvider. Keep that name as the
compatibility API, but treat it as the source plugged into a Display card.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable


@dataclass
class InputEvent:
    """A normalized input event to forward to the provider."""
    type: str  # "pointer_move", "button_press", "button_release",
               # "key_press", "key_release", "axis"
    x: float = 0.0
    y: float = 0.0
    button: int | None = None
    key: int | None = None  # X11 keysym or similar
    modifiers: int = 0
    delta_x: float = 0.0
    delta_y: float = 0.0


class SurfaceProvider(ABC):
    """Abstract base class for all display sources."""

    @abstractmethod
    def start(self) -> None:
        """Start the provider (launch compositor/app/VM, connect, etc.)."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Stop the provider and clean up all child processes."""
        ...

    @abstractmethod
    def is_running(self) -> bool:
        """Return True if the provider is active and producing frames."""
        ...

    @abstractmethod
    def get_frame(self) -> tuple[bytes, int, int] | None:
        """Return the current framebuffer as (rgba_bytes, width, height).

        Returns None if no frame is available. RGBA byte order, suitable for
        QImage.Format.Format_RGBA8888.
        """
        ...

    def poll(self) -> None:
        """Optional active frame pump for providers that need polling."""
        return None

    @abstractmethod
    def resize(self, width: int, height: int) -> None:
        """Request that the surface be resized."""
        ...

    @abstractmethod
    def send_input(self, event: InputEvent) -> None:
        """Forward an input event to the surface."""
        ...

    @abstractmethod
    def focus(self) -> None:
        """Bring the surface into focus."""
        ...

    @abstractmethod
    def minimize(self) -> None:
        """Minimize or hide the surface."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Close/terminate the surface."""
        ...

    def metadata(self) -> dict:
        """Return stable descriptive metadata for this source."""
        return {}

    def status(self) -> dict:
        """Return current provider health/lifecycle details."""
        return {"running": self.is_running()}

    def set_frame_callback(self, callback: Callable[[], None]) -> None:
        """Optional: provider may call this when a new frame is ready."""
        self._frame_callback = callback


# Compatibility-friendly vocabulary for the monitor/source model.
DisplaySourceProvider = SurfaceProvider
