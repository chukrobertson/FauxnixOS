from __future__ import annotations

import time

from fauxnix_tools.db import get_conn as _get_fauxnix_conn, init_base_tables as _init_base_tables
from archivist.config import config


def init_archivist_db():
    conn = _get_fauxnix_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS watched_dirs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT UNIQUE NOT NULL,
        label TEXT,
        auto_organize INTEGER DEFAULT 1,
        auto_index INTEGER DEFAULT 1,
        last_scan_ts REAL,
        created_ts REAL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS file_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER,
        action_type TEXT NOT NULL,
        result_json TEXT,
        decided_by TEXT DEFAULT 'rules',
        created_ts REAL,
        FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS organization_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        priority INTEGER DEFAULT 0,
        conditions_json TEXT NOT NULL,
        target_path TEXT NOT NULL,
        action TEXT DEFAULT 'move',
        enabled INTEGER DEFAULT 1,
        created_ts REAL,
        updated_ts REAL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS translation_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER,
        source_lang TEXT,
        target_lang TEXT,
        translated_text TEXT,
        segments_json TEXT,
        created_ts REAL,
        FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE,
        UNIQUE(file_id, source_lang, target_lang)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS file_relationships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id_a INTEGER NOT NULL,
        file_id_b INTEGER NOT NULL,
        relation_type TEXT NOT NULL,
        confidence REAL DEFAULT 0.0,
        evidence TEXT,
        created_ts REAL,
        FOREIGN KEY(file_id_a) REFERENCES files(id) ON DELETE CASCADE,
        FOREIGN KEY(file_id_b) REFERENCES files(id) ON DELETE CASCADE
    )
    """)

    indexes = [
        "idx_watched_dirs_path ON watched_dirs(path)",
        "idx_file_actions_file ON file_actions(file_id)",
        "idx_file_actions_type ON file_actions(action_type)",
        "idx_org_rules_enabled ON organization_rules(enabled)",
        "idx_translation_cache_file ON translation_cache(file_id)",
        "idx_file_relationships_a ON file_relationships(file_id_a)",
        "idx_file_relationships_b ON file_relationships(file_id_b)",
        "idx_file_relationships_type ON file_relationships(relation_type)",
    ]
    for idx in indexes:
        cur.execute(f"CREATE INDEX IF NOT EXISTS {idx}")

    conn.commit()
    conn.close()


def init_db():
    _init_base_tables()
    init_archivist_db()
