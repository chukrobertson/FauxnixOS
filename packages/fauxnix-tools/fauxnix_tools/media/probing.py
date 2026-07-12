from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from fauxnix_tools.config import config


MAX_STORYBOARD_FRAMES = 120
MAX_SUBTITLE_INDEX_CHARS = 24000
MAX_SUBTITLE_SEGMENT_CHARS = 6000
TRANSCRIPT_SOURCE = "video_transcript"


def _which(binary: str) -> str | None:
    try:
        if Path(binary).exists():
            return str(Path(binary))
    except OSError:
        pass
    return shutil.which(binary)


def ffmpeg_status() -> dict:
    ffmpeg = _which(config.ffmpeg_bin)
    ffprobe = _which(config.ffprobe_bin)
    return {
        "ffmpeg": {"available": bool(ffmpeg), "path": ffmpeg or config.ffmpeg_bin},
        "ffprobe": {"available": bool(ffprobe), "path": ffprobe or config.ffprobe_bin},
        "ready": bool(ffmpeg and ffprobe),
    }


def _run(args: list[str], timeout: int = 60) -> dict:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return {"ok": result.returncode == 0, "stdout": result.stdout or "", "stderr": result.stderr or "", "command": " ".join(args)}
    except (OSError, subprocess.SubprocessError) as error:
        return {"ok": False, "stdout": "", "stderr": str(error), "command": " ".join(args)}


def _context_dir(path: Path) -> Path:
    stat = path.stat()
    key = hashlib.sha1(f"{path}|{stat.st_mtime_ns}|{stat.st_size}".encode()).hexdigest()[:18]
    d = config.media_context_dir / key
    d.mkdir(parents=True, exist_ok=True)
    return d


def format_seconds(seconds: float | int | None) -> str:
    total = int(round(float(seconds or 0)))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def probe_video(path: Path) -> dict:
    status = ffmpeg_status()
    if not status["ffprobe"]["available"]:
        raise RuntimeError("ffprobe unavailable")
    result = _run([status["ffprobe"]["path"], "-v", "error", "-print_format", "json", "-show_format", "-show_streams", "-show_chapters", str(path)], timeout=45)
    if not result["ok"]:
        raise RuntimeError(result["stderr"] or "ffprobe failed")
    data = json.loads(result["stdout"] or "{}")
    for value in [(data.get("format") or {}).get("duration"), *[(s or {}).get("duration") for s in data.get("streams") or []]]:
        try:
            if value is not None:
                data["duration_seconds"] = max(0.0, float(value))
                break
        except (TypeError, ValueError):
            pass
    if "duration_seconds" not in data:
        data["duration_seconds"] = 0.0
    data["summary"] = f"Video: {path.stem}. Duration: {format_seconds(data['duration_seconds'])}."
    return data


def extract_storyboard_frames(path: Path, probe: dict, interval_seconds: int = 60, max_frames: int = 24) -> list[dict]:
    status = ffmpeg_status()
    if not status["ffmpeg"]["available"]:
        raise RuntimeError("ffmpeg unavailable")
    out_dir = _context_dir(path)
    duration = float(probe.get("duration_seconds") or 0)
    max_frames = max(1, min(max_frames, MAX_STORYBOARD_FRAMES))
    interval = max(5, min(int(interval_seconds or 60), 3600))
    segments = []
    if duration <= 0:
        timestamps = [1.0]
    else:
        timestamps = []
        current = 0.0
        while current < duration and len(timestamps) < max_frames:
            timestamps.append(current)
            current += interval
        if timestamps and duration - timestamps[-1] > interval / 2 and len(timestamps) < max_frames:
            timestamps.append(max(0.0, duration - 1.0))
    for idx, start in enumerate(timestamps, start=1):
        thumb_path = out_dir / f"frame_{idx:03d}_{int(start):06d}.jpg"
        result = _run([status["ffmpeg"]["path"], "-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-i", str(path), "-frames:v", "1", "-vf", "scale=420:-1", "-q:v", "4", str(thumb_path)], timeout=45)
        if result["ok"] and thumb_path.exists():
            end = min(duration, start + max(5, interval)) if duration else None
            segments.append({"start_seconds": start, "end_seconds": end, "title": f"Storyboard frame {idx}", "summary": f"Frame at {format_seconds(start)}.", "timeline": "storyboard", "tags": ["storyboard"], "associations": [], "thumb_path": str(thumb_path), "source": "ffmpeg_storyboard"})
    return segments


def extract_subtitle_text(path: Path, probe: dict) -> dict:
    streams = [s for s in probe.get("streams") or [] if s.get("codec_type") == "subtitle"]
    if not streams:
        return {"available": False, "streams": 0, "text": "", "error": "no subtitle streams"}
    status = ffmpeg_status()
    if not status["ffmpeg"]["available"]:
        return {"available": False, "streams": len(streams), "text": "", "error": "ffmpeg unavailable"}
    out_dir = _context_dir(path)
    sub_path = out_dir / "subtitles.srt"
    result = _run([status["ffmpeg"]["path"], "-y", "-loglevel", "error", "-i", str(path), "-map", f"0:{streams[0]['index']}", "-c:s", "srt", str(sub_path)], timeout=120)
    if not result["ok"] or not sub_path.exists():
        return {"available": False, "streams": len(streams), "text": "", "error": result["stderr"] or "subtitle extraction failed"}
    lines = []
    for line in sub_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        item = line.strip()
        if not item or item.isdigit() or "-->" in item or item.startswith("{\\") or item.startswith("WEBVTT"):
            continue
        lines.append(item)
    text = "\n".join(lines)[:MAX_SUBTITLE_INDEX_CHARS]
    return {"available": bool(text), "streams": len(streams), "text": text, "error": None}
