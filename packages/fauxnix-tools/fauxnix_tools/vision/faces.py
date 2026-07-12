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

from fauxnix_tools.config import config
from fauxnix_tools.db import get_conn
from fauxnix_tools.utils import ensure_parent
from fauxnix_tools.utils.categories import IMAGE_EXTS, VIDEO_EXTS


AUTO_FACE_IMAGE_SOURCE = "auto_image"
AUTO_FACE_VIDEO_SOURCE = "auto_video_ingest"
STORYBOARD_FACE_SOURCE = "ffmpeg_storyboard_face"
GENERATED_FACE_SOURCES = {AUTO_FACE_IMAGE_SOURCE, AUTO_FACE_VIDEO_SOURCE, STORYBOARD_FACE_SOURCE}


def _which(binary: str) -> str | None:
    try:
        if Path(binary).exists():
            return str(Path(binary))
    except OSError:
        pass
    return shutil.which(binary)


def opencv_status() -> dict:
    if not importlib.util.find_spec("cv2"):
        return {"available": False, "detector": "opencv_haar", "error": "OpenCV not installed."}
    try:
        import cv2
        cascade = None

        candidates = []
        if hasattr(cv2, "data") and hasattr(cv2.data, "haarcascades"):
            candidates.append(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")
        candidates.append(Path(cv2.__file__).parent / "data" / "haarcascade_frontalface_default.xml")

        try:
            import glob as _glob
            nix_paths = _glob.glob(
                "/nix/store/*opencv*/share/opencv4/haarcascades/haarcascade_frontalface_default.xml"
            )
            if nix_paths:
                candidates.insert(0, Path(nix_paths[0]))
        except Exception:
            pass

        for candidate in candidates:
            if candidate.exists():
                cascade = candidate
                break

        if cascade is None:
            return {"available": False, "detector": "opencv_haar", "error": "Haar cascade file not found."}
        return {"available": True, "detector": "opencv_haar", "cascade": str(cascade), "error": None}
    except Exception as error:
        return {"available": False, "detector": "opencv_haar", "error": str(error)}


def face_engine_status() -> dict:
    return {
        "opencv": opencv_status(),
        "ffmpeg": {"available": bool(_which(config.ffmpeg_bin) and _which(config.ffprobe_bin))},
        "settings": {
            "auto_scan_images": config.face_scan_images,
            "auto_scan_videos": config.face_scan_videos,
            "video_max_frames": config.face_video_max_frames,
            "max_detection_dim": config.face_max_dim,
        },
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


def _prepare_image(path: Path):
    from PIL import Image, ImageOps, Image as PILImage
    PILImage.MAX_IMAGE_PIXELS = None
    with Image.open(path) as image:
        return ImageOps.exif_transpose(image).convert("RGB")


def _scaled_for_detection(image, min_dim: int = 640, max_dim: int = 1920):
    from PIL import Image
    w, h = image.size
    largest = max(w, h)
    if largest <= config.face_max_dim:
        return image, 1.0
    scale = config.face_max_dim / float(largest)
    return image.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS), scale


def _detect_boxes(image) -> list[dict]:
    cv2, detector = _load_detector()
    import numpy as np
    work_image, scale = _scaled_for_detection(image)
    gray = cv2.cvtColor(np.array(work_image), cv2.COLOR_RGB2GRAY)
    detections = detector.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=5, minSize=(32, 32), flags=cv2.CASCADE_SCALE_IMAGE)
    boxes = []
    for x, y, width, height in detections:
        boxes.append({
            "x": int(round(float(x) / scale)),
            "y": int(round(float(y) / scale)),
            "width": int(round(float(width) / scale)),
            "height": int(round(float(height) / scale)),
        })
    boxes.sort(key=lambda box: (box["y"], box["x"], box["width"] * box["height"]))
    return boxes


def _padded_box(box: dict, image_size: tuple[int, int], pad_ratio: float = 0.22) -> tuple[int, int, int, int]:
    w, h = image_size
    pad_x = int(box["width"] * pad_ratio)
    pad_y = int(box["height"] * pad_ratio)
    left = max(0, int(box["x"]) - pad_x)
    top = max(0, int(box["y"]) - pad_y)
    right = min(w, int(box["x"]) + int(box["width"]) + pad_x)
    bottom = min(h, int(box["y"]) + int(box["height"]) + pad_y)
    return left, top, right, bottom


def _average_hash(image, size: int = 8) -> str:
    from PIL import ImageOps
    small = ImageOps.grayscale(image.resize((size, size), Image.Resampling.LANCZOS))
    pixels = list(small.getdata())
    avg = sum(pixels) / max(1, len(pixels))
    value = 0
    for pixel in pixels:
        value = (value << 1) | int(pixel >= avg)
    return f"{value:0{size * size // 4}x}"


def _save_crop(image, media_path: Path, box: dict, index: int, source: str, frame_seconds: float | None) -> tuple[str, str]:
    crop = image.crop(_padded_box(box, image.size))
    signature = _average_hash(crop)
    key = _media_key(media_path)
    frame_part = "still" if frame_seconds is None else f"{int(round(frame_seconds * 1000)):010d}"
    crop_path = config.face_crop_dir / key / f"{source}_{frame_part}_{index:02d}_{signature[:12]}.jpg"
    ensure_parent(crop_path)
    crop.thumbnail((360, 360))
    crop.convert("RGB").save(crop_path, format="JPEG", quality=90)
    return str(crop_path), signature


def _insert_face_observation(*, file_id: int | None, media_path: Path, media_type: str, frame_seconds: float | None, bbox: dict, crop_path: str, signature: str, source: str) -> dict:
    now = time.time()
    cluster_id = f"face:{signature[:16]}"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO face_observations (file_id, path, media_type, frame_seconds, bbox_json, crop_path, embedding_ref, detection_confidence, cluster_id, source, created_ts, updated_ts)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (file_id, str(media_path), media_type, frame_seconds, json.dumps(bbox), crop_path, f"ahash:{signature}", 0.72, cluster_id, source, now, now),
    )
    observation_id = int(cur.lastrowid)
    conn.commit()
    cur.execute("SELECT * FROM face_observations WHERE id = ?", (observation_id,))
    row = dict(cur.fetchone())
    conn.close()
    row["bbox"] = json.loads(row.pop("bbox_json") or "{}")
    return row


def clear_generated_face_observations(*, file_id: int | None = None, path: str | Path | None = None, media_type: str | None = None, source: str | None = None, frame_seconds: float | None = None) -> int:
    sources = [source] if source else sorted(GENERATED_FACE_SOURCES)
    clauses = [f"source IN ({','.join('?' for _ in sources)})"]
    params = list(sources)
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
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"DELETE FROM face_observations WHERE {' AND '.join(clauses)}", params)
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return int(deleted)


def detect_faces_in_image(source_image_path: str | Path, *, file_id: int | None = None, media_path: str | Path | None = None, media_type: str = "image", frame_seconds: float | None = None, source: str = AUTO_FACE_IMAGE_SOURCE, replace: bool = True) -> dict:
    source_path = Path(source_image_path)
    media = Path(media_path) if media_path else source_path
    detector_status = opencv_status()
    if not detector_status.get("available"):
        return {"ok": False, "source": source, "face_count": 0, "error": detector_status.get("error")}
    if replace:
        clear_generated_face_observations(file_id=file_id, path=media, media_type=media_type, source=source, frame_seconds=frame_seconds)
    if not source_path.exists() or not source_path.is_file():
        return {"ok": False, "source": source, "face_count": 0, "error": f"Image not found: {source_path}"}
    try:
        image = _prepare_image(source_path)
        boxes = _detect_boxes(image)
        observations = []
        for idx, box in enumerate(boxes, start=1):
            crop_path, signature = _save_crop(image, media, box, idx, source, frame_seconds)
            observations.append(_insert_face_observation(file_id=file_id, media_path=media, media_type=media_type, frame_seconds=frame_seconds, bbox={**box, "source_image": str(source_path)}, crop_path=crop_path, signature=signature, source=source))
        return {"ok": True, "source": source, "face_count": len(observations), "observations": observations}
    except Exception as e:
        return {"ok": False, "source": source, "face_count": 0, "error": str(e)}


def detect_faces_in_video(path: str | Path, *, file_id: int | None = None, max_frames: int | None = None, source: str = AUTO_FACE_VIDEO_SOURCE, replace: bool = True) -> dict:
    video_path = Path(path)
    max_frames = max_frames or config.face_video_max_frames
    detector_status = opencv_status()
    if not detector_status.get("available"):
        return {"ok": False, "source": source, "face_count": 0, "error": detector_status.get("error")}
    ffmpeg = _which(config.ffmpeg_bin)
    ffprobe = _which(config.ffprobe_bin)
    if not ffmpeg or not ffprobe:
        return {"ok": False, "source": source, "face_count": 0, "error": "ffmpeg/ffprobe required for video face detection"}
    if replace:
        clear_generated_face_observations(file_id=file_id, path=video_path, media_type="video", source=source)
    if not video_path.exists() or not video_path.is_file():
        return {"ok": False, "source": source, "face_count": 0, "error": f"Video not found: {video_path}"}
    try:
        result = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)], capture_output=True, text=True, timeout=30)
        duration = max(0.0, float((result.stdout or "0").strip() or 0)) if result.returncode == 0 else 0.0
        max_frames = max(1, min(max_frames, 12))
        if duration <= 0:
            timestamps = [1.0]
        elif max_frames <= 1:
            timestamps = [min(1.0, max(0.0, duration - 0.5))]
        else:
            step = duration / float(max_frames)
            timestamps = [min(duration - 0.5, step * i) for i in range(max_frames)]
        out_dir = config.face_video_frame_dir / _media_key(video_path)
        out_dir.mkdir(parents=True, exist_ok=True)
        observations = []
        for ts in timestamps:
            clip = max(0.0, min(float(ts), max(0.0, duration - 0.25)))
            frame_path = out_dir / f"face_frame_{int(round(clip * 1000)):010d}.jpg"
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", f"{clip:.3f}", "-i", str(video_path), "-frames:v", "1", "-vf", "scale=960:-1", "-q:v", "4", str(frame_path)], capture_output=True, timeout=45)
            if frame_path.exists():
                result = detect_faces_in_image(frame_path, file_id=file_id, media_path=video_path, media_type="video", frame_seconds=clip, source=source, replace=False)
                observations.extend(result.get("observations") or [])
        return {"ok": True, "source": source, "duration_seconds": duration, "frames_sampled": len(timestamps), "face_count": len(observations), "observations": observations}
    except Exception as e:
        return {"ok": False, "source": source, "face_count": 0, "error": str(e)}


def detect_faces_in_storyboard(video_path: str | Path, *, file_id: int | None = None, segments: list | None = None) -> dict:
    path = Path(video_path)
    detector_status = opencv_status()
    if not detector_status.get("available"):
        return {"ok": False, "source": "storyboard", "face_count": 0, "error": detector_status.get("error")}
    if not segments:
        segments = []
    observations = []
    for seg in segments:
        thumb = seg.get("thumb_path")
        if not thumb or not Path(thumb).exists():
            continue
        ts = seg.get("start_seconds") or seg.get("end_seconds") or None
        result = detect_faces_in_image(thumb, file_id=file_id, media_path=path, media_type="video", frame_seconds=ts, source="storyboard", replace=False)
        observations.extend(result.get("observations") or [])
    return {"ok": True, "source": "storyboard", "segments_checked": len(segments), "face_count": len(observations), "observations": observations}


def scan_file_faces(file_id: int, file_path: str, category: str) -> dict:
    path = Path(file_path)
    if category == "image" and config.face_scan_images:
        return detect_faces_in_image(path, file_id=file_id, media_path=path, media_type="image", source=AUTO_FACE_IMAGE_SOURCE)
    if category == "video" and config.face_scan_videos:
        return detect_faces_in_video(path, file_id=file_id, source=AUTO_FACE_VIDEO_SOURCE)
    return {"ok": True, "face_count": 0, "skipped": True, "reason": f"category {category} not scanned"}


def _serialize_embedding(embedding: list[float]) -> str:
    return json.dumps(embedding)


def _deserialize_embedding(raw: str) -> list[float]:
    return json.loads(raw)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    import math
    dot = sum(va * vb for va, vb in zip(a, b))
    na = math.sqrt(sum(v * v for v in a))
    nb = math.sqrt(sum(v * v for v in b))
    if na < 1e-10 or nb < 1e-10:
        return 0.0
    return dot / (na * nb)


def match_face(embedding: list[float], threshold: float | None = None) -> dict | None:
    threshold = threshold if threshold is not None else config.face_match_threshold
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT cluster_id, name, known_embedding FROM face_names WHERE known_embedding IS NOT NULL")
    rows = cur.fetchall()
    conn.close()
    best = None
    best_sim = threshold
    for row in rows:
        try:
            known_emb = _deserialize_embedding(row["known_embedding"])
        except Exception:
            continue
        sim = _cosine_similarity(embedding, known_emb)
        if sim > best_sim:
            best_sim = sim
            best = {"name": row["name"], "cluster_id": row["cluster_id"], "similarity": round(sim, 4)}
    return best


def name_face(cluster_id: str, name: str, embedding: list[float] | None = None, sample_crop_path: str | None = None) -> dict:
    from fauxnix_tools.utils import now_ts as _now
    ts = _now()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT OR REPLACE INTO face_names (cluster_id, name, known_embedding, sample_crop_path, created_ts, updated_ts)
           VALUES (?, ?, ?, ?, COALESCE((SELECT created_ts FROM face_names WHERE cluster_id = ?), ?), ?)""",
        (cluster_id, name,
         _serialize_embedding(embedding) if embedding else None,
         sample_crop_path,
         cluster_id, ts, ts),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "cluster_id": cluster_id, "name": name}


def get_known_faces() -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT fn.cluster_id, fn.name, fn.sample_crop_path, fn.created_ts, fn.updated_ts,
               (SELECT COUNT(*) FROM face_observations fo WHERE fo.cluster_id = fn.cluster_id) AS observation_count
        FROM face_names fn ORDER BY fn.name
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_observations_for_cluster(cluster_id: str, limit: int = 20) -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM face_observations WHERE cluster_id = ? ORDER BY created_ts DESC LIMIT ?",
        (cluster_id, limit),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        if r.get("bbox_json"):
            r["bbox"] = json.loads(r["bbox_json"])
    return rows


_INSIGHTFACE_APP = None


def _insightface_status() -> dict:
    if not importlib.util.find_spec("insightface"):
        return {"available": False, "error": "insightface not installed"}
    try:
        from insightface.app import FaceAnalysis
        _ = FaceAnalysis
        return {"available": True, "error": None}
    except Exception as e:
        return {"available": False, "error": str(e)}


def _get_insightface_app():
    global _INSIGHTFACE_APP
    if _INSIGHTFACE_APP is None:
        from insightface.app import FaceAnalysis
        _INSIGHTFACE_APP = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        _INSIGHTFACE_APP.prepare(ctx_id=0)
    return _INSIGHTFACE_APP


def insightface_detect(path: str | Path) -> list[dict]:
    import cv2
    app = _get_insightface_app()
    image = cv2.imread(str(path))
    if image is None:
        return []
    faces = app.get(image)
    pil_image = _prepare_image(Path(path))
    results = []
    for face in faces:
        bbox = face.bbox.astype(int).tolist()
        bbox_dict = {"x": bbox[0], "y": bbox[1], "width": bbox[2] - bbox[0], "height": bbox[3] - bbox[1]}
        embedding = face.embedding.tolist() if face.embedding is not None else None
        det_score = float(face.det_score) if face.det_score is not None else 0.0
        gender = int(face.gender) if hasattr(face, "gender") and face.gender is not None else -1
        age = int(face.age) if hasattr(face, "age") and face.age is not None else -1
        landmark = face.landmark.tolist() if face.landmark is not None else None
        crop = pil_image.crop((bbox_dict["x"], bbox_dict["y"],
                               bbox_dict["x"] + bbox_dict["width"],
                               bbox_dict["y"] + bbox_dict["height"]))
        signature = _average_hash(crop)
        results.append({
            "bbox": bbox_dict, "detection_score": det_score, "embedding": embedding,
            "gender": gender, "age": age, "landmark": landmark,
            "signature": signature, "cluster_id": f"face:{signature[:16]}",
        })
    return results


def recognize_faces_in_image(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {"ok": False, "face_count": 0, "error": f"File not found: {path}"}
    status = _insightface_status()
    if not status["available"]:
        return {"ok": False, "face_count": 0, "error": status.get("error", "insightface unavailable")}
    try:
        detections = insightface_detect(path)
        image = _prepare_image(path)
        results = []
        for idx, det in enumerate(detections, start=1):
            bbox = det["bbox"]
            crop = image.crop((bbox["x"], bbox["y"], bbox["x"] + bbox["width"], bbox["y"] + bbox["height"]))
            signature = _average_hash(crop)
            cluster_id = f"face:{signature[:16]}"
            crop_path = str(config.insight_face_dir / cluster_id / f"{path.stem}_{idx:02d}.jpg")
            ensure_parent(Path(crop_path))
            crop.thumbnail((360, 360))
            crop.convert("RGB").save(crop_path, format="JPEG", quality=90)
            observation = _insert_face_observation(
                file_id=None, media_path=path, media_type="image",
                frame_seconds=None, bbox=bbox, crop_path=crop_path,
                signature=signature, source="insightface",
            )
            match = None
            if det.get("embedding"):
                match = match_face(det["embedding"])
                if match:
                    conn = get_conn()
                    cur = conn.cursor()
                    cur.execute("UPDATE face_observations SET cluster_id = ? WHERE id = ?",
                                (match["cluster_id"], observation["id"]))
                    conn.commit()
                    conn.close()
                    observation["cluster_id"] = match["cluster_id"]
            entry = {
                "index": idx, "bbox": bbox, "crop_path": crop_path, "cluster_id": cluster_id,
                "detection_score": det["detection_score"],
                "gender": "male" if det["gender"] == 1 else ("female" if det["gender"] == 0 else "unknown"),
                "age": det["age"], "match": match,
            }
            results.append(entry)
        return {"ok": True, "path": str(path), "face_count": len(results), "faces": results}
    except Exception as e:
        return {"ok": False, "face_count": 0, "error": str(e)}
