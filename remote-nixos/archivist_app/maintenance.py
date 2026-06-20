from __future__ import annotations

import time
import shutil
from collections import Counter
from pathlib import Path

from app.config import ARCHIVE_DUP_REVIEW_DIR, ARCHIVE_REVIEW_DIR, ARCHIVE_ROOT
from app.db import get_conn
from app.utils import ensure_parent, file_category, file_extension, guess_mime, now_ts, path_is_inside, safe_rel_path, unique_path


PRE_INDEX_HASH_NOTE = "Pre-index hash scan only; pending full indexing"
PRE_INDEX_DEDUPE_REASON = "Exact SHA-256 duplicate; queued by pre-index dedupe scan"
MOVED_DUPLICATE_REASON = "Exact duplicate moved to archival review; excluded from chatbot indexing"


def delete_chat_embeddings_for_paths(paths: list[str]) -> dict:
    try:
        from app.chat_engine import delete_embeddings

        return delete_embeddings(paths)
    except Exception as e:
        return {"attempted": len(paths), "deleted": 0, "failed": len(paths), "error": str(e)}


def sync_chat_embeddings_for_file_ids(file_ids: list[int]) -> dict:
    results = []
    try:
        from app.chat_engine import sync_file_embedding_by_id

        for file_id in sorted(set(int(item) for item in file_ids)):
            results.append(sync_file_embedding_by_id(file_id))
    except Exception as e:
        return {"attempted": len(file_ids), "synced": 0, "failed": len(file_ids), "error": str(e)}
    synced = sum(1 for item in results if item.get("synced"))
    failed = sum(1 for item in results if item.get("mode") == "failed")
    return {"attempted": len(results), "synced": synced, "failed": failed, "sample": results[:10]}


def remove_file_index_paths(paths: list[str], reason: str | None = None) -> dict:
    normalized = sorted({str(item) for item in paths if str(item or "").strip()})
    if not normalized:
        return {"removed": 0, "embeddings": {"attempted": 0, "deleted": 0, "failed": 0}}
    conn = get_conn()
    cur = conn.cursor()
    placeholders = ",".join("?" for _ in normalized)
    cur.execute(f"SELECT id, path FROM files WHERE path IN ({placeholders})", normalized)
    rows = [dict(row) for row in cur.fetchall()]
    if rows:
        cur.execute(f"DELETE FROM files WHERE path IN ({placeholders})", normalized)
    conn.commit()
    conn.close()
    embedding_result = delete_chat_embeddings_for_paths([row["path"] for row in rows] or normalized)
    return {
        "removed": len(rows),
        "paths": [row["path"] for row in rows],
        "reason": reason or "Removed from file index",
        "embeddings": embedding_result,
    }


def humanish_path(path: str) -> str:
    try:
        return str(Path(path).relative_to(ARCHIVE_ROOT))
    except Exception:
        return path


def clean_tag_name(name: str) -> str:
    cleaned = " ".join((name or "").strip().split())
    if not cleaned:
        raise ValueError("Tag cannot be empty")
    if len(cleaned) > 64:
        raise ValueError("Tag is too long")
    return cleaned


def duplicate_keeper_key(path_text: str) -> tuple[int, int, str]:
    lower = path_text.lower().replace("\\", "/")
    parts = [part for part in lower.split("/") if part]
    penalty = 0
    suspicious_parts = {
        "$recycle.bin",
        "duplicate",
        "duplicates",
        "dupe",
        "dupes",
        "duplicates_quarantine",
        "review",
        "quarantine",
        "trash",
        "temp",
        "tmp",
        "cache",
    }
    if any(part in suspicious_parts for part in parts):
        penalty += 100
    name = Path(path_text).name.lower()
    copy_markers = [" copy", "-copy", "_copy", "(copy", "(1)", "(2)", "(3)", " - copy"]
    if any(marker in name for marker in copy_markers):
        penalty += 20
    return (penalty, len(path_text), path_text)


def archive_stats() -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            COUNT(*) AS file_count,
            COALESCE(SUM(size_bytes), 0) AS total_bytes,
            COALESCE(SUM(CASE WHEN COALESCE(deleted_candidate, 0) = 0 THEN 1 ELSE 0 END), 0) AS active_file_count,
            COALESCE(SUM(CASE WHEN COALESCE(deleted_candidate, 0) = 0 THEN size_bytes ELSE 0 END), 0) AS active_bytes,
            COALESCE(SUM(CASE WHEN deleted_candidate = 1 THEN 1 ELSE 0 END), 0) AS delete_queue_count,
            MAX(indexed_ts) AS last_indexed_ts
        FROM files
        """
    )
    totals = dict(cur.fetchone())

    cur.execute(
        """
        SELECT category, COUNT(*) AS count, COALESCE(SUM(size_bytes), 0) AS bytes
        FROM files
        WHERE COALESCE(deleted_candidate, 0) = 0
        GROUP BY category
        ORDER BY count DESC
        """
    )
    categories = [dict(row) for row in cur.fetchall()]

    cur.execute(
        """
        SELECT ext, COUNT(*) AS count, COALESCE(SUM(size_bytes), 0) AS bytes
        FROM files
        WHERE ext IS NOT NULL AND ext != ''
          AND COALESCE(deleted_candidate, 0) = 0
        GROUP BY ext
        ORDER BY count DESC
        LIMIT 16
        """
    )
    extensions = [dict(row) for row in cur.fetchall()]

    cur.execute(
        """
        SELECT COUNT(*) AS groups, COALESCE(SUM((dupe_count - 1) * size_bytes), 0) AS reclaimable_bytes
        FROM (
            SELECT sha256, COUNT(*) AS dupe_count, MAX(size_bytes) AS size_bytes
            FROM files
            WHERE sha256 IS NOT NULL AND sha256 != ''
              AND COALESCE(deleted_candidate, 0) = 0
            GROUP BY sha256
            HAVING COUNT(*) > 1
        )
        """
    )
    duplicates = dict(cur.fetchone())

    cur.execute("SELECT COUNT(*) AS count FROM index_failures WHERE resolved = 0")
    failure_count = int(cur.fetchone()["count"])
    conn.close()

    disk_usage = None
    usage_path = ARCHIVE_ROOT
    try:
        usage = shutil.disk_usage(usage_path)
    except OSError:
        try:
            usage_path = Path(ARCHIVE_ROOT.anchor or str(ARCHIVE_ROOT))
            usage = shutil.disk_usage(usage_path)
        except OSError:
            usage = None

    if usage:
        disk_usage = {
            "path": str(usage_path),
            "archive_root": str(ARCHIVE_ROOT),
            "total": int(usage.total),
            "used": int(usage.used),
            "free": int(usage.free),
            "percent_used": round((usage.used / usage.total) * 100, 2) if usage.total else 0,
        }
    else:
        disk_usage = {
            "path": str(ARCHIVE_ROOT),
            "total": 0,
            "used": 0,
            "free": 0,
            "percent_used": 0,
            "error": "Disk usage unavailable for archive root",
        }

    return {
        "archive_root": str(ARCHIVE_ROOT),
        "file_count": int(totals["file_count"] or 0),
        "total_bytes": int(totals["total_bytes"] or 0),
        "active_file_count": int(totals.get("active_file_count") or 0),
        "active_bytes": int(totals.get("active_bytes") or 0),
        "disk_usage": disk_usage,
        "delete_queue_count": int(totals["delete_queue_count"] or 0),
        "last_indexed_ts": totals["last_indexed_ts"],
        "duplicate_groups": int(duplicates["groups"] or 0),
        "duplicate_reclaimable_bytes": int(duplicates["reclaimable_bytes"] or 0),
        "index_failure_count": failure_count,
        "categories": categories,
        "extensions": extensions,
    }


def _generic_summary(name: str, category: str) -> str:
    return f"{category.title()} file: {name}"


def recategorize_file_index() -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, path, name, ext, mime_type, category, summary FROM files")
    rows = [dict(row) for row in cur.fetchall()]
    changed = 0
    ext_changed = 0
    by_category: Counter[str] = Counter()
    samples = []
    for row in rows:
        old_category = row.get("category") or "other"
        if old_category == "knowledgebase":
            continue
        path = Path(row["path"])
        name = row.get("name") or path.name
        mime = guess_mime(path)
        ext = file_extension(path)
        new_category = file_category(path, mime)
        old_summary = row.get("summary") or ""
        new_summary = row.get("summary")
        if old_summary in {_generic_summary(name, old_category), f"Other file: {name}", ""}:
            new_summary = _generic_summary(name, new_category)
        if (
            new_category != old_category
            or ext != (row.get("ext") or "")
            or mime != (row.get("mime_type") or "")
            or new_summary != row.get("summary")
        ):
            cur.execute(
                """
                UPDATE files
                SET category = ?, ext = ?, mime_type = ?, summary = ?
                WHERE id = ?
                """,
                (new_category, ext, mime, new_summary, int(row["id"])),
            )
            changed += int(new_category != old_category)
            ext_changed += int(ext != (row.get("ext") or ""))
            by_category[new_category] += 1
            if len(samples) < 12:
                samples.append(
                    {
                        "id": row["id"],
                        "path": row["path"],
                        "from": old_category,
                        "to": new_category,
                        "ext": ext,
                    }
                )
    conn.commit()
    conn.close()
    return {
        "scanned": len(rows),
        "category_changed": changed,
        "ext_changed": ext_changed,
        "by_category": dict(by_category),
        "sample": samples,
    }


def list_tags() -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT t.id, t.name, t.color, COUNT(ft.file_id) AS file_count
        FROM tags t
        LEFT JOIN file_tags ft ON ft.tag_id = t.id
        GROUP BY t.id
        ORDER BY t.name COLLATE NOCASE
        """
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


def ensure_tag(name: str, color: str | None = None) -> int:
    tag = clean_tag_name(name)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO tags (name, color, created_ts) VALUES (?, ?, ?)",
        (tag, color, time.time()),
    )
    cur.execute("SELECT id FROM tags WHERE name = ?", (tag,))
    tag_id = int(cur.fetchone()["id"])
    conn.commit()
    conn.close()
    return tag_id


def apply_tag(file_ids: list[int], tag: str) -> dict:
    tag_id = ensure_tag(tag)
    ts = time.time()
    conn = get_conn()
    cur = conn.cursor()
    applied = 0
    for file_id in sorted(set(int(fid) for fid in file_ids)):
        cur.execute("SELECT id FROM files WHERE id = ?", (file_id,))
        if not cur.fetchone():
            continue
        cur.execute(
            "INSERT OR IGNORE INTO file_tags (file_id, tag_id, source, created_ts) VALUES (?, ?, 'manual', ?)",
            (file_id, tag_id, ts),
        )
        applied += cur.rowcount
        cur.execute(
            "UPDATE file_tags SET source = 'manual' WHERE file_id = ? AND tag_id = ?",
            (file_id, tag_id),
        )
    conn.commit()
    conn.close()
    return {"tag_id": tag_id, "tag": clean_tag_name(tag), "applied": applied}


def remove_tag(file_ids: list[int], tag: str) -> dict:
    tag = clean_tag_name(tag)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM tags WHERE name = ?", (tag,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"tag": tag, "removed": 0}
    tag_id = int(row["id"])
    removed = 0
    for file_id in sorted(set(int(fid) for fid in file_ids)):
        cur.execute("DELETE FROM file_tags WHERE file_id = ? AND tag_id = ?", (file_id, tag_id))
        removed += cur.rowcount
    conn.commit()
    conn.close()
    return {"tag": tag, "removed": removed}


def queue_deletion(file_ids: list[int], reason: str | None = None) -> dict:
    ts = time.time()
    conn = get_conn()
    cur = conn.cursor()
    queued = 0
    embedding_paths: list[str] = []
    for file_id in sorted(set(int(fid) for fid in file_ids)):
        cur.execute("SELECT id, path FROM files WHERE id = ?", (file_id,))
        row = cur.fetchone()
        if not row:
            continue
        embedding_paths.append(row["path"])
        cur.execute("UPDATE files SET deleted_candidate = 1 WHERE id = ?", (file_id,))
        cur.execute(
            """
            INSERT INTO deletion_reviews (file_id, path, reason, status, created_ts, updated_ts)
            SELECT ?, ?, ?, 'queued', ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM deletion_reviews WHERE file_id = ? AND status = 'queued'
            )
            """,
            (file_id, row["path"], reason or "Queued from maintenance workbench", ts, ts, file_id),
        )
        queued += cur.rowcount
    conn.commit()
    conn.close()
    embedding_result = delete_chat_embeddings_for_paths(embedding_paths)
    return {"queued": queued, "embeddings": embedding_result}


def queue_deletion_by_path(path: str, reason: str | None = None) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM files WHERE path = ?", (path,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return {"queued": 0, "missing": path}
    return queue_deletion([int(row["id"])], reason)


def queue_exact_duplicates_for_review() -> dict:
    ts = time.time()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT sha256
        FROM files
        WHERE sha256 IS NOT NULL AND sha256 != ''
          AND COALESCE(deleted_candidate, 0) = 0
        GROUP BY sha256
        HAVING COUNT(*) > 1
        """
    )
    hashes = [row["sha256"] for row in cur.fetchall()]
    groups = 0
    queued = 0
    reclaimable_bytes = 0
    embedding_paths: list[str] = []
    reason = "Exact SHA-256 duplicate; queued by maintenance dedupe"
    for file_hash in hashes:
        cur.execute(
            """
            SELECT id, path, size_bytes
            FROM files
            WHERE sha256 = ?
              AND COALESCE(deleted_candidate, 0) = 0
            ORDER BY path COLLATE NOCASE
            """,
            (file_hash,),
        )
        files = [dict(row) for row in cur.fetchall()]
        if len(files) < 2:
            continue
        groups += 1
        keeper = min(files, key=lambda item: duplicate_keeper_key(item["path"]))
        for item in files:
            if item["id"] == keeper["id"]:
                cur.execute("UPDATE files SET duplicate_of = NULL WHERE id = ?", (item["id"],))
                continue
            cur.execute(
                "UPDATE files SET duplicate_of = ?, deleted_candidate = 1, notes = ? WHERE id = ?",
                (keeper["path"], reason, item["id"]),
            )
            cur.execute(
                """
                INSERT INTO deletion_reviews (file_id, path, reason, status, created_ts, updated_ts)
                SELECT ?, ?, ?, 'queued', ?, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM deletion_reviews WHERE file_id = ? AND status = 'queued'
                )
                """,
                (item["id"], item["path"], reason, ts, ts, item["id"]),
            )
            queued += cur.rowcount
            reclaimable_bytes += int(item["size_bytes"] or 0)
            embedding_paths.append(item["path"])
    conn.commit()
    conn.close()
    embedding_result = delete_chat_embeddings_for_paths(embedding_paths)
    return {"groups": groups, "queued": queued, "reclaimable_bytes": reclaimable_bytes, "embeddings": embedding_result}


def upsert_preindex_hash_record(path: Path, file_hash: str, duplicate_of: str | None = None) -> dict:
    stat = path.stat()
    mime = guess_mime(path)
    category = file_category(path, mime)
    ts = now_ts()
    is_duplicate = bool(duplicate_of)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM files WHERE path = ?", (str(path),))
    existing = dict(cur.fetchone() or {})

    existing_is_preindex = (existing.get("notes") or "") in {PRE_INDEX_HASH_NOTE, PRE_INDEX_DEDUPE_REASON}
    has_full_summary = bool(existing.get("summary")) and not existing_is_preindex

    if is_duplicate:
        summary = f"Exact duplicate of {duplicate_of}. Content hash matches; queued before full indexing."
        extracted_text = existing.get("extracted_text") or ""
        indexed_ts = existing.get("indexed_ts") or ts
        deleted_candidate = 1
        notes = PRE_INDEX_DEDUPE_REASON
    else:
        summary = existing.get("summary") if has_full_summary else PRE_INDEX_HASH_NOTE
        extracted_text = existing.get("extracted_text") if has_full_summary else ""
        indexed_ts = existing.get("indexed_ts") if has_full_summary else ts
        deleted_candidate = int(existing.get("deleted_candidate") or 0) if not existing_is_preindex else 0
        notes = existing.get("notes") if has_full_summary else PRE_INDEX_HASH_NOTE

    cur.execute(
        """
        INSERT INTO files (
            path, rel_path, name, ext, mime_type, size_bytes, sha256,
            created_ts, modified_ts, indexed_ts, category, summary,
            extracted_text, suggested_folder, preview_path, thumb_path,
            duplicate_of, deleted_candidate, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            rel_path=excluded.rel_path,
            name=excluded.name,
            ext=excluded.ext,
            mime_type=excluded.mime_type,
            size_bytes=excluded.size_bytes,
            sha256=excluded.sha256,
            created_ts=excluded.created_ts,
            modified_ts=excluded.modified_ts,
            indexed_ts=excluded.indexed_ts,
            category=excluded.category,
            summary=excluded.summary,
            extracted_text=excluded.extracted_text,
            duplicate_of=excluded.duplicate_of,
            deleted_candidate=excluded.deleted_candidate,
            notes=excluded.notes
        """,
        (
            str(path),
            safe_rel_path(path, ARCHIVE_ROOT),
            path.name,
            file_extension(path),
            mime,
            stat.st_size,
            file_hash,
            stat.st_ctime,
            stat.st_mtime,
            indexed_ts,
            category,
            summary,
            extracted_text,
            existing.get("suggested_folder") or "",
            existing.get("preview_path") or "",
            existing.get("thumb_path") or "",
            duplicate_of,
            deleted_candidate,
            notes,
        ),
    )

    queued = 0
    if is_duplicate:
        cur.execute("SELECT id FROM files WHERE path = ?", (str(path),))
        row = cur.fetchone()
        file_id = int(row["id"]) if row else None
        cur.execute(
            """
            INSERT INTO deletion_reviews (file_id, path, reason, status, created_ts, updated_ts)
            SELECT ?, ?, ?, 'queued', ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM deletion_reviews WHERE path = ? AND status = 'queued'
            )
            """,
            (file_id, str(path), PRE_INDEX_DEDUPE_REASON, ts, ts, str(path)),
        )
        queued = cur.rowcount

    conn.commit()
    conn.close()
    return {"path": str(path), "duplicate": is_duplicate, "queued": queued, "size_bytes": stat.st_size}


def retarget_preindex_duplicates(old_keeper: str, new_keeper: str) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE files
        SET duplicate_of = ?
        WHERE duplicate_of = ? AND notes = ?
        """,
        (new_keeper, old_keeper, PRE_INDEX_DEDUPE_REASON),
    )
    conn.commit()
    conn.close()


def remove_empty_parents(start: Path, stop: Path) -> int:
    removed = 0
    current = start
    stop_resolved = stop.resolve(strict=False)
    review_resolved = ARCHIVE_REVIEW_DIR.resolve(strict=False)
    while current != stop_resolved and path_is_inside(current, stop_resolved):
        if current == review_resolved or path_is_inside(current, review_resolved):
            break
        try:
            current.rmdir()
            removed += 1
        except OSError:
            break
        current = current.parent
    return removed


def move_queued_duplicates_to_review(
    *,
    dry_run: bool = False,
    limit: int | None = None,
    remove_empty_folders: bool = True,
) -> dict:
    limit_clause = ""
    params: list = [PRE_INDEX_DEDUPE_REASON]
    if limit:
        limit_clause = "LIMIT ?"
        params.append(max(1, int(limit)))

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT id, path, rel_path, duplicate_of, size_bytes
        FROM files
        WHERE deleted_candidate = 1
          AND notes = ?
          AND path NOT LIKE ?
        ORDER BY path COLLATE NOCASE
        {limit_clause}
        """,
        [PRE_INDEX_DEDUPE_REASON, f"{str(ARCHIVE_DUP_REVIEW_DIR)}%"] + params[1:],
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()

    moved = 0
    missing = 0
    failed = 0
    empty_removed = 0
    reclaimable_bytes = 0
    failures: list[dict] = []
    planned: list[dict] = []
    embedding_paths: list[str] = []

    for row in rows:
        source = Path(row["path"])
        if not source.exists():
            missing += 1
            embedding_paths.append(row["path"])
            continue
        try:
            rel = source.relative_to(ARCHIVE_ROOT)
        except ValueError:
            rel = Path(source.name)
        dest = unique_path(ARCHIVE_DUP_REVIEW_DIR / rel)
        planned.append({"from": str(source), "to": str(dest), "size_bytes": int(row["size_bytes"] or 0)})
        reclaimable_bytes += int(row["size_bytes"] or 0)
        if dry_run:
            continue

        try:
            ensure_parent(dest)
            shutil.move(str(source), str(dest))
            parent = source.parent
            conn = get_conn()
            cur = conn.cursor()
            ts = now_ts()
            cur.execute(
                """
                UPDATE files
                SET path = ?, rel_path = ?, suggested_folder = ?, notes = ?,
                    deleted_candidate = 1, indexed_ts = ?
                WHERE id = ?
                """,
                (
                    str(dest),
                    safe_rel_path(dest, ARCHIVE_ROOT),
                    "Review/Duplicates",
                    MOVED_DUPLICATE_REASON,
                    ts,
                    row["id"],
                ),
            )
            cur.execute(
                """
                UPDATE deletion_reviews
                SET path = ?, reason = ?, updated_ts = ?
                WHERE file_id = ? AND status = 'queued'
                """,
                (str(dest), MOVED_DUPLICATE_REASON, ts, row["id"]),
            )
            conn.commit()
            conn.close()
            moved += 1
            embedding_paths.extend([str(source), str(dest)])
            if remove_empty_folders:
                empty_removed += remove_empty_parents(parent, ARCHIVE_ROOT)
        except Exception as e:
            failed += 1
            failures.append({"path": str(source), "error": str(e)})

    embedding_result = {"attempted": 0, "deleted": 0, "failed": 0} if dry_run else delete_chat_embeddings_for_paths(embedding_paths)

    return {
        "dry_run": dry_run,
        "planned": len(planned),
        "moved": moved,
        "missing": missing,
        "failed": failed,
        "empty_folders_removed": empty_removed,
        "reclaimable_bytes": reclaimable_bytes,
        "review_dir": str(ARCHIVE_DUP_REVIEW_DIR),
        "embeddings": embedding_result,
        "failures": failures[:20],
        "sample": planned[:20],
    }


def unqueue_deletion(file_ids: list[int]) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cleared = 0
    sync_ids: list[int] = []
    for file_id in sorted(set(int(fid) for fid in file_ids)):
        cur.execute("UPDATE files SET deleted_candidate = 0 WHERE id = ?", (file_id,))
        cleared += cur.rowcount
        if cur.rowcount:
            sync_ids.append(file_id)
        cur.execute(
            "UPDATE deletion_reviews SET status = 'cleared', updated_ts = ? WHERE file_id = ? AND status = 'queued'",
            (time.time(), file_id),
        )
    conn.commit()
    conn.close()
    embedding_result = sync_chat_embeddings_for_file_ids(sync_ids)
    return {"cleared": cleared, "embeddings": embedding_result}


def file_filters(
    *,
    q: str | None,
    category: str | None,
    tag: str | None,
    duplicates: bool,
    delete_queue: bool,
) -> tuple[str, list]:
    clauses = []
    params: list = []
    if q:
        clauses.append("(f.name LIKE ? OR f.path LIKE ? OR f.summary LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])
    if category:
        clauses.append("f.category = ?")
        params.append(category)
    if tag:
        clauses.append(
            """
            EXISTS (
                SELECT 1 FROM file_tags ft
                JOIN tags t ON t.id = ft.tag_id
                WHERE ft.file_id = f.id AND t.name = ?
            )
            """
        )
        params.append(tag)
    if duplicates:
        clauses.append(
            """
            COALESCE(f.deleted_candidate, 0) = 0
            AND f.sha256 IN (
                SELECT sha256 FROM files
                WHERE sha256 IS NOT NULL AND sha256 != ''
                  AND COALESCE(deleted_candidate, 0) = 0
                GROUP BY sha256
                HAVING COUNT(*) > 1
            )
            """
        )
    if delete_queue:
        clauses.append("f.deleted_candidate = 1")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def list_files(
    *,
    q: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    duplicates: bool = False,
    delete_queue: bool = False,
    limit: int = 80,
    offset: int = 0,
    sort: str = "indexed_desc",
) -> dict:
    sort_map = {
        "name": "f.name COLLATE NOCASE ASC",
        "size_desc": "f.size_bytes DESC",
        "modified_desc": "f.modified_ts DESC",
        "indexed_desc": "f.indexed_ts DESC",
        "category": "f.category COLLATE NOCASE ASC, f.name COLLATE NOCASE ASC",
    }
    order_by = sort_map.get(sort, sort_map["indexed_desc"])
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    where, params = file_filters(
        q=q,
        category=category,
        tag=tag,
        duplicates=duplicates,
        delete_queue=delete_queue,
    )

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) AS count FROM files f {where}", params)
    total = int(cur.fetchone()["count"])
    cur.execute(
        f"""
        SELECT
            f.id, f.path, f.rel_path, f.name, f.ext, f.category, f.size_bytes,
            f.modified_ts, f.indexed_ts, f.summary, f.preview_path, f.thumb_path,
            f.deleted_candidate, f.sha256,
            GROUP_CONCAT(t.name, ', ') AS tags
        FROM files f
        LEFT JOIN file_tags ft ON ft.file_id = f.id
        LEFT JOIN tags t ON t.id = ft.tag_id
        {where}
        GROUP BY f.id
        ORDER BY {order_by}
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    )
    rows = []
    for row in cur.fetchall():
        item = dict(row)
        item["display_path"] = humanish_path(item["path"])
        item["tags"] = [tag.strip() for tag in (item["tags"] or "").split(",") if tag.strip()]
        rows.append(item)
    conn.close()
    return {"files": rows, "total": total, "limit": limit, "offset": offset}


def duplicate_groups(limit: int = 30, offset: int = 0) -> dict:
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) AS count
        FROM (
            SELECT sha256 FROM files
            WHERE sha256 IS NOT NULL AND sha256 != ''
              AND COALESCE(deleted_candidate, 0) = 0
            GROUP BY sha256
            HAVING COUNT(*) > 1
        )
        """
    )
    total = int(cur.fetchone()["count"])
    cur.execute(
        """
        SELECT sha256, COUNT(*) AS count, MAX(size_bytes) AS size_bytes,
               COALESCE(SUM(size_bytes), 0) AS total_bytes
        FROM files
        WHERE sha256 IS NOT NULL AND sha256 != ''
          AND COALESCE(deleted_candidate, 0) = 0
        GROUP BY sha256
        HAVING COUNT(*) > 1
        ORDER BY total_bytes DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    )
    groups = []
    for group in cur.fetchall():
        group_dict = dict(group)
        cur.execute(
            """
            SELECT id, path, rel_path, name, category, size_bytes, modified_ts,
                   indexed_ts, summary, preview_path, thumb_path, deleted_candidate
            FROM files
            WHERE sha256 = ?
              AND COALESCE(deleted_candidate, 0) = 0
            ORDER BY modified_ts DESC
            """,
            (group_dict["sha256"],),
        )
        files = []
        for row in cur.fetchall():
            item = dict(row)
            item["display_path"] = humanish_path(item["path"])
            files.append(item)
        group_dict["files"] = files
        group_dict["reclaimable_bytes"] = int(group_dict["size_bytes"] or 0) * (int(group_dict["count"]) - 1)
        groups.append(group_dict)
    conn.close()
    return {"groups": groups, "total": total, "limit": limit, "offset": offset}


def record_index_failure(path: str, error: str) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO index_failures (path, error, created_ts, resolved) VALUES (?, ?, ?, 0)",
        (path, error[:4000], time.time()),
    )
    conn.commit()
    conn.close()


def mark_index_success(path: str) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE index_failures SET resolved = 1 WHERE path = ? AND resolved = 0", (path,))
    conn.commit()
    conn.close()


def recent_index_failures(limit: int = 40) -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, path, error, created_ts, resolved
        FROM index_failures
        WHERE resolved = 0
        ORDER BY created_ts DESC
        LIMIT ?
        """,
        (max(1, min(int(limit), 200)),),
    )
    rows = []
    for row in cur.fetchall():
        item = dict(row)
        item["display_path"] = humanish_path(item["path"])
        rows.append(item)
    conn.close()
    return rows
