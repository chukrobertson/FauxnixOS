from __future__ import annotations

import time
from pathlib import Path

from fauxnix_tools.config import config
from fauxnix_tools.db import get_conn
from fauxnix_tools.utils import sha256_file, guess_mime, now_ts
from fauxnix_tools.utils.categories import file_category, IMAGE_EXTS
from fauxnix_tools.files.extraction import extract_any
from fauxnix_tools.files.tagging import apply_auto_tags
from fauxnix_tools.vision.faces import scan_file_faces, AUTO_FACE_IMAGE_SOURCE, AUTO_FACE_VIDEO_SOURCE


def _bounded_asset_name(path: Path, suffix: str, max_stem: int = 72) -> str:
    clean = "".join(c if c.isalnum() or c in "._-" else "_" for c in path.stem)[:max_stem]
    return f"{path.stem[:2]}_{clean}_{suffix}"


def index_file(path: str, source_dir: str | None = None) -> dict:
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        return {"indexed": False, "reason": "not_found"}

    stat = file_path.stat()
    mime = guess_mime(file_path)
    category = file_category(file_path, mime)
    name = file_path.name
    ext = file_path.suffix.lower()
    file_hash = sha256_file(file_path)
    size_bytes = stat.st_size
    created_ts = stat.st_ctime
    modified_ts = stat.st_mtime
    indexed_ts = now_ts()

    extracted_text = extract_any(file_path)

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT id, sha256 FROM files WHERE path = ?", (str(file_path),))
    existing = cur.fetchone()

    if existing:
        if existing["sha256"] == file_hash:
            cur.execute("UPDATE files SET indexed_ts = ? WHERE id = ?", (indexed_ts, int(existing["id"])))
            conn.commit()
            conn.close()
            return {"indexed": True, "path": str(file_path), "file_id": int(existing["id"]), "updated": False}
        cur.execute("DELETE FROM files WHERE id = ?", (int(existing["id"]),))

    thumb_path = None
    preview_path = None

    if category == "image" and ext in IMAGE_EXTS:
        try:
            from PIL import Image
            thumb_dir = config.thumbs_dir / _bounded_asset_name(file_path, "thumb")
            thumb_dir.mkdir(parents=True, exist_ok=True)
            thumb = thumb_dir / "thumb.jpg"
            img = Image.open(file_path)
            img.thumbnail((500, 500))
            img.convert("RGB").save(thumb, format="JPEG", quality=85)
            thumb_path = str(thumb)
        except Exception:
            pass

    cur.execute(
        """INSERT INTO files (path, name, ext, mime_type, size_bytes, sha256, created_ts, modified_ts, indexed_ts, category, summary, extracted_text, thumb_path, preview_path, source_dir)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(file_path), name, ext, mime, size_bytes, file_hash, created_ts, modified_ts, indexed_ts, category, name[:200], extracted_text[:200000], thumb_path, preview_path, source_dir or ""),
    )
    file_id = int(cur.lastrowid)
    conn.commit()
    conn.close()

    record = {"id": file_id, "path": str(file_path), "name": name, "ext": ext, "category": category, "summary": name[:200], "extracted_text": extracted_text[:200000]}
    face_result = scan_file_faces(file_id, str(file_path), category)
    apply_auto_tags(record, face_count=int(face_result.get("face_count") or 0))

    return {"indexed": True, "path": str(file_path), "file_id": file_id, "category": category, "face_count": int(face_result.get("face_count") or 0), "updated": True}


def index_directory(dir_path: str, label: str | None = None) -> dict:
    root = Path(dir_path).resolve()
    if not root.is_dir():
        return {"indexed": 0, "skipped": 0, "error": "not_a_directory"}

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO indexed_dirs (path, label, last_indexed_ts, file_count) VALUES (?, ?, ?, 0)", (str(root), label or root.name, now_ts()))
    conn.commit()
    conn.close()

    indexed = 0
    skipped = 0
    errors = []
    for entry in sorted(root.rglob("*")):
        if entry.is_file():
            try:
                result = index_file(str(entry), source_dir=str(root))
                if result.get("indexed"):
                    indexed += 1
                else:
                    skipped += 1
            except Exception:
                errors.append(str(entry))
                skipped += 1

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE indexed_dirs SET file_count = ?, last_indexed_ts = ? WHERE path = ?", (indexed, now_ts(), str(root)))
    conn.commit()
    conn.close()

    return {"indexed": indexed, "skipped": skipped, "errors": len(errors), "source_dir": str(root)}


def search_indexed_files(query: str, limit: int = 20) -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    q = f"%{query}%"
    cur.execute(
        """SELECT id, path, name, ext, category, summary, size_bytes, source_dir
           FROM files WHERE name LIKE ? OR path LIKE ? OR summary LIKE ? OR extracted_text LIKE ?
           ORDER BY indexed_ts DESC LIMIT ?""",
        (q, q, q, q, limit),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows
