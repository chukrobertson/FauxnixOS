from __future__ import annotations

import json
import re
import time
from pathlib import Path

import ollama

from app.autotagging import IMAGE_EXTS, clean_tag_name
from app.chat_engine import sync_file_embedding_by_id
from app.config import ARCHIVE_ROOT, DATA_DIR
from app.db import get_conn
from app.model_router import model_for_task, route_for_task
from app.utils import guess_mime, resolve_allowed_path


VISION_TAG_SOURCE = "vision"
VISUAL_ANALYSIS_START = "[[ARCHIVIST_VISUAL_ANALYSIS]]"
VISUAL_ANALYSIS_END = "[[/ARCHIVIST_VISUAL_ANALYSIS]]"
VISION_ALLOWED_ROOTS = [ARCHIVE_ROOT, DATA_DIR]


def _installed_ollama_models() -> set[str]:
    try:
        response = ollama.list()
        models = getattr(response, "models", []) or []
        names = set()
        for item in models:
            name = getattr(item, "model", None) or getattr(item, "name", None)
            if isinstance(item, dict):
                name = item.get("model") or item.get("name") or name
            if name:
                names.add(str(name))
        return names
    except Exception:
        return set()


def _selected_vision_model() -> str:
    installed = _installed_ollama_models()
    primary = model_for_task("vision")
    if primary in installed:
        return primary
    fallback_key = route_for_task("vision").get("fallback")
    fallback = model_for_task(fallback_key) if fallback_key else ""
    if fallback in installed:
        return fallback
    return primary


def vision_status() -> dict:
    installed = sorted(_installed_ollama_models())
    model = _selected_vision_model()
    return {
        "ready": bool(model and model in installed),
        "model": model,
        "installed": installed,
        "hint": "Install or configure OLLAMA_VISION_MODEL for object tagging. Current default is qwen3-vl:8b.",
    }


def _file_row_by_id(file_id: int | None) -> dict | None:
    if not file_id:
        return None
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM files WHERE id = ?", (int(file_id),))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def _file_row_by_path(path: Path) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM files WHERE path = ?", (str(path),))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def resolve_image_target(path: str | None = None, file_id: int | None = None) -> dict:
    row = _file_row_by_id(file_id)
    if row:
        resolved = resolve_allowed_path(row["path"], VISION_ALLOWED_ROOTS)
    elif path:
        resolved = resolve_allowed_path(path, VISION_ALLOWED_ROOTS)
        row = _file_row_by_path(resolved)
    else:
        raise ValueError("Provide an image path or indexed file id.")
    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(f"Image file not found: {resolved}")
    mime = guess_mime(resolved)
    ext = resolved.suffix.lower()
    if not mime.startswith("image/") and ext not in IMAGE_EXTS:
        raise ValueError("Selected path does not look like an image file.")
    return {"path": resolved, "row": row, "file_id": int(row["id"]) if row else None, "mime": mime}


def _message_content(response) -> str:
    try:
        return str(response["message"]["content"] or "")
    except Exception:
        message = getattr(response, "message", None)
        return str(getattr(message, "content", "") or "")


def _parse_jsonish(text: str) -> dict:
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE | re.MULTILINE).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"caption": text.strip()[:1200], "objects": [], "scene_tags": [], "text": "", "people_count": None, "warnings": ["non_json_response"]}
    return data if isinstance(data, dict) else {}


def _clean_list(values, *, limit: int = 20) -> list[str]:
    cleaned = []
    for value in values or []:
        item = re.sub(r"[^a-zA-Z0-9 &/+\-]", " ", str(value or "").lower())
        item = " ".join(item.split())
        if not item or len(item) < 2:
            continue
        if item in {"unknown", "none", "n/a", "image", "photo", "picture"}:
            continue
        if item not in cleaned:
            cleaned.append(item[:48])
    return cleaned[:limit]


def normalize_vision_result(data: dict) -> dict:
    objects = _clean_list(data.get("objects") or data.get("detected_objects") or [])
    scene_tags = _clean_list(data.get("scene_tags") or data.get("tags") or [], limit=12)
    text = str(data.get("text") or data.get("visible_text") or "").strip()
    caption = str(data.get("caption") or data.get("summary") or "").strip()
    warnings = [str(item) for item in (data.get("warnings") or []) if str(item or "").strip()]
    people_count = data.get("people_count")
    try:
        people_count = int(people_count) if people_count is not None else None
    except (TypeError, ValueError):
        people_count = None
    return {
        "caption": caption[:1200],
        "objects": objects,
        "scene_tags": scene_tags,
        "text": text[:2000],
        "people_count": people_count,
        "warnings": warnings[:6],
    }


def analyze_image_path(image_path: str | Path, *, prompt_extra: str = "") -> dict:
    status = vision_status()
    if not status["ready"]:
        raise RuntimeError(status["hint"])
    path = Path(image_path)
    prompt = f"""
Look at this image as an archivist. Do object and scene tagging only.
Do not identify people or infer identity from faces.
Return strict JSON with these keys:
caption: one concrete sentence about what is visible.
objects: array of visible object nouns, lowercase, no duplicates.
scene_tags: array of short scene/context tags.
text: any readable text in the image, otherwise empty string.
people_count: number of visible people if obvious, otherwise null.
warnings: array for uncertainty or image-quality limits.
{prompt_extra}
""".strip()
    response = ollama.chat(
        model=status["model"],
        messages=[{"role": "user", "content": prompt, "images": [str(path)]}],
        options={"temperature": 0},
    )
    parsed = _parse_jsonish(_message_content(response))
    result = normalize_vision_result(parsed)
    return {"ok": True, "model": status["model"], "analysis": result}


def vision_tag_names(analysis: dict) -> list[str]:
    tags: list[str] = []
    for obj in analysis.get("objects") or []:
        tags.append(f"object: {obj}")
    for tag in analysis.get("scene_tags") or []:
        tags.append(tag)
    if analysis.get("text"):
        tags.append("has visible text")
    if analysis.get("people_count"):
        tags.append("has people")
    unique = []
    for tag in tags:
        try:
            cleaned = clean_tag_name(tag)
        except ValueError:
            continue
        if cleaned not in unique:
            unique.append(cleaned)
    return unique[:28]


def apply_vision_tags_to_file(file_id: int | None, tags: list[str], *, refresh: bool = True) -> dict:
    if not file_id:
        return {"applied": 0, "tags": [], "reason": "missing_file"}
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM files WHERE id = ?", (int(file_id),))
    if not cur.fetchone():
        conn.close()
        return {"applied": 0, "tags": [], "reason": "missing_file"}
    if refresh:
        cur.execute("DELETE FROM file_tags WHERE file_id = ? AND source = ?", (int(file_id), VISION_TAG_SOURCE))
    applied = 0
    now = time.time()
    clean_tags = []
    for tag in tags:
        try:
            name = clean_tag_name(tag)
        except ValueError:
            continue
        cur.execute("INSERT OR IGNORE INTO tags (name, color, created_ts) VALUES (?, ?, ?)", (name, None, now))
        cur.execute("SELECT id FROM tags WHERE name = ?", (name,))
        tag_id = int(cur.fetchone()["id"])
        cur.execute(
            "INSERT OR IGNORE INTO file_tags (file_id, tag_id, source, created_ts) VALUES (?, ?, ?, ?)",
            (int(file_id), tag_id, VISION_TAG_SOURCE, now),
        )
        applied += cur.rowcount
        clean_tags.append(name)
    conn.commit()
    conn.close()
    return {"file_id": int(file_id), "applied": applied, "tags": clean_tags}


def _visual_context_block(analysis: dict) -> str:
    lines = [VISUAL_ANALYSIS_START, "Visual analysis:"]
    if analysis.get("caption"):
        lines.append(str(analysis["caption"]))
    if analysis.get("objects"):
        lines.append("Objects: " + ", ".join(analysis["objects"]))
    if analysis.get("scene_tags"):
        lines.append("Scene tags: " + ", ".join(analysis["scene_tags"]))
    if analysis.get("people_count") is not None:
        lines.append(f"Visible people count: {analysis['people_count']}")
    if analysis.get("text"):
        lines.append("Visible text: " + str(analysis["text"])[:2000])
    lines.append(VISUAL_ANALYSIS_END)
    return "\n".join(lines)


def _replace_visual_block(existing: str, block: str) -> str:
    text = existing or ""
    pattern = re.compile(re.escape(VISUAL_ANALYSIS_START) + r".*?" + re.escape(VISUAL_ANALYSIS_END), re.DOTALL)
    text = pattern.sub("", text).strip()
    return "\n\n".join(part for part in [text, block] if part).strip()


def update_image_visual_context(file_id: int | None, analysis: dict) -> dict:
    if not file_id:
        return {"synced": False, "reason": "not_indexed"}
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT summary, extracted_text FROM files WHERE id = ?", (int(file_id),))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"synced": False, "reason": "missing_file"}
    summary = row["summary"] or ""
    caption = analysis.get("caption") or ""
    next_summary = caption if caption and (not summary or summary.startswith("Image file:")) else summary
    extracted_text = _replace_visual_block(row["extracted_text"] or "", _visual_context_block(analysis))
    cur.execute(
        "UPDATE files SET summary = ?, extracted_text = ?, indexed_ts = indexed_ts WHERE id = ?",
        (next_summary, extracted_text[:200000], int(file_id)),
    )
    conn.commit()
    conn.close()
    try:
        embedding = sync_file_embedding_by_id(int(file_id))
    except Exception as error:
        embedding = {"synced": False, "error": str(error)}
    return {"synced": True, "embedding": embedding}


def analyze_image_file(path: str | None = None, file_id: int | None = None, *, update_index: bool = True) -> dict:
    target = resolve_image_target(path, file_id)
    analysis_result = analyze_image_path(target["path"])
    analysis = analysis_result["analysis"]
    tags = vision_tag_names(analysis)
    tag_result = apply_vision_tags_to_file(target["file_id"], tags)
    sync = update_image_visual_context(target["file_id"], analysis) if update_index else {"synced": False, "reason": "update_index_false"}
    return {
        "target": {"path": str(target["path"]), "file_id": target["file_id"], "name": target["path"].name},
        **analysis_result,
        "tags": tag_result,
        "sync": sync,
        "status": vision_status(),
    }
