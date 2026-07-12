from __future__ import annotations

import time
import threading

from fauxnix_tools.db import get_conn as _get_fauxnix_conn
from membrie.awareness.process import (
    get_foreground_process, get_idle_seconds, get_idle_state,
    log_process_activity, WindowHook,
)


class BaseService:
    name = "base"
    interval = 60

    def __init__(self):
        self._thread = None
        self._stop = threading.Event()

    def start(self):
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.wait(self.interval):
            try:
                self.tick()
            except Exception:
                pass

    def tick(self):
        pass


class ProcessWatcher(BaseService):
    name = "process_watcher"
    interval = 60

    def __init__(self):
        super().__init__()
        self._hook = WindowHook()

    def start(self):
        self._hook.start()
        super().start()

    def stop(self):
        self._hook.stop()
        super().stop()

    def tick(self):
        self._hook.update_current_duration()


class ClipboardMonitor(BaseService):
    name = "clipboard_monitor"
    interval = 3

    def __init__(self):
        super().__init__()
        self._last = ""

    def tick(self):
        try:
            import pyperclip
            current = pyperclip.paste()
            if current and current != self._last and len(current.strip()) > 10:
                self._last = current
                conn = _get_fauxnix_conn()
                cur = conn.cursor()
                ts = time.time()
                cur.execute(
                    "INSERT INTO clipboard_items (kind, content, source, created_ts) VALUES (?, ?, ?, ?)",
                    ("text", current[:2000], "clipboard_monitor", ts),
                )
                conn.commit()
                conn.close()
        except Exception:
            pass


class IdleDetector(BaseService):
    name = "idle_detector"
    interval = 30

    def __init__(self):
        super().__init__()
        self._last_state = "active"

    def tick(self):
        state = get_idle_state()
        if state == self._last_state:
            return
        conn = _get_fauxnix_conn()
        cur = conn.cursor()
        now = time.time()
        cur.execute(
            "INSERT INTO process_log (process_name, window_title, duration_seconds, start_ts, end_ts) VALUES (?, ?, ?, ?, ?)",
            (f"__{state}__", f"User {state}", self.interval, now - self.interval, now),
        )
        conn.commit()
        conn.close()
        self._last_state = state


class DriftDetector(BaseService):
    name = "drift_detector"
    interval = 120

    def tick(self):
        from membrie.awareness.drift import check_drift, update_focus
        check_drift()
        update_focus()


class FocusSessionTracker(BaseService):
    name = "focus_tracker"
    interval = 60

    def tick(self):
        from membrie.awareness.drift import update_focus, get_focus_state
        update_focus()


class FileIndexChecker(BaseService):
    name = "file_index_checker"
    interval = 3600

    def tick(self):
        from fauxnix_tools.files.indexing import index_directory
        conn = _get_fauxnix_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM indexed_dirs")
        row = cur.fetchone()
        conn.close()
        if row and row["c"] > 0:
            conn = _get_fauxnix_conn()
            cur = conn.cursor()
            cur.execute("SELECT path, label FROM indexed_dirs ORDER BY last_indexed_ts ASC LIMIT 1")
            row2 = cur.fetchone()
            conn.close()
            if row2:
                index_directory(row2["path"], row2["label"])


class ServicesManager:
    def __init__(self):
        self._services = [
            ProcessWatcher(),
            ClipboardMonitor(),
            IdleDetector(),
            DriftDetector(),
            FocusSessionTracker(),
            FileIndexChecker(),
        ]

    def start(self):
        for svc in self._services:
            svc.start()

    def stop(self):
        for svc in self._services:
            svc.stop()

    def status(self):
        return {
            "running": sum(1 for s in self._services if s._thread and s._thread.is_alive()),
            "services": [s.name for s in self._services],
        }

    def get_service(self, name: str) -> BaseService | None:
        for s in self._services:
            if s.name == name:
                return s
        return None

    def service_running(self, name: str) -> bool:
        svc = self.get_service(name)
        return bool(svc and svc._thread and svc._thread.is_alive())

    def toggle_service(self, name: str, enabled: bool):
        svc = self.get_service(name)
        if not svc:
            return
        if enabled:
            svc.start()
        else:
            svc.stop()
