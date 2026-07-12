from __future__ import annotations

import json
import os
import socket
import threading
from pathlib import Path

from nexus.services import BaseService
from nexus.db import insert_event, event_counts


SOCKET_DIR = "/run/nexus"
DISPATCH_SOCK = "/run/nexus/dispatch.sock"


class ContextAggregator(BaseService):
    name = "context_aggregator"
    interval_s = 5

    def __init__(self) -> None:
        super().__init__()
        self._server: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._total_events = 0

    def start(self) -> None:
        try:
            os.makedirs(SOCKET_DIR, exist_ok=True)
        except PermissionError:
            pass
        super().start()
        self._start_dispatch()

    def stop(self) -> None:
        super().stop()
        if self._server:
            try:
                self._server.close()
            except OSError:
                pass
        if self._accept_thread:
            self._accept_thread.join(timeout=3)
        try:
            os.unlink(DISPATCH_SOCK)
        except (OSError, FileNotFoundError):
            pass

    def tick(self) -> None:
        counts = event_counts()
        total = sum(counts.values())
        if total != self._total_events:
            self._total_events = total

    def _start_dispatch(self) -> None:
        try:
            os.unlink(DISPATCH_SOCK)
        except FileNotFoundError:
            pass

        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(DISPATCH_SOCK)
        os.chmod(DISPATCH_SOCK, 0o666)
        self._server.settimeout(2)
        self._server.listen(16)

        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()

    def _accept_loop(self) -> None:
        while self._running.is_set():
            try:
                conn, _ = self._server.accept()
                t = threading.Thread(target=self._handle_connection, args=(conn,), daemon=True)
                t.start()
            except socket.timeout:
                continue
            except OSError:
                break

    def _handle_connection(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(3)
            buf = b""
            try:
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
            except socket.timeout:
                pass

            if buf:
                for line in buf.decode().strip().split("\n"):
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        thread_name = event.get("thread", "unknown")
                        src = event.get("src", "unknown")
                        evt_data = event.get("data", {})
                        insert_event(thread_name, src, evt_data)
                    except json.JSONDecodeError:
                        pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def total_events(self) -> int:
        return sum(event_counts().values())


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
