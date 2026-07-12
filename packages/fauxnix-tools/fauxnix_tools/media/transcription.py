from __future__ import annotations

import importlib.util
import json
import os
import time
from pathlib import Path

from fauxnix_tools.config import config
from fauxnix_tools.db import get_conn
from fauxnix_tools.media.probing import (
    probe_video, extract_storyboard_frames, extract_subtitle_text,
    _context_dir, _run, ffmpeg_status, TRANSCRIPT_SOURCE,
    MAX_SUBTITLE_SEGMENT_CHARS, MAX_SUBTITLE_INDEX_CHARS,
)
from fauxnix_tools.vision.faces import detect_faces_in_storyboard
from fauxnix_tools.vision.analysis import analyze_image_path, apply_vision_tags_to_file, vision_tag_names, vision_status
from fauxnix_tools.utils import now_ts


MAX_TRANSCRIPT_INDEX_CHARS = 48000
MAX_TRANSCRIPT_SEGMENT_CHARS = 3500


def transcription_status() -> dict:
    faster = bool(importlib.util.find_spec("faster_whisper"))
    whisper = bool(importlib.util.find_spec("whisper"))
    return {
        "ready": faster or whisper,
        "engine": "faster_whisper" if faster else ("openai_whisper" if whisper else None),
        "model": config.whisper_model,
    }


def transcribe_video(path: str, file_id: int | None = None, *, prefer_subtitles: bool = True) -> dict:
    video_path = Path(path)
    probe = probe_video(video_path)
    duration = float(probe.get("duration_seconds") or 0)
    subtitles = extract_subtitle_text(video_path, probe) if prefer_subtitles else {"available": False, "text": ""}

    if subtitles.get("text"):
        transcript_text = subtitles["text"]
        engine = "embedded_subtitles"
    else:
        status = ffmpeg_status()
        if not status["ffmpeg"]["available"]:
            raise RuntimeError("ffmpeg required for audio extraction")
        audio_path = _context_dir(video_path) / "transcription_audio.wav"
        _run([status["ffmpeg"]["path"], "-y", "-loglevel", "error", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000", str(audio_path)], timeout=600)
        if not audio_path.exists():
            raise RuntimeError("Audio extraction failed")
        import faster_whisper
        model = faster_whisper.WhisperModel(config.whisper_model, device=config.whisper_device, compute_type=config.whisper_compute_type)
        kwargs = {"vad_filter": True}
        if config.whisper_language:
            kwargs["language"] = config.whisper_language
        segs, info = model.transcribe(str(audio_path), **kwargs)
        texts = []
        for seg in segs:
            if (seg.text or "").strip():
                texts.append(seg.text.strip())
        transcript_text = "\n".join(texts)
        engine = "faster_whisper"

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM media_segments WHERE path = ? AND source = ?", (str(video_path), TRANSCRIPT_SOURCE))
    ts = now_ts()
    cur.execute(
        """INSERT INTO media_segments (file_id, path, media_type, start_seconds, end_seconds, title, summary, timeline, tags_json, associations_json, thumb_path, source, created_ts, updated_ts)
           VALUES (?, ?, 'video', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (file_id, str(video_path), 0, duration or None, "Speech transcript", transcript_text[:MAX_TRANSCRIPT_SEGMENT_CHARS], "transcript", json.dumps(["transcript"]), json.dumps([]), None, TRANSCRIPT_SOURCE, ts, ts),
    )
    conn.commit()
    conn.close()

    return {"target": {"path": str(video_path), "file_id": file_id}, "engine": engine, "transcript_chars": len(transcript_text), "status": transcription_status()}


def analyze_video(path: str, file_id: int | None = None, interval_seconds: int = 60, max_frames: int = 24, detect_faces: bool = True, detect_objects: bool = False) -> dict:
    video_path = Path(path)
    probe = probe_video(video_path)
    segments = extract_storyboard_frames(video_path, probe, interval_seconds, max_frames)
    subtitles = extract_subtitle_text(video_path, probe)
    if subtitles.get("available"):
        segments.append({"start_seconds": 0, "end_seconds": probe.get("duration_seconds"), "title": "Embedded subtitles", "summary": subtitles["text"][:MAX_SUBTITLE_SEGMENT_CHARS], "timeline": "subtitles", "tags": ["subtitle"], "associations": [], "thumb_path": None, "source": "ffmpeg_subtitle"})

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM media_segments WHERE path = ? AND source IN ('ffmpeg_storyboard', 'ffmpeg_subtitle')", (str(video_path),))
    ts = now_ts()
    ids = []
    for s in segments:
        cur.execute(
            """INSERT INTO media_segments (file_id, path, media_type, start_seconds, end_seconds, title, summary, timeline, tags_json, associations_json, thumb_path, source, created_ts, updated_ts)
               VALUES (?, ?, 'video', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (file_id, str(video_path), float(s.get("start_seconds") or 0), s.get("end_seconds"),
             (s.get("title") or "").strip() or None, (s.get("summary") or "").strip() or None,
             (s.get("timeline") or "").strip() or None, json.dumps(s.get("tags") or []),
             json.dumps(s.get("associations") or []), s.get("thumb_path") or None,
             s.get("source") or "manual", ts, ts),
        )
        ids.append(int(cur.lastrowid))
    conn.commit()
    conn.close()

    face_scan = detect_faces_in_storyboard(video_path, file_id=file_id, segments=segments) if detect_faces else {"ok": False, "skipped": True, "face_count": 0}
    object_scan = {}
    if detect_objects:
        v_status = vision_status()
        if v_status.get("ready"):
            object_scan = {"frames_analyzed": 0, "objects": []}
            tags_all = []
            for s in segments[:12]:
                if s.get("source") == "ffmpeg_storyboard" and s.get("thumb_path") and Path(s["thumb_path"]).exists():
                    try:
                        r = analyze_image_path(s["thumb_path"])
                        a = r.get("analysis") or {}
                        object_scan["frames_analyzed"] = object_scan.get("frames_analyzed", 0) + 1
                        for o in a.get("objects") or []:
                            if o not in object_scan.get("objects", []):
                                object_scan.setdefault("objects", []).append(o)
                        tags_all.extend(vision_tag_names(a))
                    except Exception:
                        pass
            if tags_all and file_id:
                apply_vision_tags_to_file(file_id, tags_all)

    return {"target": {"path": str(video_path), "file_id": file_id}, "probe": probe, "segment_count": len(segments), "face_scan": face_scan, "object_scan": object_scan, "ffmpeg": ffmpeg_status()}
