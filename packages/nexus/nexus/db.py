from __future__ import annotations

import json
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
            thread_name TEXT NOT NULL,
            source TEXT NOT NULL,
            event_data TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS thread_vectors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_name TEXT NOT NULL,
            vector BLOB,
            text_summary TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            suggestion_type TEXT NOT NULL,
            thread_name TEXT,
            thread_b_name TEXT,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            action_json TEXT,
            confidence REAL DEFAULT 0.5,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS drift_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_name TEXT NOT NULL,
            original_topic TEXT,
            drifted_toward TEXT,
            nearest_ws TEXT,
            similarity REAL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_thread_context_name ON thread_context(thread_name);
        CREATE INDEX IF NOT EXISTS idx_thread_context_source ON thread_context(source);
        CREATE INDEX IF NOT EXISTS idx_thread_vectors_name ON thread_vectors(thread_name);
        CREATE INDEX IF NOT EXISTS idx_suggestions_status ON suggestions(status);
    """)
    conn.commit()
    conn.close()


def insert_event(thread_name: str, source: str, data: dict) -> int:
    conn = get_conn()
    event_json = json.dumps(data)
    conn.execute(
        "INSERT INTO thread_context (thread_name, source, event_data) VALUES (?, ?, ?)",
        (thread_name, source, event_json),
    )
    conn.commit()
    row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return row_id


def recent_events(thread_name: str | None = None, limit: int = 100) -> list[dict]:
    conn = get_conn()
    if thread_name:
        rows = conn.execute(
            "SELECT * FROM thread_context WHERE thread_name = ? ORDER BY id DESC LIMIT ?",
            (thread_name, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM thread_context ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


def thread_names() -> list[str]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT thread_name FROM thread_context ORDER BY thread_name"
    ).fetchall()
    conn.close()
    return [r["thread_name"] for r in rows]


def event_counts() -> dict[str, int]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT thread_name, count(*) as cnt FROM thread_context GROUP BY thread_name"
    ).fetchall()
    conn.close()
    return {r["thread_name"]: r["cnt"] for r in rows}


def count_events(thread_name: str) -> int:
    conn = get_conn()
    row = conn.execute(
        "SELECT count(*) as cnt FROM thread_context WHERE thread_name = ?",
        (thread_name,),
    ).fetchone()
    conn.close()
    return row["cnt"] if row else 0
