from __future__ import annotations

import re
import time
from pathlib import Path

from fauxnix_tools.db import get_conn
from fauxnix_tools.utils.categories import IMAGE_EXTS, VIDEO_EXTS, file_extension

AUTO_TAG_SOURCE = "auto"

KEYWORD_TAGS = [
    ("screenshot", {"screenshot", "screen shot", "screen_capture"}),
    ("receipt", {"receipt", "invoice", "order confirmation"}),
    ("document scan", {"scan", "scanned", "scanner"}),
    ("family", {"family"}),
    ("travel", {"trip", "travel", "vacation", "holiday"}),
    ("work", {"work", "meeting", "office"}),
    ("school", {"school", "class", "course", "homework"}),
]


def clean_tag_name(name: str) -> str:
    cleaned = " ".join((name or "").strip().split())
    if not cleaned:
        raise ValueError("Tag cannot be empty")
    return cleaned[:64]


def _ensure_tag(cur, name: str, color: str | None = None) -> int:
    tag = clean_tag_name(name)
    cur.execute(
        "INSERT OR IGNORE INTO tags (name, color, created_ts) VALUES (?, ?, ?)",
        (tag, color, time.time()),
    )
    cur.execute("SELECT id FROM tags WHERE name = ?", (tag,))
    return int(cur.fetchone()["id"])


def _file_id_from_record(cur, record: dict | None) -> int | None:
    if not record:
        return None
    if record.get("id"):
        return int(record["id"])
    path = record.get("path")
    if not path:
        return None
    cur.execute("SELECT id FROM files WHERE path = ?", (str(path),))
    row = cur.fetchone()
    return int(row["id"]) if row else None


def _keyword_tags(text: str) -> set[str]:
    normalized = re.sub(r"[_\-]+", " ", (text or "").lower())
    tags = set()
    for tag, needles in KEYWORD_TAGS:
        if any(needle in normalized for needle in needles):
            tags.add(tag)
    return tags


def suggested_auto_tags(record: dict | None, *, face_count: int = 0, extra_tags: list[str] | None = None) -> list[str]:
    if not record:
        return []
    category = (record.get("category") or "").strip().lower()
    ext = (record.get("ext") or Path(record.get("path") or "").suffix).strip().lower()
    name = record.get("name") or Path(record.get("path") or "").name
    summary = record.get("summary") or ""
    extracted = record.get("extracted_text") or ""

    tags = set()
    if category:
        tags.add(category)
    if category == "image" or ext in IMAGE_EXTS:
        tags.add("image")
    if category == "video" or ext in VIDEO_EXTS:
        tags.add("video")
    if extracted and not extracted.startswith("[") and not extracted.startswith("[OCR extraction error]"):
        tags.add("has text")
    if face_count > 0:
        tags.add("has faces")
    tags.update(_keyword_tags(" ".join([str(name), str(summary), str(extracted[:1000]), str(record.get("path") or "")])))
    for tag in extra_tags or []:
        if str(tag or "").strip():
            tags.add(str(tag).strip())
    return sorted(clean_tag_name(tag) for tag in tags if str(tag or "").strip())[:16]


def apply_auto_tags(record: dict | None, *, face_count: int = 0, extra_tags: list[str] | None = None, refresh: bool = True) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    file_id = _file_id_from_record(cur, record)
    if not file_id:
        conn.close()
        return {"applied": 0, "tags": [], "reason": "missing_file"}

    tags = suggested_auto_tags(record, face_count=face_count, extra_tags=extra_tags)
    if refresh:
        cur.execute("DELETE FROM file_tags WHERE file_id = ? AND source = ?", (file_id, AUTO_TAG_SOURCE))

    applied = 0
    ts = time.time()
    for tag in tags:
        tag_id = _ensure_tag(cur, tag)
        cur.execute(
            "INSERT OR IGNORE INTO file_tags (file_id, tag_id, source, created_ts) VALUES (?, ?, ?, ?)",
            (file_id, tag_id, AUTO_TAG_SOURCE, ts),
        )
        applied += cur.rowcount
    conn.commit()
    conn.close()
    return {"file_id": file_id, "applied": applied, "tags": tags}


def file_tag_names(file_id: int) -> list[str]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT t.name FROM file_tags ft
        JOIN tags t ON t.id = ft.tag_id
        WHERE ft.file_id = ?
        ORDER BY t.name COLLATE NOCASE
        """,
        (int(file_id),),
    )
    tags = [row["name"] for row in cur.fetchall()]
    conn.close()
    return tags
