from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from app.admin_controls import host_stats
from app.autotagging import apply_auto_tags
from app.chat_engine import archive_embedding_ids, delete_embeddings, sync_file_embedding_by_id
from app.config import DATA_DIR
from app.db import get_conn
from app.extractors import PLAIN_TEXT_EXTS, PLAIN_TEXT_NAMES, supports_text_extraction
from app.face_tools import GENERATED_FACE_SOURCES, scan_file_faces
from app.indexer import index_file, walk_archive
from app.maintenance import index_failure_triage, mark_index_success, record_index_failure
from app.media_tools import (
    TRANSCRIPT_SOURCE,
    analyze_video,
    ffmpeg_status,
    transcribe_video,
    transcription_status,
)
from app.source_safety import (
    CHAT_AWARE_MAX_FILE_BYTES,
    CHAT_IGNORED_PARTS,
    is_chat_aware_content_path,
    is_chat_aware_embedding_candidate,
    is_chat_aware_text_content_path,
    is_chat_safe_source,
)
from app.vision_tools import VISUAL_ANALYSIS_START, VISION_TAG_SOURCE, analyze_image_file, vision_status


ENRICHMENT_SOURCE = "deep_enrichment"
ENRICHMENT_TASK_VERSION = 1
DEEP_ENRICHMENT_STATE_PATH = DATA_DIR / "deep_enrichment_state.json"
ENRICHMENT_SNAPSHOT_DIR = DATA_DIR / "enrichment_snapshots"
ACTIVE_FILE_WHERE = "COALESCE(f.deleted_candidate, 0) = 0 AND (f.duplicate_of IS NULL OR f.duplicate_of = '')"
DOCUMENT_CATEGORIES = {"document", "knowledgebase", "code"}
VISUAL_TASKS = ("image_faces", "image_objects")
VIDEO_TASKS = ("video_storyboard", "video_faces", "video_objects", "video_transcript")
LANE_ORDER = [
    "document_ocr",
    "gmail_import",
    "embedding_sync",
    "image_faces",
    "image_objects",
    "video_storyboard",
    "video_transcript",
    "video_faces",
    "video_objects",
    "index_refresh",
]
LANE_DEFAULT_CHUNK_SIZE = {
    "index_refresh": 500,
    "document_ocr": 500,
    "gmail_import": 500,
    "embedding_sync": 500,
    "image_faces": 500,
    "image_objects": 50,
    "video_storyboard": 10,
    "video_transcript": 10,
    "video_faces": 10,
    "video_objects": 10,
}
VISION_BULK_CHUNK_SIZE = 500
LANE_TASKS = {
    "index_refresh": ("index_refresh",),
    "document_ocr": ("ocr",),
    "gmail_import": ("gmail_import",),
    "embedding_sync": ("embedding",),
    "image_faces": ("image_faces",),
    "image_objects": ("image_objects",),
    "video_storyboard": ("video_storyboard",),
    "video_transcript": ("video_transcript",),
    "video_faces": ("video_faces",),
    "video_objects": ("video_objects",),
}
LANE_LABELS = {
    "index_refresh": "Index refresh",
    "document_ocr": "Document text/OCR",
    "gmail_import": "Gmail import",
    "embedding_sync": "Embedding sync",
    "image_faces": "Image face scan",
    "image_objects": "Image object tags",
    "video_storyboard": "Video storyboard/probe",
    "video_transcript": "Video transcript/subtitles",
    "video_faces": "Video face scan",
    "video_objects": "Video object tags",
}
LANE_PURPOSES = {
    "index_refresh": "keeps file metadata current",
    "document_ocr": "extracts readable text from documents and knowledgebase files",
    "gmail_import": "indexes Gmail metadata first, with body pulls available on demand",
    "embedding_sync": "adds chat-safe files to semantic search",
    "image_faces": "finds faces in still images for identity review",
    "image_objects": "adds visual object tags to still images",
    "video_storyboard": "creates video probe/storyboard context",
    "video_transcript": "extracts subtitles or speech transcripts from videos",
    "video_faces": "finds faces in video frames for identity review",
    "video_objects": "adds visual object tags to video context",
}
TERMINAL_ENRICHMENT_STATUSES = {"completed", "skipped", "deferred"}
RETRYABLE_ENRICHMENT_STATUSES = {"failed", "failed_retryable"}
RESUMABLE_RUN_STATUSES = {"queued", "running", "pausing", "paused"}
RESUMABLE_CHUNK_STATUSES = {"pending", "running", "paused"}
PENDING_ITEM_STATUSES = {"pending", "running", "failed_retryable"}
HOST_PRESSURE_LANES = {"image_objects", "video_objects", "video_transcript"}
HOST_PRESSURE_POLL_SECONDS = 15
HOST_PRESSURE_MAX_WAIT_SECONDS = 10 * 60
SUPPORTED_IMAGE_ENRICHMENT_EXTS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
}
NON_RETRYABLE_IMAGE_ERROR_MARKERS = (
    "unsupported image format",
    "selected path does not look like an image",
    "unknown format",
    "unknown marker",
    "invalid jpeg",
    "unsupported jpeg feature",
    "short huffman data",
    "image file is truncated",
    "cannot identify image file",
    "missing 0xff00 sequence",
)
CHAT_IGNORED_PATH_SQL = " AND ".join(
    f"LOWER(REPLACE(f.path, CHAR(92), '/')) NOT LIKE '%/{part}/%'"
    for part in sorted(CHAT_IGNORED_PARTS)
)
CODE_TEXT_EXT_SQL = ", ".join(f"'{ext}'" for ext in sorted(PLAIN_TEXT_EXTS))
CODE_TEXT_NAME_SQL = ", ".join(f"'{name}'" for name in sorted(PLAIN_TEXT_NAMES))
CODE_OCR_WHERE = f"""
f.category = 'code'
AND ({CHAT_IGNORED_PATH_SQL})
AND COALESCE(f.size_bytes, 0) <= {CHAT_AWARE_MAX_FILE_BYTES}
AND (
    LOWER(COALESCE(f.ext, '')) IN ({CODE_TEXT_EXT_SQL})
    OR LOWER(COALESCE(f.name, '')) IN ({CODE_TEXT_NAME_SQL})
    OR LOWER(COALESCE(f.mime_type, '')) LIKE 'text/%'
)
"""
DOCUMENT_OCR_WHERE = f"""
(
    (f.category IN ('document', 'knowledgebase') AND COALESCE(f.size_bytes, 0) <= {CHAT_AWARE_MAX_FILE_BYTES})
    OR ({CODE_OCR_WHERE})
)
"""


deep_enrichment_job_lock = threading.Lock()
deep_enrichment_thread_lock = threading.Lock()
deep_enrichment_stop_requested = threading.Event()
deep_enrichment_job = {
    "running": False,
    "done": False,
    "stop_requested": False,
    "started_ts": None,
    "finished_ts": None,
    "phase": "",
    "total": 0,
    "processed": 0,
    "succeeded": 0,
    "failed": 0,
    "skipped": 0,
    "deferred": 0,
    "retryable_failed": 0,
    "current_path": "",
    "run_id": None,
    "chunk_id": None,
    "lane": "",
    "last_snapshot_path": "",
    "last_error": "",
    "throttle_active": False,
    "throttle_reason": "",
    "options": {},
}


def _load_deep_enrichment_state() -> dict:
    if not DEEP_ENRICHMENT_STATE_PATH.exists():
        return {}
    try:
        loaded = json.loads(DEEP_ENRICHMENT_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _save_deep_enrichment_state(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DEEP_ENRICHMENT_STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def gmail_import_enabled() -> bool:
    return bool(_load_deep_enrichment_state().get("gmail_import_enabled", True))


def set_gmail_import_enabled(enabled: bool) -> bool:
    state = _load_deep_enrichment_state()
    state["gmail_import_enabled"] = bool(enabled)
    _save_deep_enrichment_state(state)
    return bool(enabled)


def _active_file_count() -> int:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) AS count FROM files f WHERE {ACTIVE_FILE_WHERE}")
        count = int(cur.fetchone()["count"] or 0)
        conn.close()
        return count
    except Exception:
        return 0


def deep_enrichment_baseline_state() -> dict:
    state = _load_deep_enrichment_state()
    baseline_ts = state.get("baseline_completed_ts")
    active_count = _active_file_count()
    state["active_file_count"] = active_count
    state["baseline_complete"] = bool(baseline_ts and active_count > 0)
    state["next_mode"] = "incremental" if baseline_ts else "baseline"
    if not state["baseline_complete"]:
        state["next_mode"] = "baseline"
    state["task_version"] = ENRICHMENT_TASK_VERSION
    return state


def _job_snapshot() -> dict:
    with deep_enrichment_job_lock:
        return dict(deep_enrichment_job)


def _update_job(**fields) -> None:
    with deep_enrichment_job_lock:
        deep_enrichment_job.update(fields)


def _bump_job(field: str, amount: int = 1) -> None:
    with deep_enrichment_job_lock:
        deep_enrichment_job[field] = int(deep_enrichment_job.get(field) or 0) + amount


def _job_elapsed_seconds(job: dict) -> int | None:
    try:
        started = float(job.get("started_ts") or 0)
        finished = float(job.get("finished_ts") or 0) if job.get("finished_ts") else _now()
    except (TypeError, ValueError):
        return None
    if started <= 0:
        return None
    return max(0, int(round(finished - started)))


def _job_eta_seconds(job: dict) -> int | None:
    if not job.get("running"):
        return None
    try:
        started = float(job.get("started_ts") or 0)
        processed = float(job.get("processed") or 0)
        total = float(job.get("total") or 0)
    except (TypeError, ValueError):
        return None
    if started <= 0 or processed <= 0 or total <= 0 or processed >= total:
        return None
    elapsed = max(0.0, _now() - started)
    if elapsed <= 0:
        return None
    rate = processed / elapsed
    if rate <= 0:
        return None
    return max(0, int(round((total - processed) / rate)))


def _job_with_timing(job: dict) -> dict:
    return {
        **job,
        "elapsed_seconds": _job_elapsed_seconds(job),
        "eta_seconds": _job_eta_seconds(job),
    }


def reset_deep_enrichment_job_state(options: dict | None = None) -> None:
    deep_enrichment_stop_requested.clear()
    _update_job(
        running=False,
        done=False,
        stop_requested=False,
        started_ts=None,
        finished_ts=None,
        phase="",
        total=0,
        processed=0,
        succeeded=0,
        failed=0,
        skipped=0,
        deferred=0,
        retryable_failed=0,
        current_path="",
        run_id=None,
        chunk_id=None,
        lane="",
        last_snapshot_path="",
        last_error="",
        throttle_active=False,
        throttle_reason="",
        options=options or {},
    )


def mark_enrichment(file_id: int | None, task: str, status: str, detail: dict | None = None, *, source: str = ENRICHMENT_SOURCE) -> None:
    if not file_id:
        return
    payload = json.dumps(detail or {}, ensure_ascii=True, default=str)[:20000]
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO file_enrichment (file_id, task, status, source, detail_json, updated_ts)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_id, task) DO UPDATE SET
            status=excluded.status,
            source=excluded.source,
            detail_json=excluded.detail_json,
            updated_ts=excluded.updated_ts
        """,
        (int(file_id), task, status, source, payload, time.time()),
    )
    conn.commit()
    conn.close()


def reconcile_existing_file_embeddings() -> dict:
    embedded_paths = archive_embedding_ids()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT f.*, fe.status AS embedding_status
        FROM files f
        LEFT JOIN file_enrichment fe
          ON fe.file_id = f.id AND fe.task = 'embedding'
        WHERE {ACTIVE_FILE_WHERE}
        """
    )
    rows = [dict(row) for row in cur.fetchall()]
    active_paths = {
        str(row.get("path") or "")
        for row in rows
        if row.get("path") and is_chat_aware_embedding_candidate(
            row.get("path") or "",
            category=row.get("category") or "",
            size_bytes=row.get("size_bytes"),
        )
    }
    now = time.time()
    updates = []
    for row in rows:
        path = str(row.get("path") or "")
        if path not in embedded_paths or row.get("embedding_status") == "completed":
            continue
        detail = _detail_with_fingerprint(row, {"mode": "existing_vector_reconciliation", "path": path})
        updates.append((int(row["id"]), "embedding", "completed", "existing_vector_reconciliation", json.dumps(detail, ensure_ascii=True), now))
    if updates:
        cur.executemany(
            """
            INSERT INTO file_enrichment (file_id, task, status, source, detail_json, updated_ts)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_id, task) DO UPDATE SET
                status=excluded.status,
                source=excluded.source,
                detail_json=excluded.detail_json,
                updated_ts=excluded.updated_ts
            """,
            updates,
        )
        conn.commit()
    conn.close()
    stale_paths = sorted(embedded_paths - active_paths)
    deleted = delete_embeddings(stale_paths)
    return {
        "vectors": len(embedded_paths),
        "active_vectors": len(embedded_paths & active_paths),
        "ledger_rows_reconciled": len(updates),
        "stale_vectors": len(stale_paths),
        "stale_vector_cleanup": deleted,
    }


def _row_fingerprint(row: dict) -> dict:
    return {
        "sha256": row.get("sha256") or "",
        "size_bytes": int(row.get("size_bytes") or 0),
        "modified_ts": float(row.get("modified_ts") or 0),
        "task_version": ENRICHMENT_TASK_VERSION,
    }


def _detail_with_fingerprint(row: dict, detail: dict | None = None) -> dict:
    payload = dict(detail or {})
    payload["file_fingerprint"] = _row_fingerprint(row)
    return payload


def _has_usable_extracted_text(row: dict) -> bool:
    text = str(row.get("extracted_text") or "").strip()
    lowered = text.lower()
    return bool(text) and "extraction error" not in lowered and "ocr extraction error" not in lowered


def _document_ocr_candidate(row: dict) -> bool:
    path = Path(row.get("path") or "")
    if not is_chat_aware_text_content_path(path, size_bytes=row.get("size_bytes")):
        return False
    return row.get("category") != "code" or supports_text_extraction(path)


def _enrichment_record(file_id: int, task: str) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT status, detail_json, updated_ts
        FROM file_enrichment
        WHERE file_id = ? AND task = ?
        """,
        (int(file_id), task),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def _fingerprint_matches(row: dict, detail: dict) -> bool:
    fingerprint = detail.get("file_fingerprint") if isinstance(detail, dict) else None
    if not isinstance(fingerprint, dict):
        return False
    current = _row_fingerprint(row)
    if int(fingerprint.get("task_version") or 0) != ENRICHMENT_TASK_VERSION:
        return False
    old_hash = fingerprint.get("sha256") or ""
    if old_hash and current["sha256"]:
        return old_hash == current["sha256"]
    try:
        old_size = int(fingerprint.get("size_bytes") or -1)
        old_modified = float(fingerprint.get("modified_ts") or -1)
    except (TypeError, ValueError):
        return False
    return old_size == current["size_bytes"] and abs(old_modified - current["modified_ts"]) < 0.0001


def _task_is_current(row: dict, task: str) -> bool:
    file_id = row.get("id")
    if not file_id:
        return False
    record = _enrichment_record(int(file_id), task)
    if not record or record.get("status") not in {"completed", "skipped", "deferred"}:
        return False
    if task == "ocr" and record.get("status") == "completed" and not _has_usable_extracted_text(row):
        return False
    try:
        detail = json.loads(record.get("detail_json") or "{}")
    except json.JSONDecodeError:
        return False
    return _fingerprint_matches(row, detail)


def _task_needs_run(row: dict, task: str, *, force: bool = False, retry_failed: bool = False, retry_deferred: bool = False) -> bool:
    if force:
        return True
    file_id = row.get("id")
    if not file_id:
        return False
    record = _enrichment_record(int(file_id), task)
    if not record:
        return True
    try:
        detail = json.loads(record.get("detail_json") or "{}")
    except json.JSONDecodeError:
        return True
    if not _fingerprint_matches(row, detail):
        return True
    status = record.get("status")
    if task == "ocr" and status == "completed" and not _has_usable_extracted_text(row):
        return True
    if status in {"completed", "skipped"}:
        return False
    if status == "deferred" and not retry_deferred:
        return False
    if status in {"failed", "failed_retryable"} and not retry_failed:
        return False
    return True


def _row_needs_any_task(
    row: dict,
    tasks: tuple[str, ...] | list[str],
    *,
    force: bool = False,
    retry_failed: bool = False,
    retry_deferred: bool = False,
) -> bool:
    return any(_task_needs_run(row, task, force=force, retry_failed=retry_failed, retry_deferred=retry_deferred) for task in tasks)


def _active_rows(categories: set[str] | None = None, limit: int | None = None) -> list[dict]:
    params: list = []
    category_clause = ""
    if categories:
        placeholders = ",".join("?" for _ in categories)
        category_clause = f" AND f.category IN ({placeholders})"
        params.extend(sorted(categories))
    sql = f"""
        SELECT f.*
        FROM files f
        WHERE {ACTIVE_FILE_WHERE}
          {category_clause}
        ORDER BY f.indexed_ts DESC, f.id DESC
    """
    if limit:
        sql += " LIMIT ?"
        params.append(max(1, int(limit)))
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


def _count_total(where: str, params: list | None = None) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) AS count FROM files f WHERE {ACTIVE_FILE_WHERE} AND {where}", params or [])
    count = int(cur.fetchone()["count"] or 0)
    conn.close()
    return count


def _count_completed(where: str, task: str, evidence_sql: str = "0", params: list | None = None) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM files f
        WHERE {ACTIVE_FILE_WHERE}
          AND {where}
          AND (
            EXISTS (
                SELECT 1 FROM file_enrichment fe
                WHERE fe.file_id = f.id
                  AND fe.task = ?
                  AND fe.status IN ('completed', 'skipped')
            )
            OR ({evidence_sql})
          )
        """,
        [*(params or []), task],
    )
    count = int(cur.fetchone()["count"] or 0)
    conn.close()
    return count


def _count_failed(task: str, where: str, params: list | None = None) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT COUNT(DISTINCT f.id) AS count
        FROM files f
        JOIN file_enrichment fe ON fe.file_id = f.id
        WHERE {ACTIVE_FILE_WHERE}
          AND {where}
          AND fe.task = ?
          AND fe.status = 'failed'
        """,
        [*(params or []), task],
    )
    count = int(cur.fetchone()["count"] or 0)
    conn.close()
    return count


def _parse_detail_json(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {"message": str(raw)}
    return loaded if isinstance(loaded, dict) else {"message": str(loaded)}


def _detail_reason(detail: dict, fallback: str) -> str:
    for key in ("message", "error", "reason", "deferred_reason", "hint", "mode"):
        value = detail.get(key)
        if value:
            return str(value)
    sync = detail.get("sync")
    if isinstance(sync, dict):
        for key in ("reason", "mode", "error"):
            value = sync.get(key)
            if value:
                return str(value)
    return fallback


def _coverage_sample(row: dict, *, status: str | None = None) -> dict:
    path = str(row.get("path") or "")
    label = row.get("name") or (Path(path).name if path else "") or "Archive item"
    sample_status = status or row.get("status") or "missing"
    detail = _parse_detail_json(row.get("detail_json"))
    fallback = "No enrichment record has been written for this lane yet." if sample_status == "missing" else "No failure detail was recorded."
    return {
        "label": label,
        "path": path,
        "status": sample_status,
        "detail": _detail_reason(detail, fallback),
    }


def _coverage_samples(
    task: str,
    where: str,
    evidence_sql: str = "0",
    params: list | None = None,
    limit: int = 3,
    status_counts_as_complete: bool = True,
) -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT f.path, f.name, f.category, f.size_bytes, fe.status, fe.detail_json, fe.updated_ts
        FROM files f
        JOIN file_enrichment fe
          ON fe.file_id = f.id AND fe.task = ?
        WHERE {ACTIVE_FILE_WHERE}
          AND {where}
          AND fe.status IN ('deferred', 'failed', 'failed_retryable')
        ORDER BY fe.updated_ts DESC, f.indexed_ts DESC, f.id DESC
        LIMIT ?
        """,
        [task, *(params or []), max(1, int(limit))],
    )
    samples = [_coverage_sample(dict(row)) for row in cur.fetchall()]
    remaining = max(0, int(limit) - len(samples))
    if remaining:
        completion_sql = f"({evidence_sql}) OR fe.status = 'completed'" if status_counts_as_complete else f"({evidence_sql})"
        cur.execute(
            f"""
            SELECT f.path, f.name, 'missing' AS status, '' AS detail_json, f.indexed_ts
            FROM files f
            LEFT JOIN file_enrichment fe
              ON fe.file_id = f.id AND fe.task = ?
            WHERE {ACTIVE_FILE_WHERE}
              AND {where}
              AND NOT ({completion_sql})
              AND (fe.status IS NULL OR fe.status NOT IN ('skipped', 'deferred', 'failed', 'failed_retryable'))
            ORDER BY f.indexed_ts DESC, f.id DESC
            LIMIT ?
            """,
            [task, *(params or []), remaining],
        )
        samples.extend(_coverage_sample(dict(row), status="missing") for row in cur.fetchall())
    conn.close()
    return samples


def _embedding_coverage_samples(limit: int = 3) -> list[dict]:
    embedded_paths = archive_embedding_ids()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT f.path, f.name, fe.status, fe.detail_json, fe.updated_ts
        FROM files f
        JOIN file_enrichment fe
          ON fe.file_id = f.id AND fe.task = 'embedding'
        WHERE {ACTIVE_FILE_WHERE}
          AND fe.status IN ('deferred', 'failed', 'failed_retryable')
        ORDER BY fe.updated_ts DESC, f.indexed_ts DESC, f.id DESC
        LIMIT 25
        """
    )
    samples = []
    for row in cur.fetchall():
        item = dict(row)
        if item.get("path") not in embedded_paths and is_chat_safe_source(item.get("path") or "") and is_chat_aware_embedding_candidate(item.get("path") or "", category=item.get("category") or "", size_bytes=item.get("size_bytes")):
            samples.append(_coverage_sample(item))
        if len(samples) >= limit:
            break
    remaining = max(0, int(limit) - len(samples))
    if remaining:
        cur.execute(
            f"""
            SELECT f.path, f.name, f.category, f.size_bytes, 'missing' AS status, '' AS detail_json, f.indexed_ts
            FROM files f
            LEFT JOIN file_enrichment fe
              ON fe.file_id = f.id AND fe.task = 'embedding'
            WHERE {ACTIVE_FILE_WHERE}
              AND (fe.status IS NULL OR fe.status NOT IN ('completed', 'skipped', 'deferred', 'failed', 'failed_retryable'))
            ORDER BY f.indexed_ts DESC, f.id DESC
            LIMIT 100
            """
        )
        for row in cur.fetchall():
            item = dict(row)
            if item.get("path") not in embedded_paths and is_chat_safe_source(item.get("path") or "") and is_chat_aware_embedding_candidate(item.get("path") or "", category=item.get("category") or "", size_bytes=item.get("size_bytes")):
                samples.append(_coverage_sample(item, status="missing"))
            if len(samples) >= limit:
                break
    conn.close()
    return samples


def _dependency_issue_for_lane(lane: str, dependencies: dict) -> str:
    ffmpeg = dependencies.get("ffmpeg") or {}
    vision = dependencies.get("vision") or {}
    transcription = dependencies.get("transcription") or {}
    if lane in {"image_objects", "video_objects"} and not vision.get("ready"):
        return str(vision.get("hint") or "Vision model is not ready.")
    if lane.startswith("video_") and not ffmpeg.get("ready"):
        return str(ffmpeg.get("hint") or "FFmpeg is not ready.")
    if lane == "video_transcript" and not transcription.get("ready"):
        return str(transcription.get("hint") or "Speech transcription is not installed; embedded subtitles can still be extracted.")
    return ""


def _lane_action_options(lane: str, item: dict, *, retry: bool = False) -> dict:
    options = {
        "lane": lane,
        "max_runtime_minutes": 5,
        "chunk_size": LANE_DEFAULT_CHUNK_SIZE.get(lane, 50),
    }
    if retry:
        options["retry_failed"] = True
        options["retry_deferred"] = True
    elif int(item.get("failed_retryable") or 0) > 0:
        options["retry_failed"] = True
    return options


def _lane_coverage_explanation(lane: str, item: dict, dependencies: dict) -> dict:
    label = item.get("label") or LANE_LABELS.get(lane, lane.replace("_", " ").title())
    total = int(item.get("total") or 0)
    missing = int(item.get("missing") or 0)
    deferred = int(item.get("deferred") or 0)
    retryable = int(item.get("failed_retryable") if item.get("failed_retryable") is not None else item.get("failed") or 0)
    terminal = int(item.get("terminal") if item.get("terminal") is not None else item.get("completed") or 0)
    purpose = LANE_PURPOSES.get(lane, "keeps archive coverage current")
    blocked = _dependency_issue_for_lane(lane, dependencies)
    issue_count = missing + deferred + retryable
    samples = item.get("samples") or []
    if blocked and (issue_count or lane == "video_transcript"):
        state = "blocked"
        summary = f"The {label} lane is blocked: {blocked}"
        next_step = "Resolve the dependency, then run a bounded lane chunk."
        action = {"label": "Open lane", "action": "enrichment_start", "options": _lane_action_options(lane, item)}
    elif retryable:
        state = "retryable"
        summary = f"The {label} lane has {retryable:,} retryable item(s) parked from earlier attempts."
        next_step = "Use Retry when you want those parked failures included in the next bounded chunk."
        action = {"label": "Retry", "action": "enrichment_start", "options": _lane_action_options(lane, item, retry=True)}
    elif deferred:
        state = "deferred"
        summary = f"The {label} lane has {deferred:,} deferred item(s) quarantined from normal care runs."
        next_step = "Use Retry to opt deferred rows back into processing."
        action = {"label": "Retry", "action": "enrichment_start", "options": _lane_action_options(lane, item, retry=True)}
    elif missing:
        state = "missing"
        summary = f"The {label} lane still has {missing:,} unprocessed item(s); it {purpose}."
        next_step = "Run processes the next bounded chunk for this lane."
        action = {"label": "Run", "action": "enrichment_start", "options": _lane_action_options(lane, item)}
    elif total:
        state = "ready"
        summary = f"The {label} lane has no actionable gaps; {terminal:,} / {total:,} checks are terminal."
        next_step = "No repair action is needed for this lane."
        action = None
    else:
        state = "empty"
        summary = f"The {label} lane has no matching archive items yet."
        next_step = "Add matching data or refresh the archive index."
        action = None
    return {
        "state": state,
        "summary": summary,
        "next_step": next_step,
        "blocked_reason": blocked,
        "samples": samples[:3],
        "action": action,
    }


def _coverage_item(
    label: str,
    task: str,
    where: str,
    evidence_sql: str = "0",
    params: list | None = None,
    *,
    status_counts_as_complete: bool = True,
) -> dict:
    completion_sql = f"({evidence_sql}) OR fe.status = 'completed'" if status_counts_as_complete else f"({evidence_sql})"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN {completion_sql} THEN 1 ELSE 0 END) AS completed,
          SUM(CASE WHEN NOT ({completion_sql}) AND fe.status = 'skipped' THEN 1 ELSE 0 END) AS skipped,
          SUM(CASE WHEN NOT ({completion_sql}) AND fe.status = 'deferred' THEN 1 ELSE 0 END) AS deferred,
          SUM(CASE WHEN NOT ({completion_sql}) AND fe.status IN ('failed', 'failed_retryable') THEN 1 ELSE 0 END) AS failed_retryable
        FROM files f
        LEFT JOIN file_enrichment fe
          ON fe.file_id = f.id AND fe.task = ?
        WHERE {ACTIVE_FILE_WHERE}
          AND {where}
        """,
        [task, *(params or [])],
    )
    row = cur.fetchone()
    conn.close()
    total = int(row["total"] or 0) if row else 0
    completed = int(row["completed"] or 0) if row else 0
    skipped = int(row["skipped"] or 0) if row else 0
    deferred = int(row["deferred"] or 0) if row else 0
    failed_retryable = int(row["failed_retryable"] or 0) if row else 0
    terminal = completed + skipped + deferred
    missing = max(total - terminal - failed_retryable, 0)
    return {
        "label": label,
        "task": task,
        "total": total,
        "completed": completed,
        "skipped": skipped,
        "deferred": deferred,
        "failed_retryable": failed_retryable,
        "missing": missing,
        "terminal": terminal,
        "failed": failed_retryable,
        "progress_percent": round((terminal / total) * 100, 1) if total else None,
        "samples": _coverage_samples(task, where, evidence_sql, params, status_counts_as_complete=status_counts_as_complete),
    }


def _embedding_coverage_item() -> dict:
    embedded_paths = archive_embedding_ids()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT f.id, f.path, f.category, f.size_bytes, fe.status
        FROM files f
        LEFT JOIN file_enrichment fe
          ON fe.file_id = f.id AND fe.task = 'embedding'
        WHERE {ACTIVE_FILE_WHERE}
        """
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    completed = skipped = deferred = failed_retryable = missing = 0
    total = 0
    for row in rows:
        if not is_chat_safe_source(row.get("path") or "") or not is_chat_aware_embedding_candidate(row.get("path") or "", category=row.get("category") or "", size_bytes=row.get("size_bytes")):
            continue
        total += 1
        status = row.get("status")
        if status == "completed" or row.get("path") in embedded_paths:
            completed += 1
        elif status == "skipped":
            skipped += 1
        elif status == "deferred":
            deferred += 1
        elif status in RETRYABLE_ENRICHMENT_STATUSES:
            failed_retryable += 1
        else:
            missing += 1
    terminal = completed + skipped + deferred
    return {
        "label": LANE_LABELS["embedding_sync"],
        "task": "embedding",
        "total": total,
        "completed": completed,
        "skipped": skipped,
        "deferred": deferred,
        "failed_retryable": failed_retryable,
        "missing": missing,
        "terminal": terminal,
        "failed": failed_retryable,
        "progress_percent": round((terminal / total) * 100, 1) if total else None,
        "samples": _embedding_coverage_samples(),
    }


def _gmail_coverage_item() -> dict:
    enabled = gmail_import_enabled()
    try:
        from app.cloud_sync import cloud_sync_status

        status = cloud_sync_status()
        account = (status.get("accounts") or {}).get("google") or {}
        gmail = account.get("gmail") or {}
        job = status.get("gmail_import_job") or {}
        ready = bool(account.get("gmail_ready"))
        imported = int(gmail.get("imported_count") or job.get("imported_count") or 0)
        failed = int(gmail.get("failed_count") or job.get("failed_count") or 0)
        running = bool(job.get("running"))
        gmail_state = (_load_deep_enrichment_state().get("gmail_import") or {})
        completed_ts = gmail_state.get("completed_ts")
        total = int(gmail.get("total_estimate") or job.get("total_estimate") or imported or 1)
        completed = imported if imported else (0 if ready else 0)
        if completed_ts:
            total = max(total, completed, 1)
            completed = max(completed, total - failed)
        missing = max(total - completed - failed, 0) if ready and not completed_ts else 0
        deferred = 0 if ready else 1
        summary = gmail.get("summary") or ("Gmail is ready to import." if ready else "Google OAuth is not connected for Gmail import.")
    except Exception as error:
        ready = False
        running = False
        imported = 0
        failed = 0
        total = 1
        completed = 0
        missing = 0
        deferred = 1
        summary = str(error)
    if not enabled:
        summary = "Gmail import is intentionally deferred while local archive ingestion finishes."
    terminal = completed + deferred
    return {
        "label": LANE_LABELS["gmail_import"],
        "task": "gmail_import",
        "total": total,
        "completed": completed,
        "skipped": 0,
        "deferred": deferred,
        "failed_retryable": failed,
        "missing": missing,
        "terminal": terminal,
        "failed": failed,
        "progress_percent": round((terminal / total) * 100, 1) if total else None,
        "ready": ready,
        "enabled": enabled,
        "running": running,
        "summary": summary,
    }


def _index_refresh_coverage_item() -> dict:
    total = _active_file_count()
    return {
        "label": LANE_LABELS["index_refresh"],
        "task": "index_refresh",
        "total": total,
        "completed": total,
        "skipped": 0,
        "deferred": 0,
        "failed_retryable": 0,
        "missing": 0,
        "terminal": total,
        "failed": 0,
        "progress_percent": 100.0 if total else None,
    }


def deep_enrichment_coverage_report() -> dict:
    doc_where = DOCUMENT_OCR_WHERE
    image_where = "f.category = 'image'"
    video_where = "f.category = 'video'"
    generated_sources = ",".join("'" + source.replace("'", "''") + "'" for source in sorted(GENERATED_FACE_SOURCES))
    document_ocr = _coverage_item(
        "Document text/OCR",
        "ocr",
        doc_where,
        """
        LENGTH(TRIM(COALESCE(f.extracted_text, ''))) > 0
        AND LOWER(COALESCE(f.extracted_text, '')) NOT LIKE '%extraction error%'
        AND LOWER(COALESCE(f.extracted_text, '')) NOT LIKE '%ocr extraction error%'
        """,
        status_counts_as_complete=False,
    )
    image_objects = _coverage_item(
        "Image object tags",
        "image_objects",
        image_where,
        f"""
        COALESCE(f.extracted_text, '') LIKE '%{VISUAL_ANALYSIS_START}%'
        OR EXISTS (
            SELECT 1 FROM file_tags ft
            WHERE ft.file_id = f.id AND ft.source = '{VISION_TAG_SOURCE}'
        )
        """,
    )
    image_faces = _coverage_item(
        "Image face scan",
        "image_faces",
        image_where,
        f"""
        EXISTS (
            SELECT 1 FROM face_observations fo
            WHERE fo.file_id = f.id
              AND fo.media_type = 'image'
              AND fo.source IN ({generated_sources})
        )
        """,
    )
    video_storyboard = _coverage_item(
        "Video storyboard/probe",
        "video_storyboard",
        video_where,
        """
        EXISTS (
            SELECT 1 FROM media_segments ms
            WHERE ms.file_id = f.id AND ms.source = 'ffmpeg_storyboard'
        )
        """,
    )
    video_transcript = _coverage_item(
        "Video transcript/subtitles",
        "video_transcript",
        video_where,
        f"""
        EXISTS (
            SELECT 1 FROM media_segments ms
            WHERE ms.file_id = f.id AND ms.source IN ('{TRANSCRIPT_SOURCE}', 'ffmpeg_subtitle')
        )
        """,
    )
    video_objects = _coverage_item(
        "Video object tags",
        "video_objects",
        video_where,
        f"""
        EXISTS (
            SELECT 1 FROM file_tags ft
            WHERE ft.file_id = f.id AND ft.source = '{VISION_TAG_SOURCE}'
        )
        OR EXISTS (
            SELECT 1 FROM media_segments ms
            WHERE ms.file_id = f.id AND COALESCE(ms.tags_json, '') LIKE '%vision%'
        )
        """,
    )
    video_faces = _coverage_item(
        "Video face scan",
        "video_faces",
        video_where,
        f"""
        EXISTS (
            SELECT 1 FROM face_observations fo
            WHERE fo.file_id = f.id
              AND fo.media_type = 'video'
              AND fo.source IN ({generated_sources})
        )
        """,
    )
    embedding = _embedding_coverage_item()
    gmail = _gmail_coverage_item()
    index_refresh = _index_refresh_coverage_item()
    lanes = {
        "index_refresh": index_refresh,
        "document_ocr": document_ocr,
        "gmail_import": gmail,
        "embedding_sync": embedding,
        "image_faces": image_faces,
        "image_objects": image_objects,
        "video_storyboard": video_storyboard,
        "video_transcript": video_transcript,
        "video_faces": video_faces,
        "video_objects": video_objects,
    }
    dependencies = {
        "ffmpeg": ffmpeg_status(),
        "transcription": transcription_status(),
        "vision": vision_status(),
    }
    for lane, item in lanes.items():
        item["explanation"] = _lane_coverage_explanation(lane, item, dependencies)
    return {
        "documents": {
            "ocr": document_ocr,
        },
        "images": {
            "objects": image_objects,
            "faces": image_faces,
        },
        "videos": {
            "storyboard": video_storyboard,
            "transcript": video_transcript,
            "objects": video_objects,
            "faces": video_faces,
        },
        "gmail": {"import": gmail},
        "embeddings": {"sync": embedding},
        "lanes": lanes,
        "dependencies": dependencies,
    }


def _limit_rows(rows: list[dict], limit: int | None) -> list[dict]:
    if not limit:
        return rows
    return rows[: max(1, int(limit))]


def _rows_needing_tasks(categories: set[str] | None, tasks: tuple[str, ...] | list[str], options: dict) -> list[dict]:
    rows = _active_rows(categories)
    force = bool(options.get("force_enrichment"))
    retry_failed = bool(options.get("retry_failed"))
    retry_deferred = bool(options.get("retry_deferred"))
    selected = [row for row in rows if _row_needs_any_task(row, tasks, force=force, retry_failed=retry_failed, retry_deferred=retry_deferred)]
    return _limit_rows(selected, options.get("limit"))


def _document_rows(options: dict) -> list[dict]:
    rows = _active_rows(DOCUMENT_CATEGORIES)
    force = bool(options.get("force_enrichment"))
    retry_failed = bool(options.get("retry_failed"))
    retry_deferred = bool(options.get("retry_deferred"))
    selected = [
        row
        for row in rows
        if _document_ocr_candidate(row)
        and _row_needs_any_task(row, ("ocr",), force=force, retry_failed=retry_failed, retry_deferred=retry_deferred)
    ]
    return _limit_rows(selected, options.get("limit"))


def _embedding_rows(options: dict) -> list[dict]:
    force = bool(options.get("force_enrichment"))
    embedded_paths = set() if force else archive_embedding_ids()
    rows = [
        row
        for row in _active_rows()
        if is_chat_safe_source(row.get("path") or "")
        and is_chat_aware_embedding_candidate(
            row.get("path") or "",
            category=row.get("category") or "",
            size_bytes=row.get("size_bytes"),
        )
        and row.get("path") not in embedded_paths
        and _row_needs_any_task(
            row,
            ("embedding",),
            force=force,
            retry_failed=bool(options.get("retry_failed")),
            retry_deferred=bool(options.get("retry_deferred")),
        )
    ]
    return _limit_rows(rows, options.get("limit"))


def _build_enrichment_plan(options: dict) -> dict:
    return {
        "documents": _document_rows(options) if options.get("include_documents", True) else [],
        "images": _rows_needing_tasks({"image"}, VISUAL_TASKS, options) if options.get("include_images", True) else [],
        "videos": _rows_needing_tasks({"video"}, VIDEO_TASKS, options) if options.get("include_videos", True) else [],
        "embeddings": _embedding_rows(options) if options.get("rebuild_embeddings", True) else [],
    }


def _planned_total(plan: dict, reindex_count: int = 0) -> int:
    return (
        reindex_count
        + len(plan.get("documents") or [])
        + (len(plan.get("images") or []) * 2)
        + (len(plan.get("videos") or []) * 2)
        + len(plan.get("embeddings") or [])
    )


def _normalize_enrichment_options(options: dict | None) -> dict:
    provided = options or {}
    default_include_gmail = gmail_import_enabled()
    normalized = {
        "mode": "auto",
        "force_reindex": False,
        "refresh_index": False,
        "force_enrichment": False,
        "retry_failed": False,
        "retry_deferred": False,
        "include_documents": True,
        "include_images": True,
        "include_videos": True,
        "include_gmail": default_include_gmail,
        "rebuild_embeddings": True,
        "video_preset": "dense_review",
        "limit": None,
        "lane": None,
        "chunk_size": None,
        "resume_run_id": None,
        "max_runtime_minutes": None,
        "respect_host_pressure": True,
        "max_pressure_wait_seconds": HOST_PRESSURE_MAX_WAIT_SECONDS,
        **provided,
    }
    if normalized.get("include_gmail") is None:
        normalized["include_gmail"] = default_include_gmail
    else:
        normalized["include_gmail"] = bool(normalized.get("include_gmail"))
    mode = str(normalized.get("mode") or "auto").strip().lower()
    if mode in {"full", "baseline", "initial"}:
        resolved_mode = "baseline"
    elif mode in {"incremental", "new", "new_files", "changed"}:
        resolved_mode = "incremental"
    else:
        resolved_mode = deep_enrichment_baseline_state().get("next_mode") or "baseline"

    if resolved_mode == "baseline" and mode in {"full", "initial"}:
        normalized["force_reindex"] = True
        normalized["refresh_index"] = True
        normalized["force_enrichment"] = True
        normalized["rebuild_embeddings"] = True
    normalized["mode"] = mode
    normalized["resolved_mode"] = resolved_mode
    normalized["baseline_complete"] = deep_enrichment_baseline_state().get("baseline_complete", False)
    lane = str(normalized.get("lane") or "").strip().lower()
    normalized["lane"] = lane if lane in LANE_TASKS else None
    try:
        normalized["chunk_size"] = int(normalized["chunk_size"]) if normalized.get("chunk_size") else None
    except (TypeError, ValueError):
        normalized["chunk_size"] = None
    try:
        normalized["max_runtime_minutes"] = int(normalized["max_runtime_minutes"]) if normalized.get("max_runtime_minutes") else None
    except (TypeError, ValueError):
        normalized["max_runtime_minutes"] = None
    try:
        raw_pressure_wait = normalized.get("max_pressure_wait_seconds")
        normalized["max_pressure_wait_seconds"] = (
            HOST_PRESSURE_MAX_WAIT_SECONDS
            if raw_pressure_wait is None
            else max(0, int(raw_pressure_wait))
        )
    except (TypeError, ValueError):
        normalized["max_pressure_wait_seconds"] = HOST_PRESSURE_MAX_WAIT_SECONDS
    normalized["respect_host_pressure"] = bool(normalized.get("respect_host_pressure", True))
    return normalized


def _task_status_from_result(result: dict, *, ok_key: str = "ok") -> str:
    if result.get("skipped"):
        return "skipped"
    return "completed" if result.get(ok_key, False) else "failed"


def _unsupported_image_detail(row: dict, lane: str) -> dict | None:
    path = Path(row.get("path") or "")
    ext = path.suffix.lower()
    if ext in SUPPORTED_IMAGE_ENRICHMENT_EXTS:
        return None
    return {
        "reason": "unsupported_image_format",
        "extension": ext or "",
        "mime_type": row.get("mime_type") or "",
        "path": str(path),
        "lane": lane,
        "retry_eligible": False,
        "message": "Skipped visual enrichment because this file is not a supported raster image for face/object scanning.",
    }


def _is_non_retryable_image_error(error: Exception | str) -> bool:
    lowered = str(error or "").lower()
    return any(marker in lowered for marker in NON_RETRYABLE_IMAGE_ERROR_MARKERS)


def _record_failure(path: str, phase: str, error: Exception | str) -> None:
    message = f"{phase}: {error}"
    _update_job(last_error=f"{path}: {error}")
    try:
        record_index_failure(path, message)
    except Exception:
        pass


def _process_document(row: dict, *, force_index: bool = True) -> tuple[str, dict]:
    path = Path(row["path"])
    record = (index_file(path, force=True) if force_index else row) or row
    file_id = int(record.get("id") or row["id"])
    text = record.get("extracted_text") or ""
    failed = "extraction error" in text.lower() or "ocr extraction error" in text.lower()
    status = "failed" if failed else "completed" if text.strip() else "deferred"
    detail = _detail_with_fingerprint(
        record,
        {
            "chars": len(text),
            "path": str(path),
            "category": record.get("category") or row.get("category"),
            "reason": "no_extractable_text" if status == "deferred" else "",
        },
    )
    mark_enrichment(
        file_id,
        "ocr",
        status,
        detail,
    )
    if failed:
        raise RuntimeError(text[:500] or "Document extraction/OCR failed")
    if status == "completed":
        sync_file_embedding_by_id(file_id)
    return status, detail


def _process_image(row: dict) -> None:
    path = row.get("path") or ""
    file_id = int(row["id"])
    skip_detail = _unsupported_image_detail(row, "image")
    if skip_detail:
        mark_enrichment(file_id, "image_faces", "skipped", _detail_with_fingerprint(row, skip_detail))
        mark_enrichment(file_id, "image_objects", "skipped", _detail_with_fingerprint(row, skip_detail))
        mark_index_success(path)
        return
    errors = []
    face_result = scan_file_faces(row)
    face_status = _task_status_from_result(face_result)
    if face_status == "failed" and _is_non_retryable_image_error(face_result.get("error") or ""):
        face_status = "skipped"
        face_result["skipped"] = True
        face_result["reason"] = "unsupported_image_format"
        face_result["retry_eligible"] = False
    mark_enrichment(file_id, "image_faces", face_status, _detail_with_fingerprint(row, face_result))
    try:
        apply_auto_tags(row, face_count=int(face_result.get("face_count") or 0))
    finally:
        sync_file_embedding_by_id(file_id)
    if face_status == "failed":
        errors.append(face_result.get("error") or "Image face scan failed")

    try:
        object_result = analyze_image_file(file_id=file_id, update_index=True)
        mark_enrichment(
            file_id,
            "image_objects",
            "completed" if object_result.get("ok") else "failed",
            _detail_with_fingerprint(row, object_result),
        )
        if not object_result.get("ok"):
            errors.append("Image object tagging failed")
    except Exception as error:
        if _is_non_retryable_image_error(error):
            detail = {"error": str(error), "path": path, "reason": "unsupported_image_format", "retry_eligible": False}
            mark_enrichment(file_id, "image_objects", "skipped", _detail_with_fingerprint(row, detail))
            mark_index_success(path)
            return
        mark_enrichment(file_id, "image_objects", "failed", _detail_with_fingerprint(row, {"error": str(error), "path": path}))
        errors.append(str(error))
    if errors:
        raise RuntimeError("; ".join(errors))
    mark_index_success(path)


def _process_video(row: dict, options: dict) -> None:
    file_id = int(row["id"])
    errors = []
    result = analyze_video(
        file_id=file_id,
        preset=options.get("video_preset") or "dense_review",
        update_index=True,
        detect_faces=True,
        detect_objects=True,
    )
    face_scan = result.get("face_scan") or {}
    object_scan = result.get("object_scan") or {}
    mark_enrichment(
        file_id,
        "video_storyboard",
        "completed",
        _detail_with_fingerprint(row, {"scan_summary": result.get("scan_summary"), "segment_count": len(result.get("segments") or [])}),
    )
    mark_enrichment(file_id, "video_faces", _task_status_from_result(face_scan), _detail_with_fingerprint(row, face_scan))
    mark_enrichment(file_id, "video_objects", _task_status_from_result(object_scan), _detail_with_fingerprint(row, object_scan))
    if not face_scan.get("ok") and not face_scan.get("skipped"):
        errors.append(face_scan.get("error") or "Video face scan failed")
    if not object_scan.get("ok") and not object_scan.get("skipped"):
        errors.append(object_scan.get("error") or "Video object tagging failed")

    try:
        transcript = transcribe_video(file_id=file_id, update_index=True, prefer_subtitles=True)
        mark_enrichment(file_id, "video_transcript", "completed", _detail_with_fingerprint(row, transcript))
    except Exception as error:
        mark_enrichment(file_id, "video_transcript", "failed", _detail_with_fingerprint(row, {"error": str(error), "path": row.get("path")}))
        errors.append(str(error))
    if errors:
        raise RuntimeError("; ".join(errors))


def _sync_embedding_rows(rows: list[dict]) -> None:
    for row in rows:
        if deep_enrichment_stop_requested.is_set():
            return
        path = row.get("path") or ""
        _update_job(phase="embeddings", current_path=path)
        try:
            result = sync_file_embedding_by_id(int(row["id"]))
            status = _embedding_status_from_sync_result(result)
            mark_enrichment(
                int(row["id"]),
                "embedding",
                status,
                _detail_with_fingerprint(row, result),
            )
            if status in {"completed", "skipped"}:
                mark_index_success(path)
            if status == "completed":
                _bump_job("succeeded")
            elif status == "skipped":
                _bump_job("skipped")
            else:
                _bump_job("failed")
        except Exception as error:
            _bump_job("failed")
            _record_failure(path, "deep enrichment embedding sync", error)
        finally:
            _bump_job("processed")


def _json_dumps(payload: dict | list | None) -> str:
    return json.dumps(payload or {}, ensure_ascii=True, default=str)[:50000]


def _now() -> float:
    return time.time()


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _row_by_file_id(file_id: int | None) -> dict | None:
    if not file_id:
        return None
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM files WHERE id = ?", (int(file_id),))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def _is_timeout_error(error: Exception | str) -> bool:
    text = str(error or "").lower()
    return any(token in text for token in ["timed out", "timeout", "read timed out"])


def _host_pressure_reason(lane: str, options: dict) -> str:
    if lane not in HOST_PRESSURE_LANES or not options.get("respect_host_pressure", True):
        return ""
    try:
        stats = host_stats()
    except Exception as error:
        return ""
    thresholds = stats.get("thresholds") or {}
    labels = []
    if thresholds.get("gpu"):
        labels.append("GPU")
    if thresholds.get("vram"):
        labels.append("VRAM")
    if thresholds.get("temperature"):
        labels.append("temperature")
    if thresholds.get("ram"):
        labels.append("RAM")
    if not labels:
        return ""
    return f"Host pressure is high for {lane}: {', '.join(labels)} threshold reached."


def _wait_for_enrichment_slot(lane: str, options: dict, deadline: float | None = None) -> bool:
    wait_started: float | None = None
    raw_max_wait = options.get("max_pressure_wait_seconds")
    max_wait = HOST_PRESSURE_MAX_WAIT_SECONDS if raw_max_wait is None else int(raw_max_wait)
    poll_seconds = max(3, min(HOST_PRESSURE_POLL_SECONDS, max_wait or HOST_PRESSURE_POLL_SECONDS))
    while not deep_enrichment_stop_requested.is_set():
        if deadline and _now() >= deadline:
            return False
        reason = _host_pressure_reason(lane, options)
        if not reason:
            _update_job(throttle_active=False, throttle_reason="")
            return True
        if wait_started is None:
            wait_started = _now()
        elapsed = _now() - wait_started
        _update_job(throttle_active=True, throttle_reason=reason)
        if max_wait <= 0 or elapsed >= max_wait:
            _update_job(last_error=f"{reason} Pausing chunk after waiting {int(elapsed)} seconds.")
            return False
        sleep_for = poll_seconds
        if deadline:
            sleep_for = min(sleep_for, max(0.5, deadline - _now()))
        time.sleep(sleep_for)
    return False


def recover_enrichment_queue() -> list[int]:
    if _job_snapshot().get("running"):
        return []
    conn = get_conn()
    cur = conn.cursor()
    ts = _now()
    cur.execute(
        """
        SELECT id
        FROM enrichment_runs
        WHERE status IN ('queued', 'running', 'pausing')
        ORDER BY updated_ts DESC, id DESC
        """
    )
    run_ids = [int(row["id"]) for row in cur.fetchall()]
    cur.execute(
        """
        UPDATE enrichment_queue_items
        SET status = 'pending', updated_ts = ?, started_ts = NULL
        WHERE status = 'running'
        """,
        (ts,),
    )
    cur.execute(
        """
        UPDATE enrichment_chunks
        SET status = 'paused', updated_ts = ?, current_item_id = NULL
        WHERE status = 'running'
        """,
        (ts,),
    )
    cur.execute(
        """
        UPDATE enrichment_runs
        SET status = 'paused', pause_requested = 0, current_chunk_id = NULL, updated_ts = ?
        WHERE status IN ('running', 'pausing')
        """,
        (ts,),
    )
    conn.commit()
    conn.close()
    migrate_deferred_timeout_failures()
    return run_ids


def migrate_deferred_timeout_failures() -> int:
    conn = get_conn()
    cur = conn.cursor()
    ts = _now()
    cur.execute(
        """
        UPDATE file_enrichment
        SET status = 'deferred',
            detail_json = CASE
                WHEN json_valid(COALESCE(NULLIF(detail_json, ''), '{}'))
                THEN json_set(COALESCE(NULLIF(detail_json, ''), '{}'), '$.deferred_reason', 'timeout_quarantine', '$.retry_eligible', 1)
                ELSE '{"deferred_reason":"timeout_quarantine","retry_eligible":true}'
            END,
            updated_ts = ?
        WHERE status IN ('failed', 'failed_retryable')
          AND task IN ('image_objects', 'video_objects')
          AND (
            LOWER(COALESCE(detail_json, '')) LIKE '%timed out%'
            OR LOWER(COALESCE(detail_json, '')) LIKE '%timeout%'
          )
        """,
        (ts,),
    )
    file_rows = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    cur.execute(
        """
        UPDATE enrichment_queue_items
        SET status = 'deferred',
            last_error = COALESCE(last_error, 'timeout_quarantine'),
            updated_ts = ?,
            finished_ts = COALESCE(finished_ts, ?)
        WHERE status IN ('failed', 'failed_retryable')
          AND lane IN ('image_objects', 'video_objects')
          AND (
            LOWER(COALESCE(last_error, '')) LIKE '%timed out%'
            OR LOWER(COALESCE(last_error, '')) LIKE '%timeout%'
          )
        """,
        (ts, ts),
    )
    queue_rows = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    conn.commit()
    conn.close()
    return int(file_rows) + int(queue_rows)


def _set_run_status(
    run_id: int,
    status: str,
    *,
    current_lane: str | None = None,
    current_chunk_id: int | None = None,
    pause_requested: bool | None = None,
    last_error: str | None = None,
    last_snapshot_path: str | None = None,
    finished: bool = False,
) -> None:
    ts = _now()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE enrichment_runs
        SET status = ?,
            current_lane = COALESCE(?, current_lane),
            current_chunk_id = COALESCE(?, current_chunk_id),
            pause_requested = CASE WHEN ? IS NULL THEN pause_requested ELSE ? END,
            last_error = COALESCE(?, last_error),
            last_snapshot_path = COALESCE(?, last_snapshot_path),
            started_ts = CASE WHEN started_ts IS NULL AND ? = 'running' THEN ? ELSE started_ts END,
            finished_ts = CASE WHEN ? THEN ? ELSE finished_ts END,
            updated_ts = ?
        WHERE id = ?
        """,
        (
            status,
            current_lane,
            current_chunk_id,
            None if pause_requested is None else 1,
            1 if pause_requested else 0,
            (last_error or "")[:4000] if last_error else None,
            last_snapshot_path,
            status,
            ts,
            1 if finished else 0,
            ts,
            ts,
            run_id,
        ),
    )
    conn.commit()
    conn.close()


def _refresh_chunk_counts(chunk_id: int) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM enrichment_queue_items
        WHERE chunk_id = ?
        GROUP BY status
        """,
        (chunk_id,),
    )
    counts = {row["status"]: int(row["count"]) for row in cur.fetchall()}
    cur.execute("SELECT COUNT(*) AS count FROM enrichment_queue_items WHERE chunk_id = ?", (chunk_id,))
    total = int(cur.fetchone()["count"] or 0)
    pending = counts.get("pending", 0) + counts.get("running", 0)
    completed = counts.get("completed", 0)
    skipped = counts.get("skipped", 0)
    deferred = counts.get("deferred", 0)
    failed = counts.get("failed_retryable", 0) + counts.get("failed", 0)
    processed = max(0, total - pending)
    ts = _now()
    cur.execute(
        """
        UPDATE enrichment_chunks
        SET total_items = ?,
            processed_items = ?,
            completed_items = ?,
            skipped_items = ?,
            deferred_items = ?,
            failed_items = ?,
            updated_ts = ?
        WHERE id = ?
        """,
        (total, processed, completed, skipped, deferred, failed, ts, chunk_id),
    )
    conn.commit()
    conn.close()
    return {
        "total": total,
        "processed": processed,
        "completed": completed,
        "skipped": skipped,
        "deferred": deferred,
        "failed_retryable": failed,
        "pending": pending,
    }


def _refresh_run_counts(run_id: int) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
          COALESCE(SUM(total_items), 0) AS total,
          COALESCE(SUM(processed_items), 0) AS processed,
          COALESCE(SUM(completed_items), 0) AS completed,
          COALESCE(SUM(skipped_items), 0) AS skipped,
          COALESCE(SUM(deferred_items), 0) AS deferred,
          COALESCE(SUM(failed_items), 0) AS failed
        FROM enrichment_chunks
        WHERE run_id = ?
        """,
        (run_id,),
    )
    row = cur.fetchone()
    counts = {
        "total": int(row["total"] or 0),
        "processed": int(row["processed"] or 0),
        "completed": int(row["completed"] or 0),
        "skipped": int(row["skipped"] or 0),
        "deferred": int(row["deferred"] or 0),
        "failed": int(row["failed"] or 0),
    }
    ts = _now()
    cur.execute(
        """
        UPDATE enrichment_runs
        SET total_items = ?,
            processed_items = ?,
            completed_items = ?,
            skipped_items = ?,
            deferred_items = ?,
            failed_items = ?,
            updated_ts = ?
        WHERE id = ?
        """,
        (counts["total"], counts["processed"], counts["completed"], counts["skipped"], counts["deferred"], counts["failed"], ts, run_id),
    )
    conn.commit()
    conn.close()
    return counts


def _set_chunk_status(
    chunk_id: int,
    status: str,
    *,
    current_item_id: int | None = None,
    last_error: str | None = None,
    snapshot_before_path: str | None = None,
    snapshot_after_path: str | None = None,
    finished: bool = False,
) -> None:
    ts = _now()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE enrichment_chunks
        SET status = ?,
            current_item_id = ?,
            last_error = COALESCE(?, last_error),
            snapshot_before_path = COALESCE(?, snapshot_before_path),
            snapshot_after_path = COALESCE(?, snapshot_after_path),
            started_ts = CASE WHEN started_ts IS NULL AND ? = 'running' THEN ? ELSE started_ts END,
            finished_ts = CASE WHEN ? THEN ? ELSE finished_ts END,
            updated_ts = ?
        WHERE id = ?
        """,
        (
            status,
            current_item_id,
            (last_error or "")[:4000] if last_error else None,
            snapshot_before_path,
            snapshot_after_path,
            status,
            ts,
            1 if finished else 0,
            ts,
            ts,
            chunk_id,
        ),
    )
    conn.commit()
    conn.close()


def _chunk_snapshot(chunk_id: int) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM enrichment_chunks WHERE id = ?", (chunk_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def _run_snapshot(run_id: int) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM enrichment_runs WHERE id = ?", (run_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def latest_resumable_enrichment_run() -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM enrichment_runs
        WHERE status IN ('queued', 'running', 'pausing', 'paused')
        ORDER BY updated_ts DESC, id DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def latest_enrichment_run() -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM enrichment_runs ORDER BY updated_ts DESC, id DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def _queue_counts(run_id: int | None = None) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    where = "WHERE run_id = ?" if run_id else ""
    params = [run_id] if run_id else []
    cur.execute(f"SELECT status, COUNT(*) AS count FROM enrichment_queue_items {where} GROUP BY status", params)
    item_counts = {row["status"]: int(row["count"]) for row in cur.fetchall()}
    cur.execute(f"SELECT status, COUNT(*) AS count FROM enrichment_chunks {where} GROUP BY status", params)
    chunk_counts = {row["status"]: int(row["count"]) for row in cur.fetchall()}
    cur.execute(f"SELECT status, COUNT(*) AS count FROM enrichment_runs {'WHERE id = ?' if run_id else ''} GROUP BY status", params)
    run_counts = {row["status"]: int(row["count"]) for row in cur.fetchall()}
    conn.close()
    return {"items": item_counts, "chunks": chunk_counts, "runs": run_counts}


def _lane_enabled(lane: str, options: dict) -> bool:
    if lane == "index_refresh":
        return bool(options.get("force_reindex") or options.get("refresh_index"))
    if lane == "document_ocr":
        return bool(options.get("include_documents", True))
    if lane == "gmail_import":
        return bool(options.get("include_gmail", True))
    if lane == "embedding_sync":
        return bool(options.get("rebuild_embeddings", True))
    if lane.startswith("image_"):
        return bool(options.get("include_images", True))
    if lane.startswith("video_"):
        return bool(options.get("include_videos", True))
    return True


def _lane_dependency_blocker(lane: str) -> str | None:
    if lane in {"image_objects", "video_objects"}:
        status = vision_status()
        if not status.get("ready"):
            return status.get("hint") or "Vision model is not ready."
    if lane.startswith("video_"):
        status = ffmpeg_status()
        if not status.get("ready"):
            return status.get("hint") or "FFmpeg is not ready."
    if lane == "gmail_import":
        try:
            from app.cloud_sync import cloud_sync_status

            account = ((cloud_sync_status().get("accounts") or {}).get("google") or {})
            if not account.get("gmail_ready"):
                return "Connect Google OAuth before importing Gmail."
        except Exception as error:
            return str(error)
    return None


def _recommended_lane(options: dict, coverage: dict | None = None) -> dict:
    coverage = coverage or deep_enrichment_coverage_report()
    lanes = coverage.get("lanes") or {}
    blocked = []
    requested_lane = options.get("lane")
    order = [requested_lane] if requested_lane else LANE_ORDER
    for lane in order:
        if not lane or not _lane_enabled(lane, options):
            continue
        item = lanes.get(lane) or {}
        missing = int(item.get("missing") or 0)
        failed_retryable = int(item.get("failed_retryable") or 0)
        if lane == "gmail_import" and item.get("running"):
            blocked.append({"lane": lane, "reason": "Gmail import is already running."})
            continue
        wants_retry = bool(options.get("retry_failed"))
        needs_work = missing > 0 or (wants_retry and failed_retryable > 0) or bool(options.get("force_enrichment"))
        if lane == "index_refresh":
            needs_work = bool(options.get("force_reindex") or options.get("refresh_index"))
        if lane == "gmail_import":
            needs_work = bool(item.get("ready")) and (missing > 0 or not item.get("completed") or bool(options.get("retry_failed")))
        if not needs_work:
            continue
        blocker = _lane_dependency_blocker(lane)
        if blocker:
            blocked.append({"lane": lane, "reason": blocker})
            continue
        chunk_size = _safe_int(options.get("chunk_size"), 0) or _lane_default_chunk_size(lane)
        return {
            "action": "start_chunk",
            "lane": lane,
            "chunk_size": chunk_size,
            "reason": f"Next safe chunk is {LANE_LABELS.get(lane, lane)}.",
            "blocked_lanes": blocked,
        }
    if blocked:
        return {"action": "blocked", "lane": None, "chunk_size": None, "reason": blocked[0]["reason"], "blocked_lanes": blocked}
    return {"action": "idle", "lane": None, "chunk_size": None, "reason": "All enabled lane milestones are terminal.", "blocked_lanes": []}


def _lane_default_chunk_size(lane: str) -> int:
    if lane == "image_objects":
        model = str((vision_status().get("model") or "")).lower()
        if "llava" in model:
            return VISION_BULK_CHUNK_SIZE
    return LANE_DEFAULT_CHUNK_SIZE.get(lane, 100)


def _index_refresh_rows(options: dict, limit: int) -> list[dict]:
    if not _lane_enabled("index_refresh", options):
        return []
    force = bool(options.get("force_reindex"))
    rows: list[dict] = []
    for path in walk_archive() or []:
        try:
            stat = Path(path).stat()
        except OSError:
            continue
        needs = force
        if not needs:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT size_bytes, modified_ts FROM files WHERE path = ?", (str(path),))
            current = cur.fetchone()
            conn.close()
            if not current:
                needs = True
            else:
                needs = int(current["size_bytes"] or 0) != int(stat.st_size) or abs(float(current["modified_ts"] or 0) - float(stat.st_mtime)) > 0.0001
        if needs:
            rows.append({"id": None, "path": str(path), "category": "index_refresh", "size_bytes": stat.st_size, "modified_ts": stat.st_mtime})
        if len(rows) >= limit:
            break
    return rows


def _gmail_lane_rows(options: dict, limit: int) -> list[dict]:
    if not _lane_enabled("gmail_import", options):
        return []
    blocker = _lane_dependency_blocker("gmail_import")
    if blocker:
        return []
    state = _load_deep_enrichment_state()
    page_token = "" if options.get("retry_failed") else str(((state.get("gmail_import") or {}).get("next_page_token") or ""))
    return [
        {
            "id": None,
            "path": "gmail://google/archive",
            "category": "email",
            "page_token": page_token,
            "chunk_size": limit,
        }
    ]


def _rows_for_lane(lane: str, options: dict, chunk_size: int) -> list[dict]:
    if lane == "index_refresh":
        return _index_refresh_rows(options, chunk_size)
    if lane == "document_ocr":
        return _document_rows({**options, "limit": chunk_size})
    if lane == "gmail_import":
        return _gmail_lane_rows(options, chunk_size)
    if lane == "embedding_sync":
        return _limit_rows(_embedding_rows(options), chunk_size)
    if lane == "image_faces":
        return _rows_needing_tasks({"image"}, ("image_faces",), {**options, "limit": chunk_size})
    if lane == "image_objects":
        return _rows_needing_tasks({"image"}, ("image_objects",), {**options, "limit": chunk_size})
    if lane == "video_storyboard":
        return _rows_needing_tasks({"video"}, ("video_storyboard",), {**options, "limit": chunk_size})
    if lane == "video_transcript":
        return _rows_needing_tasks({"video"}, ("video_transcript",), {**options, "limit": chunk_size})
    if lane == "video_faces":
        return _rows_needing_tasks({"video"}, ("video_faces",), {**options, "limit": chunk_size})
    if lane == "video_objects":
        return _rows_needing_tasks({"video"}, ("video_objects",), {**options, "limit": chunk_size})
    return []


def _create_enrichment_run(options: dict) -> int:
    ts = _now()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO enrichment_runs (
            mode, status, autopilot, options_json, lane_order_json, created_ts, updated_ts
        ) VALUES (?, 'queued', ?, ?, ?, ?, ?)
        """,
        (
            options.get("resolved_mode") or options.get("mode") or "auto",
            1 if options.get("autopilot") else 0,
            _json_dumps(options),
            _json_dumps(LANE_ORDER),
            ts,
            ts,
        ),
    )
    run_id = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return run_id


def _select_run(options: dict) -> int:
    if options.get("resume_run_id"):
        run_id = int(options["resume_run_id"])
        if _run_snapshot(run_id):
            return run_id
    if options.get("resume_latest"):
        latest = latest_resumable_enrichment_run()
        if latest:
            return int(latest["id"])
    return _create_enrichment_run(options)


def _item_fingerprint(row: dict, lane: str) -> dict:
    if row.get("id"):
        return _row_fingerprint(row)
    return {
        "path": row.get("path") or "",
        "lane": lane,
        "page_token": row.get("page_token") or "",
        "chunk_size": row.get("chunk_size"),
        "task_version": ENRICHMENT_TASK_VERSION,
    }


def _seed_chunk(run_id: int, lane: str, options: dict, chunk_size: int) -> dict | None:
    rows = _rows_for_lane(lane, options, chunk_size)
    if not rows:
        return None
    ts = _now()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO enrichment_chunks (
            run_id, lane, status, priority, chunk_size, total_items, options_json, created_ts, updated_ts
        ) VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?)
        """,
        (run_id, lane, LANE_ORDER.index(lane) if lane in LANE_ORDER else 999, chunk_size, len(rows), _json_dumps(options), ts, ts),
    )
    chunk_id = int(cur.lastrowid)
    task = LANE_TASKS.get(lane, (lane,))[0]
    touched_chunk_ids: set[int] = set()
    for row in rows:
        file_id = int(row["id"]) if row.get("id") else None
        if file_id:
            cur.execute(
                """
                SELECT chunk_id
                FROM enrichment_queue_items
                WHERE run_id = ? AND file_id = ? AND task = ?
                """,
                (run_id, file_id, task),
            )
            existing = cur.fetchone()
            if existing and existing["chunk_id"]:
                touched_chunk_ids.add(int(existing["chunk_id"]))
        cur.execute(
            """
            INSERT INTO enrichment_queue_items (
                run_id, chunk_id, file_id, path, lane, task, status, attempts, max_attempts, fingerprint_json, created_ts, updated_ts
            ) VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, 2, ?, ?, ?)
            ON CONFLICT(run_id, file_id, task) DO UPDATE SET
                chunk_id=excluded.chunk_id,
                path=excluded.path,
                lane=excluded.lane,
                status='pending',
                attempts=0,
                max_attempts=excluded.max_attempts,
                last_error=NULL,
                fingerprint_json=excluded.fingerprint_json,
                started_ts=NULL,
                updated_ts=excluded.updated_ts,
                finished_ts=NULL
            """,
            (
                run_id,
                chunk_id,
                file_id,
                row.get("path") or "",
                lane,
                task,
                _json_dumps(_item_fingerprint(row, lane)),
                ts,
                ts,
            ),
        )
    cur.execute("SELECT COUNT(*) AS count FROM enrichment_queue_items WHERE chunk_id = ?", (chunk_id,))
    seeded_count = int(cur.fetchone()["count"] or 0)
    if not seeded_count:
        cur.execute("DELETE FROM enrichment_chunks WHERE id = ?", (chunk_id,))
        conn.commit()
        conn.close()
        return None
    cur.execute("UPDATE enrichment_chunks SET total_items = ? WHERE id = ?", (seeded_count, chunk_id))
    conn.commit()
    conn.close()
    for touched_chunk_id in sorted(touched_chunk_ids - {chunk_id}):
        _refresh_chunk_counts(touched_chunk_id)
    _refresh_chunk_counts(chunk_id)
    _refresh_run_counts(run_id)
    return _chunk_snapshot(chunk_id)


def _queue_claim_statuses(*, retry_failed: bool = False, retry_deferred: bool = False) -> list[str]:
    statuses = ["pending"]
    if retry_failed:
        statuses.extend(["failed", "failed_retryable"])
    if retry_deferred:
        statuses.append("deferred")
    return statuses


def _existing_chunk_for_run(run_id: int, *, retry_failed: bool = False, retry_deferred: bool = False) -> dict | None:
    statuses = _queue_claim_statuses(retry_failed=retry_failed, retry_deferred=retry_deferred)
    placeholders = ",".join("?" for _ in statuses)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT c.*
        FROM enrichment_chunks c
        WHERE c.run_id = ?
          AND c.status IN ('pending', 'running', 'paused')
          AND EXISTS (
            SELECT 1 FROM enrichment_queue_items qi
            WHERE qi.chunk_id = c.id AND qi.status IN ({placeholders})
          )
        ORDER BY c.id ASC
        LIMIT 1
        """,
        [run_id, *statuses],
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    chunk = dict(row)
    _set_chunk_status(int(chunk["id"]), "pending")
    return _chunk_snapshot(int(chunk["id"]))


def _has_existing_chunk_for_run(run_id: int, *, retry_failed: bool = False, retry_deferred: bool = False) -> bool:
    statuses = _queue_claim_statuses(retry_failed=retry_failed, retry_deferred=retry_deferred)
    placeholders = ",".join("?" for _ in statuses)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT 1
        FROM enrichment_chunks c
        WHERE c.run_id = ?
          AND c.status IN ('pending', 'running', 'paused')
          AND EXISTS (
            SELECT 1 FROM enrichment_queue_items qi
            WHERE qi.chunk_id = c.id AND qi.status IN ({placeholders})
          )
        LIMIT 1
        """,
        [run_id, *statuses],
    )
    found = cur.fetchone() is not None
    conn.close()
    return found


def _claim_next_item(chunk_id: int, *, retry_failed: bool = False, retry_deferred: bool = False) -> dict | None:
    statuses = _queue_claim_statuses(retry_failed=retry_failed, retry_deferred=retry_deferred)
    placeholders = ",".join("?" for _ in statuses)
    ts = _now()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT *
        FROM enrichment_queue_items
        WHERE chunk_id = ?
          AND status IN ({placeholders})
        ORDER BY id ASC
        LIMIT 1
        """,
        [chunk_id, *statuses],
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    item = dict(row)
    attempts = int(item.get("attempts") or 0) + 1
    cur.execute(
        """
        UPDATE enrichment_queue_items
        SET status = 'running',
            attempts = ?,
            started_ts = COALESCE(started_ts, ?),
            updated_ts = ?
        WHERE id = ?
        """,
        (attempts, ts, ts, int(item["id"])),
    )
    cur.execute("UPDATE enrichment_chunks SET current_item_id = ?, updated_ts = ? WHERE id = ?", (int(item["id"]), ts, chunk_id))
    conn.commit()
    conn.close()
    item["attempts"] = attempts
    item["status"] = "running"
    return item


def _mark_item(item_id: int, status: str, *, error: str | None = None) -> None:
    ts = _now()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE enrichment_queue_items
        SET status = ?,
            last_error = ?,
            updated_ts = ?,
            finished_ts = CASE WHEN ? IN ('completed', 'skipped', 'deferred', 'failed_retryable') THEN ? ELSE finished_ts END
        WHERE id = ?
        """,
        (status, (error or "")[:4000] if error else None, ts, status, ts, int(item_id)),
    )
    conn.commit()
    conn.close()


def _mark_lane_task(row: dict | None, lane: str, status: str, detail: dict | None = None) -> None:
    if not row or not row.get("id"):
        return
    for task in LANE_TASKS.get(lane, (lane,)):
        mark_enrichment(int(row["id"]), task, status, _detail_with_fingerprint(row, detail or {}))


def _dependency_deferred_detail(lane: str, reason: str) -> dict:
    return {"deferred_reason": reason, "retry_eligible": True, "lane": lane}


def _embedding_status_from_sync_result(result: dict) -> str:
    if result.get("synced"):
        return "skipped" if result.get("mode") == "deleted" else "completed"
    if result.get("reason") in {"missing_row", "missing_path", "sync_disabled"}:
        return "skipped"
    return "failed_retryable"


def _mark_terminal_queue_items(path: str, lane: str, task: str, status: str) -> int:
    if not path or status not in TERMINAL_ENRICHMENT_STATUSES:
        return 0
    ts = _now()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT run_id, chunk_id
        FROM enrichment_queue_items
        WHERE path = ?
          AND lane = ?
          AND task = ?
          AND status IN ('pending', 'running', 'failed', 'failed_retryable')
        """,
        (path, lane, task),
    )
    touched = [(int(row["run_id"]), int(row["chunk_id"])) for row in cur.fetchall() if row["run_id"] and row["chunk_id"]]
    cur.execute(
        """
        UPDATE enrichment_queue_items
        SET status = ?,
            last_error = NULL,
            updated_ts = ?,
            finished_ts = ?
        WHERE path = ?
          AND lane = ?
          AND task = ?
          AND status IN ('pending', 'running', 'failed', 'failed_retryable')
        """,
        (status, ts, ts, path, lane, task),
    )
    changed = int(cur.rowcount or 0)
    conn.commit()
    conn.close()
    for run_id, chunk_id in touched:
        _refresh_chunk_counts(chunk_id)
        _refresh_run_counts(run_id)
    return changed


def _reconcile_terminal_queue_items(limit: int = 1000) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT q.id, q.run_id, q.chunk_id, fe.status AS terminal_status
        FROM enrichment_queue_items q
        JOIN file_enrichment fe ON fe.file_id = q.file_id AND fe.task = q.task
        WHERE q.status IN ('pending', 'running', 'failed', 'failed_retryable')
          AND fe.status IN ('completed', 'skipped', 'deferred')
        ORDER BY q.updated_ts DESC
        LIMIT ?
        """,
        (max(1, min(int(limit), 5000)),),
    )
    rows = [dict(row) for row in cur.fetchall()]
    ts = _now()
    for row in rows:
        cur.execute(
            """
            UPDATE enrichment_queue_items
            SET status = ?,
                last_error = NULL,
                updated_ts = ?,
                finished_ts = ?
            WHERE id = ?
            """,
            (row["terminal_status"], ts, ts, int(row["id"])),
        )
    conn.commit()
    conn.close()
    touched = {(int(row["run_id"]), int(row["chunk_id"])) for row in rows if row.get("run_id") and row.get("chunk_id")}
    for run_id, chunk_id in touched:
        _refresh_chunk_counts(chunk_id)
        _refresh_run_counts(run_id)
    return len(rows)


def _process_gmail_chunk(item: dict, options: dict) -> dict:
    from app.cloud_sync import import_gmail_archive

    try:
        fingerprint = json.loads(item.get("fingerprint_json") or "{}")
    except json.JSONDecodeError:
        fingerprint = {}
    chunk_size = _safe_int(options.get("chunk_size"), 0) or _safe_int(fingerprint.get("chunk_size"), 0) or LANE_DEFAULT_CHUNK_SIZE["gmail_import"]
    page_token = str(fingerprint.get("page_token") or "").strip() or None
    result = import_gmail_archive(
        {
            "query": options.get("gmail_query") if options.get("gmail_query") is not None else "-in:spam -in:trash",
            "max_results": chunk_size,
            "page_size": chunk_size,
            "include_spam_trash": bool(options.get("include_spam_trash")),
            "sync_embeddings": bool(options.get("sync_embeddings", True)),
            "message_mode": options.get("gmail_message_mode") or "metadata_only",
            "attachment_mode": "metadata_only",
            "page_token": page_token,
            "should_stop": deep_enrichment_stop_requested.is_set,
        }
    )
    state = _load_deep_enrichment_state()
    gmail_state = dict(state.get("gmail_import") or {})
    gmail_state.update(
        {
            "last_chunk_ts": _now(),
            "last_page_token": page_token,
            "next_page_token": result.get("next_page_token") or "",
            "last_result": {k: v for k, v in result.items() if k != "errors"},
        }
    )
    if not result.get("next_page_token"):
        gmail_state["completed_ts"] = _now()
    state["gmail_import"] = gmail_state
    _save_deep_enrichment_state(state)
    return result


def reconcile_known_enrichment_failures(limit: int = 25) -> dict:
    triage = index_failure_triage(limit=limit, error_limit=1)
    group_rows = triage.get("groups") or []
    conn = get_conn()
    cur = conn.cursor()
    rows = []
    for group in group_rows[: max(1, min(int(limit), 100))]:
        cur.execute("SELECT * FROM files WHERE path = ?", (group.get("path") or "",))
        row = cur.fetchone()
        if not row:
            continue
        item = dict(row)
        error = str(group.get("error") or "").lower()
        item["raw_count"] = int(group.get("raw_count") or 0)
        item["failure_error"] = error
        item["embedding_failures"] = 1 if "embedding_sync" in error else 0
        item["image_failures"] = 1 if "image" in error else 0
        rows.append(item)
    conn.close()
    reconciled_paths: list[str] = []
    resolved_paths: list[str] = []
    skipped_embeddings = 0
    skipped_images = 0
    queue_items_terminal = 0
    for row in rows:
        path = row.get("path") or ""
        file_id = int(row.get("id") or 0)
        changed = False
        if int(row.get("embedding_failures") or 0) and (not is_chat_safe_source(path) or not is_chat_aware_embedding_candidate(path, category=row.get("category") or "", size_bytes=row.get("size_bytes"))):
            detail = {
                "reason": "source_not_chat_safe",
                "path": path,
                "retry_eligible": False,
                "message": "Embedding sync skipped because this source is currently chat-ignored or metadata-only.",
            }
            mark_enrichment(file_id, "embedding", "skipped", _detail_with_fingerprint(row, detail))
            queue_items_terminal += _mark_terminal_queue_items(path, "embedding_sync", "embedding", "skipped")
            skipped_embeddings += 1
            changed = True
        image_skip_detail = _unsupported_image_detail(row, "image")
        if not image_skip_detail and _is_non_retryable_image_error(row.get("failure_error") or ""):
            image_skip_detail = {
                "reason": "unsupported_image_format",
                "path": path,
                "retry_eligible": False,
                "message": "Image enrichment skipped because this file repeatedly fails visual decoding.",
                "error": row.get("failure_error") or "",
            }
        if int(row.get("image_failures") or 0) and (row.get("category") == "image") and image_skip_detail:
            detail = image_skip_detail
            mark_enrichment(file_id, "image_faces", "skipped", _detail_with_fingerprint(row, detail))
            mark_enrichment(file_id, "image_objects", "skipped", _detail_with_fingerprint(row, detail))
            queue_items_terminal += _mark_terminal_queue_items(path, "image_faces", "image_faces", "skipped")
            queue_items_terminal += _mark_terminal_queue_items(path, "image_objects", "image_objects", "skipped")
            skipped_images += 1
            changed = True
        if changed:
            reconciled_paths.append(path)
            if int(row.get("raw_count") or 0) <= 1000:
                mark_index_success(path)
                resolved_paths.append(path)
    queue_items_terminal += _reconcile_terminal_queue_items()
    return {
        "reconciled_paths": len(reconciled_paths),
        "resolved_paths": len(resolved_paths),
        "skipped_embeddings": skipped_embeddings,
        "skipped_images": skipped_images,
        "queue_items_terminal": queue_items_terminal,
        "sample_paths": reconciled_paths[:10],
    }


def _process_lane_item(item: dict, options: dict) -> tuple[str, dict, dict | None]:
    lane = item.get("lane") or ""
    row = _row_by_file_id(item.get("file_id"))
    if lane == "index_refresh":
        path = Path(item.get("path") or "")
        record = index_file(path, force=bool(options.get("force_reindex")))
        if record and record.get("id") and is_chat_safe_source(record.get("path") or "") and is_chat_aware_content_path(record.get("path") or ""):
            record["embedding"] = sync_file_embedding_by_id(int(record["id"]))
        status = "skipped" if record and record.get("skipped") else "completed"
        return status, {"path": str(path), "record": record}, record or {"path": str(path)}
    if not row and lane != "gmail_import":
        return "skipped", {"reason": "file row no longer exists", "path": item.get("path")}, None
    blocker = _lane_dependency_blocker(lane)
    if blocker:
        if row:
            _mark_lane_task(row, lane, "deferred", _dependency_deferred_detail(lane, blocker))
        return "deferred", _dependency_deferred_detail(lane, blocker), row
    if lane == "document_ocr":
        if not _document_ocr_candidate(row):
            detail = {
                "reason": "chat_ignored_generated_code",
                "path": row.get("path") or "",
                "message": "Skipped chat ingestion for generated, dependency, cache, or compiled code content.",
                "retry_eligible": False,
            }
            mark_enrichment(int(row["id"]), "ocr", "skipped", _detail_with_fingerprint(row, detail))
            return "skipped", detail, row
        status, detail = _process_document(row, force_index=not (row.get("extracted_text") or "").strip())
        return status, detail, row
    if lane == "gmail_import":
        result = _process_gmail_chunk(item, options)
        if result.get("status") not in {"connected", "partial"}:
            raise RuntimeError(result.get("last_error") or "Gmail import chunk failed")
        return "completed", result, None
    if lane == "embedding_sync":
        result = sync_file_embedding_by_id(int(row["id"]))
        status = _embedding_status_from_sync_result(result)
        mark_enrichment(int(row["id"]), "embedding", status, _detail_with_fingerprint(row, result))
        if status == "failed_retryable":
            raise RuntimeError(result.get("reason") or result.get("error") or "Embedding sync failed")
        if status in {"completed", "skipped"}:
            mark_index_success(row.get("path") or item.get("path") or "")
        return status, result, row
    if lane == "image_faces":
        skip_detail = _unsupported_image_detail(row, lane)
        if skip_detail:
            mark_enrichment(int(row["id"]), "image_faces", "skipped", _detail_with_fingerprint(row, skip_detail))
            mark_index_success(row.get("path") or item.get("path") or "")
            return "skipped", skip_detail, row
        result = scan_file_faces(row)
        status = _task_status_from_result(result)
        if status == "failed" and _is_non_retryable_image_error(result.get("error") or ""):
            status = "skipped"
            result["skipped"] = True
            result["reason"] = "unsupported_image_format"
            result["retry_eligible"] = False
        mark_enrichment(int(row["id"]), "image_faces", status, _detail_with_fingerprint(row, result))
        apply_auto_tags(row, face_count=int(result.get("face_count") or 0))
        sync_file_embedding_by_id(int(row["id"]))
        if status == "failed":
            raise RuntimeError(result.get("error") or "Image face scan failed")
        if status in {"completed", "skipped"}:
            mark_index_success(row.get("path") or item.get("path") or "")
        return status, result, row
    if lane == "image_objects":
        skip_detail = _unsupported_image_detail(row, lane)
        if skip_detail:
            mark_enrichment(int(row["id"]), "image_objects", "skipped", _detail_with_fingerprint(row, skip_detail))
            mark_index_success(row.get("path") or item.get("path") or "")
            return "skipped", skip_detail, row
        try:
            result = analyze_image_file(file_id=int(row["id"]), update_index=True)
        except Exception as error:
            if _is_non_retryable_image_error(error):
                detail = {"error": str(error), "path": row.get("path"), "reason": "unsupported_image_format", "retry_eligible": False}
                mark_enrichment(int(row["id"]), "image_objects", "skipped", _detail_with_fingerprint(row, detail))
                mark_index_success(row.get("path") or item.get("path") or "")
                return "skipped", detail, row
            raise
        status = "completed" if result.get("ok") else "failed_retryable"
        mark_enrichment(int(row["id"]), "image_objects", status, _detail_with_fingerprint(row, result))
        if status == "failed_retryable":
            raise RuntimeError(result.get("error") or "Image object tagging failed")
        mark_index_success(row.get("path") or item.get("path") or "")
        return "completed", result, row
    if lane == "video_storyboard":
        result = analyze_video(file_id=int(row["id"]), preset=options.get("video_preset") or "dense_review", update_index=True, detect_faces=False, detect_objects=False)
        detail = {"scan_summary": result.get("scan_summary"), "segment_count": len(result.get("segments") or [])}
        mark_enrichment(int(row["id"]), "video_storyboard", "completed", _detail_with_fingerprint(row, detail))
        return "completed", detail, row
    if lane == "video_transcript":
        result = transcribe_video(file_id=int(row["id"]), update_index=True, prefer_subtitles=True)
        mark_enrichment(int(row["id"]), "video_transcript", "completed", _detail_with_fingerprint(row, result))
        return "completed", result, row
    if lane == "video_faces":
        result = scan_file_faces(row, force_video=True)
        status = _task_status_from_result(result)
        mark_enrichment(int(row["id"]), "video_faces", status, _detail_with_fingerprint(row, result))
        if status in {"completed", "skipped"}:
            result["embedding"] = sync_file_embedding_by_id(int(row["id"]))
        if status == "failed":
            raise RuntimeError(result.get("error") or "Video face scan failed")
        return status, result, row
    if lane == "video_objects":
        result = analyze_video(file_id=int(row["id"]), preset=options.get("video_preset") or "dense_review", update_index=True, detect_faces=False, detect_objects=True)
        object_scan = result.get("object_scan") or {}
        status = _task_status_from_result(object_scan)
        mark_enrichment(int(row["id"]), "video_objects", status, _detail_with_fingerprint(row, object_scan))
        if status == "failed":
            raise RuntimeError(object_scan.get("error") or "Video object tagging failed")
        return status, object_scan, row
    return "skipped", {"reason": f"unknown lane {lane}"}, row


def _recent_enrichment_errors(limit: int = 8) -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT lane, path, last_error, updated_ts
        FROM enrichment_queue_items
        WHERE COALESCE(last_error, '') != ''
        ORDER BY updated_ts DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


def write_enrichment_snapshot(run_id: int | None, chunk_id: int | None, phase: str, current_item: dict | None = None, error: str | None = None) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime()) + f"-{int((time.time() % 1) * 1000):03d}"
    snapshot_dir = ENRICHMENT_SNAPSHOT_DIR / stamp
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    try:
        from app.model_router import route_for_task

        model_routes = {
            "summary": route_for_task("summary"),
            "vision": route_for_task("vision"),
            "embedding": route_for_task("embedding"),
            "reasoning": route_for_task("reasoning"),
        }
    except Exception:
        model_routes = {}
    coverage = deep_enrichment_coverage_report()
    payload = {
        "phase": phase,
        "created_ts": _now(),
        "run_id": run_id,
        "chunk_id": chunk_id,
        "run": _run_snapshot(run_id) if run_id else None,
        "chunk": _chunk_snapshot(chunk_id) if chunk_id else None,
        "current_item": current_item or {},
        "coverage": coverage,
        "queue_counts": _queue_counts(run_id),
        "model_routes": model_routes,
        "dependencies": coverage.get("dependencies") or {},
        "recent_errors": _recent_enrichment_errors(),
        "error": error or "",
    }
    path = snapshot_dir / "snapshot.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    if run_id:
        _set_run_status(run_id, (_run_snapshot(run_id) or {}).get("status") or "queued", last_snapshot_path=str(path))
    return str(path)


def _all_enabled_lanes_terminal(options: dict, coverage: dict | None = None) -> bool:
    coverage = coverage or deep_enrichment_coverage_report()
    lanes = coverage.get("lanes") or {}
    for lane in LANE_ORDER:
        if not _lane_enabled(lane, options):
            continue
        if lane == "index_refresh":
            continue
        item = lanes.get(lane) or {}
        if int(item.get("missing") or 0) > 0:
            return False
        if int(item.get("failed_retryable") or 0) > 0 and bool(options.get("retry_failed")):
            return False
    return True


def _save_completed_state(options: dict) -> None:
    state = _load_deep_enrichment_state()
    now = _now()
    state.update(
        {
            "last_completed_ts": now,
            "last_completed_mode": options.get("resolved_mode"),
            "last_options": options,
            "task_version": ENRICHMENT_TASK_VERSION,
            "baseline_completed_ts": state.get("baseline_completed_ts") or now,
            "baseline_file_count": _active_file_count(),
            "baseline_task_version": ENRICHMENT_TASK_VERSION,
        }
    )
    _save_deep_enrichment_state(state)


def _process_chunk(run_id: int, chunk: dict, options: dict, *, deadline: float | None = None) -> None:
    chunk_id = int(chunk["id"])
    lane = chunk.get("lane") or ""
    counts = _refresh_chunk_counts(chunk_id)
    _update_job(
        running=True,
        done=False,
        stop_requested=False,
        started_ts=_now(),
        finished_ts=None,
        phase=lane,
        lane=lane,
        run_id=run_id,
        chunk_id=chunk_id,
        total=counts.get("total", 0),
        processed=counts.get("processed", 0),
    )
    _set_run_status(run_id, "running", current_lane=lane, current_chunk_id=chunk_id, pause_requested=False)
    _set_chunk_status(chunk_id, "running")
    before = write_enrichment_snapshot(run_id, chunk_id, "before_chunk")
    _set_chunk_status(chunk_id, "running", snapshot_before_path=before)
    if deadline is None and options.get("max_runtime_minutes"):
        deadline = _now() + max(1, int(options["max_runtime_minutes"])) * 60
    try:
        while True:
            run = _run_snapshot(run_id) or {}
            if deep_enrichment_stop_requested.is_set() or run.get("pause_requested"):
                break
            if deadline and _now() >= deadline:
                _set_run_status(run_id, "pausing", pause_requested=True)
                break
            if not _wait_for_enrichment_slot(lane, options, deadline):
                _set_run_status(run_id, "pausing", pause_requested=True, last_error=_job_snapshot().get("throttle_reason") or None)
                break
            item = _claim_next_item(
                chunk_id,
                retry_failed=bool(options.get("retry_failed")),
                retry_deferred=bool(options.get("retry_deferred")),
            )
            if not item:
                break
            path = item.get("path") or ""
            _update_job(phase=lane, current_path=path)
            _set_chunk_status(chunk_id, "running", current_item_id=int(item["id"]))
            try:
                status, detail, row = _process_lane_item(item, options)
                if status not in {"completed", "skipped", "deferred"}:
                    status = "completed"
                _mark_item(int(item["id"]), status)
                if status == "completed":
                    _bump_job("succeeded")
                elif status == "skipped":
                    _bump_job("skipped")
                elif status == "deferred":
                    _bump_job("deferred")
                if status in {"completed", "skipped"} and path:
                    mark_index_success(path)
                if row and status in {"completed", "skipped", "deferred"} and lane in LANE_TASKS:
                    # Most processors mark their own file_enrichment row. This covers lane-level skips.
                    existing = _enrichment_record(int(row["id"]), LANE_TASKS[lane][0]) if row.get("id") else None
                    if not existing or existing.get("status") not in TERMINAL_ENRICHMENT_STATUSES:
                        _mark_lane_task(row, lane, status, detail)
            except Exception as error:
                row = _row_by_file_id(item.get("file_id"))
                attempts = int(item.get("attempts") or 1)
                max_attempts = int(item.get("max_attempts") or 2)
                should_defer = _is_timeout_error(error) and attempts >= max_attempts
                status = "deferred" if should_defer else "failed_retryable"
                detail = {
                    "error": str(error),
                    "attempts": attempts,
                    "max_attempts": max_attempts,
                    "deferred_reason": "timeout_quarantine" if should_defer else "",
                    "retry_eligible": True,
                    "lane": lane,
                }
                if row:
                    _mark_lane_task(row, lane, status, detail)
                _mark_item(int(item["id"]), status, error=str(error))
                if should_defer:
                    _bump_job("deferred")
                else:
                    _bump_job("failed")
                    _bump_job("retryable_failed")
                _record_failure(path, f"deep enrichment {lane}", error)
            finally:
                counts = _refresh_chunk_counts(chunk_id)
                _refresh_run_counts(run_id)
                _update_job(
                    processed=counts.get("processed", 0),
                    total=counts.get("total", 0),
                    failed=counts.get("failed_retryable", 0),
                    deferred=counts.get("deferred", 0),
                    skipped=counts.get("skipped", 0),
                )
    finally:
        counts = _refresh_chunk_counts(chunk_id)
        paused = deep_enrichment_stop_requested.is_set() or bool((_run_snapshot(run_id) or {}).get("pause_requested"))
        if paused and counts.get("pending", 0):
            chunk_status = "paused"
            run_status = "paused"
            done = False
        else:
            chunk_status = "completed"
            run_status = "completed" if _all_enabled_lanes_terminal(options) else "paused"
            done = True
        after = write_enrichment_snapshot(run_id, chunk_id, "after_chunk")
        _set_chunk_status(chunk_id, chunk_status, current_item_id=None, snapshot_after_path=after, finished=chunk_status == "completed")
        if run_status == "completed":
            _save_completed_state(options)
        _set_run_status(run_id, run_status, current_chunk_id=None, pause_requested=False, finished=run_status == "completed", last_snapshot_path=after)
        _refresh_run_counts(run_id)
        _update_job(
            running=False,
            done=done,
            stop_requested=paused,
            finished_ts=_now(),
            phase="",
            current_path="",
            last_snapshot_path=after,
            throttle_active=False,
            throttle_reason="",
        )


def deep_enrichment_plan(options: dict | None = None) -> dict:
    migrate_deferred_timeout_failures()
    recover_enrichment_queue()
    opts = _normalize_enrichment_options(options or {})
    coverage = deep_enrichment_coverage_report()
    recommendation = _recommended_lane(opts, coverage)
    latest = latest_enrichment_run()
    resumable = latest_resumable_enrichment_run()
    if resumable and recommendation.get("action") != "blocked":
        recommendation = {
            **recommendation,
            "action": "resume_chunk"
            if _has_existing_chunk_for_run(
                int(resumable["id"]),
                retry_failed=bool(opts.get("retry_failed")),
                retry_deferred=bool(opts.get("retry_deferred")),
            )
            else recommendation.get("action"),
            "resume_run_id": int(resumable["id"]),
            "reason": f"Resume durable run #{int(resumable['id'])}." if recommendation.get("action") != "idle" else recommendation.get("reason"),
        }
    return {
        "coverage": coverage,
        "queue": _queue_counts(),
        "latest_run": latest,
        "resumable_run": resumable,
        "recommendation": recommendation,
        "state": deep_enrichment_baseline_state(),
    }


def run_deep_enrichment(options: dict | None = None) -> None:
    options = _normalize_enrichment_options(options)
    reset_deep_enrichment_job_state(options)
    migrate_deferred_timeout_failures()
    recover_enrichment_queue()
    run_id = _select_run(options)
    deadline = _now() + max(1, int(options["max_runtime_minutes"])) * 60 if options.get("max_runtime_minutes") else None
    while True:
        selection_options = dict(options)
        if options.get("autopilot_all_lanes"):
            selection_options["lane"] = None
        recommendation = _recommended_lane(selection_options)
        chunk = _existing_chunk_for_run(
            run_id,
            retry_failed=bool(options.get("retry_failed")),
            retry_deferred=bool(options.get("retry_deferred")),
        )
        if not chunk:
            lane = selection_options.get("lane") or recommendation.get("lane")
            if lane:
                configured_chunk_size = _safe_int(options.get("chunk_size"), 0)
                if options.get("autopilot_all_lanes") and options.get("lane") and options.get("lane") != lane:
                    configured_chunk_size = 0
                chunk_size = configured_chunk_size or _safe_int(recommendation.get("chunk_size"), 0) or LANE_DEFAULT_CHUNK_SIZE.get(lane, 100)
                options["lane"] = lane
                options["chunk_size"] = chunk_size
                chunk = _seed_chunk(run_id, lane, options, chunk_size)
        if not chunk:
            snapshot = write_enrichment_snapshot(run_id, None, "no_chunk")
            if _all_enabled_lanes_terminal(options):
                _save_completed_state(options)
                _set_run_status(run_id, "completed", last_snapshot_path=snapshot, finished=True)
            else:
                _set_run_status(run_id, "paused", last_snapshot_path=snapshot)
            _update_job(running=False, done=True, finished_ts=_now(), last_snapshot_path=snapshot, phase="", current_path="")
            return
        _process_chunk(run_id, chunk, options, deadline=deadline)
        chunk_status = (_chunk_snapshot(int(chunk["id"])) or {}).get("status")
        if (
            not options.get("autopilot")
            or chunk_status != "completed"
            or deep_enrichment_stop_requested.is_set()
            or (deadline and _now() >= deadline)
            or _all_enabled_lanes_terminal(options)
        ):
            return


def start_deep_enrichment_thread(options: dict | None = None) -> tuple[bool, dict]:
    with deep_enrichment_thread_lock:
        snapshot = _job_snapshot()
        if snapshot.get("running"):
            return False, snapshot
        deep_enrichment_stop_requested.clear()
        thread = threading.Thread(target=run_deep_enrichment, kwargs={"options": options or {}}, daemon=True)
        thread.start()
        time.sleep(0.1)
        return True, _job_snapshot()


def pause_deep_enrichment_job() -> dict:
    snapshot = _job_snapshot()
    run_id = snapshot.get("run_id")
    if snapshot.get("running"):
        deep_enrichment_stop_requested.set()
        if run_id:
            _set_run_status(int(run_id), "pausing", pause_requested=True)
        _update_job(stop_requested=True)
    return _job_snapshot()


def stop_deep_enrichment_job() -> dict:
    return pause_deep_enrichment_job()


def resume_deep_enrichment_thread(run_id: int | None = None, options: dict | None = None) -> tuple[bool, dict]:
    opts = dict(options or {})
    if run_id:
        opts["resume_run_id"] = int(run_id)
    else:
        latest = latest_resumable_enrichment_run()
        if not latest:
            _update_job(last_error="No paused or incomplete enrichment run is available to resume.")
            return False, _job_snapshot()
        opts["resume_run_id"] = int(latest["id"])
        opts["resume_latest"] = True
    return start_deep_enrichment_thread(opts)


def deep_enrichment_status() -> dict:
    migrate_deferred_timeout_failures()
    state = deep_enrichment_baseline_state()
    plan = deep_enrichment_plan({})
    return {
        "job": _job_with_timing(_job_snapshot()),
        "coverage": plan.get("coverage") or deep_enrichment_coverage_report(),
        "state": state,
        "queue": plan.get("queue") or {},
        "latest_run": plan.get("latest_run"),
        "resumable_run": plan.get("resumable_run"),
        "recommendation": plan.get("recommendation") or {},
    }


def format_deep_enrichment_status(payload: dict) -> str:
    job = payload.get("job") or {}
    coverage = payload.get("coverage") or {}
    state = payload.get("state") or {}
    recommendation = payload.get("recommendation") or {}
    status = "running" if job.get("running") else "done" if job.get("done") else "idle"
    next_mode = state.get("next_mode") or "baseline"
    lines = [
        "Archive deep scan:",
        f"- Job: {status}; lane {job.get('lane') or job.get('phase') or 'none'}; processed {int(job.get('processed') or 0):,} of {int(job.get('total') or 0):,}; retryable {int(job.get('retryable_failed') or job.get('failed') or 0):,}; deferred {int(job.get('deferred') or 0):,}.",
        f"- Mode: next run is {'a new/changed-file incremental pass' if next_mode == 'incremental' else 'lane milestone recovery/baseline'}; recommendation: {recommendation.get('reason') or 'none'}.",
    ]
    if job.get("current_path"):
        lines.append(f"- Current: {job.get('current_path')}")
    if job.get("last_snapshot_path"):
        lines.append(f"- Last snapshot: {job.get('last_snapshot_path')}")
    if job.get("last_error"):
        lines.append(f"- Last error: {job.get('last_error')}")
    lanes = coverage.get("lanes") or {}
    for lane in LANE_ORDER:
        item = lanes.get(lane)
        if not item:
            continue
        lines.append(
            f"- {item.get('label')}: terminal {int(item.get('terminal') or 0):,}/{int(item.get('total') or 0):,}; "
            f"missing {int(item.get('missing') or 0):,}; deferred {int(item.get('deferred') or 0):,}; retryable {int(item.get('failed_retryable') or 0):,}."
        )
    return "\n".join(lines)


def format_deep_enrichment_coverage_explanation(payload: dict, lane: str | None = None, limit: int = 6) -> str:
    coverage = payload.get("coverage") or payload
    lanes = coverage.get("lanes") or {}
    if lane and lane in lanes:
        selected = [(lane, lanes[lane])]
    else:
        active = []
        for key in LANE_ORDER:
            item = lanes.get(key)
            if not item:
                continue
            issue_count = int(item.get("missing") or 0) + int(item.get("deferred") or 0) + int(item.get("failed_retryable") or item.get("failed") or 0)
            if issue_count:
                active.append((key, item))
        selected = active[: max(1, int(limit))]
        if not selected:
            selected = [(key, lanes[key]) for key in LANE_ORDER if key in lanes][: max(1, int(limit))]
    lines = ["Archive coverage:"]
    if not selected:
        lines.append("- Coverage has not loaded yet.")
        return "\n".join(lines)
    for key, item in selected:
        explanation = item.get("explanation") or {}
        label = item.get("label") or LANE_LABELS.get(key, key)
        lines.append(
            f"- {label}: {explanation.get('summary') or 'No explanation available.'} "
            f"Terminal {int(item.get('terminal') or 0):,}/{int(item.get('total') or 0):,}; "
            f"missing {int(item.get('missing') or 0):,}; deferred {int(item.get('deferred') or 0):,}; "
            f"retryable {int(item.get('failed_retryable') or item.get('failed') or 0):,}."
        )
        if explanation.get("next_step"):
            lines.append(f"  Next: {explanation['next_step']}")
        for sample in (explanation.get("samples") or item.get("samples") or [])[:2]:
            detail = f" - {sample.get('detail')}" if sample.get("detail") else ""
            lines.append(f"  Sample: {sample.get('label') or sample.get('path') or 'item'} ({sample.get('status') or 'unknown'}){detail}")
    dependencies = coverage.get("dependencies") or {}
    dependency_notes = []
    for key, status in dependencies.items():
        if isinstance(status, dict) and status.get("ready") is False and status.get("hint"):
            dependency_notes.append(f"{key}: {status.get('hint')}")
    if dependency_notes:
        lines.append("")
        lines.append("Dependency notes:")
        for note in dependency_notes[:3]:
            lines.append(f"- {note}")
    return "\n".join(lines)
