from __future__ import annotations

import json
import shutil
import time
from datetime import datetime
from pathlib import Path

from fauxnix_tools.config import config
from fauxnix_tools.db import get_conn


def _snapshot_id() -> str:
    return datetime.now().strftime("snapshot_%Y%m%d_%H%M%S")


def snapshot_directory(dir_path: str, reason: str = "manual") -> dict:
    root = Path(dir_path).resolve()
    if not root.is_dir():
        return {"ok": False, "error": "not_a_directory"}

    snap_id = _snapshot_id()
    snap_dir = config.snapshot_dir / snap_id
    suffix = 1
    while snap_dir.exists():
        suffix += 1
        snap_dir = config.snapshot_dir / f"{snap_id}_{suffix}"
    snap_dir.mkdir(parents=True)

    created_ts = time.time()
    files_dir = snap_dir / "files"
    files_dir.mkdir()

    manifest_path = snap_dir / "manifest.json"
    file_entries = []
    total_bytes = 0

    for entry in sorted(root.rglob("*")):
        if entry.is_file():
            rel = entry.relative_to(root)
            dest = files_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(str(entry), str(dest))
                file_entries.append({"path": str(rel), "size": entry.stat().st_size})
                total_bytes += entry.stat().st_size
            except Exception as e:
                file_entries.append({"path": str(rel), "size": 0, "error": str(e)})

    manifest = {
        "snapshot_id": snap_dir.name,
        "source_dir": str(root),
        "reason": reason,
        "created_ts": created_ts,
        "created_local": datetime.fromtimestamp(created_ts).isoformat(timespec="seconds"),
        "snapshot_dir": str(snap_dir),
        "file_count": len(file_entries),
        "total_bytes": total_bytes,
        "files": file_entries,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO snapshots (snapshot_id, source_dir, reason, file_count, total_bytes, manifest_json, created_ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (snap_dir.name, str(root), reason, len(file_entries), total_bytes, json.dumps(manifest), created_ts),
    )
    conn.commit()
    conn.close()

    return {"ok": True, "snapshot_id": snap_dir.name, "snapshot_dir": str(snap_dir), "file_count": len(file_entries), "total_bytes": total_bytes, "manifest": manifest}


def list_snapshots(limit: int = 20) -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM snapshots ORDER BY created_ts DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def restore_snapshot(snapshot_id: str, target_dir: str | None = None) -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM snapshots WHERE snapshot_id = ?", (snapshot_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return {"ok": False, "error": "snapshot_not_found"}

    manifest = json.loads(row["manifest_json"])
    snap_dir = Path(manifest["snapshot_dir"])
    if not snap_dir.exists():
        return {"ok": False, "error": "snapshot_files_missing"}

    restore_root = Path(target_dir) if target_dir else Path(manifest["source_dir"])
    restore_root.mkdir(parents=True, exist_ok=True)

    restored = 0
    for entry in manifest.get("files", []):
        src = snap_dir / "files" / entry["path"]
        dst = restore_root / entry["path"]
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(str(src), str(dst))
                restored += 1
            except Exception:
                pass

    return {"ok": True, "snapshot_id": snapshot_id, "restored": restored, "total": len(manifest.get("files", [])), "target_dir": str(restore_root)}
