from __future__ import annotations

import os
from pathlib import Path

from fauxnix_tools.config import config as _fauxnix_config


class ArchivistConfig:
    def __init__(self):
        self.fauxnix = _fauxnix_config
        self.data_dir = self.fauxnix.data_dir / "archivist"
        self.db_path = self.data_dir / "archivist.db"
        self.watch_file = self.data_dir / "watched_dirs.json"

        self.translation_languages = os.getenv("ARCHIVIST_TRANSLATION_LANGS", "en,es,fr,de,zh,ja,ko,ru,ar").split(",")
        self.auto_organize = self._env_bool("ARCHIVIST_AUTO_ORGANIZE", True)
        self.auto_dedup = self._env_bool("ARCHIVIST_AUTO_DEDUP", True)
        self.auto_classify = self._env_bool("ARCHIVIST_AUTO_CLASSIFY", True)
        self.max_file_preview_mb = int(os.getenv("ARCHIVIST_MAX_PREVIEW_MB", "50") or "50")

        for d in [self.data_dir]:
            d.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _env_bool(name: str, default: bool) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.strip().lower() not in {"0", "false", "no", "off"}


config = ArchivistConfig()
