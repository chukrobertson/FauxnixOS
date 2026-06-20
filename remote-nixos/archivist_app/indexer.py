from pathlib import Path
import hashlib
import os
from PIL import Image
import fitz

from app.db import get_conn
from app.utils import now_ts, sha256_file, safe_rel_path, guess_mime, file_category, file_extension, ensure_parent
from app.config import ARCHIVE_DUP_REVIEW_DIR, ARCHIVE_REVIEW_DIR, ARCHIVE_ROOT, KNOWLEDGEBASE_DIR, THUMBS_DIR, PREVIEW_DIR
from app.extractors import extract_any
from app.embeddings import chat_text
from app.autotagging import apply_auto_tags
from app.chat_engine import delete_embedding, sync_file_embedding_by_id
from app.face_tools import scan_file_faces
from app.maintenance import PRE_INDEX_DEDUPE_REASON, PRE_INDEX_HASH_NOTE
from app.organizer import suggest_folder_for_file
from app.source_safety import METADATA_ONLY_NOTE, is_chat_safe_source, source_policy


DEDUPE_REVIEW_REASON = "Exact SHA-256 duplicate; queued during dedupe-aware indexing"
CHATBOT_EXCLUDED_DIRS = {ARCHIVE_REVIEW_DIR, ARCHIVE_DUP_REVIEW_DIR}


def bounded_asset_name(path: Path, suffix: str, max_stem_chars: int = 72) -> str:
    digest = hashlib.sha256(str(path).encode("utf-8", errors="ignore")).hexdigest()[:16]
    safe_stem = "".join(c if c.isalnum() or c in {"-", "_"} else "_" for c in path.stem)
    safe_stem = safe_stem.strip("._")[:max_stem_chars] or "file"
    return f"{safe_stem}_{digest}{suffix}"


def duplicate_path_penalty(path_text: str) -> tuple[int, int, str]:
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


def choose_better_keeper(current_path: str, candidate_path: str) -> str:
    return min([current_path, candidate_path], key=duplicate_path_penalty)


def is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def is_chatbot_excluded(path: Path) -> bool:
    return any(is_inside(path, root) for root in CHATBOT_EXCLUDED_DIRS)


def source_is_metadata_only(path: Path) -> bool:
    policy = source_policy(path, "chat_aware")
    return policy["index_policy"] == "metadata_only"


def is_knowledgebase_path(path: Path) -> bool:
    try:
        return KNOWLEDGEBASE_DIR.exists() and is_inside(path, KNOWLEDGEBASE_DIR)
    except OSError:
        return False


def find_exact_duplicate(path: Path, file_hash: str) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT path, summary, category, preview_path, thumb_path
        FROM files
        WHERE sha256 = ? AND path != ? AND (duplicate_of IS NULL OR duplicate_of = '')
        ORDER BY deleted_candidate ASC, LENGTH(path) ASC, indexed_ts ASC
        LIMIT 1
        """,
        (file_hash, str(path)),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def queue_duplicate_review(path: str, reason: str = DEDUPE_REVIEW_REASON) -> None:
    conn = get_conn()
    cur = conn.cursor()
    ts = now_ts()
    cur.execute("SELECT id FROM files WHERE path = ?", (path,))
    row = cur.fetchone()
    file_id = int(row["id"]) if row else None
    cur.execute("UPDATE files SET deleted_candidate = 1 WHERE path = ?", (path,))
    cur.execute(
        """
        INSERT INTO deletion_reviews (file_id, path, reason, status, created_ts, updated_ts)
        SELECT ?, ?, ?, 'queued', ?, ?
        WHERE NOT EXISTS (
            SELECT 1 FROM deletion_reviews WHERE path = ? AND status = 'queued'
        )
        """,
        (file_id, path, reason, ts, ts, path),
    )
    conn.commit()
    conn.close()


def retarget_duplicate_records(old_keeper: str, new_keeper: str) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE files
        SET duplicate_of = ?
        WHERE duplicate_of = ?
        """,
        (new_keeper, old_keeper),
    )
    conn.commit()
    conn.close()


def summarize_file(name: str, category: str, text: str) -> str:
    prompt = f"""
Summarize this file for a personal archive catalog.
Be concise and practical.

Filename: {name}
Category: {category}
Content:
{text[:6000]}
"""
    try:
        return chat_text(prompt, task="summary")
    except Exception as e:
        return f"{category.title()} file: {name}. Summary unavailable during indexing: {e}"


def create_image_thumb(path: Path) -> str | None:
    try:
        img = Image.open(path)
        img.thumbnail((500, 500))
        thumb_path = THUMBS_DIR / "images" / bounded_asset_name(path, ".jpg")
        ensure_parent(thumb_path)
        img.convert("RGB").save(thumb_path, format="JPEG", quality=90)
        return str(thumb_path)
    except Exception:
        return None


def create_pdf_preview(path: Path) -> str | None:
    try:
        doc = fitz.open(path)
        page = doc.load_page(0)
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
        out = PREVIEW_DIR / bounded_asset_name(path, "_page1.jpg")
        ensure_parent(out)
        pix.save(str(out))
        return str(out)
    except Exception:
        return None


def upsert_file_record(record: dict) -> int:
    conn = get_conn()
    cur = conn.cursor()
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
            suggested_folder=excluded.suggested_folder,
            preview_path=excluded.preview_path,
            thumb_path=excluded.thumb_path,
            duplicate_of=excluded.duplicate_of,
            deleted_candidate=excluded.deleted_candidate,
            notes=excluded.notes
        """,
        (
            record["path"], record["rel_path"], record["name"], record["ext"], record["mime_type"],
            record["size_bytes"], record["sha256"], record["created_ts"], record["modified_ts"],
            record["indexed_ts"], record["category"], record["summary"], record["extracted_text"],
            record["suggested_folder"], record["preview_path"], record["thumb_path"], record["duplicate_of"],
            record["deleted_candidate"], record["notes"]
        ),
    )
    cur.execute("SELECT id FROM files WHERE path = ?", (record["path"],))
    file_id = int(cur.fetchone()["id"])
    conn.commit()
    conn.close()
    return file_id


def get_existing_file_record(path: Path) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM files WHERE path = ?", (str(path),))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def is_unchanged(existing: dict | None, stat: os.stat_result) -> bool:
    if not existing:
        return False
    if (existing.get("notes") or "") == PRE_INDEX_HASH_NOTE:
        return False
    old_mtime = float(existing.get("modified_ts") or -1)
    return (
        int(existing.get("size_bytes") or -1) == stat.st_size
        and abs(old_mtime - stat.st_mtime) < 0.0001
    )


def index_file(path: Path, force: bool = False):
    if not path.exists() or not path.is_file():
        return None

    if is_chatbot_excluded(path):
        return None

    stat = path.stat()
    existing = get_existing_file_record(path)
    if existing and int(existing.get("deleted_candidate") or 0) == 1 and (existing.get("notes") or "") == PRE_INDEX_DEDUPE_REASON:
        existing["duplicate"] = True
        existing["skipped"] = True
        return existing
    if not force and is_unchanged(existing, stat):
        existing["skipped"] = True
        return existing

    mime = guess_mime(path)
    ext = file_extension(path)
    category = file_category(path, mime)
    policy = source_policy(path, "chat_aware")
    if policy["index_policy"] == "metadata_only":
        summary = (
            f"{policy['source_kind_label']} source file: {path.name}. "
            "Metadata-only inventory; excluded from chat-aware indexing."
        )
        record = {
            "path": str(path),
            "rel_path": safe_rel_path(path, ARCHIVE_ROOT),
            "name": path.name,
            "ext": ext,
            "mime_type": mime,
            "size_bytes": stat.st_size,
            "sha256": existing.get("sha256") if existing else "",
            "created_ts": stat.st_ctime,
            "modified_ts": stat.st_mtime,
            "indexed_ts": now_ts(),
            "category": category,
            "summary": summary,
            "extracted_text": "",
            "suggested_folder": "Review/External Sources",
            "preview_path": existing.get("preview_path") if existing else None,
            "thumb_path": existing.get("thumb_path") if existing else None,
            "duplicate_of": existing.get("duplicate_of") if existing else None,
            "deleted_candidate": int(existing.get("deleted_candidate") or 0) if existing else 0,
            "notes": METADATA_ONLY_NOTE,
        }
        file_id = upsert_file_record(record)
        record["id"] = file_id
        try:
            record["auto_tags"] = apply_auto_tags(record)
        except Exception as error:
            record["auto_tags"] = {"applied": 0, "error": str(error)}
        record["metadata_only"] = True
        record["chat_policy"] = policy["chat_policy"]
        return record

    corpus = "knowledgebase" if is_knowledgebase_path(path) else "archive"
    if corpus == "knowledgebase":
        category = "knowledgebase"
    file_hash = sha256_file(path)

    exact_duplicate = find_exact_duplicate(path, file_hash)
    if exact_duplicate:
        keeper_path = exact_duplicate["path"]
        summary = f"Exact duplicate of {keeper_path}. Content hash matches; queued for deletion review."
        record = {
            "path": str(path),
            "rel_path": safe_rel_path(path, ARCHIVE_ROOT),
            "name": path.name,
            "ext": ext,
            "mime_type": mime,
            "size_bytes": stat.st_size,
            "sha256": file_hash,
            "created_ts": stat.st_ctime,
            "modified_ts": stat.st_mtime,
            "indexed_ts": now_ts(),
            "category": category,
            "summary": summary,
            "extracted_text": "",
            "suggested_folder": "Review/Duplicates",
            "preview_path": exact_duplicate.get("preview_path"),
            "thumb_path": exact_duplicate.get("thumb_path"),
            "duplicate_of": keeper_path,
            "deleted_candidate": 1,
            "notes": DEDUPE_REVIEW_REASON,
        }
        file_id = upsert_file_record(record)
        record["id"] = file_id
        queue_duplicate_review(str(path))
        delete_embedding(str(path))
        record["duplicate"] = True
        record["duplicate_of"] = keeper_path
        return record

    extracted_text = ""
    summary = ""
    preview_path = None
    thumb_path = None

    if category == "document":
        extracted_text = extract_any(path)
        summary = summarize_file(path.name, category, extracted_text) if extracted_text else f"Document file: {path.name}"
        if ext == ".pdf":
            preview_path = create_pdf_preview(path)

    elif category == "image":
        extracted_text = extract_any(path)
        summary = summarize_file(path.name, category, extracted_text) if extracted_text else f"Image file: {path.name}"
        thumb_path = create_image_thumb(path)
        preview_path = thumb_path

    elif category == "video":
        summary = f"Video file: {path.name}"

    elif category == "audio":
        summary = f"Audio file: {path.name}"

    else:
        summary = f"{category.title()} file: {path.name}"

    suggested_folder = suggest_folder_for_file(
        name=path.name,
        ext=ext,
        text=extracted_text,
        summary=summary,
        category=category,
    )

    record = {
        "path": str(path),
        "rel_path": safe_rel_path(path, ARCHIVE_ROOT),
        "name": path.name,
        "ext": ext,
        "mime_type": mime,
        "size_bytes": stat.st_size,
        "sha256": file_hash,
        "created_ts": stat.st_ctime,
        "modified_ts": stat.st_mtime,
        "indexed_ts": now_ts(),
        "category": category,
        "summary": summary,
        "extracted_text": extracted_text[:200000],
        "suggested_folder": suggested_folder,
        "preview_path": preview_path,
        "thumb_path": thumb_path,
        "duplicate_of": None,
        "deleted_candidate": 0,
        "notes": None,
    }

    file_id = upsert_file_record(record)
    record["id"] = file_id
    face_result = {"ok": True, "face_count": 0, "skipped": True, "reason": "not_visual_media"}
    if category in {"image", "video"} and not source_is_metadata_only(path):
        try:
            face_result = scan_file_faces(record)
        except Exception as error:
            face_result = {"ok": False, "face_count": 0, "error": str(error)}
    record["face_scan"] = face_result
    try:
        record["auto_tags"] = apply_auto_tags(record, face_count=int(face_result.get("face_count") or 0))
    except Exception as error:
        record["auto_tags"] = {"applied": 0, "error": str(error)}
    if is_chat_safe_source(path):
        record["embedding"] = sync_file_embedding_by_id(file_id)
    return record


def walk_archive():
    if not ARCHIVE_ROOT.exists():
        return
    if not is_chat_safe_source(ARCHIVE_ROOT):
        return
    for root, dirs, files in os.walk(ARCHIVE_ROOT):
        root_path = Path(root)
        dirs[:] = [
            directory
            for directory in dirs
            if not is_chatbot_excluded(root_path / directory)
        ]
        dirs.sort(key=lambda name: duplicate_path_penalty(str(Path(root) / name)))
        for file_name in sorted(files, key=lambda name: duplicate_path_penalty(str(Path(root) / name))):
            yield Path(root) / file_name
