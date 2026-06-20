from __future__ import annotations

import time
from pathlib import Path

from app.db import get_conn

TERMINAL_RUN_STATUSES = {"done", "failed", "cancelled"}
RESUMABLE_RUN_STATUSES = {"queued", "building", "running", "pausing", "paused"}


def now_ts() -> float:
    return time.time()


def create_run(*, force: bool, note: str | None = None) -> int:
    ts = now_ts()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO index_runs (status, force, created_ts, updated_ts, note)
        VALUES ('building', ?, ?, ?, ?)
        """,
        (1 if force else 0, ts, ts, note),
    )
    run_id = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return run_id


def add_queue_item(run_id: int, path: Path) -> bool:
    try:
        stat = path.stat()
    except OSError:
        return False
    ts = now_ts()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO index_queue (
            run_id, path, size_bytes, modified_ts, status, created_ts, updated_ts
        ) VALUES (?, ?, ?, ?, 'pending', ?, ?)
        """,
        (run_id, str(path), stat.st_size, stat.st_mtime, ts, ts),
    )
    inserted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return inserted


def set_run_status(
    run_id: int,
    status: str,
    *,
    current_path: str | None = None,
    last_error: str | None = None,
    finished: bool = False,
) -> None:
    ts = now_ts()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE index_runs
        SET status = ?,
            updated_ts = ?,
            started_ts = CASE WHEN started_ts IS NULL AND ? = 'running' THEN ? ELSE started_ts END,
            finished_ts = CASE WHEN ? THEN ? ELSE finished_ts END,
            current_path = COALESCE(?, current_path),
            last_error = COALESCE(?, last_error)
        WHERE id = ?
        """,
        (status, ts, status, ts, 1 if finished else 0, ts, current_path, last_error, run_id),
    )
    conn.commit()
    conn.close()


def reset_running_items(run_id: int) -> None:
    ts = now_ts()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE index_queue
        SET status = 'pending', updated_ts = ?
        WHERE run_id = ? AND status = 'running'
        """,
        (ts, run_id),
    )
    conn.commit()
    conn.close()


def claim_next_pending(run_id: int) -> dict | None:
    ts = now_ts()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, path, size_bytes, modified_ts
        FROM index_queue
        WHERE run_id = ? AND status = 'pending'
        ORDER BY id ASC
        LIMIT 1
        """,
        (run_id,),
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    item = dict(row)
    cur.execute(
        """
        UPDATE index_queue
        SET status = 'running', updated_ts = ?
        WHERE id = ?
        """,
        (ts, item["id"]),
    )
    cur.execute(
        "UPDATE index_runs SET current_path = ?, updated_ts = ? WHERE id = ?",
        (item["path"], ts, run_id),
    )
    conn.commit()
    conn.close()
    return item


def mark_queue_item(item_id: int, status: str, error: str | None = None) -> None:
    ts = now_ts()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE index_queue
        SET status = ?, error = ?, updated_ts = ?
        WHERE id = ?
        """,
        (status, error, ts, item_id),
    )
    conn.commit()
    conn.close()


def mark_run_error(run_id: int, error: str) -> None:
    ts = now_ts()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE index_runs
        SET last_error = ?, updated_ts = ?
        WHERE id = ?
        """,
        (error[:4000], ts, run_id),
    )
    conn.commit()
    conn.close()


def queue_counts(run_id: int) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT status, COUNT(*) AS count
        FROM index_queue
        WHERE run_id = ?
        GROUP BY status
        """,
        (run_id,),
    )
    counts = {row["status"]: int(row["count"]) for row in cur.fetchall()}
    cur.execute("SELECT COUNT(*) AS count FROM index_queue WHERE run_id = ?", (run_id,))
    total = int(cur.fetchone()["count"])
    conn.close()
    counts["total"] = total
    return counts


def run_snapshot(run_id: int) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM index_runs WHERE id = ?", (run_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    run = dict(row)
    counts = queue_counts(run_id)
    pending = counts.get("pending", 0)
    running = counts.get("running", 0)
    total = counts.get("total", 0)
    run.update(
        {
            "run_id": run_id,
            "total_files": total,
            "total_seen": max(0, total - pending),
            "indexed_count": counts.get("indexed", 0),
            "duplicate_count": counts.get("duplicate", 0),
            "skipped_count": counts.get("skipped", 0),
            "failed_count": counts.get("failed", 0),
            "pending_count": pending,
            "running_count": running,
        }
    )
    return run


def latest_resumable_run() -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM index_runs
        WHERE status IN ('queued', 'building', 'running', 'pausing', 'paused')
        ORDER BY updated_ts DESC, id DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def latest_run() -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM index_runs ORDER BY updated_ts DESC, id DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def recover_interrupted_runs() -> list[int]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id
        FROM index_runs
        WHERE status IN ('queued', 'running', 'pausing', 'building')
        ORDER BY updated_ts DESC
        """
    )
    run_ids = [int(row["id"]) for row in cur.fetchall()]
    ts = now_ts()
    for run_id in run_ids:
        cur.execute(
            """
            UPDATE index_queue
            SET status = 'pending', updated_ts = ?
            WHERE run_id = ? AND status = 'running'
            """,
            (ts, run_id),
        )
        cur.execute(
            """
            UPDATE index_runs
            SET status = CASE
                    WHEN status = 'pausing' THEN 'paused'
                    WHEN status = 'building' THEN 'building'
                    ELSE 'running'
                END,
                updated_ts = ?,
                current_path = ''
            WHERE id = ?
            """,
            (ts, run_id),
        )
    conn.commit()
    conn.close()
    return run_ids
