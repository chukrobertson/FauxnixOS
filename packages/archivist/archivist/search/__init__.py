from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fauxnix_tools.db import get_conn as _get_fauxnix_conn
from fauxnix_tools.files.tagging import file_tag_names


def search_everything(query: str, limit: int = 50) -> dict:
    results = {}

    results["files"] = search_files(query, limit)
    results["by_content"] = search_by_content(query, limit)
    results["by_tag"] = search_by_tag(query, limit)
    results["faces"] = search_faces(query, limit)
    results["media"] = search_media(query, limit)

    total = sum(len(v) for v in results.values())
    return {"ok": True, "query": query, "results": results, "total_hits": total}


def search_files(query: str, limit: int = 30) -> list[dict]:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    q = f"%{query}%"
    cur.execute(
        """SELECT id, path, name, ext, category, size_bytes, summary, thumb_path, indexed_ts
           FROM files WHERE name LIKE ? OR path LIKE ? OR summary LIKE ?
           ORDER BY indexed_ts DESC LIMIT ?""",
        (q, q, q, limit),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        r["tags"] = file_tag_names(r["id"]) if r.get("id") else []
    return rows


def search_by_content(query: str, limit: int = 20) -> list[dict]:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    q = f"%{query}%"
    cur.execute(
        """SELECT id, path, name, ext, category, size_bytes, summary, thumb_path, indexed_ts
           FROM files WHERE extracted_text LIKE ?
           ORDER BY indexed_ts DESC LIMIT ?""",
        (q, limit),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        r["tags"] = file_tag_names(r["id"]) if r.get("id") else []
    return rows


def search_by_tag(tag: str, limit: int = 30) -> list[dict]:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cur.execute(
        """SELECT f.id, f.path, f.name, f.ext, f.category, f.size_bytes, f.summary, f.thumb_path, f.indexed_ts
           FROM files f
           INNER JOIN file_tags ft ON ft.file_id = f.id
           INNER JOIN tags t ON t.id = ft.tag_id
           WHERE t.name LIKE ?
           ORDER BY f.indexed_ts DESC LIMIT ?""",
        (f"%{tag}%", limit),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        r["tags"] = file_tag_names(r["id"]) if r.get("id") else []
    return rows


def search_faces(query: str, limit: int = 20) -> list[dict]:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()

    cur.execute("SELECT cluster_id, name FROM face_names WHERE name LIKE ?", (f"%{query}%",))
    named = [dict(r) for r in cur.fetchall()]
    if named:
        results = []
        for n in named:
            cur.execute(
                """SELECT fo.id, fo.path, fo.media_type, fo.crop_path, fo.cluster_id,
                          f.name as filename, f.id as file_id
                   FROM face_observations fo
                   LEFT JOIN files f ON f.id = fo.file_id
                   WHERE fo.cluster_id = ?
                   ORDER BY fo.created_ts DESC LIMIT 5""",
                (n["cluster_id"],),
            )
            for r in cur.fetchall():
                results.append({**dict(r), "face_name": n["name"]})
        conn.close()
        return results

    conn.close()
    return []


def search_media(query: str, limit: int = 20) -> list[dict]:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    q = f"%{query}%"
    cur.execute(
        """SELECT ms.id, ms.file_id, ms.path, ms.media_type, ms.start_seconds,
                  ms.title, ms.summary, ms.timeline, ms.thumb_path, ms.source,
                  f.name as filename
           FROM media_segments ms
           LEFT JOIN files f ON f.id = ms.file_id
           WHERE ms.title LIKE ? OR ms.summary LIKE ?
           ORDER BY ms.created_ts DESC LIMIT ?""",
        (q, q, limit),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def search_duplicates(min_size: int = 0) -> dict:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cur.execute(
        """SELECT sha256, COUNT(*) as cnt, GROUP_CONCAT(path, '|||') as paths,
                  MIN(size_bytes) as size, MIN(id) as first_id
           FROM files WHERE sha256 IS NOT NULL AND sha256 != ''
           GROUP BY sha256 HAVING cnt > 1
           ORDER BY cnt DESC LIMIT 50""",
    )
    dupes = []
    for row in cur.fetchall():
        paths = row["paths"].split("|||")
        dupes.append({
            "hash": row["sha256"],
            "count": row["cnt"],
            "size": row["size"],
            "paths": paths,
            "potential_waste": (row["cnt"] - 1) * row["size"],
        })
    conn.close()
    return {"ok": True, "duplicate_groups": dupes, "total_groups": len(dupes)}


def list_all_tags() -> dict:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cur.execute(
        """SELECT t.name, COUNT(ft.file_id) as file_count
           FROM tags t LEFT JOIN file_tags ft ON ft.tag_id = t.id
           GROUP BY t.id, t.name ORDER BY file_count DESC LIMIT 100""",
    )
    tags = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"ok": True, "tags": tags, "total": len(tags)}
