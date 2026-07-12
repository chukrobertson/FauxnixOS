from __future__ import annotations

import json
import re
import time
from pathlib import Path

import ollama

from fauxnix_tools.config import config
from fauxnix_tools.db import get_conn
from fauxnix_tools.files.tagging import clean_tag_name
from fauxnix_tools.utils.categories import IMAGE_EXTS


VISION_TAG_SOURCE = "vision"
VISUAL_ANALYSIS_START = "[[FAUXNIX_VISUAL_ANALYSIS]]"
VISUAL_ANALYSIS_END = "[[/FAUXNIX_VISUAL_ANALYSIS]]"


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


def vision_status() -> dict:
    installed = sorted(_installed_ollama_models())
    model = config.ollama_vision_model
    fallback = config.ollama_vision_fallback
    selected = model if model in installed else (fallback if fallback in installed else model)
    return {
        "ready": bool(selected in installed) if installed else False,
        "model": selected,
        "installed": installed,
        "hint": "Install a vision model via Ollama (e.g. moondream:1.8b, minicpm-v:latest)",
    }


def _parse_jsonish(text: str) -> dict:
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE | re.MULTILINE).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start: end + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"caption": text.strip()[:1200], "objects": [], "scene_tags": [], "text": "", "people_count": None, "warnings": ["non_json_response"]}


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


def analyze_image_path(image_path: str | Path) -> dict:
    status = vision_status()
    if not status["ready"]:
        raise RuntimeError(status["hint"])
    path = Path(image_path)
    prompt = """
Look at this image. Do object and scene tagging only.
Do not identify people or infer identity from faces.
Return strict JSON with these keys:
caption: one concrete sentence about what is visible.
objects: array of visible object nouns, lowercase, no duplicates.
scene_tags: array of short scene/context tags.
text: any readable text in the image, otherwise empty string.
people_count: number of visible people if obvious, otherwise null.
warnings: array for uncertainty or image-quality limits.
""".strip()
    response = ollama.chat(
        model=status["model"],
        messages=[{"role": "user", "content": prompt, "images": [str(path)]}],
        options={"temperature": 0},
    )
    raw = response["message"]["content"] if isinstance(response, dict) else getattr(getattr(response, "message", None), "content", "") or ""
    parsed = _parse_jsonish(raw)
    result = normalize_vision_result(parsed)
    return {"ok": True, "model": status["model"], "analysis": result}


def vision_tag_names(analysis: dict) -> list[str]:
    tags = []
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


def analyze_image_file(path: str, file_id: int | None = None) -> dict:
    target_path = Path(path)
    analysis_result = analyze_image_path(target_path)
    analysis = analysis_result["analysis"]
    tags = vision_tag_names(analysis)
    tag_result = apply_vision_tags_to_file(file_id, tags)

    conn = get_conn()
    cur = conn.cursor()
    if file_id:
        block = f"{VISUAL_ANALYSIS_START}\nVisual analysis:\n{analysis.get('caption', '')}\nObjects: {', '.join(analysis.get('objects', []))}\nScene: {', '.join(analysis.get('scene_tags', []))}\n{VISUAL_ANALYSIS_END}"
        cur.execute("UPDATE files SET summary = COALESCE(NULLIF(summary, ''), ?) WHERE id = ?", (analysis.get("caption", "")[:500], int(file_id)))
        cur.execute("UPDATE files SET extracted_text = COALESCE(extracted_text || '\n\n', '') || ? WHERE id = ?", (block, int(file_id)))
        conn.commit()
    conn.close()

    return {"target": {"path": str(target_path), "file_id": file_id, "name": target_path.name}, **analysis_result, "tags": tag_result}
