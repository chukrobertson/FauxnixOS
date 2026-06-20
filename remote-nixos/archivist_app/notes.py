from __future__ import annotations

import shutil
import time
from pathlib import Path

from fastapi import UploadFile

from app.config import CLIPBOARD_DIR, NOTES_DIR
from app.db import get_conn
from app.utils import clean_filename, ensure_parent, unique_path


def media_kind(mime_type: str | None, filename: str | None = None) -> str:
    mime = (mime_type or "").lower()
    name = (filename or "").lower()
    if mime.startswith("image/") or name.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")):
        return "image"
    if mime.startswith("video/") or name.endswith((".mp4", ".webm", ".mov", ".mkv", ".avi")):
        return "video"
    if mime.startswith("audio/") or name.endswith((".mp3", ".wav", ".m4a", ".flac", ".ogg")):
        return "audio"
    return "file"


def title_from_content(content: str, fallback: str = "Untitled note") -> str:
    first = " ".join((content or "").strip().split())[:80]
    return first or fallback


def note_row(row) -> dict:
    item = dict(row)
    item["id"] = int(item["id"])
    return item


def clipboard_row(row) -> dict:
    item = dict(row)
    item["id"] = int(item["id"])
    if item.get("note_id") is not None:
        item["note_id"] = int(item["note_id"])
    return item


def save_upload_file(upload: UploadFile, root: Path) -> tuple[Path, int, str]:
    filename = clean_filename(upload.filename or "clipboard-item")
    target = unique_path(root / f"{int(time.time())}_{filename}")
    ensure_parent(target)
    with open(target, "wb") as handle:
        shutil.copyfileobj(upload.file, handle)
    return target, target.stat().st_size, filename


def create_note(
    *,
    title: str | None = None,
    content: str = "",
    kind: str = "text",
    file_path: str | None = None,
    original_name: str | None = None,
    mime_type: str | None = None,
    status: str = "active",
) -> dict:
    ts = time.time()
    note_title = title or title_from_content(content, original_name or "Untitled note")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO notes (title, content, kind, file_path, original_name, mime_type, status, created_ts, updated_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (note_title, content, kind, file_path, original_name, mime_type, status, ts, ts),
    )
    note_id = int(cur.lastrowid)
    cur.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
    row = cur.fetchone()
    conn.commit()
    conn.close()
    return note_row(row)


def list_notes(status: str = "active", limit: int = 80) -> list[dict]:
    clauses = []
    params: list = []
    if status != "all":
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT *
        FROM notes
        {where}
        ORDER BY updated_ts DESC, id DESC
        LIMIT ?
        """,
        [*params, max(1, min(int(limit), 200))],
    )
    rows = [note_row(row) for row in cur.fetchall()]
    conn.close()
    return rows


def update_note(note_id: int, *, title: str | None = None, content: str | None = None, status: str | None = None) -> dict:
    allowed_status = {"active", "done", "deleted"}
    fields = []
    params: list = []
    if title is not None:
        fields.append("title = ?")
        params.append(title.strip() or "Untitled note")
    if content is not None:
        fields.append("content = ?")
        params.append(content)
    if status is not None:
        if status not in allowed_status:
            raise ValueError("Unknown note status")
        fields.append("status = ?")
        params.append(status)
    fields.append("updated_ts = ?")
    params.append(time.time())
    params.append(int(note_id))
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"UPDATE notes SET {', '.join(fields)} WHERE id = ?", params)
    if cur.rowcount == 0:
        conn.close()
        raise ValueError("Note not found")
    cur.execute("SELECT * FROM notes WHERE id = ?", (int(note_id),))
    row = cur.fetchone()
    conn.commit()
    conn.close()
    return note_row(row)


def create_note_from_upload(upload: UploadFile) -> dict:
    path, size, filename = save_upload_file(upload, NOTES_DIR)
    kind = media_kind(upload.content_type, filename)
    content = f"Attached file: {path}"
    return create_note(
        title=filename,
        content=content,
        kind=kind,
        file_path=str(path),
        original_name=filename,
        mime_type=upload.content_type,
    )


def create_clipboard_text(content: str, source: str = "manual") -> dict:
    clean_content = (content or "").strip()
    if not clean_content:
        raise ValueError("Clipboard content is empty")
    note = create_note(title=title_from_content(clean_content, "Clipboard note"), content=clean_content, kind="text")
    ts = time.time()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO clipboard_items (kind, content, file_path, original_name, mime_type, size_bytes, source, note_id, created_ts)
        VALUES ('text', ?, NULL, NULL, 'text/plain', ?, ?, ?, ?)
        """,
        (clean_content, len(clean_content.encode("utf-8")), source, note["id"], ts),
    )
    item_id = int(cur.lastrowid)
    cur.execute("SELECT * FROM clipboard_items WHERE id = ?", (item_id,))
    row = cur.fetchone()
    conn.commit()
    conn.close()
    item = clipboard_row(row)
    item["note"] = note
    return item


def create_clipboard_file(upload: UploadFile, source: str = "drop") -> dict:
    path, size, filename = save_upload_file(upload, CLIPBOARD_DIR)
    kind = media_kind(upload.content_type, filename)
    note = create_note(
        title=filename,
        content=f"Attached file: {path}",
        kind=kind,
        file_path=str(path),
        original_name=filename,
        mime_type=upload.content_type,
    )
    ts = time.time()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO clipboard_items (kind, content, file_path, original_name, mime_type, size_bytes, source, note_id, created_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (kind, "", str(path), filename, upload.content_type, size, source, note["id"], ts),
    )
    item_id = int(cur.lastrowid)
    cur.execute("SELECT * FROM clipboard_items WHERE id = ?", (item_id,))
    row = cur.fetchone()
    conn.commit()
    conn.close()
    item = clipboard_row(row)
    item["note"] = note
    return item


def list_clipboard(limit: int = 20) -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM clipboard_items
        ORDER BY created_ts DESC, id DESC
        LIMIT ?
        """,
        (max(1, min(int(limit), 100)),),
    )
    rows = [clipboard_row(row) for row in cur.fetchall()]
    conn.close()
    return rows


def clear_clipboard() -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS count FROM clipboard_items")
    count = int(cur.fetchone()["count"])
    cur.execute("DELETE FROM clipboard_items")
    conn.commit()
    conn.close()
    return {"cleared": count}


def format_workspace_context(limit: int = 8) -> str:
    notes = list_notes(status="active", limit=limit)
    clips = list_clipboard(limit=min(limit, 5))
    blocks = []
    for note in notes[:limit]:
        body = note.get("content") or note.get("file_path") or ""
        blocks.append(
            f"[NOTE #{note['id']} | {note.get('kind') or 'text'} | {note.get('title') or 'Untitled'}]\n"
            f"{body[:1200]}"
        )
    for item in clips[:5]:
        body = item.get("content") or item.get("file_path") or ""
        blocks.append(
            f"[CLIPBOARD #{item['id']} | {item.get('kind') or 'text'}]\n"
            f"{body[:800]}"
        )
    return "\n\n".join(blocks)[:8000]
