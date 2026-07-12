from __future__ import annotations

import os
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

from fauxnix_tools.db import get_conn as _get_fauxnix_conn
from fauxnix_tools.utils import guess_mime, sha256_file
from fauxnix_tools.utils.categories import file_category, IMAGE_EXTS, VIDEO_EXTS, AUDIO_EXTS
from fauxnix_tools.files.tagging import file_tag_names


def browse_directory(dir_path: str, *, filter_category: str | None = None,
                     filter_ext: str | None = None, query: str | None = None,
                     sort_by: str = "name", limit: int = 200) -> dict:
    root = Path(dir_path).resolve()
    if not root.is_dir():
        return {"ok": False, "error": "not_a_directory"}

    entries = []
    for entry in sorted(root.iterdir(), key=_sort_key(sort_by)):
        if entry.name.startswith(".") and not _is_show_hidden():
            continue

        info = {
            "name": entry.name,
            "path": str(entry),
            "is_dir": entry.is_dir(),
            "size": None,
            "modified": None,
            "ext": "",
            "mime": "",
            "category": "directory" if entry.is_dir() else "other",
        }

        if entry.is_file():
            stat = entry.stat()
            info["size"] = stat.st_size
            info["modified"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
            info["ext"] = entry.suffix.lower()
            info["mime"] = guess_mime(entry)
            info["category"] = file_category(entry, info["mime"])

            if filter_category and info["category"] != filter_category:
                continue
            if filter_ext and info["ext"] != filter_ext:
                continue
            if query and query.lower() not in entry.name.lower():
                continue

        entries.append(info)
        if len(entries) >= limit:
            break

    return {
        "ok": True,
        "path": str(root),
        "name": root.name,
        "entries": entries,
        "total": len(entries),
        "parent": str(root.parent) if root.parent != root else None,
    }


def browse_indexed(query: str | None = None, category: str | None = None,
                   tag: str | None = None, limit: int = 100) -> dict:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()

    conditions = []
    params = []

    if query:
        conditions.append("(f.name LIKE ? OR f.path LIKE ? OR f.extracted_text LIKE ?)")
        q = f"%{query}%"
        params.extend([q, q, q])
    if category:
        conditions.append("f.category = ?")
        params.append(category)
    if tag:
        conditions.append("""f.id IN (SELECT ft.file_id FROM file_tags ft
                          JOIN tags t ON t.id = ft.tag_id WHERE t.name = ?)""")
        params.append(tag)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    cur.execute(
        f"""SELECT f.id, f.path, f.name, f.ext, f.category, f.mime_type,
                   f.size_bytes, f.summary, f.thumb_path, f.indexed_ts
            FROM files f {where}
            ORDER BY f.indexed_ts DESC LIMIT ?""",
        params + [limit],
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    for r in rows:
        if r.get("id"):
            r["tags"] = file_tag_names(r["id"])

    return {"ok": True, "files": rows, "total": len(rows)}


def get_file_detail(file_id: int) -> dict:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM files WHERE id = ?", (file_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"ok": False, "error": "file_not_found"}

    d = dict(row)
    d["tags"] = file_tag_names(file_id)

    cur.execute("SELECT * FROM face_observations WHERE file_id = ? ORDER BY created_ts DESC LIMIT 20", (file_id,))
    d["faces"] = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM media_segments WHERE file_id = ? ORDER BY start_seconds ASC LIMIT 20", (file_id,))
    d["media_segments"] = [dict(r) for r in cur.fetchall()]

    cur.execute("""SELECT fa.action_type, fa.result_json, fa.created_ts
                   FROM file_actions fa WHERE fa.file_id = ? ORDER BY fa.created_ts DESC""", (file_id,))
    d["actions"] = [dict(r) for r in cur.fetchall()]

    conn.close()

    for face in d.get("faces", []):
        if face.get("bbox_json"):
            try:
                face["bbox"] = json.loads(face["bbox_json"])
            except Exception:
                pass

    return {"ok": True, "file": d}


def recent_files(limit: int = 20) -> list[dict]:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, path, name, ext, category, size_bytes, thumb_path, indexed_ts FROM files ORDER BY indexed_ts DESC LIMIT ?",
        (limit,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        r["tags"] = file_tag_names(r["id"]) if r.get("id") else []
    return rows


def file_statistics() -> dict:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    stats = {}

    cur.execute("SELECT COUNT(*) as c FROM files")
    stats["total_files"] = cur.fetchone()["c"]

    cur.execute("SELECT category, COUNT(*) as c FROM files GROUP BY category")
    stats["by_category"] = {r["category"]: r["c"] for r in cur.fetchall()}

    cur.execute("SELECT COALESCE(SUM(size_bytes), 0) as total FROM files")
    stats["total_bytes"] = cur.fetchone()["total"]

    cur.execute("SELECT COUNT(*) as c FROM face_observations")
    stats["total_faces"] = cur.fetchone()["c"]

    cur.execute("SELECT COUNT(DISTINCT cluster_id) as c FROM face_observations WHERE cluster_id IS NOT NULL")
    stats["unique_faces"] = cur.fetchone()["c"]

    cur.execute("SELECT COUNT(*) as c FROM face_names")
    stats["named_faces"] = cur.fetchone()["c"]

    cur.execute("SELECT COUNT(*) as c FROM tags")
    stats["total_tags"] = cur.fetchone()["c"]

    conn.close()
    return stats


def _sort_key(sort_by: str):
    if sort_by == "size":
        return lambda e: (1 if e.is_dir() else 0, e.stat().st_size)
    elif sort_by == "modified":
        return lambda e: (1 if e.is_dir() else 0, -e.stat().st_mtime)
    elif sort_by == "type":
        return lambda e: (1 if e.is_dir() else 0, e.suffix.lower())
    return lambda e: (1 if e.is_dir() else 0, e.name.lower())


def _is_show_hidden() -> bool:
    return os.getenv("ARCHIVIST_SHOW_HIDDEN", "0") == "1"
