from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fauxnix_tools.db import get_conn as _get_fauxnix_conn
from fauxnix_tools.files.extraction import extract_any
from fauxnix_tools.utils.categories import IMAGE_EXTS, VIDEO_EXTS, AUDIO_EXTS


def preview_file(path: str, max_bytes: int = 50 * 1024 * 1024) -> dict:
    p = Path(path)
    if not p.is_file():
        return {"ok": False, "error": "not_a_file"}

    ext = p.suffix.lower()
    stat = p.stat()
    info = {
        "name": p.name, "path": str(p),
        "size": stat.st_size, "size_human": _human_size(stat.st_size),
        "modified": stat.st_mtime, "ext": ext,
    }

    if stat.st_size > max_bytes and ext not in IMAGE_EXTS:
        return {**info, "ok": True, "preview": "[File too large to preview]", "preview_type": "text"}

    if ext in IMAGE_EXTS:
        return _preview_image(p, info)
    elif ext in VIDEO_EXTS:
        return _preview_video(p, info)
    elif ext in AUDIO_EXTS:
        return _preview_audio(p, info)
    elif ext in {".pdf", ".docx", ".xlsx", ".csv", ".txt", ".md", ".json", ".xml", ".log", ".yaml", ".yml"}:
        return _preview_text(p, ext, info)
    elif ext in {".py", ".js", ".ts", ".html", ".css", ".cpp", ".c", ".h", ".rs", ".go", ".java", ".sh"}:
        return _preview_code(p, ext, info)
    else:
        return {**info, "ok": True, "preview": f"[Binary file: {ext or 'unknown'}]", "preview_type": "text"}


def _preview_image(path: Path, info: dict) -> dict:
    try:
        from PIL import Image
        img = Image.open(path)
        info["width"] = img.width
        info["height"] = img.height
        info["format"] = img.format

        from fauxnix_tools.vision.analysis import analyze_image_path
        try:
            analysis = analyze_image_path(path)
            info["vision"] = analysis.get("analysis", {})
        except Exception:
            pass
    except Exception:
        pass
    return {**info, "ok": True, "preview_type": "image"}


def _preview_video(path: Path, info: dict) -> dict:
    from fauxnix_tools.media.probing import probe_video, extract_storyboard_frames, format_seconds
    try:
        probe = probe_video(path)
        info["duration"] = probe.get("duration_seconds")
        info["duration_human"] = format_seconds(probe.get("duration_seconds"))
        info["codec"] = (probe.get("streams") or [{}])[0].get("codec_name", "") if probe.get("streams") else ""
        frames = extract_storyboard_frames(path, probe, interval_seconds=30, max_frames=4)
        info["thumbnails"] = [f.get("thumb_path") for f in frames if f.get("thumb_path")]
    except Exception:
        info["preview"] = "[Video analysis unavailable]"
    return {**info, "ok": True, "preview_type": "video"}


def _preview_audio(path: Path, info: dict) -> dict:
    from fauxnix_tools.media.probing import probe_video
    try:
        probe = probe_video(path)
        info["duration"] = probe.get("duration_seconds")
        info["codec"] = (probe.get("streams") or [{}])[0].get("codec_name", "") if probe.get("streams") else ""
    except Exception:
        pass
    return {**info, "ok": True, "preview_type": "audio"}


def _preview_text(path: Path, ext: str, info: dict) -> dict:
    text = extract_any(path)
    info["chars"] = len(text)
    preview = text[:5000]
    if len(text) > 5000:
        preview += f"\n\n[... {len(text) - 5000} more characters]"
    return {**info, "ok": True, "preview": preview, "preview_type": "text"}


def _preview_code(path: Path, ext: str, info: dict) -> dict:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        info["chars"] = len(text)
        info["lines"] = text.count("\n") + 1
        preview = text[:8000]
        if len(text) > 8000:
            preview += f"\n\n[... {len(text) - 8000} more characters]"
        return {**info, "ok": True, "preview": preview, "preview_type": "code", "language": _lang_from_ext(ext)}
    except Exception:
        return {**info, "ok": True, "preview": "[Could not read file]", "preview_type": "text"}


def _lang_from_ext(ext: str) -> str:
    return {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".html": "html", ".css": "css", ".cpp": "cpp", ".c": "c",
        ".h": "c", ".rs": "rust", ".go": "go", ".java": "java",
        ".sh": "bash", ".sql": "sql",
    }.get(ext, "text")


def _human_size(size: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"
