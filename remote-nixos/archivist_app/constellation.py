from __future__ import annotations

import time

from app.archive_locations import archive_location_status
from app.db import get_conn


def _node(
    node_id: str,
    label: str,
    group: str,
    *,
    count: int | None = None,
    size_bytes: int | None = None,
    badges: list[str] | None = None,
    detail: str = "",
    path: str = "",
) -> dict:
    metrics = {}
    if count is not None:
        metrics["count"] = int(count)
    if size_bytes is not None:
        metrics["size_bytes"] = int(size_bytes)
    return {
        "id": node_id,
        "label": label,
        "group": group,
        "path": path,
        "health_status": "available",
        "health_label": "Mapped",
        "chat_policy": "data",
        "chat_policy_label": "Data",
        "index_policy": "linked",
        "index_policy_label": "Linked",
        "badges": badges or [],
        "policy_reason": detail,
        "metrics": metrics,
        "actions": [],
    }


def _link(source: str, target: str, relation: str, *, count: int | None = None) -> dict:
    link = {"source": source, "target": target, "kind": relation, "chat_policy": "data"}
    if count is not None:
        link["count"] = int(count)
    return link


def _count(cur, sql: str, params: tuple = ()) -> int:
    cur.execute(sql, params)
    row = cur.fetchone()
    return int((row or {"count": 0})["count"] or 0)


def _rows(cur, sql: str, params: tuple = ()) -> list[dict]:
    cur.execute(sql, params)
    return [dict(row) for row in cur.fetchall()]


def _safe_id(prefix: str, value: str) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value or "")).strip("-")
    return f"{prefix}-{safe or 'unknown'}"


def data_constellation() -> dict:
    conn = get_conn()
    cur = conn.cursor()

    total_files = _count(cur, "SELECT COUNT(*) AS count FROM files")
    active_files = _count(cur, "SELECT COUNT(*) AS count FROM files WHERE COALESCE(deleted_candidate, 0) = 0")
    review_files = _count(cur, "SELECT COUNT(*) AS count FROM files WHERE COALESCE(deleted_candidate, 0) = 1")
    duplicate_files = _count(cur, "SELECT COUNT(*) AS count FROM files WHERE duplicate_of IS NOT NULL AND duplicate_of != ''")
    active_bytes = _count(
        cur,
        "SELECT COALESCE(SUM(size_bytes), 0) AS count FROM files WHERE COALESCE(deleted_candidate, 0) = 0",
    )
    knowledgebase_files = _count(
        cur,
        "SELECT COUNT(*) AS count FROM files WHERE COALESCE(deleted_candidate, 0) = 0 AND category = 'knowledgebase'",
    )
    memory_count = _count(cur, "SELECT COUNT(*) AS count FROM memory_items")
    note_count = _count(cur, "SELECT COUNT(*) AS count FROM notes WHERE status != 'deleted'")
    conversation_count = _count(cur, "SELECT COUNT(*) AS count FROM conversations")
    message_count = _count(cur, "SELECT COUNT(*) AS count FROM chat_messages")
    clipboard_count = _count(cur, "SELECT COUNT(*) AS count FROM clipboard_items")
    tag_count = _count(cur, "SELECT COUNT(*) AS count FROM tags")
    action_count = _count(cur, "SELECT COUNT(*) AS count FROM action_audit")
    queued_reviews = _count(cur, "SELECT COUNT(*) AS count FROM deletion_reviews WHERE status = 'queued'")

    category_rows = _rows(
        cur,
        """
        SELECT COALESCE(category, 'other') AS category, COUNT(*) AS count,
               COALESCE(SUM(size_bytes), 0) AS size_bytes
        FROM files
        WHERE COALESCE(deleted_candidate, 0) = 0
        GROUP BY COALESCE(category, 'other')
        ORDER BY count DESC
        LIMIT 14
        """,
    )
    tag_rows = _rows(
        cur,
        """
        SELECT t.name, COUNT(ft.file_id) AS count
        FROM tags t
        LEFT JOIN file_tags ft ON ft.tag_id = t.id
        GROUP BY t.id
        HAVING count > 0
        ORDER BY count DESC, t.name COLLATE NOCASE
        LIMIT 14
        """,
    )
    memory_status_rows = _rows(
        cur,
        """
        SELECT COALESCE(status, 'KEEP') AS status, COUNT(*) AS count
        FROM memory_items
        GROUP BY COALESCE(status, 'KEEP')
        ORDER BY count DESC
        LIMIT 10
        """,
    )
    note_kind_rows = _rows(
        cur,
        """
        SELECT COALESCE(kind, 'text') AS kind, COUNT(*) AS count
        FROM notes
        WHERE status != 'deleted'
        GROUP BY COALESCE(kind, 'text')
        ORDER BY count DESC
        LIMIT 10
        """,
    )
    clipboard_kind_rows = _rows(
        cur,
        """
        SELECT COALESCE(kind, 'text') AS kind, COUNT(*) AS count
        FROM clipboard_items
        GROUP BY COALESCE(kind, 'text')
        ORDER BY count DESC
        LIMIT 10
        """,
    )
    action_status_rows = _rows(
        cur,
        """
        SELECT COALESCE(status, 'unknown') AS status, COUNT(*) AS count
        FROM action_audit
        GROUP BY COALESCE(status, 'unknown')
        ORDER BY count DESC
        LIMIT 8
        """,
    )
    tag_category_rows = _rows(
        cur,
        """
        SELECT t.name, COALESCE(f.category, 'other') AS category, COUNT(*) AS count
        FROM file_tags ft
        JOIN tags t ON t.id = ft.tag_id
        JOIN files f ON f.id = ft.file_id
        WHERE COALESCE(f.deleted_candidate, 0) = 0
        GROUP BY t.name, COALESCE(f.category, 'other')
        ORDER BY count DESC
        LIMIT 24
        """,
    )
    note_file_links = _count(cur, "SELECT COUNT(*) AS count FROM notes WHERE file_path IS NOT NULL AND file_path != '' AND status != 'deleted'")
    clipboard_note_links = _count(cur, "SELECT COUNT(*) AS count FROM clipboard_items WHERE note_id IS NOT NULL")
    memory_conversation_links = _count(cur, "SELECT COUNT(*) AS count FROM memory_items WHERE source_conversation_id IS NOT NULL AND source_conversation_id != ''")

    conn.close()

    locations = archive_location_status()
    nodes = [
        _node("core-archivist", "Archivist", "core", badges=["Control", "Continuity"], detail="The local continuity system tying the archive together."),
        _node("hub-files", "Files", "archive", count=active_files, size_bytes=active_bytes, badges=["Archive", "Indexed"], detail="Active indexed files available to maintenance and retrieval policy."),
        _node("hub-knowledgebase", "Knowledgebase", "knowledgebase", count=knowledgebase_files, badges=["Reference", "Chat aware"], detail="Reference material indexed distinctly from the personal archive."),
        _node("hub-review", "Review Queue", "review", count=review_files, badges=["Deletion review", "Excluded"], detail="Queued and duplicate-review material retained for audit but excluded from chat retrieval."),
        _node("hub-tags", "Tags", "tag", count=tag_count, badges=["Organization"], detail="Human or agent-assigned labels attached to files."),
        _node("hub-memories", "Memories", "memory", count=memory_count, badges=["Continuity"], detail="Persisted memory items and their statuses."),
        _node("hub-notes", "Notes", "note", count=note_count, badges=["Workspace"], detail="Active workspace notes and saved note cards."),
        _node("hub-clipboard", "Clipboard", "clipboard", count=clipboard_count, badges=["Workspace"], detail="Recent shared clipboard context."),
        _node("hub-conversations", "Chat Threads", "conversation", count=conversation_count, badges=["Dialogue"], detail=f"{message_count:,} chat messages across saved threads."),
        _node("hub-actions", "Action Audit", "action", count=action_count, badges=["Audit"], detail="Confirmed, cancelled, failed, and pending tool actions."),
        _node("hub-sources", "Sources", "source", count=len((locations.get("chat_aware") or []) + (locations.get("chat_ignored") or []) + (locations.get("external_sources") or [])), badges=["Roots"], detail="Configured archive, knowledgebase, ignored, and discovery source slots."),
    ]
    links = [
        _link("core-archivist", "hub-files", "contains", count=active_files),
        _link("core-archivist", "hub-knowledgebase", "references", count=knowledgebase_files),
        _link("core-archivist", "hub-memories", "remembers", count=memory_count),
        _link("core-archivist", "hub-notes", "works-with", count=note_count),
        _link("core-archivist", "hub-conversations", "talks-through", count=conversation_count),
        _link("core-archivist", "hub-actions", "audits", count=action_count),
        _link("core-archivist", "hub-sources", "draws-from"),
        _link("hub-files", "hub-review", "queues", count=queued_reviews),
        _link("hub-files", "hub-tags", "tagged-by", count=tag_count),
        _link("hub-conversations", "hub-memories", "evidence-for", count=memory_conversation_links),
        _link("hub-clipboard", "hub-notes", "captured-as", count=clipboard_note_links),
        _link("hub-notes", "hub-files", "references", count=note_file_links),
    ]

    if duplicate_files:
        duplicate_node = _node("review-duplicates", "Exact Duplicates", "review", count=duplicate_files, badges=["SHA-256"], detail="Files marked as exact duplicates or duplicate review candidates.")
        nodes.append(duplicate_node)
        links.append(_link("hub-review", "review-duplicates", "contains", count=duplicate_files))

    for row in category_rows:
        category = row["category"] or "other"
        node_id = _safe_id("category", category)
        nodes.append(
            _node(
                node_id,
                category.title(),
                "category",
                count=row["count"],
                size_bytes=row["size_bytes"],
                badges=["File type"],
                detail=f"{int(row['count']):,} active files in this category.",
            )
        )
        links.append(_link("hub-files", node_id, "category", count=row["count"]))
        if category == "knowledgebase":
            links.append(_link("hub-knowledgebase", node_id, "indexed-as", count=row["count"]))

    for row in tag_rows:
        tag = row["name"] or "tag"
        node_id = _safe_id("tag", tag)
        nodes.append(_node(node_id, f"#{tag}", "tag", count=row["count"], badges=["Tag"], detail="Top file tag by attached file count."))
        links.append(_link("hub-tags", node_id, "tag", count=row["count"]))

    category_node_ids = {_safe_id("category", row["category"] or "other") for row in category_rows}
    tag_node_ids = {_safe_id("tag", row["name"] or "tag") for row in tag_rows}
    for row in tag_category_rows:
        tag_id = _safe_id("tag", row["name"] or "tag")
        category_id = _safe_id("category", row["category"] or "other")
        if tag_id in tag_node_ids and category_id in category_node_ids:
            links.append(_link(tag_id, category_id, "labels", count=row["count"]))

    for row in memory_status_rows:
        status = row["status"] or "KEEP"
        node_id = _safe_id("memory", status)
        nodes.append(_node(node_id, status, "memory", count=row["count"], badges=["Memory status"], detail="Memory items grouped by reflective status."))
        links.append(_link("hub-memories", node_id, "status", count=row["count"]))

    for row in note_kind_rows:
        kind = row["kind"] or "text"
        node_id = _safe_id("note", kind)
        nodes.append(_node(node_id, kind.title(), "note", count=row["count"], badges=["Note kind"], detail="Active notes grouped by kind."))
        links.append(_link("hub-notes", node_id, "kind", count=row["count"]))

    for row in clipboard_kind_rows:
        kind = row["kind"] or "text"
        node_id = _safe_id("clipboard", kind)
        nodes.append(_node(node_id, kind.title(), "clipboard", count=row["count"], badges=["Clipboard kind"], detail="Clipboard items grouped by kind."))
        links.append(_link("hub-clipboard", node_id, "kind", count=row["count"]))

    for row in action_status_rows:
        status = row["status"] or "unknown"
        node_id = _safe_id("action", status)
        nodes.append(_node(node_id, status.replace("_", " ").title(), "action", count=row["count"], badges=["Action status"], detail="Audited actions grouped by status."))
        links.append(_link("hub-actions", node_id, "status", count=row["count"]))

    source_slots = (locations.get("chat_aware") or []) + (locations.get("chat_ignored") or []) + (locations.get("external_sources") or [])
    for slot in source_slots:
        path = slot.get("path") or ""
        if not path:
            continue
        node_id = f"source-{slot.get('key')}"
        nodes.append(
            _node(
                node_id,
                slot.get("label") or slot.get("key", "Source"),
                "source",
                badges=slot.get("badges") or ["Source"],
                detail=slot.get("policy_reason") or slot.get("chat_policy_label") or "Configured source slot.",
                path=path,
            )
        )
        links.append(_link("hub-sources", node_id, "source"))
        if slot.get("key") == "knowledgebase_root":
            links.append(_link(node_id, "hub-knowledgebase", "feeds", count=knowledgebase_files))
        elif slot.get("chat_policy") == "chat_aware":
            links.append(_link(node_id, "hub-files", "feeds", count=active_files))
        else:
            links.append(_link(node_id, "hub-review" if "review" in path.lower() else "hub-sources", "inventory"))

    return {
        "generated_ts": time.time(),
        "summary": {
            "nodes": len(nodes),
            "links": len(links),
            "files": total_files,
            "active_files": active_files,
            "review_files": review_files,
            "memories": memory_count,
            "notes": note_count,
            "threads": conversation_count,
            "messages": message_count,
            "tags": tag_count,
            "clipboard": clipboard_count,
            "actions": action_count,
        },
        "nodes": nodes,
        "links": links,
        "locations": locations,
    }
