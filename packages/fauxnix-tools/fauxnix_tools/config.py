from __future__ import annotations

import os
from pathlib import Path


class FauxnixConfig:
    def __init__(self):
        xdg_data = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        xdg_cache = Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache"))
        xdg_config = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))

        self.base_dir = xdg_data / "fauxnix"
        self.cache_dir = xdg_cache / "fauxnix"
        self.config_dir = xdg_config / "fauxnix"

        self.data_dir = self.base_dir / "data"
        self.chroma_dir = self.data_dir / "chroma"
        self.thumbs_dir = self.data_dir / "thumbs"
        self.preview_dir = self.data_dir / "previews"
        self.media_context_dir = self.data_dir / "media" / "video_context"
        self.face_crop_dir = self.data_dir / "media" / "faces"
        self.face_video_frame_dir = self.data_dir / "media" / "face_video_frames"
        self.insight_face_dir = self.data_dir / "media" / "insight_faces"
        self.snapshot_dir = self.data_dir / "snapshots"
        self.archive_root = self.data_dir / "archive"
        self.knowledgebase_dir = self.data_dir / "knowledgebase"
        self.notes_dir = self.data_dir / "notes"
        self.clipboard_dir = self.data_dir / "clipboard"

        for p in [
            self.data_dir, self.chroma_dir, self.thumbs_dir, self.preview_dir,
            self.media_context_dir, self.face_crop_dir, self.face_video_frame_dir,
            self.insight_face_dir, self.snapshot_dir,
            self.archive_root, self.knowledgebase_dir, self.notes_dir, self.clipboard_dir,
        ]:
            p.mkdir(parents=True, exist_ok=True)

        self.db_path = self.data_dir / "fauxnix.db"

        self.ollama_chat_model = os.getenv("FAUXNIX_CHAT_MODEL", "qwen2.5:7b")
        self.ollama_embed_model = os.getenv("FAUXNIX_EMBED_MODEL", "nomic-embed-text:latest")
        self.ollama_reason_model = os.getenv("FAUXNIX_REASON_MODEL", "qwen2.5:7b")
        self.ollama_vision_model = os.getenv("FAUXNIX_VISION_MODEL", "llava-phi3:3.8b")
        self.ollama_vision_fallback = os.getenv("FAUXNIX_VISION_FALLBACK", "moondream:1.8b")
        self.ollama_summary_model = os.getenv("FAUXNIX_SUMMARY_MODEL", "qwen2.5:1.5b")

        self.tesseract_cmd = os.getenv("FAUXNIX_TESSERACT_CMD", "tesseract")
        self.ffmpeg_bin = os.getenv("FAUXNIX_FFMPEG_BIN", "ffmpeg")
        self.ffprobe_bin = os.getenv("FAUXNIX_FFPROBE_BIN", "ffprobe")

        self.whisper_model = os.getenv("FAUXNIX_WHISPER_MODEL", "base")
        self.whisper_language = os.getenv("FAUXNIX_WHISPER_LANGUAGE", "")
        self.whisper_device = os.getenv("FAUXNIX_WHISPER_DEVICE", "cpu")
        self.whisper_compute_type = os.getenv("FAUXNIX_WHISPER_COMPUTE_TYPE", "int8")

        self.face_scan_images = self._env_bool("FAUXNIX_FACE_SCAN_IMAGES", True)
        self.face_scan_videos = self._env_bool("FAUXNIX_FACE_SCAN_VIDEOS", True)
        self.face_max_dim = int(os.getenv("FAUXNIX_FACE_MAX_DIM", "1600") or "1600")
        self.face_video_max_frames = max(1, min(int(os.getenv("FAUXNIX_FACE_VIDEO_FRAMES", "3") or "3"), 12))
        self.face_match_threshold = float(os.getenv("FAUXNIX_FACE_MATCH_THRESHOLD", "0.4") or "0.4")

    @staticmethod
    def _env_bool(name: str, default: bool) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.strip().lower() not in {"0", "false", "no", "off"}


config = FauxnixConfig()
