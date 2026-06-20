import sqlite3
from app.config import DATA_DIR

DB_PATH = DATA_DIR / "archive.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_column(cur, table: str, column: str, definition: str) -> None:
    cur.execute(f"PRAGMA table_info({table})")
    existing = {row["name"] for row in cur.fetchall()}
    if column not in existing:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    conn = get_conn()
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
        suggested_folder TEXT,
        preview_path TEXT,
        thumb_path TEXT,
        duplicate_of TEXT,
        deleted_candidate INTEGER DEFAULT 0,
        notes TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS uploads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        original_name TEXT,
        temp_path TEXT,
        processed INTEGER DEFAULT 0,
        final_suggested_path TEXT,
        summary TEXT,
        extracted_text TEXT,
        created_ts REAL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS conversations (
        id TEXT PRIMARY KEY,
        title TEXT,
        scope TEXT DEFAULT 'archivist',
        created_ts REAL,
        updated_ts REAL
    )
    """)
    ensure_column(cur, "conversations", "scope", "TEXT DEFAULT 'archivist'")
    cur.execute("UPDATE conversations SET scope = 'archivist' WHERE scope IS NULL OR scope = ''")

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
    CREATE TABLE IF NOT EXISTS deletion_reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER,
        path TEXT NOT NULL,
        reason TEXT,
        status TEXT DEFAULT 'queued',
        created_ts REAL,
        updated_ts REAL,
        FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE SET NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS index_failures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT NOT NULL,
        error TEXT,
        created_ts REAL,
        resolved INTEGER DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS index_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        status TEXT NOT NULL DEFAULT 'queued',
        force INTEGER DEFAULT 0,
        created_ts REAL,
        started_ts REAL,
        updated_ts REAL,
        finished_ts REAL,
        current_path TEXT,
        last_error TEXT,
        note TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS index_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL,
        path TEXT NOT NULL,
        size_bytes INTEGER,
        modified_ts REAL,
        status TEXT NOT NULL DEFAULT 'pending',
        error TEXT,
        created_ts REAL,
        updated_ts REAL,
        UNIQUE(run_id, path),
        FOREIGN KEY(run_id) REFERENCES index_runs(id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS action_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT,
        tool TEXT NOT NULL,
        intent TEXT,
        status TEXT NOT NULL,
        requires_confirmation INTEGER DEFAULT 0,
        params_json TEXT,
        result_json TEXT,
        created_ts REAL,
        executed_ts REAL,
        error TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS admin_development_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        status TEXT DEFAULT 'queued',
        priority TEXT DEFAULT 'medium',
        source TEXT DEFAULT 'manual',
        plan_json TEXT,
        recommended_tools_json TEXT,
        verification_json TEXT,
        rollback_json TEXT,
        notes TEXT,
        last_action_id INTEGER,
        created_ts REAL,
        updated_ts REAL,
        FOREIGN KEY(last_action_id) REFERENCES action_audit(id) ON DELETE SET NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        content TEXT,
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
        source TEXT,
        note_id INTEGER,
        created_ts REAL,
        FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE SET NULL
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
    CREATE TABLE IF NOT EXISTS people (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        display_name TEXT NOT NULL,
        aliases_json TEXT,
        notes TEXT,
        sensitivity TEXT DEFAULT 'normal',
        created_ts REAL,
        updated_ts REAL
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
    CREATE TABLE IF NOT EXISTS person_face_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id INTEGER NOT NULL,
        face_observation_id INTEGER,
        cluster_id TEXT,
        status TEXT DEFAULT 'confirmed',
        confidence REAL DEFAULT 1.0,
        source TEXT DEFAULT 'user',
        created_ts REAL,
        updated_ts REAL,
        FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE CASCADE,
        FOREIGN KEY(face_observation_id) REFERENCES face_observations(id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS timeline_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        summary TEXT,
        start_ts REAL,
        end_ts REAL,
        date_precision TEXT DEFAULT 'unknown',
        location_text TEXT,
        confidence REAL DEFAULT 0.0,
        status TEXT DEFAULT 'candidate',
        uncertainty_notes TEXT,
        created_ts REAL,
        updated_ts REAL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS timeline_event_evidence (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER NOT NULL,
        evidence_type TEXT NOT NULL,
        evidence_id INTEGER,
        path TEXT,
        quote TEXT,
        description TEXT,
        confidence REAL DEFAULT 0.0,
        created_ts REAL,
        FOREIGN KEY(event_id) REFERENCES timeline_events(id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS timeline_event_people (
        event_id INTEGER NOT NULL,
        person_id INTEGER NOT NULL,
        role TEXT DEFAULT 'unknown',
        confidence REAL DEFAULT 0.0,
        PRIMARY KEY (event_id, person_id, role),
        FOREIGN KEY(event_id) REFERENCES timeline_events(id) ON DELETE CASCADE,
        FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE CASCADE
    )
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_files_name ON files(name)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_files_ext ON files(ext)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_files_path ON files(path)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_files_sha256 ON files(sha256)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_files_category ON files(category)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_files_deleted_candidate ON files(deleted_candidate)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation ON chat_messages(conversation_id, created_ts)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_memory_status ON memory_items(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_memory_updated ON memory_items(updated_ts)")
    ensure_column(cur, "file_tags", "source", "TEXT DEFAULT 'manual'")
    ensure_column(cur, "face_observations", "source", "TEXT DEFAULT 'manual'")
    ensure_column(cur, "face_observations", "updated_ts", "REAL")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_file_tags_file ON file_tags(file_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_file_tags_tag ON file_tags(tag_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_file_tags_source ON file_tags(source)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_deletion_reviews_file ON deletion_reviews(file_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_deletion_reviews_status ON deletion_reviews(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_index_failures_path ON index_failures(path)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_index_failures_resolved ON index_failures(resolved)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_index_runs_status ON index_runs(status, updated_ts)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_index_queue_run_status ON index_queue(run_id, status, id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_index_queue_path ON index_queue(path)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_action_audit_conversation_status ON action_audit(conversation_id, status, created_ts)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_admin_development_tasks_status ON admin_development_tasks(status, priority, updated_ts)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_admin_development_tasks_title ON admin_development_tasks(title)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_notes_status_updated ON notes(status, updated_ts)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_clipboard_created ON clipboard_items(created_ts)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_media_segments_file ON media_segments(file_id, start_seconds)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_media_segments_path ON media_segments(path, start_seconds)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_media_segments_timeline ON media_segments(timeline)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_people_display_name ON people(display_name)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_face_observations_file ON face_observations(file_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_face_observations_cluster ON face_observations(cluster_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_face_observations_source ON face_observations(source)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_person_face_links_person ON person_face_links(person_id, status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_person_face_links_face ON person_face_links(face_observation_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_timeline_events_status_start ON timeline_events(status, start_ts)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_timeline_events_title ON timeline_events(title)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_timeline_evidence_event ON timeline_event_evidence(event_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_timeline_evidence_type ON timeline_event_evidence(evidence_type, evidence_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_timeline_event_people_person ON timeline_event_people(person_id, event_id)")
    conn.commit()
    conn.close()


def clear_file_index() -> dict:
    conn = get_conn()
    cur = conn.cursor()
    counts = {}
    for table in ["media_segments", "file_tags", "deletion_reviews", "index_failures", "index_queue", "index_runs", "files", "uploads"]:
        cur.execute(f"SELECT COUNT(*) AS count FROM {table}")
        counts[table] = int(cur.fetchone()["count"])
        cur.execute(f"DELETE FROM {table}")
    conn.commit()
    conn.close()
    return counts
