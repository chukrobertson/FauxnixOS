from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from fauxnix_tools.db import get_conn as _get_fauxnix_conn
from fauxnix_tools.files.indexing import index_directory
from fauxnix_tools.files.snapshot import snapshot_directory
from archivist.smart_actions import auto_classify_file, detect_duplicates
from archivist.organizer import apply_rules_to_directory


class ArchivistDaemon:
    def __init__(self):
        self._thread = None
        self._running = False
        self._stop = threading.Event()

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="archivist_daemon", daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    @property
    def is_running(self) -> bool:
        return self._running

    def _run(self):
        while not self._stop.wait(60):
            try:
                self._tick()
            except Exception:
                pass

    def _tick(self):
        conn = _get_fauxnix_conn()
        cur = conn.cursor()
        cur.execute("SELECT path, label, auto_index, auto_organize FROM watched_dirs WHERE auto_index = 1")
        watched = [dict(r) for r in cur.fetchall()]
        conn.close()

        for w in watched:
            try:
                result = index_directory(w["path"], w.get("label"))
                if result.get("indexed", 0) > 0:
                    self._notify(f"Indexed {result['indexed']} files in {w.get('label', w['path'])}")

                if w.get("auto_organize"):
                    org_result = apply_rules_to_directory(w["path"])
                    if org_result.get("moved", 0) > 0:
                        self._notify(f"Organized {org_result['moved']} files in {w.get('label', w['path'])}")
            except Exception:
                pass

    def _notify(self, message: str):
        try:
            import subprocess
            subprocess.run(["notify-send", "Archivist", message], timeout=5)
        except Exception:
            pass


def add_watched_directory(dir_path: str, label: str | None = None,
                          auto_organize: bool = True,
                          auto_index: bool = True) -> dict:
    root = Path(dir_path).resolve()
    if not root.is_dir():
        return {"ok": False, "error": "not_a_directory"}

    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    now = time.time()
    try:
        cur.execute(
            """INSERT INTO watched_dirs (path, label, auto_organize, auto_index, last_scan_ts, created_ts)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (str(root), label or root.name, 1 if auto_organize else 0, 1 if auto_index else 0, now, now),
        )
        conn.commit()
    except Exception:
        pass
    conn.close()

    index_directory(str(root), label or root.name)

    return {"ok": True, "path": str(root), "label": label or root.name}


def remove_watched_directory(dir_path: str) -> dict:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM watched_dirs WHERE path = ?", (str(dir_path),))
    conn.commit()
    conn.close()
    return {"ok": True, "removed": str(dir_path)}


def list_watched_directories() -> list[dict]:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM watched_dirs ORDER BY created_ts DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def scan_now(dir_path: str | None = None) -> dict:
    if dir_path:
        return index_directory(dir_path)
    watched = list_watched_directories()
    results = []
    for w in watched:
        results.append(index_directory(w["path"], w.get("label")))
    return {"ok": True, "scanned": len(results), "results": results}
