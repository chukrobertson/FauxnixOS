from __future__ import annotations

import json
import threading
import time
from pathlib import Path


class BaseService:
    name: str = "base"
    interval_s: float = 60

    def __init__(self) -> None:
        self._running = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running.set()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=5)

    def is_running(self) -> bool:
        return self._running.is_set()

    def tick(self) -> None:
        pass

    def _run(self) -> None:
        while self._running.is_set():
            try:
                self.tick()
            except Exception:
                pass
            self._running.wait(self.interval_s)

    def status(self) -> dict:
        return {"name": self.name, "running": self.is_running()}


class ServicesManager:
    def __init__(self) -> None:
        self._services: list[BaseService] = []

    def add(self, service: BaseService) -> None:
        self._services.append(service)

    def start_all(self) -> None:
        for s in self._services:
            s.start()

    def stop_all(self) -> None:
        for s in self._services:
            s.stop()

    def status(self) -> dict:
        return {
            "running": sum(1 for s in self._services if s.is_running()),
            "total": len(self._services),
            "services": [s.status() for s in self._services],
        }

    def get(self, name: str) -> BaseService | None:
        for s in self._services:
            if s.name == name:
                return s
        return None

    def toggle(self, name: str, enable: bool) -> None:
        s = self.get(name)
        if not s:
            return
        if enable and not s.is_running():
            s.start()
        elif not enable and s.is_running():
            s.stop()
