from __future__ import annotations

import sqlite3
from pathlib import Path


DB_PATH = Path.home() / ".local" / "share" / "fauxnix" / "nexus" / "nexus.db"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS thread_context (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT NOT NULL,
            thread_name TEXT NOT NULL,
            source TEXT NOT NULL,
            event_data TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS thread_vectors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT NOT NULL,
            thread_name TEXT NOT NULL,
            vector BLOB,
            text_summary TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            suggestion_type TEXT NOT NULL,
            thread_id TEXT,
            thread_b_id TEXT,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            action_json TEXT,
            confidence REAL DEFAULT 0.5,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS drift_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id TEXT NOT NULL,
            original_topic TEXT,
            drifted_toward TEXT,
            nearest_ws TEXT,
            similarity REAL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_thread_context_thread ON thread_context(thread_id);
        CREATE INDEX IF NOT EXISTS idx_thread_context_source ON thread_context(source);
        CREATE INDEX IF NOT EXISTS idx_thread_vectors_thread ON thread_vectors(thread_id);
        CREATE INDEX IF NOT EXISTS idx_suggestions_status ON suggestions(status);
    """)
    conn.commit()
    conn.close()
