from __future__ import annotations

import json
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from app.config import CHROMA_DIR, DATA_DIR
from app.db import DB_PATH, get_conn


SNAPSHOT_ROOT = DATA_DIR / "index_snapshots"
INDEX_SNAPSHOT_TABLES = [
    "files",
    "file_tags",
    "tags",
    "deletion_reviews",
    "index_failures",
    "index_queue",
    "index_runs",
    "media_segments",
    "uploads",
]


def _snapshot_id() -> str:
    return datetime.now().strftime("index_snapshot_%Y%m%d_%H%M%S")


def _table_exists(cur: sqlite3.Cursor, table: str) -> bool:
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cur.fetchone() is not None


def _count_table(cur: sqlite3.Cursor, table: str) -> int:
    if not _table_exists(cur, table):
        return 0
    cur.execute(f'SELECT COUNT(*) AS count FROM "{table}"')
    row = cur.fetchone()
    return int(row["count"] if isinstance(row, sqlite3.Row) else row[0])


def _export_table_jsonl(cur: sqlite3.Cursor, table: str, dest: Path) -> int:
    if not _table_exists(cur, table):
        return 0
    count = 0
    with dest.open("w", encoding="utf-8") as handle:
        for row in cur.execute(f'SELECT * FROM "{table}"'):
            handle.write(json.dumps(dict(row), ensure_ascii=False, default=str))
            handle.write("\n")
            count += 1
    return count


def _backup_sqlite(dest: Path) -> None:
    source = sqlite3.connect(DB_PATH, timeout=30)
    try:
        target = sqlite3.connect(dest)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def snapshot_file_index(reason: str = "manual") -> dict:
    SNAPSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    snapshot_dir = SNAPSHOT_ROOT / _snapshot_id()
    suffix = 1
    while snapshot_dir.exists():
        snapshot_dir = SNAPSHOT_ROOT / f"{_snapshot_id()}_{suffix}"
        suffix += 1
    snapshot_dir.mkdir(parents=True)

    created_ts = time.time()
    db_snapshot = snapshot_dir / "archive_index_snapshot.db"
    manifest_path = snapshot_dir / "manifest.json"
    tables_dir = snapshot_dir / "tables"
    tables_dir.mkdir()

    _backup_sqlite(db_snapshot)

    conn = get_conn()
    cur = conn.cursor()
    table_info = {}
    try:
        for table in INDEX_SNAPSHOT_TABLES:
            count = _export_table_jsonl(cur, table, tables_dir / f"{table}.jsonl")
            table_info[table] = {"rows": count, "jsonl": str(tables_dir / f"{table}.jsonl")}
    finally:
        conn.close()

    chroma_info = {"attempted": False, "copied": False, "path": "", "error": ""}
    if CHROMA_DIR.exists():
        chroma_dest = snapshot_dir / "chroma"
        chroma_info.update({"attempted": True, "path": str(chroma_dest)})
        try:
            shutil.copytree(CHROMA_DIR, chroma_dest)
            chroma_info["copied"] = True
        except Exception as error:
            chroma_info["error"] = str(error)

    manifest = {
        "snapshot_id": snapshot_dir.name,
        "reason": reason,
        "created_ts": created_ts,
        "created_local": datetime.fromtimestamp(created_ts).isoformat(timespec="seconds"),
        "snapshot_dir": str(snapshot_dir),
        "manifest_path": str(manifest_path),
        "database": str(db_snapshot),
        "source_database": str(DB_PATH),
        "tables": table_info,
        "total_rows": sum(item["rows"] for item in table_info.values()),
        "chroma": chroma_info,
        "restore_note": (
            "This is a pre-wipe index snapshot. The SQLite backup preserves the full local database "
            "at snapshot time; tables/*.jsonl gives browsable exports of index-related tables. "
            "If the Chroma copy is unavailable, archive embeddings can be rebuilt from restored file rows."
        ),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest
