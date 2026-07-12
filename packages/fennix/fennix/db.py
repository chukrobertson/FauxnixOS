from __future__ import annotations

import time

from fauxnix_tools.db import get_conn as _get_fauxnix_conn, init_base_tables as _init_base_tables


def init_fennix_db():
    _init_base_tables()
    conn = _get_fauxnix_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS fennix_conversations (
        id TEXT PRIMARY KEY,
        title TEXT,
        started_ts REAL NOT NULL,
        ended_ts REAL,
        session_id TEXT,
        summary TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS fennix_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'context')),
        content TEXT NOT NULL,
        embedding_id TEXT,
        created_ts REAL NOT NULL,
        FOREIGN KEY(conversation_id) REFERENCES fennix_conversations(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS fennix_ingested_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT NOT NULL UNIQUE,
        file_hash TEXT NOT NULL,
        mime_type TEXT,
        file_size INTEGER,
        title TEXT,
        summary TEXT,
        source TEXT DEFAULT 'manual',
        ingested_ts REAL NOT NULL,
        updated_ts REAL NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS fennix_file_chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ingested_file_id INTEGER NOT NULL,
        chunk_index INTEGER NOT NULL,
        content TEXT NOT NULL,
        token_count INTEGER,
        embedding_id TEXT NOT NULL,
        created_ts REAL NOT NULL,
        FOREIGN KEY(ingested_file_id) REFERENCES fennix_ingested_files(id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS fennix_clipboard_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        content_hash TEXT NOT NULL UNIQUE,
        mime_type TEXT DEFAULT 'text/plain',
        source_app TEXT,
        captured_ts REAL NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS fennix_context_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_type TEXT NOT NULL,
        snapshot_data TEXT NOT NULL,
        captured_ts REAL NOT NULL
    )
    """)

    indexes = [
        "idx_fennix_messages_conversation ON fennix_messages(conversation_id, created_ts)",
        "idx_fennix_messages_embedding ON fennix_messages(embedding_id)",
        "idx_fennix_ingested_files_hash ON fennix_ingested_files(file_hash)",
        "idx_fennix_ingested_files_source ON fennix_ingested_files(source)",
        "idx_fennix_ingested_files_updated ON fennix_ingested_files(updated_ts)",
        "idx_fennix_file_chunks_ingested ON fennix_file_chunks(ingested_file_id, chunk_index)",
        "idx_fennix_file_chunks_embedding ON fennix_file_chunks(embedding_id)",
        "idx_fennix_clipboard_hash ON fennix_clipboard_snapshots(content_hash)",
        "idx_fennix_clipboard_captured ON fennix_clipboard_snapshots(captured_ts)",
        "idx_fennix_context_type ON fennix_context_snapshots(snapshot_type)",
        "idx_fennix_context_captured ON fennix_context_snapshots(captured_ts)",
    ]
    for idx in indexes:
        cur.execute(f"CREATE INDEX IF NOT EXISTS {idx}")

    conn.commit()
    conn.close()
