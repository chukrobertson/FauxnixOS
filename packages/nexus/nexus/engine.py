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


class PipelineRunner(BaseService):
    name = "pipeline_runner"
    interval_s = 60

    def tick(self) -> None:
        from nexus.db import thread_names, count_events
        from nexus.pipeline import cluster_threads, detect_drift

        names = thread_names()
        if not names:
            return

        for name in names:
            count = count_events(name)
            if count < 5:
                continue
            drift = detect_drift(name)
            if drift:
                _queue_suggestion("drift", drift["thread_name"], {
                    "similarity": drift["similarity"],
                    "older_topic": drift["older_topic"],
                    "recent_topic": drift["recent_topic"],
                })

        if len(names) >= 2:
            overlaps = cluster_threads(names)
            for o in overlaps[:3]:
                _queue_suggestion("merge", o["thread_a"], {
                    "thread_b": o["thread_b"],
                    "similarity": o["similarity"],
                })


class SnapshotService(BaseService):
    name = "snapshot_service"
    interval_s = 3600

    def tick(self) -> None:
        import subprocess
        try:
            result = subprocess.run(
                ["sudo", "machinectl", "list", "--no-legend"],
                capture_output=True, text=True,
            )
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                name = line.split()[0]
                subprocess.run(
                    ["sudo", "/home/chxk/.local/bin/wsctl", "snapshot",
                     name, "--label", "auto-hourly"],
                    capture_output=True,
                )
        except Exception:
            pass


def _queue_suggestion(suggestion_type: str, thread_name: str, data: dict) -> None:
    from nexus.db import get_conn

    conn = get_conn()

    if suggestion_type == "merge":
        existing = conn.execute(
            """SELECT id FROM suggestions
               WHERE suggestion_type = 'merge'
               AND thread_name = ? AND thread_b_name = ?
               AND status = 'pending'""",
            (thread_name, data.get("thread_b", "")),
        ).fetchone()
        if existing:
            conn.close()
            return

    titles = {
        "drift": f"Topic drift detected in '{thread_name}'",
        "merge": f"Threads '{thread_name}' and '{data.get('thread_b', '?')}' are similar",
    }

    bodies = {
        "drift": f"Recent activity differs from historical pattern (similarity: {data.get('similarity', '?')}). Consider forking a new thread.",
        "merge": f"These threads have {data.get('similarity', '?')} topic similarity. Consider merging.",
    }

    action = {
        "drift": f"wsctl fork {thread_name} {thread_name}-drift",
        "merge": f"wsctl merge {thread_name} {data.get('thread_b', '?')}",
    }

    conn.execute(
        """INSERT INTO suggestions
           (suggestion_type, thread_name, thread_b_name, title, body, action_json, confidence)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            suggestion_type,
            thread_name,
            data.get("thread_b", ""),
            titles.get(suggestion_type, suggestion_type),
            bodies.get(suggestion_type, ""),
            action.get(suggestion_type, ""),
            data.get("similarity", 0.5),
        ),
    )
    conn.commit()
    conn.close()

    _notify(titles.get(suggestion_type, suggestion_type), bodies.get(suggestion_type, ""))


def _notify(title: str, body: str) -> None:
    try:
        import subprocess
        subprocess.run(
            ["notify-send", "-a", "Nexus", "-i", "dialog-information",
             title, body, "--hint=int:transient:1"],
            capture_output=True, timeout=3,
        )
    except Exception:
        pass


class ThreadHealthMonitor(BaseService):
    name = "health_monitor"
    interval_s = 30

    def tick(self) -> None:
        import subprocess
        from nexus.db import update_health, get_health, recent_events, thread_names

        try:
            result = subprocess.run(
                ["sudo", "machinectl", "list", "--no-legend"],
                capture_output=True, text=True,
            )
            active = set()
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    active.add(line.split()[0])
        except Exception:
            active = set()

        known = set(thread_names())
        all_names = active | known

        for name in all_names:
            status = "running" if name in active else "stopped"
            cpu = None
            mem = None

            events = recent_events(name, 5)
            for e in reversed(events):
                if e["source"] == "system":
                    try:
                        import json
                        data = json.loads(e["event_data"])
                        cpu = data.get("cpu")
                        mem = data.get("mem")
                    except Exception:
                        pass

            update_health(name, status, cpu, mem)
