from __future__ import annotations

from fauxnix_tools.vision.faces import (
    detect_faces_in_image, detect_faces_in_video, detect_faces_in_storyboard,
    scan_file_faces, opencv_status, face_engine_status,
    match_face, name_face, get_known_faces, recognize_faces_in_image,
    insightface_detect, get_observations_for_cluster,
    AUTO_FACE_IMAGE_SOURCE, AUTO_FACE_VIDEO_SOURCE,
)
from fauxnix_tools.vision.analysis import (
    analyze_image_path, analyze_image_file, vision_status,
    vision_tag_names, apply_vision_tags_to_file, normalize_vision_result,
)
from fauxnix_tools.vision.objects import (
    detect_objects_in_image, detect_objects_in_video,
)

__all__ = [
    "detect_faces_in_image", "detect_faces_in_video", "detect_faces_in_storyboard",
    "scan_file_faces", "opencv_status", "face_engine_status",
    "match_face", "name_face", "get_known_faces", "recognize_faces_in_image",
    "insightface_detect", "get_observations_for_cluster",
    "AUTO_FACE_IMAGE_SOURCE", "AUTO_FACE_VIDEO_SOURCE",
    "analyze_image_path", "analyze_image_file", "vision_status",
    "vision_tag_names", "apply_vision_tags_to_file", "normalize_vision_result",
    "detect_objects_in_image", "detect_objects_in_video",
]
