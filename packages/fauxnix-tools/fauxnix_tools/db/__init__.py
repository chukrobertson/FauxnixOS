from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from fauxnix_tools import config


def get_conn(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = db_path or config.db_path
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_column(cur, table: str, column: str, definition: str):
    cur.execute(f"PRAGMA table_info({table})")
    existing = {row["name"] for row in cur.fetchall()}
    if column not in existing:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_base_tables(db_path: Optional[Path] = None):
    conn = get_conn(db_path)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT UNIQUE NOT NULL,
        rel_path TEXT,
        name TEXT,
        ext TEXT,
        mime_type TEXT,
        size_bytes INTEGER,
        sha256 TEXT,
        created_ts REAL,
        modified_ts REAL,
        indexed_ts REAL,
        category TEXT,
        summary TEXT,
        extracted_text TEXT,
        preview_path TEXT,
        thumb_path TEXT,
        source_dir TEXT,
        notes TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        color TEXT,
        created_ts REAL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS file_tags (
        file_id INTEGER NOT NULL,
        tag_id INTEGER NOT NULL,
        source TEXT DEFAULT 'manual',
        created_ts REAL,
        PRIMARY KEY (file_id, tag_id),
        FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE,
        FOREIGN KEY(tag_id) REFERENCES tags(id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS media_segments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER,
        path TEXT NOT NULL,
        media_type TEXT DEFAULT 'video',
        start_seconds REAL DEFAULT 0,
        end_seconds REAL,
        title TEXT,
        summary TEXT,
        timeline TEXT,
        tags_json TEXT,
        associations_json TEXT,
        thumb_path TEXT,
        source TEXT DEFAULT 'manual',
        created_ts REAL,
        updated_ts REAL,
        FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS face_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER,
        path TEXT NOT NULL,
        media_type TEXT DEFAULT 'image',
        frame_seconds REAL,
        bbox_json TEXT,
        crop_path TEXT,
        embedding_ref TEXT,
        detection_confidence REAL,
        cluster_id TEXT,
        source TEXT DEFAULT 'manual',
        created_ts REAL,
        updated_ts REAL,
        FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS face_names (
        cluster_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        known_embedding TEXT,
        sample_crop_path TEXT,
        created_ts REAL,
        updated_ts REAL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id TEXT,
        source_dir TEXT NOT NULL,
        reason TEXT,
        file_count INTEGER,
        total_bytes INTEGER,
        manifest_json TEXT,
        created_ts REAL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS indexed_dirs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT UNIQUE NOT NULL,
        label TEXT,
        last_indexed_ts REAL,
        file_count INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS archive_locations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT NOT NULL,
        label TEXT,
        slot TEXT,
        "group" TEXT DEFAULT 'default',
        created_ts REAL
    )
    """)

    indexes = [
        "idx_files_name ON files(name)",
        "idx_files_ext ON files(ext)",
        "idx_files_path ON files(path)",
        "idx_files_sha256 ON files(sha256)",
        "idx_files_category ON files(category)",
        "idx_files_source_dir ON files(source_dir)",
        "idx_file_tags_file ON file_tags(file_id)",
        "idx_file_tags_tag ON file_tags(tag_id)",
        "idx_file_tags_source ON file_tags(source)",
        "idx_media_segments_file ON media_segments(file_id, start_seconds)",
        "idx_media_segments_path ON media_segments(path, start_seconds)",
        "idx_face_observations_file ON face_observations(file_id)",
        "idx_face_observations_cluster ON face_observations(cluster_id)",
        "idx_indexed_dirs_path ON indexed_dirs(path)",
        "idx_archive_locations_slot ON archive_locations(slot)",
    ]
    for idx in indexes:
        cur.execute(f"CREATE INDEX IF NOT EXISTS {idx}")

    conn.commit()
    conn.close()
