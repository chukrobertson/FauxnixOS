"""Bridge to archivist core modules — wraps DB, indexer, extractors, embeddings, and search.

The archivist backend is imported dynamically. At Nix build time the source is
bundled into the store as the `archivist_app` package. During local development
  on Windows set ARCHIVIST_SRC to E:/Archivist/app (imported as `app`).

The bridge normalises to `_a` (archivist app) so callers don't care which
module name the backend lives under at runtime.
"""

from __future__ import annotations

import importlib
import os
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from . import archivist_core


class ArchivistBridge:
    """Adapter that wraps archivist core modules for use from the GTK app."""

    def __init__(self, data_dir: Path):
        self._data_dir = data_dir
        self._ready = False
        self._error: str | None = None
        self._a: ModuleType | None = None

    def initialize(self) -> bool:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("FAUXNIX_ARCHIVIST_DATA", str(self._data_dir))
        os.environ.setdefault("ARCHIVIST_DATA_DIR", str(self._data_dir))
        if not archivist_core.available():
            self._error = archivist_core.load_error() or "archivist core not available"
            return False
        self._a = archivist_core.import_module("archivist_app")
        if self._a is None:
            self._error = archivist_core.load_error() or "cannot import archivist_app"
            return False
        try:
            for module_name in (
                "db",
                "config",
                "indexer",
                "extractors",
                "maintenance",
                "chat_engine",
                "embeddings",
                "autotagging",
            ):
                setattr(
                    self._a,
                    module_name,
                    importlib.import_module(f"archivist_app.{module_name}"),
                )
            self._a.db.init_db()
            self._ready = True
            return True
        except Exception as e:
            self._error = str(e)
            return False

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def error(self) -> str | None:
        return self._error

    # ── helpers ───────────────────────────────────────────────────────

    def _db(self):
        return self._a.db

    def _config(self):
        return self._a.config

    def _idx(self):
        return self._a.indexer

    def _ext(self):
        return self._a.extractors

    def _maint(self):
        return self._a.maintenance

    def _chat(self):
        return self._a.chat_engine

    def _emb(self):
        return self._a.embeddings

    def _tags(self):
        return self._a.autotagging

    # ── indexing ──────────────────────────────────────────────────────

    def index_paths(self, paths: list[Path], force: bool = False,
                    progress_cb: Callable = None) -> dict:
        if not self._ready:
            return {"error": "not initialized"}
        index_file = self._idx().index_file
        total = len(paths)
        indexed = []
        failed = []
        for i, item in enumerate(paths):
            if not item.exists() or item.name.startswith("."):
                continue
            try:
                rec = index_file(item, force=force)
                if rec:
                    indexed.append(rec)
            except Exception as e:
                failed.append({"path": str(item), "error": str(e)})
            if progress_cb and i % 10 == 0:
                progress_cb(i + 1, total)
        return {"indexed": len(indexed), "failed": len(failed), "total": total}

    # ── extraction ─────────────────────────────────────────────────────

    def extract_text(self, path: Path) -> str:
        if not self._ready:
            return ""
        try:
            return self._ext().extract_any(path)
        except Exception:
            return ""

    def extract_pdf(self, path: Path) -> str:
        if not self._ready:
            return ""
        try:
            return self._ext().extract_pdf_text(path)
        except Exception:
            return ""

    def ocr_image(self, path: Path) -> str:
        if not self._ready:
            return ""
        try:
            return self._ext().extract_image_ocr(path)
        except Exception:
            return ""

    # ── file listing ───────────────────────────────────────────────────

    def list_files(self, root: Path | None = None, limit: int = 200,
                   offset: int = 0, category: str | None = None) -> list[dict]:
        if not self._ready:
            return []
        try:
            result = self._maint().list_files(limit=limit, offset=offset, category=category)
            if isinstance(result, dict):
                return [dict(r) for r in result.get("files", [])]
            return [dict(r) for r in result]
        except Exception:
            return []

    def recent_files(self, limit: int = 80) -> list[dict]:
        return self.list_files(limit=limit, offset=0)

    def duplicate_files(self, limit: int = 50) -> list[dict]:
        if not self._ready:
            return []
        try:
            result = self._maint().duplicate_groups(limit=limit)
            rows = []
            for group in result.get("groups", []):
                for item in group.get("files", []):
                    row = dict(item)
                    row["summary"] = (
                        row.get("summary")
                        or f"Duplicate group: {group.get('count', 0)} files, "
                        f"{self.format_size(group.get('reclaimable_bytes', 0))} reclaimable"
                    )
                    rows.append(row)
            return rows
        except Exception:
            return []

    def index_failures(self, limit: int = 80) -> list[dict]:
        if not self._ready:
            return []
        try:
            result = self._maint().index_failure_triage(limit=limit)
            rows = []
            for item in result.get("groups", []):
                failures = item.get("failures") or []
                sample = failures[0].get("error") if failures else item.get("error", "")
                path = item.get("path", "")
                rows.append({
                    "path": path,
                    "name": Path(path).name,
                    "category": "index failure",
                    "summary": sample or "Indexing failed for this path.",
                    "modified_ts": item.get("last_ts") or 0,
                })
            return rows
        except Exception:
            return []

    def get_file_by_path(self, path: Path) -> dict | None:
        if not self._ready:
            return None
        try:
            conn = self._db().get_conn()
            cur = conn.cursor()
            cur.execute("""
                SELECT id, path, name, ext, category, size_bytes, modified_ts,
                       sha256, summary, preview_path, thumb_path, extracted_text
                FROM files WHERE path = ?
            """, (str(path),))
            row = cur.fetchone()
            conn.close()
            return dict(row) if row else None
        except Exception:
            return None

    # ── tags ───────────────────────────────────────────────────────────

    def list_tags(self) -> list[dict]:
        if not self._ready:
            return []
        try:
            return self._maint().list_tags()
        except Exception:
            return []

    def apply_tag(self, file_ids: list[int], tag: str) -> dict:
        if not self._ready:
            return {"error": "not initialized"}
        try:
            return self._maint().apply_tag(file_ids, tag)
        except Exception:
            return {"error": "failed"}

    def remove_tag(self, file_ids: list[int], tag: str) -> dict:
        if not self._ready:
            return {"error": "not initialized"}
        try:
            return self._maint().remove_tag(file_ids, tag)
        except Exception:
            return {"error": "failed"}

    # ── duplicates ─────────────────────────────────────────────────────

    def duplicate_groups(self, limit: int = 50) -> list[dict]:
        if not self._ready:
            return []
        try:
            return self._maint().duplicate_groups(limit=limit)
        except Exception:
            return []

    # ── semantic search ────────────────────────────────────────────────

    def search(self, query: str, limit: int = 20) -> list[dict]:
        if not self._ready:
            return []
        try:
            search_fn = getattr(self._chat(), "search_archive", None)
            if search_fn:
                return search_fn(query, limit=limit)
        except Exception:
            pass
        return self.search_keyword(query, limit)

    def search_keyword(self, query: str, limit: int = 50) -> list[dict]:
        if not self._ready:
            return []
        try:
            conn = self._db().get_conn()
            cur = conn.cursor()
            like = f"%{query}%"
            cur.execute("""
                SELECT id, path, name, ext, category, size_bytes, modified_ts,
                       summary, preview_path, thumb_path
                FROM files
                WHERE name LIKE ? OR summary LIKE ? OR extracted_text LIKE ?
                ORDER BY modified_ts DESC LIMIT ?
            """, (like, like, like, limit))
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows
        except Exception:
            return []

    def reindex_embeddings(self) -> dict:
        if not self._ready:
            return {"error": "not initialized"}
        try:
            return self._chat().reset_archive_embeddings()
        except Exception:
            return {"error": "failed"}

    # ── stats ──────────────────────────────────────────────────────────

    def stats(self) -> dict:
        if not self._ready:
            return {"files": 0, "tags": 0}
        try:
            return self._maint().archive_stats()
        except Exception:
            return {"files": 0, "tags": 0}

    @staticmethod
    def format_size(size_bytes: int | float | None) -> str:
        value = float(size_bytes or 0)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB":
                if unit == "B":
                    return f"{int(value)} {unit}"
                return f"{value:.1f} {unit}"
            value /= 1024

    def close(self):
        self._ready = False
        self._a = None


def file_category(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic"}:
        return "image"
    if ext in {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}:
        return "video"
    if ext in {".mp3", ".wav", ".m4a", ".flac", ".ogg"}:
        return "audio"
    if ext in {".pdf", ".docx", ".doc", ".txt", ".md", ".csv", ".xlsx", ".pptx"}:
        return "document"
    if ext in {".py", ".js", ".ts", ".rs", ".go", ".c", ".cpp", ".h", ".nix", ".sh", ".css", ".html"}:
        return "code"
    if ext in {".zip", ".tar", ".gz", ".7z", ".rar"}:
        return "archive"
    return "other"
