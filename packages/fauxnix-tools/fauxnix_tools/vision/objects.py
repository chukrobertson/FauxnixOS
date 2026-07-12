from __future__ import annotations

from pathlib import Path
from typing import Optional


def detect_objects_in_image(image_path: str | Path) -> dict:
    """
    Object detection using a local vision model via Ollama.
    This is a stub — full YOLO/OWL-ViT integration planned for Archivist.
    """
    path = Path(image_path)
    if not path.exists():
        return {"ok": False, "objects": [], "error": f"File not found: {path}"}

    try:
        from fauxnix_tools.vision.analysis import analyze_image_path
        result = analyze_image_path(path)
        analysis = result.get("analysis", {})
        return {
            "ok": True,
            "objects": analysis.get("objects", []),
            "scene_tags": analysis.get("scene_tags", []),
            "model": result.get("model"),
        }
    except Exception as e:
        return {"ok": False, "objects": [], "error": str(e)}


def detect_objects_in_video(video_path: str | Path, frame_interval: int = 5) -> dict:
    """
    Detect objects across video frames.
    This is a stub — full implementation will use ffmpeg + vision model.
    """
    path = Path(video_path)
    if not path.exists():
        return {"ok": False, "objects": [], "error": f"File not found: {path}"}
    return {"ok": False, "objects": [], "error": "Video object detection not yet implemented. Will use ffmpeg frame extraction + vision model analysis."}
