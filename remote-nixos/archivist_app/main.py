from pathlib import Path
import json
import re
import shutil
import subprocess
import sys
import threading
import time

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import ARCHIVE_DUP_REVIEW_DIR, ARCHIVE_REVIEW_DIR, ARCHIVE_ROOT, DATA_DIR, UPLOAD_DIR, REVIEW_UNCERTAIN_DIR
from app.access_control import private_access_middleware
from app.archive_locations import (
    add_additional_root,
    archive_location_status,
    browse_directories,
    remove_additional_root,
    set_archive_root,
    set_source_slot,
)
from app.cowriter import (
    ask as cowriter_ask,
    current_document,
    document_timeline,
    edit_selection as cowriter_edit_selection,
    help_write as cowriter_help_write,
    import_uploaded_document,
    load_document_file,
    preview_draft as cowriter_preview_draft,
    save_document,
    save_version,
)
from app.constellation import data_constellation
from app.db import clear_file_index, init_db, get_conn
from app.discovery import discovery_constellation
from app.explorer import list_explorer_directory
from app.models import (
    AdminDevelopmentTaskCreateRequest,
    AdminDevelopmentTaskUpdateRequest,
    AdminConnectStartRequest,
    AdminConnectVerifyRequest,
    AdminControlRequest,
    ArchiveLocationRequest,
    ArchiveSourceSlotRequest,
    ChatRequest,
    ClipboardTextRequest,
    CoWriterDocumentRequest,
    CoWriterLoadRequest,
    CoWriterPromptRequest,
    DeletionQueuePathRequest,
    DeletionQueueRequest,
    FauxdexEngineRequest,
    FauxdexPlanRequest,
    FileIdsRequest,
    HostStatsSettingsRequest,
    IndexSchedulerRequest,
    MediaSegmentRequest,
    MemoryCreateRequest,
    MoveQueuedDuplicatesRequest,
    NoteCreateRequest,
    NoteUpdateRequest,
    FaceObservationRequest,
    FaceBackfillRequest,
    FaceDetectionRequest,
    TagApplyRequest,
    PersonFaceLinkRequest,
    PersonRequest,
    PersonUpdateRequest,
    TimelineEventPersonRequest,
    TimelineEventRequest,
    TimelineEventUpdateRequest,
    TimelineEvidenceRequest,
    VideoAnalyzeRequest,
    VideoArchiveScanRequest,
    VideoTranscribeRequest,
    VisionAnalysisRequest,
    WeatherSettingsRequest,
)
from app.admin_development import (
    attach_action_to_task,
    create_development_task,
    development_task_summary,
    get_development_task,
    list_development_tasks,
    next_development_task,
    seed_development_tasks,
    update_development_task,
)
from app.admin_connect import (
    easy_connect_status,
    installer_profile,
    reset_easy_connect,
    start_easy_connect,
    verify_easy_connect,
)
from app.admin_controls import (
    archive_control_status,
    free_gpu,
    host_stats,
    request_server_restart,
    request_server_stop,
    update_host_stats_settings,
)
from app.admin_patch_service import (
    admin_apply_readiness_payload,
    admin_diff_validation_payload,
    admin_patch_apply_payload,
    admin_patch_proposal_payload,
    admin_patch_rollback_payload,
    admin_patch_snapshot_payload,
    admin_unified_diff_proposal_payload,
    execute_admin_patch_apply_action,
    execute_admin_patch_rollback_action,
    format_admin_apply_readiness,
    format_admin_diff_validation,
    format_admin_patch_apply,
    format_admin_patch_proposal,
    format_admin_patch_rollback,
    format_admin_patch_snapshot,
)
from app.admin_tool_catalog import ADMIN_ENGINE_TOOLS, admin_engine_tools_payload, format_admin_tool_catalog
from app.media_tools import (
    add_video_segment,
    analyze_video,
    ffmpeg_status,
    search_video_context,
    transcription_status,
    transcribe_video,
    video_analysis_presets,
    video_context,
    video_scan_candidates,
)
from app.autotagging import apply_auto_tags
from app.face_tools import face_engine_status, scan_file_faces, scan_indexed_media_faces
from app.vision_tools import analyze_image_file, vision_status
from app.indexer import index_file, walk_archive
from app.index_state import (
    add_queue_item,
    claim_next_pending,
    create_run,
    latest_resumable_run,
    latest_run,
    mark_queue_item,
    mark_run_error,
    recover_interrupted_runs,
    reset_running_items,
    run_snapshot,
    set_run_status,
)
from app.index_snapshot import snapshot_file_index
from app.fauxdex import ENGINE_PLAN_SCHEMA, plan_fauxdex_task, plan_intelligent_admin_task
from app.file_operator import (
    audit_action,
    cancel_action_by_id,
    confirm_action_by_id,
    latest_pending_action,
    load_action,
    recent_actions,
    update_action,
)
from app.dashboard import dashboard_context, update_weather_settings, weather_context
from app.chat_engine import add_embedding, answer_query, keyword_search, reset_archive_embeddings, semantic_search, sync_file_embedding_by_id
from app.embeddings import chat_messages
from app.maintenance import (
    PRE_INDEX_DEDUPE_REASON,
    apply_tag,
    archive_stats,
    duplicate_keeper_key,
    duplicate_groups,
    list_files,
    list_tags,
    mark_index_success,
    move_queued_duplicates_to_review,
    queue_exact_duplicates_for_review,
    queue_deletion,
    queue_deletion_by_path,
    recategorize_file_index,
    recent_index_failures,
    record_index_failure,
    remove_file_index_paths,
    remove_tag,
    retarget_preindex_duplicates,
    unqueue_deletion,
    upsert_preindex_hash_record,
)
from app.memory import (
    add_message,
    create_memory,
    ensure_conversation,
    list_conversations,
    list_memories,
    list_messages,
    memory_status,
    maybe_capture_memory,
)
from app.model_router import model_for_task, model_matrix, route_for_task
from app.notes import (
    clear_clipboard,
    create_clipboard_file,
    create_clipboard_text,
    create_note,
    create_note_from_upload,
    list_clipboard,
    list_notes,
    update_note,
)
from app.timeline import (
    add_event_evidence,
    add_event_person,
    create_face_observation,
    create_person,
    create_timeline_event,
    get_person,
    get_timeline_event,
    link_person_face,
    list_face_observations,
    list_people,
    list_timeline_events,
    timeline_overview,
    update_person,
    update_timeline_event,
)
from app.source_safety import is_chat_safe_source
from app.utils import (
    clean_filename,
    ensure_parent,
    file_category,
    guess_mime,
    move_to,
    path_is_inside,
    resolve_allowed_path,
    safe_relative_folder,
    sha256_file,
    unique_path,
)
from app.worker import run_watcher

app = FastAPI(title="AI Archivist OS")
app.middleware("http")(private_access_middleware)
app.mount("/web", StaticFiles(directory="web"), name="web")
app.mount("/data", StaticFiles(directory="data"), name="data")

INDEX_ALLOWED_ROOTS = [ARCHIVE_ROOT, DATA_DIR]
index_job_lock = threading.Lock()
index_job = {
    "running": False,
    "done": False,
    "paused": False,
    "pause_requested": False,
    "building_queue": False,
    "run_status": "",
    "active_run_id": None,
    "force": False,
    "started_ts": None,
    "finished_ts": None,
    "total_files": 0,
    "total_seen": 0,
    "indexed_count": 0,
    "duplicate_count": 0,
    "skipped_count": 0,
    "failed_count": 0,
    "pending_count": 0,
    "current_path": "",
    "last_error": "",
    "throttle_active": False,
    "throttle_until_ts": None,
}
index_pause_requested = threading.Event()
index_thread_lock = threading.Lock()
last_chat_activity_lock = threading.Lock()
last_chat_activity_ts = 0.0
index_scheduler = {
    "throttle_enabled": True,
    "chat_idle_seconds": 180,
}
embedding_rebuild_job_lock = threading.Lock()
embedding_rebuild_job = {
    "running": False,
    "done": False,
    "started_ts": None,
    "finished_ts": None,
    "total": 0,
    "processed": 0,
    "failed": 0,
    "current_path": "",
    "last_error": "",
    "detect_faces": True,
    "detect_objects": False,
}
pre_dedupe_job_lock = threading.Lock()
pre_dedupe_job = {
    "running": False,
    "done": False,
    "started_ts": None,
    "finished_ts": None,
    "total_seen": 0,
    "unique_count": 0,
    "duplicate_count": 0,
    "queued_count": 0,
    "failed_count": 0,
    "reclaimable_bytes": 0,
    "groups": 0,
    "current_path": "",
    "last_error": "",
}
video_scan_job_lock = threading.Lock()
video_scan_thread_lock = threading.Lock()
video_scan_stop_requested = threading.Event()
video_scan_job = {
    "running": False,
    "done": False,
    "stop_requested": False,
    "started_ts": None,
    "finished_ts": None,
    "preset": "",
    "update_index": True,
    "rescan_existing": False,
    "include_delete_queue": False,
    "total": 0,
    "processed": 0,
    "succeeded": 0,
    "failed": 0,
    "skipped": 0,
    "current_path": "",
    "last_error": "",
}


def index_job_snapshot():
    with index_job_lock:
        return dict(index_job)


def update_index_job(**fields):
    with index_job_lock:
        index_job.update(fields)


def note_chat_activity():
    global last_chat_activity_ts
    with last_chat_activity_lock:
        last_chat_activity_ts = time.time()


def scheduler_snapshot() -> dict:
    with last_chat_activity_lock:
        last_activity = last_chat_activity_ts
    idle_for = max(0.0, time.time() - last_activity) if last_activity else None
    seconds_until_full_speed = 0
    if index_scheduler["throttle_enabled"] and last_activity:
        seconds_until_full_speed = max(0, int(index_scheduler["chat_idle_seconds"] - (idle_for or 0)))
    return {
        "throttle_enabled": index_scheduler["throttle_enabled"],
        "chat_idle_seconds": index_scheduler["chat_idle_seconds"],
        "last_chat_activity_ts": last_activity or None,
        "idle_for_seconds": idle_for,
        "throttle_active": seconds_until_full_speed > 0,
        "seconds_until_full_speed": seconds_until_full_speed,
    }


def index_should_throttle() -> tuple[bool, float | None]:
    snap = scheduler_snapshot()
    if not snap["throttle_active"]:
        return False, None
    until_ts = time.time() + snap["seconds_until_full_speed"]
    return True, until_ts


def wait_for_index_slot() -> bool:
    while not index_pause_requested.is_set():
        active, until_ts = index_should_throttle()
        if not active:
            update_index_job(throttle_active=False, throttle_until_ts=None)
            return True
        update_index_job(throttle_active=True, throttle_until_ts=until_ts)
        time.sleep(1.0)
    return False


def apply_persistent_run_snapshot(run_id: int | None) -> None:
    if not run_id:
        return
    snap = run_snapshot(run_id)
    if not snap:
        return
    status = snap.get("status")
    update_index_job(
        active_run_id=run_id,
        run_status=status or "",
        running=status == "running",
        building_queue=status == "building",
        paused=status == "paused",
        done=status == "done",
        pause_requested=status == "pausing",
        force=bool(snap.get("force")),
        started_ts=snap.get("started_ts"),
        finished_ts=snap.get("finished_ts"),
        total_files=snap.get("total_files", 0),
        total_seen=snap.get("total_seen", 0),
        indexed_count=snap.get("indexed_count", 0),
        duplicate_count=snap.get("duplicate_count", 0),
        skipped_count=snap.get("skipped_count", 0),
        failed_count=snap.get("failed_count", 0),
        pending_count=snap.get("pending_count", 0),
        current_path=snap.get("current_path") or "",
        last_error=snap.get("last_error") or "",
    )


def pre_dedupe_job_snapshot():
    with pre_dedupe_job_lock:
        return dict(pre_dedupe_job)


def update_pre_dedupe_job(**fields):
    with pre_dedupe_job_lock:
        pre_dedupe_job.update(fields)


def video_scan_job_snapshot():
    with video_scan_job_lock:
        return dict(video_scan_job)


def update_video_scan_job(**fields):
    with video_scan_job_lock:
        video_scan_job.update(fields)


def reset_video_scan_job_state():
    video_scan_stop_requested.clear()
    update_video_scan_job(
        running=False,
        done=False,
        stop_requested=False,
        started_ts=None,
        finished_ts=None,
        preset="",
        update_index=True,
        rescan_existing=False,
        include_delete_queue=False,
        total=0,
        processed=0,
        succeeded=0,
        failed=0,
        skipped=0,
        current_path="",
        last_error="",
        detect_faces=True,
        detect_objects=False,
    )


def reset_pre_dedupe_job_state():
    update_pre_dedupe_job(
        running=False,
        done=False,
        started_ts=None,
        finished_ts=None,
        total_seen=0,
        unique_count=0,
        duplicate_count=0,
        queued_count=0,
        failed_count=0,
        reclaimable_bytes=0,
        groups=0,
        current_path="",
        last_error="",
    )


def embedding_rebuild_job_snapshot():
    with embedding_rebuild_job_lock:
        return dict(embedding_rebuild_job)


def update_embedding_rebuild_job(**fields):
    with embedding_rebuild_job_lock:
        embedding_rebuild_job.update(fields)


def embedding_rebuild_plan() -> dict:
    conn = get_conn()
    cur = conn.cursor()
    active_where = """
        deleted_candidate = 0
        AND path NOT LIKE ?
        AND path NOT LIKE ?
    """
    params = [f"{str(ARCHIVE_REVIEW_DIR)}%", f"{str(ARCHIVE_DUP_REVIEW_DIR)}%"]
    cur.execute(f"SELECT COUNT(*) AS count FROM files WHERE {active_where}", params)
    active_total = int(cur.fetchone()["count"] or 0)
    cur.execute(f"SELECT path FROM files WHERE {active_where}", params)
    embeddable_count = sum(1 for row in cur.fetchall() if is_chat_safe_source(row["path"]))
    cur.execute("SELECT COUNT(*) AS count FROM files WHERE deleted_candidate = 1")
    review = int(cur.fetchone()["count"] or 0)
    cur.execute(
        f"""
        SELECT id, path, name, category, summary
        FROM files
        WHERE {active_where}
        ORDER BY indexed_ts DESC, id DESC
        LIMIT 8
        """,
        params,
    )
    sample = []
    for row in cur.fetchall():
        item = dict(row)
        if is_chat_safe_source(item.get("path") or ""):
            sample.append(item)
        if len(sample) >= 8:
            break
    conn.close()
    return {
        "active_files": embeddable_count,
        "indexed_active_files": active_total,
        "chat_ignored_files": max(active_total - embeddable_count, 0),
        "review_excluded_files": review,
        "collection": "archive_files",
        "sample": sample,
    }


def embedding_rebuild_rows() -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT path, name, category, summary, extracted_text
        FROM files
        WHERE deleted_candidate = 0
          AND path NOT LIKE ?
          AND path NOT LIKE ?
        ORDER BY indexed_ts DESC, id DESC
        """,
        (f"{str(ARCHIVE_REVIEW_DIR)}%", f"{str(ARCHIVE_DUP_REVIEW_DIR)}%"),
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return [row for row in rows if is_chat_safe_source(row.get("path") or "")]


def run_embedding_rebuild_job():
    update_embedding_rebuild_job(
        running=True,
        done=False,
        started_ts=time.time(),
        finished_ts=None,
        total=0,
        processed=0,
        failed=0,
        current_path="Resetting archive embeddings...",
        last_error="",
    )
    rows = []
    try:
        reset_archive_embeddings()
        rows = embedding_rebuild_rows()
        update_embedding_rebuild_job(total=len(rows), current_path="")
        for row in rows:
            path = row.get("path") or ""
            update_embedding_rebuild_job(current_path=path)
            try:
                category = row.get("category") or "other"
                summary = row.get("summary") or ""
                extracted = row.get("extracted_text") or ""
                text = "\n".join([row.get("name") or Path(path).name, summary, extracted[:6000]]).strip()
                corpus = "knowledgebase" if category == "knowledgebase" else "archive"
                embedded = add_embedding(
                    doc_id=path,
                    text=text,
                    metadata={
                        "path": path,
                        "name": row.get("name") or Path(path).name,
                        "category": category,
                        "corpus": corpus,
                        "summary": summary,
                    },
                )
                if not embedded:
                    raise RuntimeError("Embedding upsert failed")
            except Exception as e:
                snapshot = embedding_rebuild_job_snapshot()
                update_embedding_rebuild_job(failed=int(snapshot.get("failed") or 0) + 1, last_error=f"{path}: {e}")
            finally:
                snapshot = embedding_rebuild_job_snapshot()
                update_embedding_rebuild_job(processed=int(snapshot.get("processed") or 0) + 1)
    finally:
        update_embedding_rebuild_job(
            running=False,
            done=True,
            finished_ts=time.time(),
            current_path="",
            total=len(rows),
        )


def embedding_rebuild_summary(job: dict | None = None) -> str:
    job = job or embedding_rebuild_job_snapshot()
    status = "running" if job.get("running") else "done" if job.get("done") else "idle"
    return (
        f"status `{status}`; processed {int(job.get('processed') or 0):,} "
        f"of {int(job.get('total') or 0):,}; failed {int(job.get('failed') or 0):,}"
    )


def start_embedding_rebuild_thread() -> tuple[bool, dict]:
    snapshot = embedding_rebuild_job_snapshot()
    if snapshot.get("running"):
        return False, snapshot
    thread = threading.Thread(target=run_embedding_rebuild_job, daemon=True)
    thread.start()
    time.sleep(0.1)
    return True, embedding_rebuild_job_snapshot()


def run_pre_dedupe_job():
    update_pre_dedupe_job(
        running=True,
        done=False,
        started_ts=time.time(),
        finished_ts=None,
        total_seen=0,
        unique_count=0,
        duplicate_count=0,
        queued_count=0,
        failed_count=0,
        reclaimable_bytes=0,
        groups=0,
        current_path="",
        last_error="",
    )
    seen: dict[str, str] = {}
    duplicate_groups_seen: set[str] = set()
    try:
        for path in walk_archive() or []:
            snapshot = pre_dedupe_job_snapshot()
            update_pre_dedupe_job(total_seen=snapshot["total_seen"] + 1, current_path=str(path))
            try:
                file_hash = sha256_file(path)
                current_path = str(path)
                keeper_path = seen.get(file_hash)
                snapshot = pre_dedupe_job_snapshot()
                if not keeper_path:
                    seen[file_hash] = current_path
                    upsert_preindex_hash_record(path, file_hash)
                    update_pre_dedupe_job(unique_count=snapshot["unique_count"] + 1)
                    continue

                duplicate_groups_seen.add(file_hash)
                if duplicate_keeper_key(current_path) < duplicate_keeper_key(keeper_path):
                    old_keeper = keeper_path
                    seen[file_hash] = current_path
                    upsert_preindex_hash_record(path, file_hash)
                    result = upsert_preindex_hash_record(Path(old_keeper), file_hash, duplicate_of=current_path)
                    retarget_preindex_duplicates(old_keeper, current_path)
                else:
                    result = upsert_preindex_hash_record(path, file_hash, duplicate_of=keeper_path)

                snapshot = pre_dedupe_job_snapshot()
                update_pre_dedupe_job(
                    duplicate_count=snapshot["duplicate_count"] + 1,
                    queued_count=snapshot["queued_count"] + int(result.get("queued") or 0),
                    reclaimable_bytes=snapshot["reclaimable_bytes"] + int(result.get("size_bytes") or 0),
                    groups=len(duplicate_groups_seen),
                )
            except Exception as e:
                snapshot = pre_dedupe_job_snapshot()
                update_pre_dedupe_job(
                    failed_count=snapshot["failed_count"] + 1,
                    last_error=f"{path}: {e}",
                )
                record_index_failure(str(path), f"pre-index dedupe scan: {e}")
    finally:
        update_pre_dedupe_job(running=False, done=True, finished_ts=time.time(), current_path="")


def run_video_archive_scan(
    *,
    preset: str = "quick_skim",
    update_index: bool = True,
    rescan_existing: bool = False,
    include_delete_queue: bool = False,
    limit: int | None = None,
    detect_faces: bool = True,
    detect_objects: bool = False,
):
    candidates = []
    try:
        candidates = video_scan_candidates(
            rescan_existing=rescan_existing,
            include_delete_queue=include_delete_queue,
            limit=limit,
        )
        update_video_scan_job(
            running=True,
            done=False,
            stop_requested=False,
            started_ts=time.time(),
            finished_ts=None,
            preset=preset,
            update_index=update_index,
            rescan_existing=rescan_existing,
            include_delete_queue=include_delete_queue,
            total=len(candidates),
            detect_faces=detect_faces,
            detect_objects=detect_objects,
            processed=0,
            succeeded=0,
            failed=0,
            skipped=0,
            current_path="",
            last_error="",
        )
        for item in candidates:
            if video_scan_stop_requested.is_set():
                update_video_scan_job(stop_requested=True, current_path="")
                return
            if not wait_for_index_slot():
                update_video_scan_job(stop_requested=True, current_path="")
                return
            path = item["path"]
            snapshot = video_scan_job_snapshot()
            update_video_scan_job(current_path=path, processed=int(snapshot.get("processed") or 0) + 1)
            try:
                analyze_video(
                    file_id=int(item["id"]),
                    preset=preset,
                    update_index=update_index,
                    detect_faces=detect_faces,
                    detect_objects=detect_objects,
                )
                snapshot = video_scan_job_snapshot()
                update_video_scan_job(succeeded=int(snapshot.get("succeeded") or 0) + 1)
            except FileNotFoundError:
                snapshot = video_scan_job_snapshot()
                update_video_scan_job(skipped=int(snapshot.get("skipped") or 0) + 1)
            except Exception as e:
                snapshot = video_scan_job_snapshot()
                error = f"{path}: {e}"
                update_video_scan_job(
                    failed=int(snapshot.get("failed") or 0) + 1,
                    last_error=error,
                )
                record_index_failure(path, f"video context scan: {e}")
    except Exception as e:
        update_video_scan_job(last_error=str(e))
    finally:
        stopped = video_scan_stop_requested.is_set()
        update_video_scan_job(
            running=False,
            done=not stopped,
            stop_requested=stopped,
            finished_ts=time.time(),
            current_path="",
        )


def build_index_queue(run_id: int) -> bool:
    set_run_status(run_id, "building")
    update_index_job(building_queue=True, run_status="building", current_path="Building persistent index queue...")
    queued = 0
    try:
        for path in walk_archive() or []:
            if index_pause_requested.is_set():
                set_run_status(run_id, "paused", current_path="")
                update_index_job(
                    building_queue=False,
                    paused=True,
                    running=False,
                    pause_requested=False,
                    run_status="paused",
                    current_path="",
                )
                return False
            if add_queue_item(run_id, path):
                queued += 1
                if queued % 250 == 0:
                    update_index_job(total_files=queued, pending_count=queued)
    finally:
        update_index_job(building_queue=False)
    update_index_job(total_files=queued, pending_count=queued)
    set_run_status(run_id, "queued", current_path="")
    update_index_job(run_status="queued")
    return True


def run_index_job(force: bool = False, run_id: int | None = None, resume: bool = False):
    try:
        if run_id is None:
            run_id = create_run(force=force, note="Full archive index")
            update_index_job(active_run_id=run_id)
            queue_ready = build_index_queue(run_id)
            if not queue_ready:
                return
        else:
            snap = run_snapshot(run_id)
            if snap:
                force = bool(snap.get("force"))
                if snap.get("status") == "building":
                    queue_ready = build_index_queue(run_id)
                    if not queue_ready:
                        return
            reset_running_items(run_id)
    except Exception as e:
        error = f"Failed to build or resume index queue: {e}"
        if run_id:
            set_run_status(run_id, "failed", last_error=error, finished=True)
        update_index_job(
            running=False,
            done=False,
            paused=False,
            pause_requested=False,
            building_queue=False,
            run_status="failed",
            current_path="",
            last_error=error,
            finished_ts=time.time(),
        )
        return

    index_pause_requested.clear()
    set_run_status(run_id, "running")
    update_index_job(
        running=True,
        done=False,
        paused=False,
        pause_requested=False,
        building_queue=False,
        run_status="running",
        active_run_id=run_id,
        force=force,
        started_ts=time.time(),
        finished_ts=None,
        total_seen=0,
        indexed_count=0,
        duplicate_count=0,
        skipped_count=0,
        failed_count=0,
        pending_count=0,
        current_path="",
        last_error="",
        throttle_active=False,
        throttle_until_ts=None,
    )
    apply_persistent_run_snapshot(run_id)
    try:
        while True:
            if index_pause_requested.is_set():
                set_run_status(run_id, "paused", current_path="")
                update_index_job(
                    running=False,
                    paused=True,
                    pause_requested=False,
                    run_status="paused",
                    current_path="",
                    throttle_active=False,
                )
                return
            if not wait_for_index_slot():
                set_run_status(run_id, "paused", current_path="")
                update_index_job(
                    running=False,
                    paused=True,
                    pause_requested=False,
                    run_status="paused",
                    current_path="",
                    throttle_active=False,
                )
                return

            item = claim_next_pending(run_id)
            if not item:
                set_run_status(run_id, "done", current_path="", finished=True)
                apply_persistent_run_snapshot(run_id)
                return

            path = Path(item["path"])
            update_index_job(current_path=str(path))
            try:
                record = index_file(path, force=force)
                if record and record.get("duplicate"):
                    mark_queue_item(item["id"], "duplicate")
                elif record and record.get("skipped"):
                    mark_queue_item(item["id"], "skipped")
                elif record:
                    mark_queue_item(item["id"], "indexed")
                    mark_index_success(str(path))
                else:
                    mark_queue_item(item["id"], "skipped")
            except Exception as e:
                error = f"{path}: {e}"
                update_index_job(last_error=error)
                mark_queue_item(item["id"], "failed", str(e))
                mark_run_error(run_id, error)
                record_index_failure(str(path), str(e))
                print(f"[index-all] failed {path}: {e}")
            apply_persistent_run_snapshot(run_id)
    finally:
        snapshot = run_snapshot(run_id)
        status = snapshot.get("status") if snapshot else ""
        update_index_job(
            running=False,
            done=status == "done",
            paused=status == "paused",
            run_status=status or "",
            finished_ts=(snapshot or {}).get("finished_ts") if snapshot else time.time(),
            current_path="",
            throttle_active=False,
            throttle_until_ts=None,
        )


def reset_index_job_state():
    index_pause_requested.clear()
    update_index_job(
        running=False,
        done=False,
        paused=False,
        pause_requested=False,
        building_queue=False,
        run_status="",
        active_run_id=None,
        force=False,
        started_ts=None,
        finished_ts=None,
        total_files=0,
        total_seen=0,
        indexed_count=0,
        duplicate_count=0,
        skipped_count=0,
        failed_count=0,
        pending_count=0,
        current_path="",
        last_error="",
        throttle_active=False,
        throttle_until_ts=None,
    )


def index_is_active(snapshot: dict | None = None) -> bool:
    snapshot = snapshot or index_job_snapshot()
    return bool(snapshot.get("running") or snapshot.get("building_queue") or snapshot.get("pause_requested"))


def restore_index_status_from_files() -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN duplicate_of IS NOT NULL AND duplicate_of != '' THEN 1 ELSE 0 END) AS duplicates,
            MAX(indexed_ts) AS last_indexed_ts
        FROM files
        """
    )
    totals = dict(cur.fetchone())
    cur.execute("SELECT COUNT(*) AS count FROM index_failures")
    failures = int(cur.fetchone()["count"] or 0)
    conn.close()
    total = int(totals.get("total") or 0)
    if not total:
        return
    duplicates = int(totals.get("duplicates") or 0)
    update_index_job(
        running=False,
        done=True,
        paused=False,
        pause_requested=False,
        building_queue=False,
        run_status="done",
        active_run_id=None,
        force=False,
        started_ts=None,
        finished_ts=totals.get("last_indexed_ts"),
        total_files=total,
        total_seen=total,
        indexed_count=max(0, total - duplicates),
        duplicate_count=duplicates,
        skipped_count=0,
        failed_count=failures,
        pending_count=0,
        current_path="",
        last_error="",
        throttle_active=False,
        throttle_until_ts=None,
    )


def index_status_payload() -> dict:
    snapshot = index_job_snapshot()
    run_id = snapshot.get("active_run_id")
    if run_id:
        apply_persistent_run_snapshot(int(run_id))
    elif not index_is_active(snapshot):
        run = latest_run()
        if run:
            apply_persistent_run_snapshot(int(run["id"]))
        else:
            restore_index_status_from_files()
    snapshot = index_job_snapshot()
    snapshot["scheduler"] = scheduler_snapshot()
    return snapshot


def start_index_thread(*, force: bool, run_id: int | None = None, resume: bool = False) -> tuple[bool, dict]:
    with index_thread_lock:
        snapshot = index_job_snapshot()
        if index_is_active(snapshot):
            return False, index_status_payload()
        index_pause_requested.clear()
        update_index_job(
            running=True,
            done=False,
            paused=False,
            pause_requested=False,
            building_queue=run_id is None,
            run_status="starting",
            active_run_id=run_id,
            force=force,
            started_ts=time.time(),
            finished_ts=None,
            current_path="Starting index run...",
            last_error="",
            throttle_active=False,
            throttle_until_ts=None,
        )
        thread = threading.Thread(
            target=run_index_job,
            kwargs={"force": force, "run_id": run_id, "resume": resume},
            daemon=True,
        )
        thread.start()
        return True, index_status_payload()


def chat_index_summary(job: dict) -> str:
    status = job.get("run_status") or ("running" if job.get("running") else "idle")
    seen = int(job.get("total_seen") or 0)
    total = int(job.get("total_files") or 0)
    pending = int(job.get("pending_count") or 0)
    indexed = int(job.get("indexed_count") or 0)
    duplicates = int(job.get("duplicate_count") or 0)
    failed = int(job.get("failed_count") or 0)
    current = job.get("current_path") or ""
    parts = [
        f"status `{status}`",
        f"seen {seen:,}" + (f" of {total:,}" if total else ""),
        f"pending {pending:,}",
        f"indexed {indexed:,}",
        f"duplicates {duplicates:,}",
        f"failed {failed:,}",
    ]
    if current:
        parts.append(f"current `{current}`")
    return "; ".join(parts)


def project_status_terms(query: str) -> list[str]:
    lowered = query.lower()
    known = [
        "vanishing share",
        "vanishing share link",
        "temporary share",
        "share link",
        "tailscale",
        "intelligent admin",
        "fauxdex",
    ]
    terms = [term for term in known if term in lowered]
    if terms:
        return terms
    words = [
        word
        for word in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{3,}", lowered)
        if word not in {"status", "update", "project", "development", "progress", "please", "about", "what", "ready"}
    ]
    return words[:4]


def admin_project_status_payload(query: str) -> dict:
    terms = project_status_terms(query)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM action_audit
        ORDER BY created_ts DESC, id DESC
        LIMIT 120
        """
    )
    rows = cur.fetchall()
    conn.close()
    matches = []
    patch_proposals = []
    validations = []
    snapshots = []
    apply_requests = []
    for row in rows:
        item = dict(row)
        params = json.loads(item.get("params_json") or "{}")
        result = json.loads(item.get("result_json") or "{}")
        haystack = json.dumps({"params": params, "result": result, "tool": item.get("tool"), "intent": item.get("intent")}, default=str).lower()
        if terms and not any(term in haystack for term in terms):
            continue
        summary = {
            "id": item["id"],
            "tool": item.get("tool"),
            "status": item.get("status"),
            "intent": item.get("intent"),
            "params": params,
            "result_summary": {
                "task": result.get("task"),
                "proposal_action_id": result.get("proposal_action_id"),
                "action_id": result.get("action_id"),
                "snapshot_dir": result.get("snapshot_dir"),
                "error": result.get("error"),
            },
        }
        matches.append(summary)
        if item.get("tool") == "admin.patch_proposal":
            patch_proposals.append(summary)
        elif item.get("tool") == "admin.diff_validation":
            validations.append(summary)
        elif item.get("tool") == "admin.patch_snapshot":
            snapshots.append(summary)
        elif item.get("tool") == "admin.patch_apply":
            apply_requests.append(summary)
    has_patch = bool(patch_proposals)
    return {
        "query": query,
        "terms": terms,
        "matches": matches[:20],
        "patch_proposals": patch_proposals[:10],
        "validations": validations[:10],
        "snapshots": snapshots[:10],
        "apply_requests": apply_requests[:10],
        "has_patch_proposal": has_patch,
        "status": "staged_patch_exists" if has_patch else "planning_only",
        "truth_note": (
            "A staged patch proposal exists in the audit ledger."
            if has_patch
            else "No audited patch proposal exists for this project yet. Any prior claim that code drafts were ready should be treated as unverified planning text."
        ),
    }


def format_admin_project_status(payload: dict) -> str:
    terms = ", ".join(payload.get("terms") or []) or "general"
    lines = [
        "Project status from audit ledger:",
        f"- Search terms: {terms}.",
        f"- Status: {payload.get('status')}.",
        f"- Truth note: {payload.get('truth_note')}",
        f"- Matching audited actions: {len(payload.get('matches') or [])}.",
        f"- Patch proposals: {len(payload.get('patch_proposals') or [])}.",
        f"- Validations: {len(payload.get('validations') or [])}.",
        f"- Snapshots: {len(payload.get('snapshots') or [])}.",
    ]
    if payload.get("matches"):
        lines.append("- Recent matches:")
        for item in (payload.get("matches") or [])[:6]:
            params = item.get("params") or {}
            task = params.get("task") or (item.get("result_summary") or {}).get("task") or ""
            lines.append(f"  - #{item.get('id')} {item.get('tool')} {item.get('status')}: {task}")
    lines.append("")
    lines.append("Next safe move: stage a real `admin.patch_proposal` before describing code as ready for review.")
    return "\n".join(lines)


PROJECT_BRIEF_DOCS = [
    "README.md",
    "docs/ROADMAP.md",
    "docs/ARCHITECTURE.md",
    "docs/TIMELINE_RECONSTRUCTION.md",
    "docs/FAUXDEX_ADMIN_KNOWLEDGEBASE.md",
]


def read_project_brief_doc(path: str, limit: int = 2200) -> dict:
    doc = Path(path)
    if not doc.exists():
        return {"path": path, "exists": False, "heading": "", "open_items": [], "excerpt": ""}
    text = doc.read_text(encoding="utf-8", errors="ignore")
    heading = ""
    open_items = []
    done_items = 0
    for line in text.splitlines():
        if not heading and line.startswith("#"):
            heading = line.lstrip("#").strip()
        stripped = line.strip()
        if stripped.startswith("- [ ]"):
            open_items.append(stripped[5:].strip())
        elif stripped.startswith("- [x]"):
            done_items += 1
    return {
        "path": path,
        "exists": True,
        "heading": heading,
        "open_items": open_items[:12],
        "done_items": done_items,
        "excerpt": text[:limit],
    }


def recent_admin_actions(limit: int = 40) -> list[dict]:
    actions = []
    for item in recent_actions(limit):
        if not str(item.get("tool") or "").startswith("admin."):
            continue
        actions.append(
            {
                "id": item.get("id"),
                "tool": item.get("tool"),
                "status": item.get("status"),
                "intent": item.get("intent"),
                "params": item.get("params") or {},
                "result_summary": {
                    "task": (item.get("result") or {}).get("task"),
                    "proposal_action_id": (item.get("result") or {}).get("proposal_action_id"),
                    "ready": (item.get("result") or {}).get("ready"),
                    "ok": (item.get("result") or {}).get("ok"),
                    "error": (item.get("result") or {}).get("error"),
                },
            }
        )
    return actions


def clean_task_display(value: str | None) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s*,\s*,+", ",", text)
    text = re.sub(r",\s+and\b", " and", text)
    text = re.sub(r"\s+", " ", text)
    return text


def is_test_task(text: str | None) -> bool:
    lowered = str(text or "").lower()
    return any(word in lowered for word in ["smoke test", "validation smoke", "readiness smoke", "snapshot smoke"])


def admin_project_brief_payload() -> dict:
    docs = [read_project_brief_doc(path) for path in PROJECT_BRIEF_DOCS]
    actions = recent_admin_actions(80)
    patch_proposals = [a for a in actions if a.get("tool") == "admin.patch_proposal"]
    real_patch_proposals = [
        a for a in patch_proposals
        if not is_test_task((a.get("params") or {}).get("task") or (a.get("result_summary") or {}).get("task"))
    ]
    validations = [a for a in actions if a.get("tool") == "admin.diff_validation"]
    snapshots = [a for a in actions if a.get("tool") == "admin.patch_snapshot"]
    apply_requests = [a for a in actions if a.get("tool") == "admin.patch_apply"]
    open_items = []
    for doc in docs:
        for item in doc.get("open_items") or []:
            open_items.append({"doc": doc["path"], "item": item})
    recommendations = [
        "Keep Fauxdex Engine extraction modular while ArchivistOS remains the proving ground.",
        "For vanishing share, continue from audited proposal #117: validate, snapshot, then implement with Codex rather than trusting earlier planning text.",
        "Use the unified-diff apply and patch rollback paths only for exact, validated, snapshotted patches.",
        "Return to timeline reconstruction once the Engine can reliably manage its own development loop.",
    ]
    return {
        "docs": docs,
        "recent_admin_actions": actions[:30],
        "open_items": open_items[:20],
        "active_patch_proposals": real_patch_proposals[:8],
        "test_patch_proposals": patch_proposals[:8],
        "validations": validations[:8],
        "snapshots": snapshots[:8],
        "apply_requests": apply_requests[:8],
        "recommendations": recommendations,
        "engine_profile": admin_engine_profile_payload(),
    }


def format_admin_project_brief(payload: dict) -> str:
    docs = [doc for doc in payload.get("docs") or [] if doc.get("exists")]
    open_items = payload.get("open_items") or []
    proposals = payload.get("active_patch_proposals") or []
    lines = [
        "ArchivistOS project manager brief:",
        f"- Docs loaded: {len(docs)}.",
        f"- Open roadmap/doc items sampled: {len(open_items)}.",
        f"- Recent Admin actions sampled: {len(payload.get('recent_admin_actions') or [])}.",
        f"- Active/recent patch proposals: {len(proposals)}.",
        "",
        "Current priorities:",
        "- Strengthen Fauxdex Engine as admin/developer/project manager.",
        "- Keep project status audit-grounded.",
        "- Continue vanishing share only from real patch proposal artifacts.",
        "- Preserve timeline reconstruction as the core ArchivistOS value target.",
        "",
        "Recommended next actions:",
    ]
    lines.extend(f"- {item}" for item in payload.get("recommendations") or [])
    if proposals:
        lines.append("")
        lines.append("Recent patch proposals:")
        for item in proposals[:5]:
            task = (item.get("params") or {}).get("task") or (item.get("result_summary") or {}).get("task") or ""
            lines.append(f"- #{item.get('id')} {item.get('status')}: {clean_task_display(task)}")
    if open_items:
        lines.append("")
        lines.append("Open items sample:")
        for item in open_items[:8]:
            lines.append(f"- {item.get('doc')}: {item.get('item')}")
    return "\n".join(lines)


def admin_engine_profile_payload() -> dict:
    matrix = model_matrix()
    routes = matrix.get("routes") if isinstance(matrix, dict) else None
    return {
        "definitions": {
            "fauxdex_engine": "Internal agentic framework for planning, tool selection, patch staging, verification, and audit contracts. It is intended to power a future Codex-like Fauxdex product.",
            "fauxdex": "Future separate Codex-like workspace/product powered by Fauxdex Engine; it is not a visible Archivist app surface.",
            "intelligent_admin": "Built-in ArchivistOS administrator for maintenance, recovery, verification, and guarded development. It can use Fauxdex Engine or another workflow adapter when that is the better fit.",
            "archivistos": "The archive app and current proving ground for the admin workflow; engine code should remain portable and removable.",
        },
        "model_roles": {
            "reasoning": model_for_task("reasoning"),
            "large_coder": model_for_task("cowriter_code"),
            "small_coder": model_for_task("cowriter_code_fast"),
            "archivist_chat": model_for_task("archivist_chat"),
        },
        "route_tasks": {
            "reasoning": route_for_task("reasoning"),
            "large_coder": route_for_task("cowriter_code"),
            "small_coder": route_for_task("cowriter_code_fast"),
        },
        "extraction_goal": "Keep the reusable engine portable inside ArchivistOS, then extract it only when the future Fauxdex product needs a standalone framework.",
        "current_engine_gates": [
            "Audit-grounded project status",
            "Patch proposals with exact draft hunks",
            "Diff validation",
            "Patch snapshots",
            "Apply readiness",
            "Confirmation-gated apply for validated, snapshotted unified diffs",
            "Post-apply fixed verification checks",
            "Confirmation-gated rollback from patch snapshot manifests",
            "Post-rollback fixed verification checks",
        ],
        "model_matrix": matrix,
        "routes_available": len(routes or []),
    }


def format_admin_engine_profile(payload: dict) -> str:
    defs = payload.get("definitions") or {}
    models = payload.get("model_roles") or {}
    lines = [
        "Agentic admin profile:",
        f"- Fauxdex Engine: {defs.get('fauxdex_engine')}",
        f"- Fauxdex: {defs.get('fauxdex')}",
        f"- Intelligent Admin: {defs.get('intelligent_admin')}",
        f"- ArchivistOS: {defs.get('archivistos')}",
        "",
        "Model roles:",
        f"- Reasoning: {models.get('reasoning')}",
        f"- Large coder: {models.get('large_coder')}",
        f"- Small coder: {models.get('small_coder')}",
        f"- Archivist chat: {models.get('archivist_chat')}",
        "",
        f"Extraction goal: {payload.get('extraction_goal')}",
        "Current gates:",
    ]
    lines.extend(f"- {item}" for item in payload.get("current_engine_gates") or [])
    return "\n".join(lines)


def admin_self_development_status_payload() -> dict:
    return {
        "capable_now": True,
        "current_capabilities": [
            "Read project docs through the admin planning context.",
            "Answer and plan from Intelligent Admin chat.",
            "Run safe audited runtime tools for status checks, handoff notes, and maintenance previews.",
            "Run a fixed verification suite for frontend and Python syntax checks.",
            "Read host telemetry for CPU, RAM, GPU, VRAM, temperature, and thresholds.",
            "Maintain a persisted ArchivistOS development task queue with priority, status, verification, rollback notes, and latest audit action.",
            "Stage patch proposals with affected files, draft hunks, validation checks, readiness reports, and snapshots.",
            "Stage exact unified-diff proposals and validate them against current files.",
            "Apply validated, snapshotted unified diffs after a separate confirmation.",
            "Run fixed verification checks immediately after a confirmed apply.",
            "Restore files from trusted patch snapshot manifests after a separate confirmation.",
            "Run fixed verification checks immediately after a confirmed rollback.",
            "Create action-audit records that Codex can inspect and continue from.",
        ],
        "missing_capabilities": [
            "Autonomous high-quality unified-diff generation from model output.",
            "Patch rollback UI controls beyond the chat/runtime action path.",
            "Sandboxed command runner exposed through an audited Admin contract.",
        ],
        "next_capability": "Model-authored unified-diff generation with validation failures fed back into retry loops.",
        "authority_model": "Intelligent Admin can now apply exact validated unified diffs with snapshot and confirmation gates. Codex remains the stronger author for complex code generation until model-authored diffs are consistently reliable.",
    }


def format_admin_self_development_status(payload: dict) -> str:
    lines = [
        "Self-development status:",
        "- Intelligent Admin can now perform a narrow class of guarded source-code development.",
        "- It can apply exact unified diffs only after validation, snapshot, readiness, and confirmation gates pass.",
        "- It is not yet a fully autonomous developer; model-authored diffs still need hardening.",
        "",
        "Available now:",
    ]
    lines.extend(f"- {item}" for item in payload.get("current_capabilities") or [])
    lines.append("")
    lines.append("Still missing:")
    lines.extend(f"- {item}" for item in payload.get("missing_capabilities") or [])
    lines.append("")
    lines.append(f"Next build: {payload.get('next_capability')}")
    return "\n".join(lines)


ADMIN_VERIFICATION_COMMANDS = [
    {
        "id": "web_app_js_syntax",
        "label": "Frontend syntax",
        "command": ["node", "--check", "web\\app.js"],
    },
    {
        "id": "python_compileall",
        "label": "Python compile",
        "command": [sys.executable, "-m", "compileall", "app", "run_server.py", "run_index.py"],
    },
]


def run_fixed_verification_command(spec: dict) -> dict:
    started = time.time()
    try:
        result = subprocess.run(
            spec["command"],
            cwd=str(Path.cwd()),
            capture_output=True,
            text=True,
            timeout=90,
        )
        return {
            "id": spec["id"],
            "label": spec["label"],
            "command": spec["command"],
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "duration_seconds": round(time.time() - started, 3),
            "stdout": (result.stdout or "")[-4000:],
            "stderr": (result.stderr or "")[-4000:],
        }
    except Exception as error:
        return {
            "id": spec["id"],
            "label": spec["label"],
            "command": spec["command"],
            "ok": False,
            "returncode": None,
            "duration_seconds": round(time.time() - started, 3),
            "stdout": "",
            "stderr": str(error),
        }


def admin_verification_checks_payload() -> dict:
    checks = [run_fixed_verification_command(spec) for spec in ADMIN_VERIFICATION_COMMANDS]
    return {
        "ok": all(check.get("ok") for check in checks),
        "checks": checks,
        "fixed_command_set": True,
    }


def format_admin_verification_checks(payload: dict) -> str:
    lines = ["Verification checks:", f"- Overall: {'passed' if payload.get('ok') else 'failed'}."]
    for check in payload.get("checks") or []:
        status = "passed" if check.get("ok") else "failed"
        command = " ".join(str(part) for part in check.get("command") or [])
        lines.append(f"- {check.get('label')}: {status} in {check.get('duration_seconds')}s (`{command}`).")
        if not check.get("ok") and check.get("stderr"):
            lines.append(f"  stderr: {str(check.get('stderr'))[:400]}")
    return "\n".join(lines)


INSPECTABLE_CODE_ROOTS = ["app", "web", "docs"]
INSPECTABLE_ROOT_FILES = [
    "README.md",
    "requirements.txt",
    "run_server.py",
    "run_index.py",
]
INSPECTABLE_EXTENSIONS = {".py", ".js", ".html", ".css", ".md", ".json", ".toml"}


def codebase_file_inventory() -> list[Path]:
    files: list[Path] = []
    for root in INSPECTABLE_CODE_ROOTS:
        base = Path(root)
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() in INSPECTABLE_EXTENSIONS:
                files.append(path)
    for rel_path in INSPECTABLE_ROOT_FILES:
        path = Path(rel_path)
        if path.exists() and path.is_file():
            files.append(path)
    return sorted({path.resolve(strict=False) for path in files})


def codebase_search_terms(task: str) -> list[str]:
    lowered = task.lower()
    terms = []
    for term in [
        "intelligent admin",
        "fauxdex",
        "timeline",
        "face",
        "patch",
        "action_audit",
        "runtime",
        "tool",
        "codex",
    ]:
        if term in lowered:
            terms.append(term)
    if not terms:
        terms = [word for word in re.findall(r"[a-zA-Z_]{4,}", lowered)[:5] if word not in {"inspect", "codebase", "about", "show", "find"}]
    return terms[:6]


def admin_codebase_inspection_payload(task: str) -> dict:
    terms = codebase_search_terms(task)
    files = codebase_file_inventory()
    by_extension: dict[str, int] = {}
    for path in files:
        ext = path.suffix.lower() or "no_ext"
        by_extension[ext] = by_extension.get(ext, 0) + 1
    matches = []
    for path in files:
        rel_path = str(path.relative_to(Path.cwd()))
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        line_hits = []
        lower_text = text.lower()
        if terms and not any(term in lower_text for term in terms):
            continue
        for index, line in enumerate(text.splitlines(), start=1):
            lowered_line = line.lower()
            if any(term in lowered_line for term in terms):
                line_hits.append({"line": index, "text": line.strip()[:220]})
            if len(line_hits) >= 4:
                break
        if line_hits:
            matches.append({"path": rel_path, "hits": line_hits})
        if len(matches) >= 12:
            break
    return {
        "task": task,
        "terms": terms,
        "file_count": len(files),
        "by_extension": by_extension,
        "matches": matches,
        "read_only": True,
    }


def format_admin_codebase_inspection(payload: dict) -> str:
    terms = ", ".join(payload.get("terms") or []) or "general project structure"
    lines = [
        "Codebase inspection:",
        f"- Scope: {int(payload.get('file_count') or 0):,} inspectable project files.",
        f"- Search terms: {terms}.",
        "- File types: "
        + ", ".join(f"{ext} {count}" for ext, count in sorted((payload.get("by_extension") or {}).items()))
        + ".",
    ]
    matches = payload.get("matches") or []
    if not matches:
        lines.append("- No direct text matches found in the inspected files.")
    else:
        lines.append("- Likely touch points:")
        for match in matches[:8]:
            first_hit = (match.get("hits") or [{}])[0]
            lines.append(f"  - {match.get('path')}:{first_hit.get('line')} {first_hit.get('text')}")
    lines.append("")
    lines.append("This inspection is read-only. Use a patch proposal next if you want Codex to implement from these touch points.")
    return "\n".join(lines)


def admin_health_check_payload() -> dict:
    return {
        "archive_control": archive_control_status(
            index_job=index_status_payload(),
            embedding_job=embedding_rebuild_job_snapshot(),
            pre_dedupe_job=pre_dedupe_job_snapshot(),
        ),
        "archive_locations": archive_location_status(),
        "video_scan": video_scan_job_snapshot(),
        "ffmpeg": ffmpeg_status(),
        "recent_index_failures": recent_index_failures(5),
        "models": model_matrix(),
    }


def format_admin_health_check(payload: dict) -> str:
    control = payload.get("archive_control") or {}
    locations = payload.get("archive_locations") or {}
    video = payload.get("video_scan") or {}
    ffmpeg = payload.get("ffmpeg") or {}
    failures = payload.get("recent_index_failures") or []
    index_job = control.get("index_job") or {}
    embedding_job = control.get("embedding_job") or {}
    pre_dedupe = control.get("pre_dedupe_job") or {}
    roots = (
        (locations.get("chat_aware") or [])
        + (locations.get("chat_ignored") or [])
        + (locations.get("external_sources") or [])
    )
    available_roots = sum(1 for item in roots if item.get("health_status") == "available")
    lines = [
        "Admin health check:",
        f"- Index: {chat_index_summary(index_job)}.",
        f"- Embeddings: {embedding_rebuild_summary(embedding_job)}.",
        f"- Pre-index dedupe: {'running' if pre_dedupe.get('running') else 'idle'}.",
        f"- Video scan: {'running' if video.get('running') else 'idle'}; processed {int(video.get('processed') or 0):,}; failed {int(video.get('failed') or 0):,}.",
        f"- FFmpeg: {'available' if ffmpeg.get('available') else 'unavailable'}.",
        f"- Archive roots: {available_roots} available of {len(roots)} configured.",
        f"- Recent index failures: {len(failures)} shown.",
    ]
    if failures:
        first = failures[0]
        lines.append(f"- Latest failure: {first.get('path') or 'unknown'}: {first.get('error') or first.get('reason') or 'no detail'}")
    return "\n".join(lines)


def format_admin_host_stats(payload: dict) -> str:
    cpu = payload.get("cpu") or {}
    memory = payload.get("memory") or {}
    gpu = payload.get("gpu") or {}
    settings = payload.get("settings") or {}
    temps = payload.get("temperatures") or []
    gpu_name = (gpu.get("cards") or [{}])[0].get("name") if gpu.get("cards") else "unavailable"
    lines = [
        "Host system stats:",
        f"- CPU: {cpu.get('usage_percent') if cpu.get('usage_percent') is not None else 'unknown'}% across {(payload.get('host') or {}).get('cpu_count', '?')} threads.",
        f"- System RAM: {memory.get('usage_percent') if memory.get('usage_percent') is not None else 'unknown'}% used.",
        f"- GPU: {gpu_name}; usage {gpu.get('usage_percent') if gpu.get('usage_percent') is not None else 'unknown'}%; VRAM {gpu.get('vram_percent') if gpu.get('vram_percent') is not None else 'unknown'}%.",
        f"- Thresholds: CPU {settings.get('cpu_threshold_percent')}%, GPU {settings.get('gpu_threshold_percent')}%, RAM {settings.get('ram_threshold_percent')}%, VRAM {settings.get('vram_threshold_percent')}%, temp {settings.get('temperature_threshold_c')}C.",
    ]
    if temps:
        lines.append("- Temperatures: " + "; ".join(f"{item.get('label')}: {item.get('temperature_c')}C" for item in temps))
    else:
        lines.append("- Temperatures: no sensor rows available yet.")
    return "\n".join(lines)


def format_admin_development_task(task: dict | None) -> str:
    if not task:
        return "No queued development task exists yet. Seed the development queue to create the next Admin build steps."
    lines = [
        f"Task #{task.get('id')}: {task.get('title')}",
        f"- Status: {task.get('status')} | priority: {task.get('priority')}",
    ]
    if task.get("description"):
        lines.append(f"- Goal: {task.get('description')}")
    tools = task.get("recommended_tools") or []
    if tools:
        lines.append(f"- Recommended tools: {', '.join(tools)}")
    checks = task.get("verification") or []
    if checks:
        lines.append("- Verification: " + "; ".join(str(item) for item in checks[:3]))
    rollback = task.get("rollback") or []
    if rollback:
        lines.append("- Rollback: " + "; ".join(str(item) for item in rollback[:2]))
    if task.get("last_action_id"):
        lines.append(f"- Latest audit action: #{task.get('last_action_id')}")
    return "\n".join(lines)


def format_admin_development_queue(payload: dict) -> str:
    tasks = payload.get("tasks") or []
    summary = payload.get("summary") or {}
    lines = [
        "Development task queue:",
        f"- Total: {summary.get('total', len(tasks))}",
    ]
    by_status = summary.get("by_status") or {}
    if by_status:
        lines.append("- Status: " + ", ".join(f"{key} {value}" for key, value in sorted(by_status.items())))
    next_task = payload.get("next")
    if next_task:
        lines.append("")
        lines.append("Next:")
        lines.append(format_admin_development_task(next_task))
    if tasks:
        lines.append("")
        lines.append("Queue:")
        for task in tasks[:8]:
            lines.append(f"- #{task.get('id')} [{task.get('status')}/{task.get('priority')}] {task.get('title')}")
    else:
        lines.append("- Queue is empty. Run `seed development queue` to add the first build tasks.")
    return "\n".join(lines)


def format_admin_development_seed(payload: dict) -> str:
    created = payload.get("created") or []
    skipped = payload.get("skipped") or []
    lines = [
        "Development queue seeded:",
        f"- Created: {len(created)}",
        f"- Already present: {len(skipped)}",
        f"- Total tasks: {payload.get('total', 0)}",
    ]
    for task in created[:6]:
        lines.append(f"- #{task.get('id')} {task.get('title')}")
    return "\n".join(lines)


def format_engine_plan_schema() -> str:
    fields = ENGINE_PLAN_SCHEMA.get("fields") or []
    return "\n".join(
        [
            "Fauxdex Engine structured plan schema:",
            f"- Schema: {ENGINE_PLAN_SCHEMA.get('schema')}",
            "- Fields: " + ", ".join(fields),
            "- Purpose: keep Intelligent Admin and future engine-consumer plans machine-readable while preserving a human answer.",
        ]
    )


HANDOFF_DOCS = [
    "README.md",
    "docs/ROADMAP.md",
    "docs/ARCHITECTURE.md",
    "docs/TIMELINE_RECONSTRUCTION.md",
    "docs/FAUXDEX_ADMIN_KNOWLEDGEBASE.md",
]


def _read_handoff_doc(path: str, limit: int = 1400) -> dict:
    doc_path = Path(path)
    if not doc_path.exists():
        return {"path": path, "exists": False, "excerpt": ""}
    text = doc_path.read_text(encoding="utf-8", errors="ignore").strip()
    heading = ""
    for line in text.splitlines():
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            break
    return {
        "path": path,
        "exists": True,
        "heading": heading,
        "excerpt": text[:limit],
    }


def admin_codex_handoff_payload() -> dict:
    docs = [_read_handoff_doc(path) for path in HANDOFF_DOCS]
    return {"docs": docs, "tools": ADMIN_ENGINE_TOOLS, "development_queue": development_task_summary()}


def format_admin_codex_handoff(payload: dict) -> str:
    docs = payload.get("docs") or []
    available = [doc for doc in docs if doc.get("exists")]
    missing = [doc["path"] for doc in docs if not doc.get("exists")]
    lines = [
        "Codex handoff:",
        "Current direction: keep Intelligent Admin as the user-facing administrator, keep engine code portable behind it, and center the long-term archive priority on face-linked evidence and timeline reconstruction.",
        f"Docs loaded: {len(available)} available" + (f"; missing {', '.join(missing)}." if missing else "."),
        "",
        "Next useful pass:",
        "1. Expand Admin run tools from status checks into preview-first patch proposals.",
        "2. Add timeline event creation/search controls that connect people, face observations, files, and evidence.",
        "3. Keep summaries fact-based: cite evidence, flag missing dates/people/sources, and preserve uncertainty.",
        "",
        "Relevant doc headings:",
    ]
    for doc in available:
        lines.append(f"- {doc.get('path')}: {doc.get('heading') or 'no heading'}")
    next_task = (payload.get("development_queue") or {}).get("next")
    if next_task:
        lines.extend(["", "Current Admin development task:", f"- #{next_task.get('id')} {next_task.get('title')} ({next_task.get('status')}/{next_task.get('priority')})"])
    return "\n".join(lines)


def preview_embedding_rebuild_action(conversation_id: str) -> dict:
    if index_is_active(index_job_snapshot()):
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="index.rebuild_embeddings",
            intent="rebuild_embeddings",
            status="failed",
            error="Archive indexing is active.",
            result={"started": False},
        )
        return {
            "handled": True,
            "answer": f"Action #{action_id}: wait for indexing to finish before rebuilding archive embeddings.",
            "operator_action": {"id": action_id},
        }
    plan = embedding_rebuild_plan()
    action_id = audit_action(
        conversation_id=conversation_id,
        tool="index.rebuild_embeddings",
        intent="rebuild_embeddings",
        status="pending_confirmation",
        requires_confirmation=True,
        result=plan,
    )
    answer = (
        f"Action #{action_id}: I can rebuild the chat-aware archive embeddings from the persisted file index.\n\n"
        f"Active files to embed: {int(plan.get('active_files') or 0):,}\n"
        f"Chat-ignored active inventory excluded: {int(plan.get('chat_ignored_files') or 0):,}\n"
        f"Review/deletion candidates excluded: {int(plan.get('review_excluded_files') or 0):,}\n\n"
        f"Say `confirm action {action_id}` to start the rebuild. It runs in the background."
    )
    return {"handled": True, "answer": answer, "operator_action": {"id": action_id, "pending": True}}


def execute_runtime_pending_action(action: dict) -> dict | None:
    if not action or action.get("status") != "pending_confirmation":
        return None
    if action.get("tool") == "admin.patch_apply":
        apply_result = execute_admin_patch_apply_action(action)
        verification = admin_verification_checks_payload() if apply_result.get("applied") else {}
        result = {
            **(action.get("result") or {}),
            "applied": bool(apply_result.get("applied")),
            "apply_result": apply_result,
            "post_apply_verification": verification,
            "confirmed_ts": time.time(),
        }
        ok = bool(apply_result.get("applied")) and bool(verification.get("ok"))
        update_action(
            int(action["id"]),
            status="completed" if ok else "failed",
            result=result,
            error=None if ok else (apply_result.get("error") or "Post-apply verification failed."),
        )
        answer = f"Action #{action['id']}: {format_admin_patch_apply(result)}"
        if apply_result.get("applied") and not verification.get("ok"):
            answer += "\n\nVerification failed after apply. Restore from the recorded patch snapshot before continuing."
        return {"handled": True, "answer": answer, "operator_action": {"id": int(action["id"])}}
    if action.get("tool") == "admin.patch_rollback":
        rollback_result = execute_admin_patch_rollback_action(action)
        verification = admin_verification_checks_payload() if rollback_result.get("rolled_back") else {}
        result = {
            **(action.get("result") or {}),
            "rolled_back": bool(rollback_result.get("rolled_back")),
            "rollback_result": rollback_result,
            "post_rollback_verification": verification,
            "confirmed_ts": time.time(),
        }
        ok = bool(rollback_result.get("rolled_back")) and bool(verification.get("ok"))
        update_action(
            int(action["id"]),
            status="completed" if ok else "failed",
            result=result,
            error=None if ok else (rollback_result.get("error") or "Post-rollback verification failed."),
        )
        answer = f"Action #{action['id']}: {format_admin_patch_rollback(result)}"
        return {"handled": True, "answer": answer, "operator_action": {"id": int(action["id"])}}
    if action.get("tool") == "admin.patch_proposal":
        result = action.get("result") or {}
        update_action(
            int(action["id"]),
            status="completed",
            result={**result, "confirmed_for_codex": True},
        )
        return {
            "handled": True,
            "answer": (
                f"Action #{action['id']}: patch proposal marked ready for Codex handoff. "
                "No source files were changed by Intelligent Admin."
            ),
            "operator_action": {"id": int(action["id"])},
        }
    if action.get("tool") != "index.rebuild_embeddings":
        return None
    if index_is_active(index_job_snapshot()):
        update_action(int(action["id"]), status="failed", result=action.get("result") or {}, error="Archive indexing is active.")
        return {
            "handled": True,
            "answer": f"Action #{action['id']}: wait for indexing to finish before rebuilding archive embeddings.",
            "operator_action": {"id": int(action["id"])},
        }
    started, job = start_embedding_rebuild_thread()
    update_action(
        int(action["id"]),
        status="completed",
        result={"started": started, "job": job, "plan": action.get("result") or {}},
    )
    verb = "started" if started else "is already running"
    return {
        "handled": True,
        "answer": f"Action #{action['id']}: embedding rebuild {verb}. {embedding_rebuild_summary(job)}.",
        "operator_action": {"id": int(action["id"])},
    }


def maybe_confirm_runtime_action(query: str, conversation_id: str) -> dict:
    lowered = query.lower().strip()
    if lowered not in {"confirm", "confirm last action", "do it", "yes do it"} and not lowered.startswith("confirm action"):
        return {"handled": False}
    match = re.search(r"confirm\s+action\s+#?(\d+)", query, re.I)
    action = load_action(int(match.group(1))) if match else latest_pending_action(conversation_id)
    if action and action.get("conversation_id") and action.get("conversation_id") != conversation_id:
        return {
            "handled": True,
            "answer": "That pending action belongs to a different chat lane. Open that lane to confirm it there.",
        }
    result = execute_runtime_pending_action(action) if action else None
    if result:
        return result
    return {"handled": False}


def handle_archive_runtime_chat_tool(query: str, conversation_id: str) -> dict:
    lowered = query.lower().strip()
    runtime_confirmation = maybe_confirm_runtime_action(query, conversation_id)
    if runtime_confirmation.get("handled"):
        return runtime_confirmation

    if any(
        phrase in lowered
        for phrase in [
            "embedding rebuild status",
            "embeddings rebuild status",
            "vector rebuild status",
            "embedding status",
            "embeddings status",
        ]
    ):
        job = embedding_rebuild_job_snapshot()
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="index.embedding_status",
            intent="embedding_status",
            status="completed",
            result={"job": job},
        )
        return {
            "handled": True,
            "answer": f"Action #{action_id}: embedding rebuild {embedding_rebuild_summary(job)}.",
            "operator_action": {"id": action_id},
        }

    if re.search(r"\b(rebuild|refresh|clean)\b.*\b(embedding|embeddings|vector|vectors|semantic)\b", lowered):
        return preview_embedding_rebuild_action(conversation_id)

    if re.search(r"\bwipe\b.*\bindex\b|\bclear\b.*\bindex\b", lowered):
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="index.wipe.refused",
            intent="wipe_index",
            status="completed",
            result={"refused": True},
        )
        return {
            "handled": True,
            "answer": (
                f"Action #{action_id}: I will not wipe the index from chat. "
                "Use the guarded `Wipe index` button in Archive Maintenance and type its confirmation number."
            ),
            "operator_action": {"id": action_id},
        }

    wants_status = any(
        phrase in lowered
        for phrase in ["index status", "indexing status", "what is index doing", "what's the index doing", "is indexing running"]
    )
    if wants_status:
        job = index_status_payload()
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="index.status",
            intent="index_status",
            status="completed",
            result={"job": job},
        )
        return {
            "handled": True,
            "answer": f"Action #{action_id}: index status: {chat_index_summary(job)}.",
            "operator_action": {"id": action_id},
        }

    if re.search(r"\b(pause|stop)\b.*\b(index|indexing)\b", lowered):
        snapshot = index_job_snapshot()
        run_id = snapshot.get("active_run_id")
        paused = False
        if index_is_active(snapshot):
            index_pause_requested.set()
            update_index_job(pause_requested=True, run_status="pausing")
            if run_id:
                set_run_status(int(run_id), "pausing")
            paused = True
        job = index_status_payload()
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="index.pause",
            intent="pause_index",
            status="completed",
            result={"paused": paused, "job": job},
        )
        answer = "Pause requested. The indexer will stop at the next checkpoint." if paused else "The indexer is not currently active."
        return {
            "handled": True,
            "answer": f"Action #{action_id}: {answer}\n\n{chat_index_summary(job)}",
            "operator_action": {"id": action_id},
        }

    if re.search(r"\b(resume|continue)\b.*\b(index|indexing)\b", lowered):
        if pre_dedupe_job_snapshot()["running"]:
            answer = "Pre-index dedupe is still running. Wait for it to finish before resuming the full index."
            action_id = audit_action(
                conversation_id=conversation_id,
                tool="index.resume",
                intent="resume_index",
                status="failed",
                result={"started": False},
                error=answer,
            )
            return {"handled": True, "answer": f"Action #{action_id}: {answer}", "operator_action": {"id": action_id}}
        snapshot = index_job_snapshot()
        if index_is_active(snapshot):
            job = index_status_payload()
            action_id = audit_action(
                conversation_id=conversation_id,
                tool="index.resume",
                intent="resume_index",
                status="completed",
                result={"started": False, "job": job},
            )
            return {
                "handled": True,
                "answer": f"Action #{action_id}: indexing is already active.\n\n{chat_index_summary(job)}",
                "operator_action": {"id": action_id},
            }
        run = latest_resumable_run()
        if not run:
            action_id = audit_action(
                conversation_id=conversation_id,
                tool="index.resume",
                intent="resume_index",
                status="failed",
                result={"started": False},
                error="No paused or interrupted index run is available to resume.",
            )
            return {
                "handled": True,
                "answer": f"Action #{action_id}: no paused or interrupted index run is available to resume.",
                "operator_action": {"id": action_id},
            }
        started, job = start_index_thread(force=bool(run.get("force")), run_id=int(run["id"]), resume=True)
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="index.resume",
            intent="resume_index",
            status="completed",
            result={"started": started, "job": job},
        )
        return {
            "handled": True,
            "answer": f"Action #{action_id}: resume requested.\n\n{chat_index_summary(job)}",
            "operator_action": {"id": action_id},
        }

    if re.search(r"\b(start|run|begin)\b.*\b(index|indexing)\b", lowered):
        if pre_dedupe_job_snapshot()["running"]:
            answer = "Pre-index dedupe is still running. Wait for it to finish before starting a full index."
            action_id = audit_action(
                conversation_id=conversation_id,
                tool="index.start",
                intent="start_index",
                status="failed",
                result={"started": False},
                error=answer,
            )
            return {"handled": True, "answer": f"Action #{action_id}: {answer}", "operator_action": {"id": action_id}}
        force = any(word in lowered for word in ["force", "reprocess", "unchanged"])
        started, job = start_index_thread(force=force)
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="index.start",
            intent="start_index",
            status="completed",
            params={"force": force},
            result={"started": started, "job": job},
        )
        answer = "started a full archive index" if started else "indexing is already active"
        return {
            "handled": True,
            "answer": f"Action #{action_id}: {answer}.\n\n{chat_index_summary(job)}",
            "operator_action": {"id": action_id},
        }

    return {"handled": False}


def handle_runtime_chat_tool(query: str, conversation_id: str, *, include_admin_tools: bool = True) -> dict:
    lowered = query.lower().strip()
    if not include_admin_tools:
        return handle_archive_runtime_chat_tool(query, conversation_id)

    runtime_confirmation = maybe_confirm_runtime_action(query, conversation_id)
    if runtime_confirmation.get("handled"):
        return runtime_confirmation

    if any(phrase in lowered for phrase in ["admin tools", "engine tools", "fauxdex tools", "what tools can admin use"]):
        payload = admin_engine_tools_payload()
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="admin.tools.catalog",
            intent="admin_tools_catalog",
            status="completed",
            result=payload,
        )
        return {
            "handled": True,
            "answer": f"Action #{action_id}: {format_admin_tool_catalog()}",
            "operator_action": {"id": action_id},
        }

    if any(phrase in lowered for phrase in ["fauxdex engine plan schema", "engine plan schema", "structured plan schema", "structured engine plan"]):
        payload = {"schema": ENGINE_PLAN_SCHEMA}
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="admin.engine_plan_schema",
            intent="admin_engine_plan_schema",
            status="completed",
            result=payload,
        )
        return {
            "handled": True,
            "answer": f"Action #{action_id}: {format_engine_plan_schema()}",
            "operator_action": {"id": action_id},
        }

    if (
        "host system stats" in lowered
        or "system stats" in lowered
        or "host stats" in lowered
        or re.search(r"\b(cpu|gpu|vram|ram|temperature|telemetry)\b.*\b(status|stats|threshold|usage)\b", lowered)
    ):
        payload = host_stats()
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="admin.host_stats",
            intent="admin_host_stats",
            status="completed",
            result=payload,
        )
        return {
            "handled": True,
            "answer": f"Action #{action_id}: {format_admin_host_stats(payload)}",
            "operator_action": {"id": action_id},
        }

    task_status_match = re.search(r"\bmark\s+(?:development\s+)?task\s+#?(\d+)\s+(queued|active|blocked|paused|done)\b", lowered)
    if task_status_match:
        task_id = int(task_status_match.group(1))
        status = task_status_match.group(2)
        try:
            task = update_development_task(task_id, status=status)
            action_id = audit_action(
                conversation_id=conversation_id,
                tool="admin.development_tasks.update",
                intent="admin_development_task_update",
                status="completed",
                params={"task_id": task_id, "status": status},
                result={"task": task},
            )
            attach_action_to_task(task_id, action_id)
            task = get_development_task(task_id) or task
            return {
                "handled": True,
                "answer": f"Action #{action_id}: {format_admin_development_task(task)}",
                "operator_action": {"id": action_id},
            }
        except ValueError as error:
            action_id = audit_action(
                conversation_id=conversation_id,
                tool="admin.development_tasks.update",
                intent="admin_development_task_update",
                status="failed",
                params={"task_id": task_id, "status": status},
                error=str(error),
            )
            return {"handled": True, "answer": f"Action #{action_id}: {error}", "operator_action": {"id": action_id}}

    if any(phrase in lowered for phrase in ["seed development queue", "seed admin queue", "setup development queue", "setup admin work queue"]):
        payload = seed_development_tasks()
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="admin.development_tasks.seed",
            intent="admin_development_tasks_seed",
            status="completed",
            result=payload,
        )
        for task in payload.get("created") or []:
            attach_action_to_task(int(task["id"]), action_id)
        return {
            "handled": True,
            "answer": f"Action #{action_id}: {format_admin_development_seed(payload)}",
            "operator_action": {"id": action_id},
        }

    if any(phrase in lowered for phrase in ["next development task", "next admin task", "next dev task", "what should admin work on next"]):
        task = next_development_task()
        payload = {"task": task}
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="admin.development_tasks.next",
            intent="admin_development_task_next",
            status="completed",
            result=payload,
        )
        if task:
            attach_action_to_task(int(task["id"]), action_id)
            task = get_development_task(int(task["id"])) or task
        return {
            "handled": True,
            "answer": f"Action #{action_id}: {format_admin_development_task(task)}",
            "operator_action": {"id": action_id},
        }

    if any(phrase in lowered for phrase in ["development task queue", "development queue", "admin work queue", "dev task list", "development tasks"]):
        tasks = list_development_tasks(40)
        payload = {"tasks": tasks, "summary": development_task_summary(), "next": next_development_task()}
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="admin.development_tasks.list",
            intent="admin_development_tasks_list",
            status="completed",
            result=payload,
        )
        return {
            "handled": True,
            "answer": f"Action #{action_id}: {format_admin_development_queue(payload)}",
            "operator_action": {"id": action_id},
        }

    create_task_match = re.search(r"\b(?:create|add|queue)\s+(?:admin\s+)?(?:development\s+|dev\s+)?task\s*:?\s*(.+)", query, re.I | re.S)
    if create_task_match:
        title = create_task_match.group(1).strip()
        try:
            task = create_development_task(title=title, description="", priority="medium", source="admin-chat")
            action_id = audit_action(
                conversation_id=conversation_id,
                tool="admin.development_tasks.create",
                intent="admin_development_task_create",
                status="completed",
                params={"title": title},
                result={"task": task},
            )
            attach_action_to_task(int(task["id"]), action_id)
            task = get_development_task(int(task["id"])) or task
            return {
                "handled": True,
                "answer": f"Action #{action_id}: created {format_admin_development_task(task)}",
                "operator_action": {"id": action_id},
            }
        except ValueError as error:
            action_id = audit_action(
                conversation_id=conversation_id,
                tool="admin.development_tasks.create",
                intent="admin_development_task_create",
                status="failed",
                params={"title": title},
                error=str(error),
            )
            return {"handled": True, "answer": f"Action #{action_id}: {error}", "operator_action": {"id": action_id}}

    if any(
        phrase in lowered
        for phrase in [
            "fauxdex engine profile",
            "engine profile",
            "engine architecture",
            "what is fauxdex engine",
            "fauxdex definitions",
        ]
    ):
        payload = admin_engine_profile_payload()
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="admin.engine_profile",
            intent="admin_engine_profile",
            status="completed",
            result=payload,
        )
        return {
            "handled": True,
            "answer": f"Action #{action_id}: {format_admin_engine_profile(payload)}",
            "operator_action": {"id": action_id},
        }

    if (
        re.search(r"\b(project|development|build|patch)\b.*\b(status|update|progress|ready|review)\b", lowered)
        or re.search(r"\b(status|update|progress)\b.*\b(project|development|build|patch)\b", lowered)
        or "ready for review" in lowered
    ):
        payload = admin_project_status_payload(query)
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="admin.project_status",
            intent="admin_project_status",
            status="completed",
            params={"query": query, "terms": payload.get("terms") or []},
            result=payload,
        )
        return {
            "handled": True,
            "answer": f"Action #{action_id}: {format_admin_project_status(payload)}",
            "operator_action": {"id": action_id},
        }

    if (
        "project manager brief" in lowered
        or "project brief" in lowered
        or "development brief" in lowered
        or re.search(r"\bwhat\b.*\b(next|priority|priorities)\b", lowered)
        or re.search(r"\bnext\b.*\b(project|development|build)\b", lowered)
    ):
        payload = admin_project_brief_payload()
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="admin.project_brief",
            intent="admin_project_brief",
            status="completed",
            result=payload,
        )
        return {
            "handled": True,
            "answer": f"Action #{action_id}: {format_admin_project_brief(payload)}",
            "operator_action": {"id": action_id},
        }

    if any(
        phrase in lowered
        for phrase in [
            "self development status",
            "own development status",
            "can you continue your own development",
            "capable of continuing its own development",
            "capable of continuing your own development",
        ]
    ):
        payload = admin_self_development_status_payload()
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="admin.self_development_status",
            intent="admin_self_development_status",
            status="completed",
            result=payload,
        )
        return {
            "handled": True,
            "answer": f"Action #{action_id}: {format_admin_self_development_status(payload)}",
            "operator_action": {"id": action_id},
        }

    if (
        re.search(r"\b(inspect|scan|search|read)\b.*\b(codebase|project|source|repo)\b", lowered)
        or "codebase inspection" in lowered
    ):
        payload = admin_codebase_inspection_payload(query)
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="admin.codebase_inspection",
            intent="admin_codebase_inspection",
            status="completed",
            params={"task": query, "terms": payload.get("terms") or []},
            result=payload,
        )
        return {
            "handled": True,
            "answer": f"Action #{action_id}: {format_admin_codebase_inspection(payload)}",
            "operator_action": {"id": action_id},
        }

    if (
        re.search(r"\b(run|start|perform)\b.*\b(verification|checks|syntax checks|compileall)\b", lowered)
        or "admin verification checks" in lowered
    ):
        payload = admin_verification_checks_payload()
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="admin.verification_checks",
            intent="admin_verification_checks",
            status="completed" if payload.get("ok") else "failed",
            params={"fixed_command_set": True},
            result=payload,
            error=None if payload.get("ok") else "One or more fixed verification checks failed.",
        )
        model_answer = chat_messages(
            [
                {"role": "system", "content": "You are the verifier. Run fixed verification commands (node --check web/app.js, python -m compileall). Report pass/fail clearly. No interpretation needed."},
                {"role": "user", "content": f"User request: {query}\n\nVerification payload: {json.dumps(payload)}"}
            ],
            task="admin_verification_checks",
        )
        return {
            "handled": True,
            "answer": f"Action #{action_id}: {model_answer}",
            "operator_action": {"id": action_id},
        }

    if (
        ("```diff" in query or "```patch" in query or "\n--- " in query)
        and re.search(r"\b(stage|create|prepare|propose)\b.*\b(unified diff|diff|patch)\b", lowered)
    ):
        payload = admin_unified_diff_proposal_payload(query)
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="admin.patch_proposal",
            intent="admin_unified_diff_patch_proposal",
            status="pending_confirmation" if payload.get("unified_diff_validation", {}).get("ok") else "failed",
            params={"task": payload["task"], "mode": "admin", "diff_preview_kind": "unified_diff"},
            result=payload,
            requires_confirmation=bool(payload.get("unified_diff_validation", {}).get("ok")),
            error=None if payload.get("unified_diff_validation", {}).get("ok") else "Unified diff did not validate.",
        )
        suffix = (
            f"\n\nSay `confirm action {action_id}` to mark this unified-diff proposal ready for snapshot/readiness/apply."
            if payload.get("unified_diff_validation", {}).get("ok")
            else "\n\nFix the unified diff validation errors before requesting apply."
        )
        return {
            "handled": True,
            "answer": f"Action #{action_id}: {format_admin_patch_proposal(payload)}{suffix}",
            "operator_action": {"id": action_id, "pending": bool(payload.get("unified_diff_validation", {}).get("ok"))},
        }

    if (
        re.search(r"\b(stage|create|make|draft|prepare)\b.*\bpatch\b", lowered)
        or re.search(r"\bpatch\b.*\b(proposal|flow|preview)\b", lowered)
        or re.search(r"\b(design|build|stage|test)\b.*\b(vanishing|temporary share|share link|tailscale)\b", lowered)
        or re.search(r"\b(vanishing|temporary share|share link|tailscale)\b.*\b(design|build|stage|test)\b", lowered)
        or "continue development proposal" in lowered
    ):
        payload = admin_patch_proposal_payload(query)
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="admin.patch_proposal",
            intent="admin_patch_proposal",
            status="pending_confirmation",
            params={"task": payload["task"], "mode": "admin"},
            result=payload,
            requires_confirmation=True,
        )
        model_answer = chat_messages(
            [
                {"role": "system", "content": "You are the patch proposal architect. Present the proposal clearly with affected files, diff previews, and safety gates."},
                {"role": "user", "content": f"User request: {query}\n\nProposal payload: {json.dumps(payload)}"}
            ],
            task="admin_patch_proposal",
        )
        return {
            "handled": True,
            "answer": f"Action #{action_id}: {model_answer}",
            "operator_action": {"id": action_id, "pending": True},
        }

    if (
        re.search(r"\b(validate|check)\b.*\b(diff|draft|hunk|patch proposal|proposal)\b", lowered)
        or re.search(r"\bvalidate\s+action\s+#?\d+\b", lowered)
        or "validate latest patch proposal" in lowered
    ):
        payload = admin_diff_validation_payload(query, conversation_id)
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="admin.diff_validation",
            intent="admin_diff_validation",
            status="completed" if payload.get("ok") else "failed",
            params={"query": query, "proposal_action_id": payload.get("action_id")},
            result=payload,
            error=payload.get("error") or (None if payload.get("ok") else "One or more draft hunks did not validate."),
        )
        model_answer = chat_messages(
            [
                {"role": "system", "content": "You are the diff validator. Report exact line matches, context accuracy, and hunk applicability. Reject anything that doesn't apply cleanly."},
                {"role": "user", "content": f"User request: {query}\n\nValidation payload: {json.dumps(payload)}"}
            ],
            task="admin_diff_validation",
        )
        return {
            "handled": True,
            "answer": f"Action #{action_id}: {model_answer}",
            "operator_action": {"id": action_id},
        }

    if (
        re.search(r"\bapply\b.*\breadiness\b", lowered)
        or re.search(r"\breadiness\b.*\b(proposal|apply|patch)\b", lowered)
        or "can this be applied" in lowered
    ):
        payload = admin_apply_readiness_payload(query, conversation_id)
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="admin.apply_readiness",
            intent="admin_apply_readiness",
            status="completed",
            params={"query": query, "proposal_action_id": payload.get("proposal_action_id")},
            result=payload,
        )
        model_answer = chat_messages(
            [
                {"role": "system", "content": "You are the gatekeeper. Verify all apply-readiness gates: diff validation passed, snapshot exists, verification checks pass, confirmation received. Block if any gate fails."},
                {"role": "user", "content": f"User request: {query}\n\nReadiness payload: {json.dumps(payload)}"}
            ],
            task="admin_apply_readiness",
        )
        return {
            "handled": True,
            "answer": f"Action #{action_id}: {model_answer}",
            "operator_action": {"id": action_id},
        }

    if (
        re.search(r"\b(snapshot|backup)\b.*\b(patch|proposal|action)\b", lowered)
        or "snapshot latest patch proposal" in lowered
    ):
        payload = admin_patch_snapshot_payload(query, conversation_id)
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="admin.patch_snapshot",
            intent="admin_patch_snapshot",
            status="completed" if payload.get("ok") else "failed",
            params={"query": query, "proposal_action_id": payload.get("proposal_action_id")},
            result=payload,
            error=payload.get("error") or (None if payload.get("ok") else "One or more affected files could not be snapshotted."),
        )
        model_answer = chat_messages(
            [
                {"role": "system", "content": "You are the snapshot guardian. Ensure all affected files are captured with correct paths and hashes. Report what was snapshotted."},
                {"role": "user", "content": f"User request: {query}\n\nSnapshot payload: {json.dumps(payload)}"}
            ],
            task="admin_patch_snapshot",
        )
        return {
            "handled": True,
            "answer": f"Action #{action_id}: {format_admin_patch_snapshot(payload)}",
            "operator_action": {"id": action_id},
        }

    if (
        re.search(r"\b(rollback|restore)\b.*\b(patch|snapshot|proposal|apply|action)\b", lowered)
        or "rollback latest patch" in lowered
        or "restore patch snapshot" in lowered
    ):
        payload = admin_patch_rollback_payload(query, conversation_id)
        ready = bool(payload.get("ready_to_rollback"))
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="admin.patch_rollback",
            intent="admin_patch_rollback",
            status="pending_confirmation" if ready else "failed",
            params={"query": query, "snapshot_action_id": payload.get("snapshot_action_id")},
            result=payload,
            requires_confirmation=ready,
            error=None if ready else "Patch rollback request blocked by safety gates.",
        )
        suffix = f"\n\nSay `confirm action {action_id}` to restore the snapshot files and run verification." if ready else ""
        return {
            "handled": True,
            "answer": f"Action #{action_id}: {format_admin_patch_rollback(payload)}{suffix}",
            "operator_action": {"id": action_id, "pending": ready},
        }

    if (
        re.search(r"\bapply\b.*\b(patch|proposal|action)\b", lowered)
        or "apply latest patch proposal" in lowered
    ):
        payload = admin_patch_apply_payload(query, conversation_id)
        ready = bool(payload.get("ready_to_apply"))
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="admin.patch_apply",
            intent="admin_patch_apply",
            status="pending_confirmation" if ready else "failed",
            params={"query": query, "proposal_action_id": payload.get("proposal_action_id")},
            result=payload,
            requires_confirmation=ready,
            error=None if ready else "Patch apply request blocked by safety gates.",
        )
        model_answer = chat_messages(
            [
                {"role": "system", "content": "You are the patch applier. Apply validated unified diffs after all gates pass. Only execute after explicit confirmation. Report what was applied."},
                {"role": "user", "content": f"User request: {query}\n\nApply payload: {json.dumps(payload)}"}
            ],
            task="admin_patch_apply",
        )
        suffix = f"\n\nSay `confirm action {action_id}` to apply the validated unified diff." if ready else ""
        return {
            "handled": True,
            "answer": f"Action #{action_id}: {model_answer}{suffix}",
            "operator_action": {"id": action_id, "pending": ready},
        }

    if re.search(r"\b(admin|system|archive)\b.*\bhealth check\b", lowered) or lowered in {"health check", "admin health"}:
        payload = admin_health_check_payload()
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="admin.health_check",
            intent="admin_health_check",
            status="completed",
            result=payload,
        )
        return {
            "handled": True,
            "answer": f"Action #{action_id}: {format_admin_health_check(payload)}",
            "operator_action": {"id": action_id},
        }

    if re.search(r"\b(codex|fauxdex)\b.*\bhandoff\b", lowered) or "handoff note" in lowered:
        payload = admin_codex_handoff_payload()
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="admin.codex_handoff",
            intent="admin_codex_handoff",
            status="completed",
            result=payload,
        )
        return {
            "handled": True,
            "answer": f"Action #{action_id}: {format_admin_codex_handoff(payload)}",
            "operator_action": {"id": action_id},
        }

    if any(
        phrase in lowered
        for phrase in [
            "embedding rebuild status",
            "embeddings rebuild status",
            "vector rebuild status",
            "embedding status",
            "embeddings status",
        ]
    ):
        job = embedding_rebuild_job_snapshot()
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="index.embedding_status",
            intent="embedding_status",
            status="completed",
            result={"job": job},
        )
        return {
            "handled": True,
            "answer": f"Action #{action_id}: embedding rebuild {embedding_rebuild_summary(job)}.",
            "operator_action": {"id": action_id},
        }

    if re.search(r"\b(rebuild|refresh|clean)\b.*\b(embedding|embeddings|vector|vectors|semantic)\b", lowered):
        return preview_embedding_rebuild_action(conversation_id)

    if re.search(r"\bwipe\b.*\bindex\b|\bclear\b.*\bindex\b", lowered):
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="index.wipe.refused",
            intent="wipe_index",
            status="completed",
            result={"refused": True},
        )
        return {
            "handled": True,
            "answer": (
                f"Action #{action_id}: I will not wipe the index from chat. "
                "Use the guarded `Wipe index` button in Archive Maintenance and type its confirmation number."
            ),
            "operator_action": {"id": action_id},
        }

    wants_status = any(
        phrase in lowered
        for phrase in ["index status", "indexing status", "what is index doing", "what's the index doing", "is indexing running"]
    )
    if wants_status:
        job = index_status_payload()
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="index.status",
            intent="index_status",
            status="completed",
            result={"job": job},
        )
        return {
            "handled": True,
            "answer": f"Action #{action_id}: index status: {chat_index_summary(job)}.",
            "operator_action": {"id": action_id},
        }

    if re.search(r"\b(pause|stop)\b.*\b(index|indexing)\b", lowered):
        snapshot = index_job_snapshot()
        run_id = snapshot.get("active_run_id")
        paused = False
        if index_is_active(snapshot):
            index_pause_requested.set()
            update_index_job(pause_requested=True, run_status="pausing")
            if run_id:
                set_run_status(int(run_id), "pausing")
            paused = True
        job = index_status_payload()
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="index.pause",
            intent="pause_index",
            status="completed",
            result={"paused": paused, "job": job},
        )
        answer = "Pause requested. The indexer will stop at the next checkpoint." if paused else "The indexer is not currently active."
        return {
            "handled": True,
            "answer": f"Action #{action_id}: {answer}\n\n{chat_index_summary(job)}",
            "operator_action": {"id": action_id},
        }

    if re.search(r"\b(resume|continue)\b.*\b(index|indexing)\b", lowered):
        if pre_dedupe_job_snapshot()["running"]:
            answer = "Pre-index dedupe is still running. Wait for it to finish before resuming the full index."
            action_id = audit_action(
                conversation_id=conversation_id,
                tool="index.resume",
                intent="resume_index",
                status="failed",
                result={"started": False},
                error=answer,
            )
            return {"handled": True, "answer": f"Action #{action_id}: {answer}", "operator_action": {"id": action_id}}
        snapshot = index_job_snapshot()
        if index_is_active(snapshot):
            job = index_status_payload()
            action_id = audit_action(
                conversation_id=conversation_id,
                tool="index.resume",
                intent="resume_index",
                status="completed",
                result={"started": False, "job": job},
            )
            return {
                "handled": True,
                "answer": f"Action #{action_id}: indexing is already active.\n\n{chat_index_summary(job)}",
                "operator_action": {"id": action_id},
            }
        run = latest_resumable_run()
        if not run:
            action_id = audit_action(
                conversation_id=conversation_id,
                tool="index.resume",
                intent="resume_index",
                status="failed",
                result={"started": False},
                error="No paused or interrupted index run is available to resume.",
            )
            return {
                "handled": True,
                "answer": f"Action #{action_id}: no paused or interrupted index run is available to resume.",
                "operator_action": {"id": action_id},
            }
        started, job = start_index_thread(force=bool(run.get("force")), run_id=int(run["id"]), resume=True)
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="index.resume",
            intent="resume_index",
            status="completed",
            result={"started": started, "job": job},
        )
        return {
            "handled": True,
            "answer": f"Action #{action_id}: resume requested.\n\n{chat_index_summary(job)}",
            "operator_action": {"id": action_id},
        }

    if re.search(r"\b(start|run|begin)\b.*\b(index|indexing)\b", lowered):
        if pre_dedupe_job_snapshot()["running"]:
            answer = "Pre-index dedupe is still running. Wait for it to finish before starting a full index."
            action_id = audit_action(
                conversation_id=conversation_id,
                tool="index.start",
                intent="start_index",
                status="failed",
                result={"started": False},
                error=answer,
            )
            return {"handled": True, "answer": f"Action #{action_id}: {answer}", "operator_action": {"id": action_id}}
        force = any(word in lowered for word in ["force", "reprocess", "unchanged"])
        started, job = start_index_thread(force=force)
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="index.start",
            intent="start_index",
            status="completed",
            params={"force": force},
            result={"started": started, "job": job},
        )
        answer = "started a full archive index" if started else "indexing is already active"
        return {
            "handled": True,
            "answer": f"Action #{action_id}: {answer}.\n\n{chat_index_summary(job)}",
            "operator_action": {"id": action_id},
        }

    return {"handled": False}


def answer_intelligent_admin_runtime(task: str, conversation_id: str | None = None) -> dict:
    clean_task = (task or "").strip()
    if len(clean_task) < 2:
        raise ValueError("Intelligent Admin task is too short")

    admin_conversation_id = ensure_conversation(conversation_id, clean_task, scope="admin")
    operator = handle_runtime_chat_tool(clean_task, admin_conversation_id, include_admin_tools=True)
    if operator.get("handled"):
        user_message_id = add_message(admin_conversation_id, "user", f"Intelligent Admin run:\n{clean_task}")
        answer = operator.get("answer") or ""
        assistant_message_id = add_message(admin_conversation_id, "assistant", answer)
        return {
            "conversation_id": admin_conversation_id,
            "user_message_id": user_message_id,
            "assistant_message_id": assistant_message_id,
            "answer": answer,
            "keyword_hits": operator.get("keyword_hits", []),
            "semantic_hits": [],
            "memory_hits": [],
            "created_memories": [],
            "operator_action": operator.get("operator_action"),
            "mode": "admin_run",
        }

    return plan_intelligent_admin_task(clean_task, admin_conversation_id)


@app.on_event("startup")
def startup():
    init_db()
    recovered_run_ids = recover_interrupted_runs()
    for run_id in recovered_run_ids:
        snapshot = run_snapshot(run_id)
        if snapshot and snapshot.get("status") in {"running", "building"}:
            start_index_thread(force=bool(snapshot.get("force")), run_id=run_id, resume=True)
            break
    watcher_thread = threading.Thread(target=run_watcher, daemon=True)
    watcher_thread.start()


@app.get("/", response_class=HTMLResponse)
def home():
    with open("web/index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.post("/api/chat")
def api_chat(req: ChatRequest):
    note_chat_activity()
    try:
        return answer_query(req.query, req.conversation_id, runtime_tools=lambda q, cid: handle_runtime_chat_tool(q, cid, include_admin_tools=True))
    finally:
        note_chat_activity()


@app.post("/api/fauxdex/plan")
def api_fauxdex_plan(req: FauxdexPlanRequest):
    note_chat_activity()
    try:
        return plan_fauxdex_task(req.task, req.conversation_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        note_chat_activity()


@app.get("/api/fauxdex/plan-schema")
def api_fauxdex_plan_schema():
    return ENGINE_PLAN_SCHEMA


@app.post("/api/fauxdex/run")
def api_fauxdex_run(req: FauxdexPlanRequest):
    note_chat_activity()
    try:
        result = plan_fauxdex_task(req.task, req.conversation_id)
        action_id = audit_action(
            conversation_id=result.get("conversation_id") or req.conversation_id or "",
            tool="fauxdex.run",
            intent="fauxdex_compatibility_run",
            status="completed",
            params={"task": req.task, "mode": "fauxdex"},
            result={
                "conversation_id": result.get("conversation_id"),
                "user_message_id": result.get("user_message_id"),
                "assistant_message_id": result.get("assistant_message_id"),
                "structured_plan": result.get("structured_plan"),
                "model_task": result.get("model_task"),
                "model_error": result.get("model_error"),
            },
        )
        result["fauxdex_action_id"] = action_id
        result["engine"] = "fauxdex"
        result["mode"] = "fauxdex_compatibility_run"
        return result
    finally:
        note_chat_activity()


def run_intelligent_admin_plan(req: FauxdexEngineRequest):
    note_chat_activity()
    try:
        result = plan_intelligent_admin_task(req.task, req.conversation_id)
        action_id = audit_action(
            conversation_id=result.get("conversation_id") or req.conversation_id or "",
            tool="admin.intelligent_admin.plan",
            intent="intelligent_admin_plan",
            status="completed",
            params={"task": req.task, "mode": "admin"},
            result={
                "conversation_id": result.get("conversation_id"),
                "user_message_id": result.get("user_message_id"),
                "assistant_message_id": result.get("assistant_message_id"),
                "model_task": result.get("model_task"),
                "model_error": result.get("model_error"),
                "structured_plan": result.get("structured_plan"),
                "plan_schema": result.get("plan_schema"),
            },
        )
        result["operator_action"] = {"id": action_id}
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        note_chat_activity()


def run_intelligent_admin_runtime(req: FauxdexEngineRequest):
    note_chat_activity()
    try:
        result = answer_intelligent_admin_runtime(req.task, req.conversation_id)
        action_id = audit_action(
            conversation_id=result.get("conversation_id") or req.conversation_id or "",
            tool="admin.intelligent_admin.run",
            intent="intelligent_admin_run",
            status="completed",
            params={"task": req.task, "mode": "admin"},
            result={
                "conversation_id": result.get("conversation_id"),
                "user_message_id": result.get("user_message_id"),
                "assistant_message_id": result.get("assistant_message_id"),
                "operator_action": result.get("operator_action"),
                "created_memories": result.get("created_memories", []),
            },
        )
        result["admin_action_id"] = action_id
        result["engine"] = "fauxdex"
        result["mode"] = "admin_run"
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        note_chat_activity()


@app.post("/api/admin/intelligent-admin")
def api_admin_intelligent_admin(req: FauxdexEngineRequest):
    return run_intelligent_admin_plan(req)


@app.post("/api/admin/intelligent-admin/run")
def api_admin_intelligent_admin_run(req: FauxdexEngineRequest):
    return run_intelligent_admin_runtime(req)


@app.post("/api/admin/fauxdex-engine")
def api_admin_fauxdex_engine(req: FauxdexEngineRequest):
    return run_intelligent_admin_plan(req)


@app.post("/api/admin/fauxdex-engine/run")
def api_admin_fauxdex_engine_run(req: FauxdexEngineRequest):
    return run_intelligent_admin_runtime(req)


@app.get("/api/admin/fauxdex-engine/tools")
def api_admin_fauxdex_engine_tools():
    return admin_engine_tools_payload()


@app.get("/api/admin/intelligent-admin/tools")
def api_admin_intelligent_admin_tools():
    return admin_engine_tools_payload()


@app.get("/api/admin/development-tasks")
def api_admin_development_tasks(limit: int = 40, status: str | None = None):
    tasks = list_development_tasks(limit, status=status)
    return {"tasks": tasks, "summary": development_task_summary(), "next": next_development_task()}


@app.get("/api/admin/development-tasks/next")
def api_admin_development_task_next():
    return {"task": next_development_task(), "summary": development_task_summary()}


@app.post("/api/admin/development-tasks")
def api_admin_development_task_create(req: AdminDevelopmentTaskCreateRequest):
    try:
        task = create_development_task(
            title=req.title,
            description=req.description,
            priority=req.priority,
            status=req.status,
            source="admin-ui",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    action_id = audit_action(
        conversation_id="admin-ui",
        tool="admin.development_tasks.create",
        intent="admin_development_task_create",
        status="completed",
        params=req.model_dump(),
        result={"task": task},
    )
    attach_action_to_task(int(task["id"]), action_id)
    return {"task": get_development_task(int(task["id"])) or task, "action_id": action_id, "summary": development_task_summary()}


@app.post("/api/admin/development-tasks/seed")
def api_admin_development_tasks_seed():
    payload = seed_development_tasks()
    action_id = audit_action(
        conversation_id="admin-ui",
        tool="admin.development_tasks.seed",
        intent="admin_development_tasks_seed",
        status="completed",
        result=payload,
    )
    for task in payload.get("created") or []:
        attach_action_to_task(int(task["id"]), action_id)
    return {**payload, "action_id": action_id, "summary": development_task_summary()}


@app.post("/api/admin/development-tasks/{task_id}")
def api_admin_development_task_update(task_id: int, req: AdminDevelopmentTaskUpdateRequest):
    try:
        task = update_development_task(
            task_id,
            status=req.status,
            priority=req.priority,
            notes=req.notes,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    action_id = audit_action(
        conversation_id="admin-ui",
        tool="admin.development_tasks.update",
        intent="admin_development_task_update",
        status="completed",
        params={"task_id": task_id, **req.model_dump()},
        result={"task": task},
    )
    attach_action_to_task(task_id, action_id)
    return {"task": get_development_task(task_id) or task, "action_id": action_id, "summary": development_task_summary()}


@app.get("/api/conversations")
def api_conversations(limit: int = 40, scope: str = "archivist"):
    return {"conversations": list_conversations(limit, scope=scope)}


@app.post("/api/conversations")
def api_create_conversation(scope: str = "archivist"):
    conversation_id = ensure_conversation(None, "New thread", scope=scope)
    return {"conversation_id": conversation_id}


@app.get("/api/conversations/{conversation_id}")
def api_conversation(conversation_id: str):
    return {"conversation_id": conversation_id, "messages": list_messages(conversation_id)}


@app.get("/api/memories")
def api_memories(limit: int = 30):
    return {"memories": list_memories(limit), "status": memory_status()}


@app.post("/api/memories")
def api_create_memory(req: MemoryCreateRequest):
    memory = create_memory(
        req.content,
        kind=req.kind,
        status=req.status,
        evidence=req.evidence,
        confidence=req.confidence,
    )
    if not memory:
        raise HTTPException(status_code=400, detail="Memory content is too short")
    return {"memory": memory, "status": memory_status()}


@app.get("/api/clipboard")
def api_clipboard(limit: int = 20):
    return {"items": list_clipboard(limit)}


@app.post("/api/clipboard/text")
def api_clipboard_text(req: ClipboardTextRequest):
    try:
        item = create_clipboard_text(req.content, req.source)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"item": item, "items": list_clipboard(20), "notes": list_notes("active", 80)}


@app.post("/api/clipboard/file")
async def api_clipboard_file(file: UploadFile = File(...)):
    item = create_clipboard_file(file)
    return {"item": item, "items": list_clipboard(20), "notes": list_notes("active", 80)}


@app.post("/api/clipboard/clear")
def api_clipboard_clear():
    return clear_clipboard()


@app.get("/api/notes")
def api_notes(status: str = "active", limit: int = 80):
    return {"notes": list_notes(status, limit)}


@app.post("/api/notes")
def api_create_note(req: NoteCreateRequest):
    return {"note": create_note(title=req.title, content=req.content, kind=req.kind)}


@app.post("/api/notes/file")
async def api_create_note_file(file: UploadFile = File(...)):
    return {"note": create_note_from_upload(file)}


@app.post("/api/notes/{note_id}")
def api_update_note(note_id: int, req: NoteUpdateRequest):
    try:
        return {"note": update_note(note_id, title=req.title, content=req.content, status=req.status)}
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 400, detail=str(e))


@app.get("/api/search")
def api_search(query: str, limit: int = 10):
    return {"keyword_hits": keyword_search(query, limit), "semantic_hits": semantic_search(query, limit)}


@app.get("/api/actions")
def api_actions(limit: int = 40, status: str | None = None, scope: str | None = None):
    return {"actions": recent_actions(limit, status=status, scope=scope)}


@app.get("/api/actions/{action_id}")
def api_action_detail(action_id: int):
    action = load_action(action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    return {"action": action}


@app.post("/api/actions/{action_id}/confirm")
def api_action_confirm(action_id: int):
    action = load_action(action_id)
    runtime_result = execute_runtime_pending_action(action) if action else None
    if runtime_result:
        refreshed = load_action(action_id)
        if refreshed:
            runtime_result["action"] = refreshed
        return runtime_result
    result = confirm_action_by_id(action_id)
    action = load_action(action_id)
    if action:
        result["action"] = action
    if "not found" in (result.get("answer") or "").lower():
        raise HTTPException(status_code=404, detail=result["answer"])
    return result


@app.post("/api/actions/{action_id}/cancel")
def api_action_cancel(action_id: int):
    result = cancel_action_by_id(action_id)
    action = load_action(action_id)
    if action:
        result["action"] = action
    if "not found" in (result.get("answer") or "").lower():
        raise HTTPException(status_code=404, detail=result["answer"])
    return result


@app.get("/api/dashboard")
def api_dashboard():
    return dashboard_context()


@app.post("/api/weather/settings")
def api_weather_settings(req: WeatherSettingsRequest):
    return update_weather_settings(
        provider=req.provider,
        location=req.location,
        sync_enabled=req.sync_enabled,
        latitude=req.latitude,
        longitude=req.longitude,
    )


@app.post("/api/weather/refresh")
def api_weather_refresh():
    return {"weather": weather_context(force=True)}


@app.get("/api/models")
def api_models():
    return model_matrix()


@app.get("/api/admin/easy-connect")
def api_admin_easy_connect():
    return easy_connect_status()


@app.post("/api/admin/easy-connect/start")
def api_admin_easy_connect_start(req: AdminConnectStartRequest):
    return start_easy_connect(req.host_label)


@app.post("/api/admin/easy-connect/verify")
def api_admin_easy_connect_verify(req: AdminConnectVerifyRequest):
    try:
        return verify_easy_connect(req.remote_code, req.host_label)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/admin/easy-connect/reset")
def api_admin_easy_connect_reset():
    return reset_easy_connect()


@app.get("/api/admin/installer-profile")
def api_admin_installer_profile():
    return installer_profile()


@app.get("/api/admin/archive-control")
def api_admin_archive_control():
    return archive_control_status(
        index_job=index_job_snapshot(),
        embedding_job=embedding_rebuild_job_snapshot(),
        pre_dedupe_job=pre_dedupe_job_snapshot(),
    )


@app.get("/api/admin/host-stats")
def api_admin_host_stats():
    return host_stats()


@app.post("/api/admin/host-stats/settings")
def api_admin_host_stats_settings(req: HostStatsSettingsRequest):
    settings = update_host_stats_settings(req.model_dump())
    data = host_stats()
    data["settings"] = settings
    data["summary"] = "Host telemetry thresholds saved."
    return data


@app.post("/api/admin/archive-control/free-gpu")
def api_admin_archive_control_free_gpu(req: AdminControlRequest):
    return free_gpu(req.model)


@app.post("/api/admin/archive-control/restart")
def api_admin_archive_control_restart(req: AdminControlRequest):
    try:
        return request_server_restart(index_job_snapshot(), force=req.force)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/api/admin/archive-control/stop")
def api_admin_archive_control_stop(req: AdminControlRequest):
    try:
        return request_server_stop(index_job_snapshot(), force=req.force)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.get("/api/discovery")
def api_discovery():
    return discovery_constellation()


@app.get("/api/constellation")
def api_constellation():
    return data_constellation()


@app.get("/api/timeline/overview")
def api_timeline_overview():
    return timeline_overview()


@app.get("/api/timeline/people")
def api_timeline_people(q: str | None = None, limit: int = 80):
    return list_people(q=q, limit=limit)


@app.post("/api/timeline/people")
def api_timeline_create_person(req: PersonRequest):
    try:
        return create_person(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/timeline/people/{person_id}")
def api_timeline_person(person_id: int):
    person = get_person(person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    return person


@app.post("/api/timeline/people/{person_id}")
def api_timeline_update_person(person_id: int, req: PersonUpdateRequest):
    try:
        return update_person(person_id, req)
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 400, detail=str(e))


@app.get("/api/timeline/faces")
def api_timeline_faces(
    person_id: int | None = None,
    cluster_id: str | None = None,
    file_id: int | None = None,
    limit: int = 120,
):
    return list_face_observations(person_id=person_id, cluster_id=cluster_id, file_id=file_id, limit=limit)


@app.post("/api/timeline/faces")
def api_timeline_create_face(req: FaceObservationRequest):
    try:
        return create_face_observation(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _face_detection_record(req: FaceDetectionRequest) -> dict:
    if req.file_id:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM files WHERE id = ?", (int(req.file_id),))
        row = cur.fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="Indexed file not found")
        return dict(row)
    if req.path:
        try:
            path = resolve_allowed_path(req.path, INDEX_ALLOWED_ROOTS)
        except ValueError:
            raise HTTPException(status_code=403, detail="Path is outside allowed roots")
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM files WHERE path = ?", (str(path),))
        row = cur.fetchone()
        conn.close()
        if row:
            return dict(row)
        mime = guess_mime(path)
        return {
            "id": None,
            "path": str(path),
            "name": path.name,
            "ext": path.suffix.lower(),
            "mime_type": mime,
            "category": file_category(path, mime),
            "summary": "",
            "extracted_text": "",
        }
    raise HTTPException(status_code=400, detail="Provide a file_id or path")


@app.get("/api/timeline/faces/detector-status")
def api_timeline_face_detector_status():
    return face_engine_status()


@app.post("/api/timeline/faces/detect")
def api_timeline_detect_faces(req: FaceDetectionRequest):
    record = _face_detection_record(req)
    result = scan_file_faces(record, force_video=req.force_video)
    try:
        tags = apply_auto_tags(record, face_count=int(result.get("face_count") or 0))
    except Exception as error:
        tags = {"applied": 0, "error": str(error)}
    sync = {"synced": False, "reason": "not_indexed"}
    if record.get("id") and is_chat_safe_source(record.get("path") or ""):
        try:
            sync = sync_file_embedding_by_id(int(record["id"]))
        except Exception as error:
            sync = {"synced": False, "error": str(error)}
    return {"record": {"id": record.get("id"), "path": record.get("path"), "category": record.get("category")}, "face_scan": result, "auto_tags": tags, "sync": sync}


@app.post("/api/timeline/faces/backfill")
def api_timeline_backfill_faces(req: FaceBackfillRequest):
    return scan_indexed_media_faces(limit=req.limit, include_video=req.include_video, force=req.force)


@app.post("/api/timeline/face-links")
def api_timeline_link_face(req: PersonFaceLinkRequest):
    try:
        return link_person_face(req)
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 400, detail=str(e))


@app.get("/api/timeline/events")
def api_timeline_events(
    q: str | None = None,
    person_id: int | None = None,
    status: str | None = None,
    limit: int = 80,
):
    return list_timeline_events(q=q, person_id=person_id, status=status, limit=limit)


@app.post("/api/timeline/events")
def api_timeline_create_event(req: TimelineEventRequest):
    try:
        return create_timeline_event(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/timeline/events/{event_id}")
def api_timeline_event(event_id: int):
    event = get_timeline_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Timeline event not found")
    return event


@app.post("/api/timeline/events/{event_id}")
def api_timeline_update_event(event_id: int, req: TimelineEventUpdateRequest):
    try:
        return update_timeline_event(event_id, req)
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 400, detail=str(e))


@app.post("/api/timeline/events/{event_id}/evidence")
def api_timeline_add_evidence(event_id: int, req: TimelineEvidenceRequest):
    try:
        return add_event_evidence(event_id, req)
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 400, detail=str(e))


@app.post("/api/timeline/events/{event_id}/people")
def api_timeline_add_person(event_id: int, req: TimelineEventPersonRequest):
    try:
        return add_event_person(event_id, req)
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 400, detail=str(e))


@app.get("/api/embeddings/rebuild-status")
def api_embedding_rebuild_status():
    return embedding_rebuild_job_snapshot()


@app.get("/api/media/ffmpeg/status")
def api_media_ffmpeg_status():
    return ffmpeg_status()


@app.get("/api/media/video/presets")
def api_media_video_presets():
    return {"presets": video_analysis_presets()}


@app.get("/api/media/video/scan-status")
def api_media_video_scan_status():
    snapshot = video_scan_job_snapshot()
    if not snapshot.get("running"):
        snapshot["pending_candidates"] = len(video_scan_candidates(rescan_existing=False, include_delete_queue=False))
    return snapshot


@app.post("/api/media/video/scan-all")
def api_media_video_scan_all(req: VideoArchiveScanRequest):
    if index_is_active(index_job_snapshot()):
        raise HTTPException(status_code=409, detail="Wait for the main archive index to finish before scanning all videos.")
    if pre_dedupe_job_snapshot()["running"]:
        raise HTTPException(status_code=409, detail="Wait for pre-index dedupe to finish before scanning all videos.")
    with video_scan_thread_lock:
        if video_scan_job_snapshot().get("running"):
            return {"started": False, "job": video_scan_job_snapshot()}
        reset_video_scan_job_state()
        thread = threading.Thread(
            target=run_video_archive_scan,
            kwargs={
                "preset": req.preset or "quick_skim",
                "update_index": bool(req.update_index),
                "rescan_existing": bool(req.rescan_existing),
                "include_delete_queue": bool(req.include_delete_queue),
                "limit": req.limit,
                "detect_faces": bool(req.detect_faces),
                "detect_objects": bool(req.detect_objects),
            },
            daemon=True,
        )
        thread.start()
    return {"started": True, "job": video_scan_job_snapshot()}


@app.post("/api/media/video/scan-stop")
def api_media_video_scan_stop():
    snapshot = video_scan_job_snapshot()
    if not snapshot.get("running"):
        return {"stopped": False, "job": snapshot}
    video_scan_stop_requested.set()
    update_video_scan_job(stop_requested=True)
    return {"stopped": True, "job": video_scan_job_snapshot()}


@app.get("/api/media/video/context")
def api_media_video_context(path: str | None = None, file_id: int | None = None):
    try:
        return video_context(path=path, file_id=file_id)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/media/video/analyze")
def api_media_video_analyze(req: VideoAnalyzeRequest):
    try:
        return analyze_video(
            path=req.path,
            file_id=req.file_id,
            interval_seconds=req.interval_seconds,
            max_frames=req.max_frames,
            update_index=req.update_index,
            preset=req.preset,
            detect_faces=req.detect_faces,
            detect_objects=req.detect_objects,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/media/transcription/status")
def api_media_transcription_status():
    return transcription_status()


@app.get("/api/media/vision/status")
def api_media_vision_status():
    return vision_status()


@app.post("/api/media/vision/analyze")
def api_media_vision_analyze(req: VisionAnalysisRequest):
    try:
        return analyze_image_file(path=req.path, file_id=req.file_id, update_index=req.update_index)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/media/video/transcribe")
def api_media_video_transcribe(req: VideoTranscribeRequest):
    try:
        return transcribe_video(path=req.path, file_id=req.file_id, update_index=req.update_index, prefer_subtitles=req.prefer_subtitles)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/media/video/segments")
def api_media_video_segments(req: MediaSegmentRequest):
    try:
        return add_video_segment(req)
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/media/video/search")
def api_media_video_search(q: str, limit: int = 40):
    return search_video_context(q, limit)


@app.get("/api/archive-locations")
def api_archive_locations():
    return archive_location_status()


@app.get("/api/archive-locations/browse")
def api_archive_location_browse(path: str | None = None):
    return browse_directories(path)


@app.post("/api/archive-locations/root")
def api_archive_location_root(req: ArchiveLocationRequest):
    try:
        return set_archive_root(req.path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/archive-locations/source")
def api_archive_location_source(req: ArchiveSourceSlotRequest):
    try:
        return set_source_slot(req.slot, req.path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/archive-locations/additional")
def api_archive_location_additional(req: ArchiveLocationRequest):
    try:
        return add_additional_root(req.path, req.label)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/archive-locations/remove")
def api_archive_location_remove(req: ArchiveLocationRequest):
    return remove_additional_root(req.path)


@app.get("/api/maintenance/stats")
def api_maintenance_stats():
    return archive_stats()


@app.post("/api/maintenance/recategorize")
def api_maintenance_recategorize():
    return recategorize_file_index()


@app.get("/api/maintenance/files")
def api_maintenance_files(
    q: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    duplicates: bool = False,
    delete_queue: bool = False,
    limit: int = 80,
    offset: int = 0,
    sort: str = "indexed_desc",
):
    return list_files(
        q=q,
        category=category,
        tag=tag,
        duplicates=duplicates,
        delete_queue=delete_queue,
        limit=limit,
        offset=offset,
        sort=sort,
    )


@app.get("/api/maintenance/duplicates")
def api_maintenance_duplicates(limit: int = 30, offset: int = 0):
    return duplicate_groups(limit=limit, offset=offset)


@app.post("/api/maintenance/dedupe/preindex")
def api_preindex_dedupe():
    if index_is_active(index_job_snapshot()):
        raise HTTPException(
            status_code=409,
            detail="The full indexer is already running. Pre-index dedupe should run before starting a full index.",
        )
    if pre_dedupe_job_snapshot()["running"]:
        return {"job": pre_dedupe_job_snapshot()}
    reset_pre_dedupe_job_state()
    thread = threading.Thread(target=run_pre_dedupe_job, daemon=True)
    thread.start()
    return {"job": pre_dedupe_job_snapshot(), "reason": PRE_INDEX_DEDUPE_REASON}


@app.get("/api/maintenance/dedupe/preindex-status")
def api_preindex_dedupe_status():
    return pre_dedupe_job_snapshot()


@app.post("/api/maintenance/dedupe/move-queued")
def api_move_queued_duplicates(req: MoveQueuedDuplicatesRequest):
    if index_is_active(index_job_snapshot()):
        raise HTTPException(
            status_code=409,
            detail="Stop the full indexer before moving duplicate files into review.",
        )
    if pre_dedupe_job_snapshot()["running"]:
        raise HTTPException(
            status_code=409,
            detail="Wait for pre-index dedupe to finish before moving duplicate files.",
        )
    return move_queued_duplicates_to_review(
        dry_run=req.dry_run,
        limit=req.limit,
        remove_empty_folders=req.remove_empty_folders,
    )


@app.post("/api/maintenance/dedupe/queue-exact")
def api_queue_exact_duplicates():
    return queue_exact_duplicates_for_review()


@app.get("/api/maintenance/failures")
def api_maintenance_failures(limit: int = 40):
    return {"failures": recent_index_failures(limit)}


@app.get("/api/maintenance/tags")
def api_maintenance_tags():
    return {"tags": list_tags()}


@app.post("/api/maintenance/tags/apply")
def api_apply_tag(req: TagApplyRequest):
    return apply_tag(req.file_ids, req.tag)


@app.post("/api/maintenance/tags/remove")
def api_remove_tag(req: TagApplyRequest):
    return remove_tag(req.file_ids, req.tag)


@app.post("/api/maintenance/delete-queue")
def api_queue_deletion(req: DeletionQueueRequest):
    return queue_deletion(req.file_ids, req.reason)


@app.post("/api/maintenance/delete-queue-path")
def api_queue_deletion_path(req: DeletionQueuePathRequest):
    return queue_deletion_by_path(req.path, req.reason)


@app.post("/api/maintenance/delete-unqueue")
def api_unqueue_deletion(req: FileIdsRequest):
    return unqueue_deletion(req.file_ids)


@app.get("/api/cowriter/document")
def api_cowriter_document():
    return current_document()


@app.get("/api/cowriter/timeline")
def api_cowriter_timeline(limit: int = 80):
    return document_timeline(limit)


@app.post("/api/cowriter/document")
def api_cowriter_save(req: CoWriterDocumentRequest, autosave: bool = False):
    return save_document(req.content, autosave=autosave)


@app.post("/api/cowriter/version")
def api_cowriter_version(req: CoWriterDocumentRequest):
    return save_version(req.content)


@app.post("/api/cowriter/load")
def api_cowriter_load(req: CoWriterLoadRequest):
    try:
        path = resolve_allowed_path(req.path, INDEX_ALLOWED_ROOTS)
        return load_document_file(path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found")


@app.post("/api/cowriter/import-upload")
async def api_cowriter_import_upload(file: UploadFile = File(...)):
    filename = clean_filename(file.filename or "document")
    temp_path = UPLOAD_DIR / f"cowriter_import_{int(time.time())}_{filename}"
    ensure_parent(temp_path)
    try:
        with open(temp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        return import_uploaded_document(temp_path, file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def persist_cowriter_turn(req: CoWriterPromptRequest, label: str, result: dict) -> dict:
    title_seed = req.instruction or label
    conversation_id = ensure_conversation(req.conversation_id, title_seed)
    selected_note = f"\n\nSelected text:\n{req.selected_text}" if req.selected_text else ""
    user_text = f"{label}: {req.instruction or '(no extra instruction)'}{selected_note}"
    user_message_id = add_message(conversation_id, "user", user_text)
    created_memories = maybe_capture_memory(conversation_id, user_message_id, user_text)

    assistant_text = result.get("answer") or ""
    if result.get("replacement"):
        assistant_text = f"Replacement preview:\n\n{result['replacement']}"
    elif result.get("revised_document"):
        assistant_text = f"Preview draft saved.\n\n{result['revised_document']}"
    assistant_message_id = add_message(conversation_id, "assistant", assistant_text)

    result.update(
        {
            "conversation_id": conversation_id,
            "user_message_id": user_message_id,
            "assistant_message_id": assistant_message_id,
            "created_memories": created_memories,
        }
    )
    return result


@app.post("/api/cowriter/ask")
def api_cowriter_ask(req: CoWriterPromptRequest):
    note_chat_activity()
    try:
        result = cowriter_ask(req.document, req.instruction or "", req.chat_history)
        return persist_cowriter_turn(req, "Ask", result)
    finally:
        note_chat_activity()


@app.post("/api/cowriter/edit-selection")
def api_cowriter_edit_selection(req: CoWriterPromptRequest):
    if not req.selected_text:
        raise HTTPException(status_code=400, detail="No selected text supplied")
    note_chat_activity()
    try:
        result = cowriter_edit_selection(req.document, req.selected_text, req.instruction, req.chat_history)
        return persist_cowriter_turn(req, "Edit selection", result)
    finally:
        note_chat_activity()


@app.post("/api/cowriter/preview-draft")
def api_cowriter_preview_draft(req: CoWriterPromptRequest):
    note_chat_activity()
    try:
        result = cowriter_preview_draft(req.document, req.instruction, req.chat_history)
        return persist_cowriter_turn(req, "Preview draft", result)
    finally:
        note_chat_activity()


@app.post("/api/cowriter/help-write")
def api_cowriter_help_write(req: CoWriterPromptRequest):
    note_chat_activity()
    try:
        result = cowriter_help_write(req.document, req.chat_history)
        return persist_cowriter_turn(req, "Help write", result)
    finally:
        note_chat_activity()


@app.get("/api/explorer")
def api_explorer(path: str | None = None, limit: int = 500):
    try:
        current = ARCHIVE_ROOT if not path else resolve_allowed_path(path, [ARCHIVE_ROOT])
    except ValueError:
        raise HTTPException(status_code=403, detail="Path is outside the archive root")
    if not current.exists():
        raise HTTPException(status_code=404, detail="Explorer path not found")
    if not current.is_dir():
        raise HTTPException(status_code=400, detail="Explorer path must be a directory")
    return list_explorer_directory(current, limit=limit)


@app.get("/api/file")
def api_file(path: str):
    try:
        p = resolve_allowed_path(path, INDEX_ALLOWED_ROOTS)
    except ValueError:
        raise HTTPException(status_code=403, detail="Path is outside allowed archive roots")
    if not p.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(p), filename=p.name)


@app.get("/api/preview")
def api_preview(path: str):
    try:
        p = resolve_allowed_path(path, INDEX_ALLOWED_ROOTS)
    except ValueError:
        raise HTTPException(status_code=403, detail="Path is outside allowed archive roots")
    if not p.exists():
        raise HTTPException(status_code=404, detail="Preview not found")
    return FileResponse(str(p))


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)):
    ts = int(time.time())
    safe_name = clean_filename(file.filename)
    temp_path = unique_path(UPLOAD_DIR / f"{ts}_{safe_name}")
    ensure_parent(temp_path)
    with open(temp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    record = index_file(temp_path, force=True)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO uploads (original_name, temp_path, processed, final_suggested_path, summary, extracted_text, created_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            safe_name,
            str(temp_path),
            1,
            record["suggested_folder"] if record else None,
            record["summary"] if record else None,
            record["extracted_text"] if record else None,
            time.time(),
        ),
    )
    conn.commit()
    conn.close()

    return {
        "uploaded_to": str(temp_path),
        "summary": record["summary"] if record else "",
        "suggested_folder": record["suggested_folder"] if record else "",
        "preview_path": record["preview_path"] if record else None,
        "thumb_path": record["thumb_path"] if record else None,
        "face_scan": record.get("face_scan") if record else None,
        "auto_tags": record.get("auto_tags") if record else None,
    }


@app.post("/api/accept-upload-placement")
def api_accept_upload_placement(temp_path: str, rel_folder: str):
    try:
        src = resolve_allowed_path(temp_path, [UPLOAD_DIR])
        target_folder = (ARCHIVE_ROOT / safe_relative_folder(rel_folder)).resolve(strict=False)
        if target_folder != ARCHIVE_ROOT.resolve(strict=False) and not path_is_inside(target_folder, ARCHIVE_ROOT):
            raise ValueError("Target folder is outside archive")
    except ValueError:
        raise HTTPException(status_code=403, detail="Upload placement is outside allowed roots")
    if not src.exists():
        raise HTTPException(status_code=404, detail="Uploaded temp file not found")
    target_path = unique_path(target_folder / src.name)
    ensure_parent(target_path)
    old_path = str(src)
    move_to(src, target_path)
    cleanup = remove_file_index_paths([old_path], "Upload temp file moved into archive")
    return {"saved_to": str(target_path), "record": index_file(target_path, force=True), "cleanup": cleanup}


@app.post("/api/reject-upload-placement")
def api_reject_upload_placement(temp_path: str):
    try:
        src = resolve_allowed_path(temp_path, [UPLOAD_DIR])
    except ValueError:
        raise HTTPException(status_code=403, detail="Upload is outside allowed roots")
    if not src.exists():
        raise HTTPException(status_code=404, detail="Uploaded temp file not found")
    dst = unique_path(REVIEW_UNCERTAIN_DIR / src.name)
    old_path = str(src)
    move_to(src, dst)
    cleanup = remove_file_index_paths([old_path], "Upload temp file moved to review")
    return {"moved_to_review": str(dst), "cleanup": cleanup}


@app.post("/api/index-all")
def api_index_all(force: bool = False):
    if pre_dedupe_job_snapshot()["running"]:
        raise HTTPException(status_code=409, detail="Wait for pre-index dedupe to finish before starting a full index.")
    started, job = start_index_thread(force=force)
    return {"started": started, "job": job}


@app.post("/api/index-pause")
def api_index_pause():
    snapshot = index_job_snapshot()
    run_id = snapshot.get("active_run_id")
    if not index_is_active(snapshot):
        return {"paused": False, "job": index_status_payload()}
    index_pause_requested.set()
    update_index_job(pause_requested=True, run_status="pausing")
    if run_id:
        set_run_status(int(run_id), "pausing")
    return {"paused": True, "job": index_status_payload()}


@app.post("/api/index-resume")
def api_index_resume():
    if pre_dedupe_job_snapshot()["running"]:
        raise HTTPException(status_code=409, detail="Wait for pre-index dedupe to finish before resuming the full index.")
    snapshot = index_job_snapshot()
    if index_is_active(snapshot):
        return {"started": False, "job": index_status_payload()}
    run = latest_resumable_run()
    if not run:
        raise HTTPException(status_code=404, detail="No paused or interrupted index run is available to resume.")
    run_id = int(run["id"])
    started, job = start_index_thread(force=bool(run.get("force")), run_id=run_id, resume=True)
    return {"started": started, "job": job}


@app.get("/api/index-scheduler")
def api_index_scheduler():
    return scheduler_snapshot()


@app.post("/api/index-scheduler")
def api_update_index_scheduler(req: IndexSchedulerRequest):
    if req.throttle_enabled is not None:
        index_scheduler["throttle_enabled"] = bool(req.throttle_enabled)
    if req.chat_idle_seconds is not None:
        index_scheduler["chat_idle_seconds"] = max(15, min(3600, int(req.chat_idle_seconds)))
    return scheduler_snapshot()


@app.post("/api/index-wipe")
def api_index_wipe():
    snapshot = index_job_snapshot()
    if index_is_active(snapshot):
        raise HTTPException(status_code=409, detail="Cannot wipe while archive indexing is running")
    index_snapshot = snapshot_file_index("pre_index_wipe")
    table_counts = clear_file_index()
    embedding_result = reset_archive_embeddings()
    reset_index_job_state()
    return {"snapshot": index_snapshot, "cleared": table_counts, "embeddings": embedding_result, "job": index_job_snapshot()}


@app.get("/api/index-status")
def api_index_status():
    return index_status_payload()
