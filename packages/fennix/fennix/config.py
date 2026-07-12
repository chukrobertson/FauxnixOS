from __future__ import annotations

import os
from pathlib import Path

from fauxnix_tools.config import config as _fauxnix_config


class FennixConfig:
    def __init__(self):
        self.fauxnix = _fauxnix_config

        self.data_dir = self.fauxnix.data_dir / "fennix"
        self.conversations_dir = self.data_dir / "conversations"
        self.ingested_dir = self.data_dir / "ingested"
        self.clipboard_dir = self.data_dir / "clipboard"
        self.context_dir = self.data_dir / "context"
        self.db_path = self.data_dir / "fennix.db"

        for d in [
            self.data_dir, self.conversations_dir, self.ingested_dir,
            self.clipboard_dir, self.context_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)

        self.model = os.getenv("FENNIX_MODEL", "qwen2.5:7b")
        self.thread_name = os.getenv("FENNIX_THREAD_NAME", "workspace")
        self.ingest_dirs = [
            Path(p) for p in os.getenv("FENNIX_INGEST_DIRS", "").split(":")
            if p.strip()
        ]
        if not self.ingest_dirs:
            self.ingest_dirs = [
                Path.home() / "Documents",
                Path.home() / "Projects",
                Path.home() / "Downloads",
            ]

        self.auto_ingest = self._env_bool("FENNIX_AUTO_INGEST", True)
        self.recall_top_k = int(os.getenv("FENNIX_RECALL_TOPK", "5") or "5")
        self.max_context_tokens = int(os.getenv("FENNIX_MAX_CONTEXT_TOKENS", "8192") or "8192")
        self.clipboard_watch = self._env_bool("FENNIX_CLIPBOARD_WATCH", True)
        self.system_snapshot_interval = int(os.getenv("FENNIX_SYSTEM_SNAPSHOT_INTERVAL", "300") or "300")
        self.max_ingest_file_mb = int(os.getenv("FENNIX_MAX_INGEST_FILE_MB", "10") or "10")
        self.chunk_size = int(os.getenv("FENNIX_CHUNK_SIZE", "1000") or "1000")
        self.chunk_overlap = int(os.getenv("FENNIX_CHUNK_OVERLAP", "200") or "200")
        self.recall_threshold = float(os.getenv("FENNIX_RECALL_THRESHOLD", "0.65") or "0.65")

    @staticmethod
    def _env_bool(name: str, default: bool) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.strip().lower() not in {"0", "false", "no", "off"}


config = FennixConfig()
