from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import shutil
import subprocess
import time
from pathlib import Path

from app.chat_engine import sync_file_embedding_by_id
from app.autotagging import apply_auto_tags
from app.config import ARCHIVE_ROOT, DATA_DIR
from app.db import get_conn
from app.face_tools import detect_faces_in_storyboard
from app.utils import guess_mime, resolve_allowed_path
from app.vision_tools import analyze_image_path, apply_vision_tags_to_file, vision_status, vision_tag_names


MEDIA_CONTEXT_DIR = DATA_DIR / "media" / "video_context"
VIDEO_ALLOWED_ROOTS = [ARCHIVE_ROOT, DATA_DIR]
LOCAL_FFMPEG_BIN = DATA_DIR / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
LOCAL_FFPROBE_BIN = DATA_DIR / "tools" / "ffmpeg" / "bin" / "ffprobe.exe"
FFMPEG_BIN = os.getenv("FFMPEG_BIN", str(LOCAL_FFMPEG_BIN) if LOCAL_FFMPEG_BIN.exists() else "ffmpeg")
FFPROBE_BIN = os.getenv("FFPROBE_BIN", str(LOCAL_FFPROBE_BIN) if LOCAL_FFPROBE_BIN.exists() else "ffprobe")
MAX_STORYBOARD_FRAMES = 120
MAX_SUBTITLE_INDEX_CHARS = 24000
MAX_SUBTITLE_SEGMENT_CHARS = 6000
MAX_TRANSCRIPT_INDEX_CHARS = 48000
MAX_TRANSCRIPT_SEGMENT_CHARS = 3500
TRANSCRIPT_SOURCE = "video_transcript"
VIDEO_OBJECT_FRAME_LIMIT = max(1, min(int(os.getenv("VIDEO_OBJECT_FRAME_LIMIT", "12")), 40))
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "")


VIDEO_ANALYSIS_PRESETS = {
    "quick_skim": {
        "label": "Quick skim",
        "description": "Fast triage for long videos. Good first pass when you just need landmarks.",
        "interval_seconds": 120,
        "max_frames": 24,
    },
    "standard_survey": {
        "label": "Standard survey",
        "description": "Balanced archive scan. Enough frames to make the video searchable without being heavy.",
        "interval_seconds": 60,
        "max_frames": 48,
    },
    "dense_review": {
        "label": "Dense review",
        "description": "Closer review for important or visually busy footage.",
        "interval_seconds": 20,
        "max_frames": 120,
    },
    "short_clip": {
        "label": "Short clip",
        "description": "Tighter sampling for short videos, clips, phone footage, and excerpts.",
        "interval_seconds": 10,
        "max_frames": 60,
    },
}


def video_analysis_presets() -> list[dict]:
    return [{"id": preset_id, **config} for preset_id, config in VIDEO_ANALYSIS_PRESETS.items()]


def video_scan_candidates(*, rescan_existing: bool = False, include_delete_queue: bool = False, limit: int | None = None) -> list[dict]:
    clauses = ["category = 'video'"]
    params: list = []
    if not include_delete_queue:
        clauses.append("COALESCE(deleted_candidate, 0) = 0")
        clauses.append("(duplicate_of IS NULL OR duplicate_of = '')")
    if not rescan_existing:
        clauses.append(
            """
            NOT EXISTS (
                SELECT 1 FROM media_segments ms
                WHERE ms.file_id = files.id
                  AND ms.source IN ('ffmpeg_storyboard', 'ffprobe_chapter', 'ffmpeg_subtitle')
            )
            """
        )
    sql = f"""
        SELECT id, path, name, size_bytes, summary
        FROM files
        WHERE {' AND '.join(clauses)}
        ORDER BY size_bytes ASC, id ASC
    """
    if limit:
        sql += " LIMIT ?"
        params.append(max(1, min(int(limit), 10000)))
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


def _which(binary: str) -> str | None:
    try:
        if Path(binary).exists():
            return str(Path(binary))
    except OSError:
        pass
    return shutil.which(binary)


def ffmpeg_status() -> dict:
    ffmpeg = _which(FFMPEG_BIN)
    ffprobe = _which(FFPROBE_BIN)
    return {
        "ffmpeg": {"available": bool(ffmpeg), "path": ffmpeg or FFMPEG_BIN},
        "ffprobe": {"available": bool(ffprobe), "path": ffprobe or FFPROBE_BIN},
        "ready": bool(ffmpeg and ffprobe),
        "hint": "Install FFmpeg and make ffmpeg/ffprobe available on PATH, or set FFMPEG_BIN and FFPROBE_BIN.",
    }


def transcription_status() -> dict:
    faster = bool(importlib.util.find_spec("faster_whisper"))
    whisper = bool(importlib.util.find_spec("whisper"))
    whisper_cli = bool(shutil.which("whisper"))
    engine = None
    if faster:
        engine = "faster_whisper"
    elif whisper:
        engine = "openai_whisper"
    elif whisper_cli:
        engine = "whisper_cli"
    return {
        "ready": bool(engine),
        "engine": engine,
        "model": WHISPER_MODEL,
        "language": WHISPER_LANGUAGE or "auto",
        "ffmpeg": ffmpeg_status(),
        "hint": "Embedded subtitles work without ASR. For speech transcription, install faster-whisper or openai-whisper and set WHISPER_MODEL if needed.",
    }


def _run(args: list[str], timeout: int = 60) -> dict:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return {
            "ok": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "command": " ".join(args),
        }
    except (OSError, subprocess.SubprocessError) as error:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": str(error), "command": " ".join(args)}


def _preset_or_custom(preset: str | None, interval_seconds: int, max_frames: int) -> dict:
    if preset and preset in VIDEO_ANALYSIS_PRESETS:
        config = dict(VIDEO_ANALYSIS_PRESETS[preset])
        config["id"] = preset
    else:
        config = {
            "id": "custom",
            "label": "Custom",
            "description": "Manual interval and frame count.",
            "interval_seconds": interval_seconds,
            "max_frames": max_frames,
        }
    config["interval_seconds"] = max(5, min(int(config.get("interval_seconds") or interval_seconds or 60), 3600))
    config["max_frames"] = max(1, min(int(config.get("max_frames") or max_frames or 24), MAX_STORYBOARD_FRAMES))
    return config


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


def resolve_video_target(path: str | None = None, file_id: int | None = None) -> dict:
    row = _file_row_by_id(file_id)
    if row:
        resolved = resolve_allowed_path(row["path"], VIDEO_ALLOWED_ROOTS)
    elif path:
        resolved = resolve_allowed_path(path, VIDEO_ALLOWED_ROOTS)
        row = _file_row_by_path(resolved)
    else:
        raise ValueError("Provide a video path or indexed file id.")
    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(f"Video file not found: {resolved}")
    mime = guess_mime(resolved)
    if row and row.get("category") and row.get("category") != "video" and not mime.startswith("video/"):
        raise ValueError("Selected file is not indexed as video.")
    if not mime.startswith("video/") and resolved.suffix.lower() not in {
        ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".wmv", ".mpg", ".mpeg",
        ".3gp", ".3g2", ".mts", ".m2ts", ".ts", ".vob", ".ogv", ".flv", ".f4v",
        ".divx", ".mod", ".lrv", ".insv",
    }:
        raise ValueError("Selected path does not look like a video file.")
    return {"path": resolved, "row": row, "file_id": int(row["id"]) if row else None, "mime": mime}


def probe_video(path: Path) -> dict:
    status = ffmpeg_status()
    if not status["ffprobe"]["available"]:
        raise RuntimeError(status["hint"])
    result = _run(
        [
            status["ffprobe"]["path"],
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            "-show_chapters",
            str(path),
        ],
        timeout=45,
    )
    if not result["ok"]:
        raise RuntimeError(result["stderr"] or "ffprobe failed")
    data = json.loads(result["stdout"] or "{}")
    data["duration_seconds"] = _duration_from_probe(data)
    data["summary"] = summarize_probe(path, data)
    return data


def _duration_from_probe(data: dict) -> float:
    for value in [
        (data.get("format") or {}).get("duration"),
        *[(stream or {}).get("duration") for stream in data.get("streams") or []],
    ]:
        try:
            if value is not None:
                return max(0.0, float(value))
        except (TypeError, ValueError):
            pass
    return 0.0


def _stream_summary(data: dict) -> list[str]:
    parts = []
    for stream in data.get("streams") or []:
        codec_type = stream.get("codec_type") or "stream"
        codec = stream.get("codec_name") or "unknown"
        if codec_type == "video":
            width = stream.get("width")
            height = stream.get("height")
            fps = stream.get("avg_frame_rate") or ""
            parts.append(f"video {codec} {width or '?'}x{height or '?'} {fps}")
        elif codec_type == "audio":
            channels = stream.get("channels")
            parts.append(f"audio {codec} {channels or '?'}ch")
        elif codec_type == "subtitle":
            parts.append(f"subtitle {codec}")
        else:
            parts.append(f"{codec_type} {codec}")
    return parts


def _selected_tags(data: dict) -> dict:
    tags = (data.get("format") or {}).get("tags") or {}
    keep = {}
    for key in ["title", "artist", "album", "date", "creation_time", "encoder", "comment"]:
        value = tags.get(key)
        if value:
            keep[key] = str(value)[:240]
    return keep


def summarize_probe(path: Path, data: dict) -> str:
    duration = _duration_from_probe(data)
    streams = "; ".join(_stream_summary(data)) or "streams unknown"
    chapters = len(data.get("chapters") or [])
    tags = _selected_tags(data)
    title = tags.get("title") or path.stem
    tag_text = ""
    if tags:
        tag_text = " Tags: " + "; ".join(f"{key}={value}" for key, value in tags.items()) + "."
    return f"Video: {title}. Duration {format_seconds(duration)}. Streams: {streams}. Chapters: {chapters}.{tag_text}"


def format_seconds(seconds: float | int | None) -> str:
    total = int(round(float(seconds or 0)))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _context_dir(path: Path) -> Path:
    stat = path.stat()
    key = hashlib.sha1(f"{path}|{stat.st_mtime_ns}|{stat.st_size}".encode("utf-8", errors="ignore")).hexdigest()[:18]
    return MEDIA_CONTEXT_DIR / key


def _timestamps(duration: float, interval_seconds: int, max_frames: int) -> list[float]:
    max_frames = max(1, min(int(max_frames or 24), MAX_STORYBOARD_FRAMES))
    interval = max(5, min(int(interval_seconds or 60), 3600))
    if duration <= 0:
        return [1.0]
    values = []
    current = 0.0
    while current < duration and len(values) < max_frames:
        values.append(current)
        current += interval
    if values and duration - values[-1] > interval / 2 and len(values) < max_frames:
        values.append(max(0.0, duration - 1.0))
    return values or [0.0]


def extract_storyboard_frames(path: Path, probe: dict, interval_seconds: int = 60, max_frames: int = 24) -> list[dict]:
    status = ffmpeg_status()
    if not status["ffmpeg"]["available"]:
        raise RuntimeError(status["hint"])
    out_dir = _context_dir(path)
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = float(probe.get("duration_seconds") or 0)
    segments = []
    for index, start in enumerate(_timestamps(duration, interval_seconds, max_frames), start=1):
        thumb_path = out_dir / f"frame_{index:03d}_{int(start):06d}.jpg"
        result = _run(
            [
                status["ffmpeg"]["path"],
                "-y",
                "-loglevel",
                "error",
                "-ss",
                f"{start:.3f}",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-vf",
                "scale=420:-1",
                "-q:v",
                "4",
                str(thumb_path),
            ],
            timeout=45,
        )
        if result["ok"] and thumb_path.exists():
            end = min(duration, start + max(5, interval_seconds)) if duration else None
            segments.append(
                {
                    "start_seconds": start,
                    "end_seconds": end,
                    "title": f"Storyboard frame {index}",
                    "summary": f"FFmpeg storyboard frame at {format_seconds(start)}.",
                    "timeline": "storyboard",
                    "tags": ["storyboard", "video"],
                    "associations": [],
                    "thumb_path": str(thumb_path),
                    "source": "ffmpeg_storyboard",
                }
            )
    return segments


def _float_or_none(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_chapter_segments(probe: dict) -> list[dict]:
    segments = []
    for index, chapter in enumerate(probe.get("chapters") or [], start=1):
        start = _float_or_none(chapter.get("start_time")) or 0.0
        end = _float_or_none(chapter.get("end_time"))
        tags = chapter.get("tags") or {}
        title = tags.get("title") or f"Chapter {index}"
        summary = f"Embedded chapter marker from {format_seconds(start)}"
        if end is not None:
            summary += f" to {format_seconds(end)}"
        segments.append(
            {
                "start_seconds": start,
                "end_seconds": end,
                "title": title,
                "summary": summary + ".",
                "timeline": "chapters",
                "tags": ["chapter", "video"],
                "associations": [],
                "thumb_path": None,
                "source": "ffprobe_chapter",
            }
        )
    return segments


def _subtitle_streams(probe: dict) -> list[dict]:
    return [stream for stream in probe.get("streams") or [] if stream.get("codec_type") == "subtitle"]


def _clean_subtitle_text(text: str, limit: int = MAX_SUBTITLE_INDEX_CHARS) -> str:
    lines = []
    for line in (text or "").splitlines():
        item = line.strip()
        if not item:
            continue
        if item.isdigit() or "-->" in item:
            continue
        if item.startswith("{\\") or item.startswith("WEBVTT"):
            continue
        lines.append(item)
    cleaned = "\n".join(lines)
    return cleaned[:limit]


def extract_subtitle_text(path: Path, probe: dict) -> dict:
    streams = _subtitle_streams(probe)
    if not streams:
        return {"available": False, "streams": 0, "text": "", "path": None, "error": None}
    status = ffmpeg_status()
    if not status["ffmpeg"]["available"]:
        return {"available": False, "streams": len(streams), "text": "", "path": None, "error": status["hint"]}
    stream = streams[0]
    stream_index = stream.get("index", 0)
    out_dir = _context_dir(path)
    out_dir.mkdir(parents=True, exist_ok=True)
    subtitle_path = out_dir / f"subtitles_stream_{stream_index}.srt"
    result = _run(
        [
            status["ffmpeg"]["path"],
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-map",
            f"0:{stream_index}",
            "-c:s",
            "srt",
            str(subtitle_path),
        ],
        timeout=120,
    )
    if not result["ok"] or not subtitle_path.exists():
        return {
            "available": False,
            "streams": len(streams),
            "text": "",
            "path": None,
            "error": result["stderr"] or "Subtitle extraction failed.",
        }
    raw = subtitle_path.read_text(encoding="utf-8", errors="ignore")
    text = _clean_subtitle_text(raw)
    return {"available": bool(text), "streams": len(streams), "text": text, "path": str(subtitle_path), "error": None}


def subtitle_segment(subtitles: dict, duration: float) -> dict | None:
    text = (subtitles or {}).get("text") or ""
    if not text:
        return None
    summary = text[:MAX_SUBTITLE_SEGMENT_CHARS]
    if len(text) > MAX_SUBTITLE_SEGMENT_CHARS:
        summary += "\n[subtitle text truncated for timeline card]"
    return {
        "start_seconds": 0,
        "end_seconds": duration or None,
        "title": "Embedded subtitles",
        "summary": summary,
        "timeline": "subtitles",
        "tags": ["subtitle", "transcript", "video"],
        "associations": [],
        "thumb_path": None,
        "source": "ffmpeg_subtitle",
    }


def _extract_audio_for_transcription(path: Path) -> Path:
    status = ffmpeg_status()
    if not status["ffmpeg"]["available"]:
        raise RuntimeError(status["hint"])
    out_dir = _context_dir(path)
    out_dir.mkdir(parents=True, exist_ok=True)
    audio_path = out_dir / "transcription_audio.wav"
    result = _run(
        [
            status["ffmpeg"]["path"],
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(audio_path),
        ],
        timeout=600,
    )
    if not result["ok"] or not audio_path.exists():
        raise RuntimeError(result["stderr"] or "Audio extraction failed.")
    return audio_path


def _write_transcript_artifacts(path: Path, text: str, segments: list[dict]) -> dict:
    out_dir = _context_dir(path)
    out_dir.mkdir(parents=True, exist_ok=True)
    txt_path = out_dir / "transcript.txt"
    json_path = out_dir / "transcript_segments.json"
    txt_path.write_text(text or "", encoding="utf-8", errors="ignore")
    json_path.write_text(json.dumps(segments or [], indent=2), encoding="utf-8")
    return {"text_path": str(txt_path), "segments_path": str(json_path)}


def _transcribe_with_faster_whisper(audio_path: Path) -> dict:
    from faster_whisper import WhisperModel

    device = os.getenv("WHISPER_DEVICE", "cpu")
    compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
    model = WhisperModel(WHISPER_MODEL, device=device, compute_type=compute_type)
    kwargs = {"vad_filter": True}
    if WHISPER_LANGUAGE:
        kwargs["language"] = WHISPER_LANGUAGE
    segments, info = model.transcribe(str(audio_path), **kwargs)
    rows = []
    texts = []
    for segment in segments:
        text = (segment.text or "").strip()
        if not text:
            continue
        rows.append({"start": float(segment.start or 0), "end": float(segment.end or 0), "text": text})
        texts.append(text)
    return {"text": "\n".join(texts), "segments": rows, "language": getattr(info, "language", None), "engine": "faster_whisper"}


def _transcribe_with_openai_whisper(audio_path: Path) -> dict:
    import whisper

    model = whisper.load_model(WHISPER_MODEL)
    kwargs = {}
    if WHISPER_LANGUAGE:
        kwargs["language"] = WHISPER_LANGUAGE
    result = model.transcribe(str(audio_path), **kwargs)
    rows = []
    for segment in result.get("segments") or []:
        text = (segment.get("text") or "").strip()
        if text:
            rows.append({"start": float(segment.get("start") or 0), "end": float(segment.get("end") or 0), "text": text})
    text = (result.get("text") or "\n".join(row["text"] for row in rows)).strip()
    return {"text": text, "segments": rows, "language": result.get("language"), "engine": "openai_whisper"}


def _transcribe_with_whisper_cli(audio_path: Path, video_path: Path) -> dict:
    out_dir = _context_dir(video_path)
    args = ["whisper", str(audio_path), "--model", WHISPER_MODEL, "--output_dir", str(out_dir), "--output_format", "json", "--fp16", "False"]
    if WHISPER_LANGUAGE:
        args.extend(["--language", WHISPER_LANGUAGE])
    result = _run(args, timeout=7200)
    if not result["ok"]:
        raise RuntimeError(result["stderr"] or "Whisper CLI failed.")
    json_path = out_dir / f"{audio_path.stem}.json"
    if not json_path.exists():
        raise RuntimeError("Whisper CLI did not produce a JSON transcript.")
    data = json.loads(json_path.read_text(encoding="utf-8", errors="ignore"))
    rows = []
    for segment in data.get("segments") or []:
        text = (segment.get("text") or "").strip()
        if text:
            rows.append({"start": float(segment.get("start") or 0), "end": float(segment.get("end") or 0), "text": text})
    text = (data.get("text") or "\n".join(row["text"] for row in rows)).strip()
    return {"text": text, "segments": rows, "language": data.get("language"), "engine": "whisper_cli"}


def _run_asr(audio_path: Path, video_path: Path) -> dict:
    status = transcription_status()
    engine = status.get("engine")
    if engine == "faster_whisper":
        return _transcribe_with_faster_whisper(audio_path)
    if engine == "openai_whisper":
        return _transcribe_with_openai_whisper(audio_path)
    if engine == "whisper_cli":
        return _transcribe_with_whisper_cli(audio_path, video_path)
    raise RuntimeError(status["hint"])


def _chunk_transcript_segments(transcript: dict, duration: float) -> list[dict]:
    rows = transcript.get("segments") or []
    if not rows:
        text = (transcript.get("text") or "").strip()
        if not text:
            return []
        return [
            {
                "start_seconds": 0,
                "end_seconds": duration or None,
                "title": "Speech transcript",
                "summary": text[:MAX_TRANSCRIPT_SEGMENT_CHARS],
                "timeline": "transcript",
                "tags": ["transcript", "speech", "video"],
                "associations": [],
                "thumb_path": None,
                "source": TRANSCRIPT_SOURCE,
            }
        ]
    chunks = []
    current = []
    start = None
    end = None
    for row in rows:
        text = (row.get("text") or "").strip()
        if not text:
            continue
        row_start = float(row.get("start") or 0)
        row_end = float(row.get("end") or row_start)
        if start is None:
            start = row_start
        would_be = " ".join([*current, text]).strip()
        if current and (len(would_be) > MAX_TRANSCRIPT_SEGMENT_CHARS or row_start - float(start or 0) > 90):
            chunks.append((start or 0, end, " ".join(current).strip()))
            current = [text]
            start = row_start
        else:
            current.append(text)
        end = row_end
    if current:
        chunks.append((start or 0, end, " ".join(current).strip()))
    return [
        {
            "start_seconds": chunk_start,
            "end_seconds": chunk_end,
            "title": f"Speech transcript {index}",
            "summary": text,
            "timeline": "transcript",
            "tags": ["transcript", "speech", "video"],
            "associations": [],
            "thumb_path": None,
            "source": TRANSCRIPT_SOURCE,
        }
        for index, (chunk_start, chunk_end, text) in enumerate(chunks, start=1)
    ]


def create_contact_sheet(path: Path, segments: list[dict]) -> str | None:
    thumbs = [Path(segment["thumb_path"]) for segment in segments if segment.get("thumb_path") and Path(segment["thumb_path"]).exists()]
    if len(thumbs) < 2:
        return str(thumbs[0]) if thumbs else None
    status = ffmpeg_status()
    if not status["ffmpeg"]["available"]:
        return None
    out_dir = _context_dir(path)
    out_dir.mkdir(parents=True, exist_ok=True)
    list_path = out_dir / "contact_sheet_inputs.txt"
    chosen = thumbs[: min(len(thumbs), 80)]
    with list_path.open("w", encoding="utf-8") as handle:
        for thumb in chosen:
            escaped = str(thumb).replace("\\", "/").replace("'", "'\\''")
            handle.write(f"file '{escaped}'\n")
    cols = 4
    rows = max(1, math.ceil(len(chosen) / cols))
    sheet_path = out_dir / "contact_sheet.jpg"
    result = _run(
        [
            status["ffmpeg"]["path"],
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-vf",
            f"scale=260:-1,tile={cols}x{rows}:padding=8:margin=8",
            "-frames:v",
            "1",
            str(sheet_path),
        ],
        timeout=60,
    )
    return str(sheet_path) if result["ok"] and sheet_path.exists() else None


def _object_summary_text(analysis: dict) -> str:
    parts = []
    if analysis.get("caption"):
        parts.append(str(analysis["caption"]))
    if analysis.get("objects"):
        parts.append("Objects: " + ", ".join(analysis["objects"]))
    if analysis.get("scene_tags"):
        parts.append("Scene: " + ", ".join(analysis["scene_tags"]))
    if analysis.get("text"):
        parts.append("Visible text: " + str(analysis["text"])[:500])
    return " ".join(parts).strip()


def analyze_storyboard_objects(video_path: Path, *, file_id: int | None, segments: list[dict], max_frames: int | None = None) -> dict:
    status = vision_status()
    if not status.get("ready"):
        return {"ok": False, "skipped": True, "frames_analyzed": 0, "objects": [], "tags": [], "error": status.get("hint"), "status": status}
    frame_limit = max(1, min(int(max_frames or VIDEO_OBJECT_FRAME_LIMIT), 40))
    frame_segments = [
        segment
        for segment in segments
        if segment.get("source") == "ffmpeg_storyboard" and segment.get("thumb_path") and Path(segment["thumb_path"]).exists()
    ][:frame_limit]
    objects: list[str] = []
    tag_names: list[str] = []
    analyses = []
    for segment in frame_segments:
        try:
            result = analyze_image_path(
                segment["thumb_path"],
                prompt_extra="This is a video storyboard frame. Prefer stable objects and scene clues useful for archive search.",
            )
            analysis = result.get("analysis") or {}
            analyses.append({"start_seconds": segment.get("start_seconds"), "thumb_path": segment.get("thumb_path"), "analysis": analysis})
            for item in analysis.get("objects") or []:
                if item not in objects:
                    objects.append(item)
            for tag in vision_tag_names(analysis):
                if tag not in tag_names:
                    tag_names.append(tag)
            summary = _object_summary_text(analysis)
            if summary:
                segment["summary"] = f"{segment.get('summary') or ''} {summary}".strip()
            segment["tags"] = sorted({*(segment.get("tags") or []), "vision", *(analysis.get("objects") or []), *(analysis.get("scene_tags") or [])})[:24]
        except Exception as error:
            analyses.append({"start_seconds": segment.get("start_seconds"), "thumb_path": segment.get("thumb_path"), "error": str(error)})
    tag_result = apply_vision_tags_to_file(file_id, tag_names) if file_id else {"applied": 0, "tags": [], "reason": "not_indexed"}
    return {
        "ok": True,
        "frames_analyzed": len(frame_segments),
        "objects": objects[:60],
        "tags": tag_result,
        "analyses": analyses,
        "status": status,
    }


def video_artifacts(path: Path) -> dict:
    out_dir = _context_dir(path)
    sheet = out_dir / "contact_sheet.jpg"
    return {
        "context_dir": str(out_dir),
        "contact_sheet": str(sheet) if sheet.exists() else None,
    }


def scan_summary(path: Path, probe: dict, segments: list[dict], preset: dict | None = None, subtitles: dict | None = None, contact_sheet: str | None = None) -> dict:
    streams = probe.get("streams") or []
    stream_counts = {}
    for stream in streams:
        kind = stream.get("codec_type") or "stream"
        stream_counts[kind] = stream_counts.get(kind, 0) + 1
    storyboards = [segment for segment in segments if segment.get("source") == "ffmpeg_storyboard"]
    chapters = [segment for segment in segments if segment.get("source") == "ffprobe_chapter"]
    transcripts = [segment for segment in segments if segment.get("source") in {TRANSCRIPT_SOURCE, "ffmpeg_subtitle"}]
    vision_segments = [segment for segment in storyboards if "vision" in (segment.get("tags") or [])]
    return {
        "duration_seconds": probe.get("duration_seconds") or 0,
        "duration_label": format_seconds(probe.get("duration_seconds") or 0),
        "streams": stream_counts,
        "chapters": len(chapters) if chapters else len(probe.get("chapters") or []),
        "storyboard_frames": len(storyboards),
        "subtitle_streams": (subtitles or {}).get("streams", len(_subtitle_streams(probe))),
        "subtitles_extracted": bool((subtitles or {}).get("text")),
        "transcript_segments": len(transcripts),
        "object_frames": len(vision_segments),
        "contact_sheet": contact_sheet or video_artifacts(path).get("contact_sheet"),
        "context_dir": video_artifacts(path).get("context_dir"),
        "preset": preset or {},
        "tags": _selected_tags(probe),
    }


def _segment_from_row(row) -> dict:
    item = dict(row)
    item["tags"] = json.loads(item.get("tags_json") or "[]")
    item["associations"] = json.loads(item.get("associations_json") or "[]")
    return item


def list_video_segments(path: str | Path | None = None, file_id: int | None = None) -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    if file_id:
        cur.execute("SELECT * FROM media_segments WHERE file_id = ? ORDER BY start_seconds, id", (int(file_id),))
    else:
        cur.execute("SELECT * FROM media_segments WHERE path = ? ORDER BY start_seconds, id", (str(path),))
    rows = [_segment_from_row(row) for row in cur.fetchall()]
    conn.close()
    return rows


def _insert_segment(cur, *, file_id: int | None, path: Path, segment: dict, source: str = "manual") -> int:
    now = time.time()
    cur.execute(
        """
        INSERT INTO media_segments (
            file_id, path, media_type, start_seconds, end_seconds, title, summary,
            timeline, tags_json, associations_json, thumb_path, source, created_ts, updated_ts
        )
        VALUES (?, ?, 'video', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_id,
            str(path),
            float(segment.get("start_seconds") or 0),
            segment.get("end_seconds"),
            (segment.get("title") or "").strip() or None,
            (segment.get("summary") or "").strip() or None,
            (segment.get("timeline") or "").strip() or None,
            json.dumps(segment.get("tags") or []),
            json.dumps(segment.get("associations") or []),
            segment.get("thumb_path") or None,
            segment.get("source") or source,
            now,
            now,
        ),
    )
    return int(cur.lastrowid)


def _segment_context_text(segments: list[dict]) -> str:
    lines = []
    for segment in segments:
        title = segment.get("title") or "segment"
        summary = segment.get("summary") or ""
        timeline = segment.get("timeline") or ""
        tags = ", ".join(segment.get("tags") or [])
        associations = ", ".join(segment.get("associations") or [])
        end_text = format_seconds(segment.get("end_seconds")) if segment.get("end_seconds") is not None else "open"
        lines.append(
            f"{format_seconds(segment.get('start_seconds'))}-{end_text}: "
            f"{title}. {summary} Timeline: {timeline}. Tags: {tags}. Associations: {associations}."
        )
    return "\n".join(lines)


def refresh_video_file_context(file_id: int | None, path: Path, probe: dict | None = None, extra_text: str | None = None) -> dict:
    if not file_id:
        return {"synced": False, "reason": "not_indexed"}
    segments = list_video_segments(file_id=file_id)
    probe_summary = (probe or {}).get("summary") or f"Video file: {path.name}"
    parts = [probe_summary, _segment_context_text(segments)]
    if extra_text:
        parts.append("Extracted subtitle text:\n" + extra_text[:MAX_SUBTITLE_INDEX_CHARS])
    extracted_text = "\n".join(part for part in parts if part).strip()
    thumb_path = next((segment.get("thumb_path") for segment in segments if segment.get("thumb_path")), None)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE files
        SET category = 'video',
            summary = ?,
            extracted_text = ?,
            preview_path = COALESCE(?, preview_path),
            thumb_path = COALESCE(?, thumb_path)
        WHERE id = ?
        """,
        (probe_summary, extracted_text, thumb_path, thumb_path, int(file_id)),
    )
    conn.commit()
    conn.close()
    try:
        embedding = sync_file_embedding_by_id(int(file_id))
    except Exception as error:
        embedding = {"synced": False, "error": str(error)}
    return {"synced": True, "embedding": embedding, "segments": len(segments)}


def analyze_video(
    path: str | None = None,
    file_id: int | None = None,
    interval_seconds: int = 60,
    max_frames: int = 24,
    update_index: bool = True,
    preset: str | None = "standard_survey",
    detect_faces: bool = True,
    detect_objects: bool = False,
) -> dict:
    profile = _preset_or_custom(preset, interval_seconds, max_frames)
    target = resolve_video_target(path, file_id)
    video_path = target["path"]
    probe = probe_video(video_path)
    segments = extract_storyboard_frames(
        video_path,
        probe,
        profile["interval_seconds"],
        profile["max_frames"],
    )
    chapter_segments = extract_chapter_segments(probe)
    subtitles = extract_subtitle_text(video_path, probe)
    subtitle = subtitle_segment(subtitles, float(probe.get("duration_seconds") or 0))
    all_generated_segments = [*segments, *chapter_segments]
    if subtitle:
        all_generated_segments.append(subtitle)
    contact_sheet = create_contact_sheet(video_path, segments)
    face_scan = (
        detect_faces_in_storyboard(video_path, file_id=target["file_id"], segments=segments)
        if detect_faces
        else {"ok": False, "skipped": True, "face_count": 0, "reason": "detect_faces_false"}
    )
    object_scan = (
        analyze_storyboard_objects(video_path, file_id=target["file_id"], segments=segments)
        if detect_objects
        else {"ok": False, "skipped": True, "frames_analyzed": 0, "objects": [], "reason": "detect_objects_false"}
    )
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        DELETE FROM media_segments
        WHERE path = ? AND source IN ('ffmpeg_storyboard', 'ffprobe_chapter', 'ffmpeg_subtitle')
        """,
        (str(video_path),),
    )
    ids = [_insert_segment(cur, file_id=target["file_id"], path=video_path, segment=segment, source=segment.get("source") or "ffmpeg") for segment in all_generated_segments]
    conn.commit()
    conn.close()
    stored_segments = list_video_segments(path=video_path, file_id=target["file_id"])
    record_for_tags = dict(target["row"] or {})
    record_for_tags.update({"id": target["file_id"], "path": str(video_path), "name": video_path.name, "category": "video"})
    try:
        auto_extra_tags = ["storyboard"]
        if object_scan.get("objects"):
            auto_extra_tags.append("objects detected")
        auto_tags = apply_auto_tags(record_for_tags, face_count=int(face_scan.get("face_count") or 0), extra_tags=auto_extra_tags)
    except Exception as error:
        auto_tags = {"applied": 0, "error": str(error)}
    sync = (
        refresh_video_file_context(target["file_id"], video_path, probe, extra_text=subtitles.get("text"))
        if update_index
        else {"synced": False, "reason": "update_index_false"}
    )
    return {
        "target": {"path": str(video_path), "file_id": target["file_id"], "name": video_path.name},
        "probe": probe,
        "created_segment_ids": ids,
        "segments": stored_segments,
        "face_scan": face_scan,
        "object_scan": object_scan,
        "auto_tags": auto_tags,
        "scan_summary": scan_summary(video_path, probe, stored_segments, preset=profile, subtitles=subtitles, contact_sheet=contact_sheet),
        "artifacts": video_artifacts(video_path),
        "sync": sync,
        "ffmpeg": ffmpeg_status(),
    }


def transcribe_video(path: str | None = None, file_id: int | None = None, *, update_index: bool = True, prefer_subtitles: bool = True) -> dict:
    target = resolve_video_target(path, file_id)
    video_path = target["path"]
    probe = probe_video(video_path)
    duration = float(probe.get("duration_seconds") or 0)
    subtitles = extract_subtitle_text(video_path, probe) if prefer_subtitles else {"available": False, "text": "", "streams": 0}
    if subtitles.get("text"):
        transcript = {
            "text": subtitles["text"],
            "segments": [{"start": 0, "end": duration or 0, "text": subtitles["text"][:MAX_TRANSCRIPT_INDEX_CHARS]}],
            "language": "embedded",
            "engine": "embedded_subtitles",
        }
    else:
        audio_path = _extract_audio_for_transcription(video_path)
        transcript = _run_asr(audio_path, video_path)
    text = (transcript.get("text") or "").strip()
    if not text:
        raise RuntimeError("No transcript text was produced.")
    transcript_segments = _chunk_transcript_segments(transcript, duration)
    artifacts = _write_transcript_artifacts(video_path, text[:MAX_TRANSCRIPT_INDEX_CHARS], transcript.get("segments") or [])
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM media_segments WHERE path = ? AND source = ?", (str(video_path), TRANSCRIPT_SOURCE))
    ids = [
        _insert_segment(cur, file_id=target["file_id"], path=video_path, segment=segment, source=TRANSCRIPT_SOURCE)
        for segment in transcript_segments
    ]
    conn.commit()
    conn.close()
    stored_segments = list_video_segments(path=video_path, file_id=target["file_id"])
    sync = (
        refresh_video_file_context(target["file_id"], video_path, probe, extra_text=text[:MAX_TRANSCRIPT_INDEX_CHARS])
        if update_index
        else {"synced": False, "reason": "update_index_false"}
    )
    return {
        "target": {"path": str(video_path), "file_id": target["file_id"], "name": video_path.name},
        "engine": transcript.get("engine"),
        "language": transcript.get("language"),
        "text_path": artifacts["text_path"],
        "segments_path": artifacts["segments_path"],
        "created_segment_ids": ids,
        "transcript_chars": len(text),
        "segments": stored_segments,
        "scan_summary": scan_summary(video_path, probe, stored_segments),
        "artifacts": video_artifacts(video_path),
        "sync": sync,
        "status": transcription_status(),
    }


def video_context(path: str | None = None, file_id: int | None = None) -> dict:
    target = resolve_video_target(path, file_id)
    video_path = target["path"]
    probe = None
    try:
        probe = probe_video(video_path)
    except Exception as error:
        probe = {"summary": f"Probe unavailable: {error}", "duration_seconds": 0}
    segments = list_video_segments(path=video_path, file_id=target["file_id"])
    return {
        "target": {"path": str(video_path), "file_id": target["file_id"], "name": video_path.name},
        "probe": probe,
        "segments": segments,
        "scan_summary": scan_summary(video_path, probe, segments),
        "artifacts": video_artifacts(video_path),
        "ffmpeg": ffmpeg_status(),
    }


def add_video_segment(req) -> dict:
    target = resolve_video_target(req.path, req.file_id)
    segment = {
        "start_seconds": req.start_seconds,
        "end_seconds": req.end_seconds,
        "title": req.title,
        "summary": req.summary,
        "timeline": req.timeline,
        "tags": req.tags or [],
        "associations": req.associations or [],
        "thumb_path": req.thumb_path,
        "source": "manual",
    }
    conn = get_conn()
    cur = conn.cursor()
    segment_id = _insert_segment(cur, file_id=target["file_id"], path=target["path"], segment=segment, source="manual")
    conn.commit()
    conn.close()
    sync = refresh_video_file_context(target["file_id"], target["path"])
    return {"segment_id": segment_id, "segments": list_video_segments(path=target["path"], file_id=target["file_id"]), "sync": sync}


def search_video_context(query: str, limit: int = 40) -> dict:
    q = f"%{(query or '').strip()}%"
    limit = max(1, min(int(limit or 40), 120))
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM media_segments
        WHERE path LIKE ? OR title LIKE ? OR summary LIKE ? OR timeline LIKE ?
           OR tags_json LIKE ? OR associations_json LIKE ?
        ORDER BY updated_ts DESC, start_seconds ASC
        LIMIT ?
        """,
        (q, q, q, q, q, q, limit),
    )
    segments = [_segment_from_row(row) for row in cur.fetchall()]
    cur.execute(
        """
        SELECT id, path, name, summary, extracted_text, preview_path, thumb_path
        FROM files
        WHERE category = 'video'
          AND (name LIKE ? OR path LIKE ? OR summary LIKE ? OR extracted_text LIKE ?)
        ORDER BY indexed_ts DESC, id DESC
        LIMIT ?
        """,
        (q, q, q, q, limit),
    )
    files = [dict(row) for row in cur.fetchall()]
    conn.close()
    return {"query": query, "segments": segments, "files": files, "limit": limit}
