from __future__ import annotations

import json
import os
import socket
import threading
from pathlib import Path

from nexus.services import BaseService


SOCKET_DIR = "/run/nexus"


class ContextAggregator(BaseService):
    name = "context_aggregator"
    interval_s = 5

    def __init__(self) -> None:
        super().__init__()
        self._listener: threading.Thread | None = None
        self._events: list[dict] = []
        self._lock = threading.Lock()

    def start(self) -> None:
        try:
            os.makedirs(SOCKET_DIR, exist_ok=True)
        except PermissionError:
            pass
        self._listener = threading.Thread(target=self._listen, daemon=True)
        self._listener.start()
        super().start()

    def stop(self) -> None:
        super().stop()
        if self._listener:
            self._listener.join(timeout=5)

    def _listen(self) -> None:
        pass

    def tick(self) -> None:
        with self._lock:
            self._events.clear()

    def recent_events(self, n: int = 100) -> list[dict]:
        with self._lock:
            return list(self._events[-n:])

    def events_for_thread(self, thread_id: str, n: int = 50) -> list[dict]:
        with self._lock:
            return [e for e in self._events if e.get("thread") == thread_id][-n:]


class ThreadSupervisor(BaseService):
    name = "thread_supervisor"
    interval_s = 30

    def __init__(self) -> None:
        super().__init__()
        self._threads: dict[str, dict] = {}

    def tick(self) -> None:
        self._refresh_thread_list()

    def _refresh_thread_list(self) -> None:
        import subprocess
        try:
            result = subprocess.run(
                ["sudo", "machinectl", "list", "--no-legend"],
                capture_output=True, text=True,
            )
            active = set()
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    parts = line.split()
                    if parts:
                        active.add(parts[0])
            for name in list(self._threads):
                self._threads[name]["running"] = name in active
        except Exception:
            pass

    def register_thread(self, name: str, info: dict) -> None:
        self._threads[name] = info

    def list_threads(self) -> dict[str, dict]:
        return dict(self._threads)


class SuggestionEngine(BaseService):
    name = "suggestion_engine"
    interval_s = 300

    def tick(self) -> None:
        pass

    def suggest_workload(self, description: str) -> dict | None:
        return None

    def check_drift(self) -> list[dict]:
        return []

    def check_overlap(self) -> list[dict]:
        return []
