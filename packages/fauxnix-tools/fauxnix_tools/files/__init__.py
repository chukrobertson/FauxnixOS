from __future__ import annotations

from fauxnix_tools.files.extraction import extract_any, extract_text
from fauxnix_tools.files.indexing import index_file, index_directory, search_indexed_files
from fauxnix_tools.files.tagging import apply_auto_tags, suggested_auto_tags, file_tag_names, clean_tag_name
from fauxnix_tools.files.snapshot import snapshot_directory, list_snapshots, restore_snapshot

__all__ = [
    "extract_any", "extract_text",
    "index_file", "index_directory", "search_indexed_files",
    "apply_auto_tags", "suggested_auto_tags", "file_tag_names", "clean_tag_name",
    "snapshot_directory", "list_snapshots", "restore_snapshot",
]
