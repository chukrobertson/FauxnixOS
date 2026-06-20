from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageOps

from app.config import DATA_DIR
from app.db import get_conn
from app.utils import ensure_parent


FACE_CROP_DIR = DATA_DIR / "media" / "faces"
FACE_VIDEO_FRAME_DIR = DATA_DIR / "media" / "face_video_frames"

AUTO_FACE_IMAGE_SOURCE = "auto_image"
AUTO_FACE_VIDEO_SOURCE = "auto_video_ingest"
STORYBOARD_FACE_SOURCE = "ffmpeg_storyboard_face"
GENERATED_FACE_SOURCES = {AUTO_FACE_IMAGE_SOURCE, AUTO_FACE_VIDEO_SOURCE, STORYBOARD_FACE_SOURCE}

LOCAL_FFMPEG_BIN = DATA_DIR / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
LOCAL_FFPROBE_BIN = DATA_DIR / "tools" / "ffmpeg" / "bin" / "ffprobe.exe"
FFMPEG_BIN = os.getenv("FFMPEG_BIN", str(LOCAL_FFMPEG_BIN) if LOCAL_FFMPEG_BIN.exists() else "ffmpeg")
FFPROBE_BIN = os.getenv("FFPROBE_BIN", str(LOCAL_FFPROBE_BIN) if LOCAL_FFPROBE_BIN.exists() else "ffprobe")
MAX_DETECTION_DIM = int(os.getenv("AUTO_FACE_MAX_DETECTION_DIM", "1600") or "1600")
AUTO_FACE_VIDEO_MAX_FRAMES = max(1, min(int(os.getenv("AUTO_FACE_VIDEO_MAX_FRAMES", "3") or "3"), 12))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


AUTO_FACE_SCAN_IMAGES = _env_bool("AUTO_FACE_SCAN_IMAGES", True)
AUTO_FACE_SCAN_VIDEOS = _env_bool("AUTO_FACE_SCAN_VIDEOS", True)


def _which(binary: str) -> str | None:
    try:
        if Path(binary).exists():
            return str(Path(binary))
    except OSError:
        pass
    return shutil.which(binary)


def _run(args: list[str], timeout: int = 60) -> dict:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout or "",
            "stderr": result.stderr or "",
            "returncode": result.returncode,
            "command": " ".join(args),
        }
    except (OSError, subprocess.SubprocessError) as error:
        return {"ok": False, "stdout": "", "stderr": str(error), "returncode": None, "command": " ".join(args)}


def opencv_status() -> dict:
    if not importlib.util.find_spec("cv2"):
        return {
            "available": False,
            "detector": "opencv_haar",
            "error": "OpenCV is not installed. Install opencv-python-headless to enable local face detection.",
        }
    try:
        import cv2

        cascade = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        return {
            "available": cascade.exists(),
            "detector": "opencv_haar",
            "cascade": str(cascade),
            "error": None if cascade.exists() else "OpenCV Haar cascade file was not found.",
        }
    except Exception as error:
        return {"available": False, "detector": "opencv_haar", "error": str(error)}


def ffmpeg_face_status() -> dict:
    ffmpeg = _which(FFMPEG_BIN)
    ffprobe = _which(FFPROBE_BIN)
    return {
        "ffmpeg": {"available": bool(ffmpeg), "path": ffmpeg or FFMPEG_BIN},
        "ffprobe": {"available": bool(ffprobe), "path": ffprobe or FFPROBE_BIN},
        "ready": bool(ffmpeg and ffprobe),
    }


def face_engine_status() -> dict:
    return {
        "opencv": opencv_status(),
        "ffmpeg": ffmpeg_face_status(),
        "settings": {
            "auto_scan_images": AUTO_FACE_SCAN_IMAGES,
            "auto_scan_videos": AUTO_FACE_SCAN_VIDEOS,
            "video_max_frames": AUTO_FACE_VIDEO_MAX_FRAMES,
            "max_detection_dim": MAX_DETECTION_DIM,
        },
        "sources": sorted(GENERATED_FACE_SOURCES),
    }


def _media_key(path: Path) -> str:
    try:
        stat = path.stat()
        seed = f"{path}|{stat.st_mtime_ns}|{stat.st_size}"
    except OSError:
        seed = str(path)
    return hashlib.sha1(seed.encode("utf-8", errors="ignore")).hexdigest()[:18]


def _load_detector():
    status = opencv_status()
    if not status.get("available"):
        raise RuntimeError(status.get("error") or "OpenCV face detector unavailable")
    import cv2

    return cv2, cv2.CascadeClassifier(status["cascade"])


def _prepare_image(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return ImageOps.exif_transpose(image).convert("RGB")


def _scaled_for_detection(image: Image.Image) -> tuple[Image.Image, float]:
    width, height = image.size
    largest = max(width, height)
    if largest <= MAX_DETECTION_DIM:
        return image, 1.0
    scale = MAX_DETECTION_DIM / float(largest)
    resized = image.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.Resampling.LANCZOS)
    return resized, scale


def _detect_boxes(image: Image.Image) -> list[dict]:
    cv2, detector = _load_detector()
    import numpy as np

    work_image, scale = _scaled_for_detection(image)
    gray = cv2.cvtColor(np.array(work_image), cv2.COLOR_RGB2GRAY)
    detections = detector.detectMultiScale(
        gray,
        scaleFactor=1.08,
        minNeighbors=5,
        minSize=(32, 32),
        flags=cv2.CASCADE_SCALE_IMAGE,
    )
    boxes = []
    for x, y, width, height in detections:
        boxes.append(
            {
                "x": int(round(float(x) / scale)),
                "y": int(round(float(y) / scale)),
                "width": int(round(float(width) / scale)),
                "height": int(round(float(height) / scale)),
            }
        )
    boxes.sort(key=lambda box: (box["y"], box["x"], box["width"] * box["height"]))
    return boxes


def _padded_box(box: dict, image_size: tuple[int, int], pad_ratio: float = 0.22) -> tuple[int, int, int, int]:
    width, height = image_size
    pad_x = int(box["width"] * pad_ratio)
    pad_y = int(box["height"] * pad_ratio)
    left = max(0, int(box["x"]) - pad_x)
    top = max(0, int(box["y"]) - pad_y)
    right = min(width, int(box["x"]) + int(box["width"]) + pad_x)
    bottom = min(height, int(box["y"]) + int(box["height"]) + pad_y)
    return left, top, right, bottom


def _average_hash(image: Image.Image, size: int = 8) -> str:
    small = ImageOps.grayscale(image.resize((size, size), Image.Resampling.LANCZOS))
    pixels = list(small.getdata())
    avg = sum(pixels) / max(1, len(pixels))
    value = 0
    for pixel in pixels:
        value = (value << 1) | int(pixel >= avg)
    return f"{value:0{size * size // 4}x}"


def _save_crop(image: Image.Image, media_path: Path, box: dict, index: int, source: str, frame_seconds: float | None) -> tuple[str, str]:
    crop = image.crop(_padded_box(box, image.size))
    signature = _average_hash(crop)
    key = _media_key(media_path)
    frame_part = "still" if frame_seconds is None else f"{int(round(frame_seconds * 1000)):010d}"
    crop_path = FACE_CROP_DIR / key / f"{source}_{frame_part}_{index:02d}_{signature[:12]}.jpg"
    ensure_parent(crop_path)
    crop.thumbnail((360, 360))
    crop.convert("RGB").save(crop_path, format="JPEG", quality=90)
    return str(crop_path), signature


def _insert_face_observation(
    *,
    file_id: int | None,
    media_path: Path,
    media_type: str,
    frame_seconds: float | None,
    bbox: dict,
    crop_path: str,
    signature: str,
    source: str,
) -> dict:
    now = time.time()
    cluster_id = f"face:{signature[:16]}"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO face_observations (
            file_id, path, media_type, frame_seconds, bbox_json, crop_path,
            embedding_ref, detection_confidence, cluster_id, source, created_ts, updated_ts
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_id,
            str(media_path),
            media_type,
            frame_seconds,
            json.dumps(bbox),
            crop_path,
            f"ahash:{signature}",
            0.72,
            cluster_id,
            source,
            now,
            now,
        ),
    )
    observation_id = int(cur.lastrowid)
    conn.commit()
    cur.execute("SELECT * FROM face_observations WHERE id = ?", (observation_id,))
    row = dict(cur.fetchone())
    conn.close()
    row["bbox"] = json.loads(row.pop("bbox_json") or "{}")
    return row


def clear_generated_face_observations(
    *,
    file_id: int | None = None,
    path: str | Path | None = None,
    media_type: str | None = None,
    source: str | None = None,
    frame_seconds: float | None = None,
) -> int:
    sources = [source] if source else sorted(GENERATED_FACE_SOURCES)
    clauses = [f"source IN ({','.join('?' for _ in sources)})"]
    params: list = list(sources)
    if file_id:
        clauses.append("file_id = ?")
        params.append(int(file_id))
    elif path:
        clauses.append("path = ?")
        params.append(str(path))
    if media_type:
        clauses.append("media_type = ?")
        params.append(media_type)
    if frame_seconds is not None:
        clauses.append("ABS(COALESCE(frame_seconds, -999999) - ?) < 0.05")
        params.append(float(frame_seconds))
    sql = f"DELETE FROM face_observations WHERE {' AND '.join(clauses)}"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql, params)
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return int(deleted)


def detect_faces_in_image(
    source_image_path: str | Path,
    *,
    file_id: int | None = None,
    media_path: str | Path | None = None,
    media_type: str = "image",
    frame_seconds: float | None = None,
    source: str = AUTO_FACE_IMAGE_SOURCE,
    replace: bool = True,
) -> dict:
    source_path = Path(source_image_path)
    media = Path(media_path) if media_path else source_path
    detector_status = opencv_status()
    if not detector_status.get("available"):
        return {"ok": False, "source": source, "face_count": 0, "error": detector_status.get("error"), "status": face_engine_status()}
    if replace:
        clear_generated_face_observations(
            file_id=file_id,
            path=media,
            media_type=media_type,
            source=source,
            frame_seconds=frame_seconds,
        )
    if not source_path.exists() or not source_path.is_file():
        return {"ok": False, "source": source, "face_count": 0, "error": f"Image not found: {source_path}"}
    try:
        image = _prepare_image(source_path)
        boxes = _detect_boxes(image)
        observations = []
        for index, box in enumerate(boxes, start=1):
            crop_path, signature = _save_crop(image, media, box, index, source, frame_seconds)
            observations.append(
                _insert_face_observation(
                    file_id=file_id,
                    media_path=media,
                    media_type=media_type,
                    frame_seconds=frame_seconds,
                    bbox={**box, "source_image": str(source_path)},
                    crop_path=crop_path,
                    signature=signature,
                    source=source,
                )
            )
        return {"ok": True, "source": source, "face_count": len(observations), "observations": observations}
    except Exception as error:
        return {"ok": False, "source": source, "face_count": 0, "error": str(error), "status": face_engine_status()}


def _file_record(file_id: int | None = None, path: str | Path | None = None) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    if file_id:
        cur.execute("SELECT * FROM files WHERE id = ?", (int(file_id),))
    elif path:
        cur.execute("SELECT * FROM files WHERE path = ?", (str(path),))
    else:
        conn.close()
        return None
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def _probe_duration(path: Path) -> float:
    status = ffmpeg_face_status()
    if not status["ffprobe"]["available"]:
        raise RuntimeError("ffprobe is unavailable")
    result = _run(
        [
            status["ffprobe"]["path"],
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        timeout=30,
    )
    if not result["ok"]:
        raise RuntimeError(result["stderr"] or "ffprobe failed")
    try:
        return max(0.0, float((result["stdout"] or "0").strip() or 0))
    except ValueError:
        return 0.0


def _video_timestamps(duration: float, max_frames: int) -> list[float]:
    if duration <= 0:
        return [1.0]
    if max_frames <= 1:
        return [min(1.0, max(0.0, duration - 0.5))]
    if max_frames == 2:
        values = [0.0, max(0.0, duration - 1.0)]
    else:
        values = [0.0, duration / 2.0, max(0.0, duration - 1.0)]
        if max_frames > 3:
            step = duration / float(max_frames - 1)
            values = [min(duration - 0.5, step * index) for index in range(max_frames)]
    deduped: list[float] = []
    for value in values:
        clipped = max(0.0, min(float(value), max(0.0, duration - 0.25)))
        if not any(abs(clipped - existing) < 0.5 for existing in deduped):
            deduped.append(clipped)
    return deduped[:max_frames] or [0.0]


def _extract_video_frame(path: Path, timestamp: float, out_dir: Path) -> Path | None:
    status = ffmpeg_face_status()
    if not status["ffmpeg"]["available"]:
        raise RuntimeError("ffmpeg is unavailable")
    frame_path = out_dir / f"face_frame_{int(round(timestamp * 1000)):010d}.jpg"
    result = _run(
        [
            status["ffmpeg"]["path"],
            "-y",
            "-loglevel",
            "error",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            "scale=960:-1",
            "-q:v",
            "4",
            str(frame_path),
        ],
        timeout=45,
    )
    return frame_path if result["ok"] and frame_path.exists() else None


def detect_faces_in_video(
    path: str | Path,
    *,
    file_id: int | None = None,
    max_frames: int = AUTO_FACE_VIDEO_MAX_FRAMES,
    source: str = AUTO_FACE_VIDEO_SOURCE,
    replace: bool = True,
) -> dict:
    video_path = Path(path)
    detector_status = opencv_status()
    ffmpeg_status = ffmpeg_face_status()
    if not detector_status.get("available"):
        return {"ok": False, "source": source, "face_count": 0, "error": detector_status.get("error"), "status": face_engine_status()}
    if not ffmpeg_status.get("ready"):
        return {"ok": False, "source": source, "face_count": 0, "error": "ffmpeg and ffprobe are required for video face sampling", "status": face_engine_status()}
    if replace:
        clear_generated_face_observations(file_id=file_id, path=video_path, media_type="video", source=source)
    if not video_path.exists() or not video_path.is_file():
        return {"ok": False, "source": source, "face_count": 0, "error": f"Video not found: {video_path}"}
    try:
        duration = _probe_duration(video_path)
        out_dir = FACE_VIDEO_FRAME_DIR / _media_key(video_path)
        out_dir.mkdir(parents=True, exist_ok=True)
        frame_results = []
        observations = []
        for timestamp in _video_timestamps(duration, max_frames):
            frame = _extract_video_frame(video_path, timestamp, out_dir)
            if not frame:
                frame_results.append({"timestamp": timestamp, "ok": False, "face_count": 0})
                continue
            result = detect_faces_in_image(
                frame,
                file_id=file_id,
                media_path=video_path,
                media_type="video",
                frame_seconds=timestamp,
                source=source,
                replace=False,
            )
            frame_results.append({"timestamp": timestamp, **{key: result.get(key) for key in ["ok", "face_count", "error"] if key in result}})
            observations.extend(result.get("observations") or [])
        return {
            "ok": True,
            "source": source,
            "duration_seconds": duration,
            "frames_sampled": len(frame_results),
            "face_count": len(observations),
            "frame_results": frame_results,
            "observations": observations,
        }
    except Exception as error:
        return {"ok": False, "source": source, "face_count": 0, "error": str(error), "status": face_engine_status()}


def detect_faces_in_storyboard(video_path: str | Path, *, file_id: int | None, segments: list[dict]) -> dict:
    path = Path(video_path)
    detector_status = opencv_status()
    if not detector_status.get("available"):
        return {"ok": False, "source": STORYBOARD_FACE_SOURCE, "frames_sampled": 0, "face_count": 0, "error": detector_status.get("error"), "status": face_engine_status()}
    clear_generated_face_observations(file_id=file_id, path=path, media_type="video", source=STORYBOARD_FACE_SOURCE)
    observations = []
    frames = 0
    errors = []
    for segment in segments:
        if segment.get("source") != "ffmpeg_storyboard" or not segment.get("thumb_path"):
            continue
        thumb = Path(segment["thumb_path"])
        if not thumb.exists():
            continue
        frames += 1
        result = detect_faces_in_image(
            thumb,
            file_id=file_id,
            media_path=path,
            media_type="video",
            frame_seconds=float(segment.get("start_seconds") or 0),
            source=STORYBOARD_FACE_SOURCE,
            replace=False,
        )
        observations.extend(result.get("observations") or [])
        if not result.get("ok"):
            errors.append({"thumb_path": str(thumb), "error": result.get("error")})
    return {
        "ok": not errors,
        "source": STORYBOARD_FACE_SOURCE,
        "frames_sampled": frames,
        "face_count": len(observations),
        "observations": observations,
        "errors": errors[:10],
    }


def scan_file_faces(record: dict, *, force_video: bool | None = None) -> dict:
    if not record:
        return {"ok": False, "face_count": 0, "error": "missing record"}
    path = Path(record.get("path") or "")
    file_id = int(record["id"]) if record.get("id") else None
    category = (record.get("category") or "").lower()
    if category == "image":
        if not AUTO_FACE_SCAN_IMAGES:
            return {"ok": False, "face_count": 0, "skipped": True, "reason": "AUTO_FACE_SCAN_IMAGES disabled"}
        return detect_faces_in_image(path, file_id=file_id, media_path=path, media_type="image", source=AUTO_FACE_IMAGE_SOURCE)
    if category == "video":
        should_scan = AUTO_FACE_SCAN_VIDEOS if force_video is None else bool(force_video)
        if not should_scan:
            return {"ok": False, "face_count": 0, "skipped": True, "reason": "AUTO_FACE_SCAN_VIDEOS disabled"}
        return detect_faces_in_video(path, file_id=file_id, source=AUTO_FACE_VIDEO_SOURCE)
    return {"ok": True, "face_count": 0, "skipped": True, "reason": f"category {category or 'unknown'} is not visual media"}


def scan_indexed_media_faces(*, limit: int = 40, include_video: bool = True, force: bool = False) -> dict:
    limit = max(1, min(int(limit or 40), 500))
    categories = ["image", "video"] if include_video else ["image"]
    placeholders = ",".join("?" for _ in categories)
    exists_clause = "" if force else """
        AND NOT EXISTS (
            SELECT 1 FROM face_observations fo
            WHERE fo.file_id = files.id
              AND fo.source IN ('auto_image', 'auto_video_ingest', 'ffmpeg_storyboard_face')
        )
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT *
        FROM files
        WHERE category IN ({placeholders})
          AND COALESCE(deleted_candidate, 0) = 0
          AND (duplicate_of IS NULL OR duplicate_of = '')
          {exists_clause}
        ORDER BY indexed_ts DESC, id DESC
        LIMIT ?
        """,
        [*categories, limit],
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()

    results = []
    total_faces = 0
    for row in rows:
        result = scan_file_faces(row)
        total_faces += int(result.get("face_count") or 0)
        try:
            from app.autotagging import apply_auto_tags

            tag_result = apply_auto_tags(row, face_count=int(result.get("face_count") or 0))
        except Exception as error:
            tag_result = {"applied": 0, "error": str(error)}
        results.append({"file_id": row.get("id"), "path": row.get("path"), "category": row.get("category"), "face_scan": result, "auto_tags": tag_result})
    return {"scanned": len(results), "face_count": total_faces, "results": results, "detector": face_engine_status()}
