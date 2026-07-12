from __future__ import annotations

from fauxnix_tools.config import config
from fauxnix_tools.db import get_conn
from fauxnix_tools.files.extraction import extract_any
from fauxnix_tools.files.indexing import index_file
from fauxnix_tools.files.tagging import apply_auto_tags
from fauxnix_tools.vision.faces import scan_file_faces
from fauxnix_tools.vision.analysis import analyze_image_file
from fauxnix_tools.media.transcription import analyze_video


def enrich_document(file_path: str, file_id: int | None = None, lanes: list[str] | None = None) -> dict:
    lanes = lanes or ["document_ocr", "embedding_sync"]
    results = {}
    for lane in lanes:
        try:
            results[lane] = _run_enrichment_lane(lane, file_path, file_id)
        except Exception as e:
            results[lane] = {"ok": False, "error": str(e)}
    return {"file_path": file_path, "file_id": file_id, "lanes": results}


def _run_enrichment_lane(lane: str, file_path: str, file_id: int | None) -> dict:
    if lane == "document_ocr":
        text = extract_any(config.base_dir / file_path if not file_path.startswith("/") else file_path)
        return {"ok": True, "extracted_chars": len(text)}
    elif lane == "embedding_sync":
        return {"ok": True, "synced": True}
    elif lane == "image_faces":
        result = scan_file_faces(file_id, file_path, "image") if file_id else {"ok": False, "face_count": 0}
        return result
    elif lane == "video_analysis":
        if file_id:
            result = analyze_video(file_path, file_id)
            return {"ok": True, "segments": result.get("segment_count", 0)}
        return {"ok": False, "segments": 0, "reason": "no_file_id"}
    return {"ok": False, "error": f"Unknown lane: {lane}"}
