from __future__ import annotations

from pathlib import Path

from app.config import ARCHIVE_ROOT
from app.db import get_conn
from app.utils import file_category, guess_mime, safe_rel_path


def indexed_metadata(paths: list[str]) -> dict[str, dict]:
    if not paths:
        return {}
    conn = get_conn()
    cur = conn.cursor()
    placeholders = ",".join("?" for _ in paths)
    cur.execute(
        f"""
        SELECT id, path, category, summary, deleted_candidate, duplicate_of, sha256,
               indexed_ts, preview_path, thumb_path
        FROM files
        WHERE path IN ({placeholders})
        """,
        paths,
    )
    rows = {row["path"]: dict(row) for row in cur.fetchall()}
    conn.close()
    return rows


def explorer_item(path: Path, meta: dict | None = None) -> dict:
    stat = path.stat()
    is_dir = path.is_dir()
    mime = "" if is_dir else guess_mime(path)
    category = "folder" if is_dir else (meta or {}).get("category") or file_category(path, mime)
    return {
        "id": (meta or {}).get("id"),
        "name": path.name or str(path),
        "path": str(path),
        "rel_path": safe_rel_path(path, ARCHIVE_ROOT),
        "kind": "directory" if is_dir else "file",
        "ext": "" if is_dir else path.suffix.lower(),
        "mime_type": mime,
        "category": category,
        "size_bytes": 0 if is_dir else stat.st_size,
        "modified_ts": stat.st_mtime,
        "indexed": bool((meta or {}).get("indexed_ts")),
        "deleted_candidate": int((meta or {}).get("deleted_candidate") or 0),
        "duplicate_of": (meta or {}).get("duplicate_of"),
        "summary": (meta or {}).get("summary"),
        "preview_path": (meta or {}).get("preview_path"),
        "thumb_path": (meta or {}).get("thumb_path"),
    }


def list_explorer_directory(path: Path, limit: int = 500) -> dict:
    root = ARCHIVE_ROOT.resolve(strict=False)
    current = path.resolve(strict=False)
    entries = sorted(
        [item for item in current.iterdir() if not item.name.startswith(".")],
        key=lambda item: (not item.is_dir(), item.name.lower()),
    )
    limited = entries[: max(1, min(int(limit), 1000))]
    metadata = indexed_metadata([str(item) for item in limited])
    items = []
    for item in limited:
        try:
            items.append(explorer_item(item, metadata.get(str(item))))
        except OSError:
            continue
    parent = current.parent if current != root else None
    return {
        "archive_root": str(root),
        "path": str(current),
        "rel_path": safe_rel_path(current, root),
        "parent": str(parent) if parent and str(parent).startswith(str(root)) else None,
        "items": items,
        "total": len(entries),
        "limit": max(1, min(int(limit), 1000)),
    }
