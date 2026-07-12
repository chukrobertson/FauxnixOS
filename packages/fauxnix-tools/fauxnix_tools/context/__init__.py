from __future__ import annotations

import time
from pathlib import Path

from fauxnix_tools.config import config
from fauxnix_tools.db import get_conn


def _table_exists(table: str) -> bool:
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(f"SELECT 1 FROM {table} LIMIT 1")
        conn.close()
        return True
    except Exception:
        return False


def discover_archive_sources(mode: str = "archive_sources") -> dict:
    try:
        sources = []
        if (mode == "archive_sources" or mode == "all") and _table_exists("archive_locations"):
            conn = get_conn()
            cur = conn.cursor()
            cur.execute('SELECT id, path, label, slot, "group" as source_group FROM archive_locations')
            rows = cur.fetchall()
            conn.close()
            for row in rows:
                sources.append({
                    "id": row["id"], "label": row["label"] or row["path"],
                    "path": row["path"], "group": row["source_group"],
                    "slot": row["slot"], "configured": True, "health_status": "available",
                })
        return {"mode": mode, "sources": sources, "total": len(sources), "generated_ts": time.time()}
    except Exception as e:
        return {"mode": mode, "sources": [], "error": str(e)}


def get_active_archive_state(include_workspace: bool = False) -> dict:
    try:
        conn = get_conn()
        cur = conn.cursor()
        active_root = None
        active_knowledgebase = None
        sources_count = 0
        if _table_exists("archive_locations"):
            cur.execute("SELECT id, path, label FROM archive_locations WHERE slot = 'archive_root'")
            active_root = cur.fetchone()
            cur.execute("SELECT id, path, label FROM archive_locations WHERE slot = 'knowledgebase_root'")
            active_knowledgebase = cur.fetchone()
            cur.execute("SELECT COUNT(*) as count FROM archive_locations")
            sources_count = cur.fetchone()[0]
        result = {
            "active_archive_root": active_root["path"] if active_root else str(config.archive_root),
            "active_knowledgebase_root": active_knowledgebase["path"] if active_knowledgebase else str(config.knowledgebase_dir),
            "sources_count": sources_count,
            "last_updated": time.time(),
        }
        if include_workspace:
            if _table_exists("workspace_snapshots"):
                cur.execute("SELECT COUNT(*) as count FROM workspace_snapshots")
                result["workspace_snapshots"] = cur.fetchone()[0]
            else:
                result["workspace_snapshots"] = 0
            if _table_exists("notes"):
                cur.execute("SELECT COUNT(*) as count FROM notes")
                result["notes_count"] = cur.fetchone()[0]
            else:
                result["notes_count"] = 0
        conn.close()
        return result
    except Exception as e:
        return {"error": str(e)}


def list_available_context_sources() -> dict:
    try:
        conn = get_conn()
        cur = conn.cursor()
        locations = []
        if _table_exists("archive_locations"):
            cur.execute("SELECT slot, path, label FROM archive_locations")
            for row in cur.fetchall():
                locations.append({
                    "slot": row["slot"], "path": row["path"],
                    "label": row["label"], "type": "archive_location",
                })
        notes_count = 0
        if _table_exists("notes"):
            cur.execute("SELECT COUNT(*) as count FROM notes WHERE status = 'active'")
            notes_count = cur.fetchone()[0]
        workspace_count = 0
        if _table_exists("workspace_snapshots"):
            cur.execute("SELECT COUNT(*) as count FROM workspace_snapshots")
            workspace_count = cur.fetchone()[0]
        conn.close()
        return {
            "archive_sources": locations, "active_notes": notes_count,
            "workspace_snapshots": workspace_count,
            "total_context": notes_count + workspace_count,
            "last_updated": time.time(),
        }
    except Exception as e:
        return {"error": str(e)}


def get_context_constellation() -> dict:
    try:
        return {
            "generated_ts": time.time(),
            "active_archive_root": str(config.archive_root),
            "active_knowledgebase_root": str(config.knowledgebase_dir),
            "sources": [
                {"id": "core-fauxnix", "label": "Fauxnix", "group": "core", "health_status": "available"},
                {"id": "workspace-1", "label": "Workspace 1", "group": "workspace", "health_status": "available"},
                {"id": "discovery", "label": "Context Discovery", "group": "discovery", "health_status": "available"},
            ],
            "links": [
                {"source": "core-fauxnix", "target": "workspace-1", "kind": "workspace"},
                {"source": "core-fauxnix", "target": "discovery", "kind": "discovery"},
            ],
        }
    except Exception as e:
        return {"error": str(e)}
