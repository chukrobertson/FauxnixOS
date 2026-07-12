from __future__ import annotations

import time
import threading

from fauxnix_tools.db import get_conn as _get_fauxnix_conn, init_base_tables as _init_base_tables


def init_membrie_db():
    _init_base_tables()
    conn = _get_fauxnix_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY,
        title TEXT,
        created_ts REAL,
        updated_ts REAL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_ts REAL,
        FOREIGN KEY(conversation_id) REFERENCES conversations(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS memory_items (
        id TEXT PRIMARY KEY,
        kind TEXT,
        status TEXT,
        content TEXT NOT NULL,
        evidence TEXT,
        confidence REAL,
        source_conversation_id TEXT,
        source_message_id INTEGER,
        created_ts REAL,
        updated_ts REAL,
        notes TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS process_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        process_name TEXT NOT NULL,
        window_title TEXT,
        duration_seconds REAL,
        start_ts REAL,
        end_ts REAL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        content TEXT NOT NULL DEFAULT '',
        kind TEXT DEFAULT 'text',
        file_path TEXT,
        original_name TEXT,
        mime_type TEXT,
        status TEXT DEFAULT 'active',
        created_ts REAL,
        updated_ts REAL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS clipboard_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT DEFAULT 'text',
        content TEXT,
        file_path TEXT,
        original_name TEXT,
        mime_type TEXT,
        size_bytes INTEGER,
        source TEXT DEFAULT 'manual',
        note_id INTEGER,
        created_ts REAL,
        FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE SET NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS workspace_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        workspace_json TEXT NOT NULL,
        node_count INTEGER DEFAULT 0,
        created_ts REAL,
        updated_ts REAL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        started_ts REAL NOT NULL,
        ended_ts REAL,
        app_summary_json TEXT,
        total_active_seconds REAL DEFAULT 0,
        focus_seconds REAL DEFAULT 0,
        drift_count INTEGER DEFAULT 0,
        summary TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS session_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        event_data TEXT,
        created_ts REAL,
        FOREIGN KEY(session_id) REFERENCES sessions(id)
    )
    """)

    indexes = [
        "idx_chat_messages_conversation ON chat_messages(conversation_id, created_ts)",
        "idx_memory_status ON memory_items(status)",
        "idx_memory_updated ON memory_items(updated_ts)",
        "idx_process_log_start ON process_log(start_ts)",
        "idx_process_log_name ON process_log(process_name)",
        "idx_notes_status ON notes(status)",
        "idx_notes_updated ON notes(updated_ts)",
        "idx_clipboard_created ON clipboard_items(created_ts)",
        "idx_sessions_started ON sessions(started_ts)",
        "idx_session_events_session ON session_events(session_id)",
    ]
    for idx in indexes:
        cur.execute(f"CREATE INDEX IF NOT EXISTS {idx}")

    conn.commit()
    conn.close()
