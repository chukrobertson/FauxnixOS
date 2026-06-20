from __future__ import annotations

import json
import os
import re
import shutil
import venv
from pathlib import Path

from app.config import (
    ARCHIVE_DUP_REVIEW_DIR,
    ARCHIVE_INBOX,
    ARCHIVE_REVIEW_DIR,
    ARCHIVE_ROOT,
    DATA_DIR,
    KNOWLEDGEBASE_DIR,
)
from app.db import get_conn
from app.maintenance import (
    MOVED_DUPLICATE_REASON,
    PRE_INDEX_DEDUPE_REASON,
    apply_tag,
    duplicate_groups,
    list_files,
    move_queued_duplicates_to_review,
    queue_deletion,
    queue_deletion_by_path,
    queue_exact_duplicates_for_review,
    remove_tag,
)
from app.notes import list_clipboard, list_notes
from app.utils import clean_filename, ensure_parent, now_ts, path_is_inside, resolve_allowed_path, safe_rel_path, unique_path

PROTECTED_EMPTY_DIRS = {
    ARCHIVE_ROOT.resolve(strict=False),
    ARCHIVE_INBOX.resolve(strict=False),
    ARCHIVE_REVIEW_DIR.resolve(strict=False),
    ARCHIVE_DUP_REVIEW_DIR.resolve(strict=False),
    KNOWLEDGEBASE_DIR.resolve(strict=False),
    DATA_DIR.resolve(strict=False),
}


def operator_help() -> str:
    return """
I can operate on the archive through typed tools now:

- Search files: "find files about garden"
- Queue a file for deletion review: "queue delete E:\\path\\to\\file.pdf"
- Create a folder: "create folder Projects\\My Folder"
- Scaffold a project: "create project named Garden Notes and initialize a .venv"
- Scan empty folders: "remove all empty folders" starts with a dry-run
- Tag indexed files: "tag files about taxes as finance"
- Queue matching files for deletion review: "queue files about temp for deletion review"
- Queue exact duplicates: "queue exact duplicates" starts with a preview
- Show duplicate review status: "duplicate review status"
- Move queued duplicates to review: "move queued duplicates to review" starts with a dry-run
- Restore one reviewed duplicate: "restore duplicate file id 123" starts with a preview
- Review workspace context: "show clipboard" or "show notes"
- Confirm the last dry-run: "confirm" or "confirm action 12"

Physical deletion is not part of this toolbelt. Broad cleanup, tagging, and queueing use audit records and require confirmation.
""".strip()


def audit_action(
    *,
    conversation_id: str,
    tool: str,
    intent: str,
    status: str,
    params: dict | None = None,
    result: dict | None = None,
    requires_confirmation: bool = False,
    error: str | None = None,
) -> int:
    conn = get_conn()
    cur = conn.cursor()
    ts = now_ts()
    cur.execute(
        """
        INSERT INTO action_audit (
            conversation_id, tool, intent, status, requires_confirmation,
            params_json, result_json, created_ts, executed_ts, error
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            conversation_id,
            tool,
            intent,
            status,
            1 if requires_confirmation else 0,
            json.dumps(params or {}),
            json.dumps(result or {}),
            ts,
            ts if status in {"completed", "failed"} else None,
            error,
        ),
    )
    action_id = int(cur.lastrowid)
    conn.commit()
    conn.close()
    return action_id


def update_action(action_id: int, *, status: str, result: dict | None = None, error: str | None = None) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE action_audit
        SET status = ?, result_json = ?, executed_ts = ?, error = ?
        WHERE id = ?
        """,
        (status, json.dumps(result or {}), now_ts(), error, action_id),
    )
    conn.commit()
    conn.close()


def load_action(action_id: int) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM action_audit WHERE id = ?", (action_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    item = dict(row)
    item["params"] = json.loads(item.get("params_json") or "{}")
    item["result"] = json.loads(item.get("result_json") or "{}")
    return item


def latest_pending_action(conversation_id: str) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM action_audit
        WHERE conversation_id = ? AND status = 'pending_confirmation'
        ORDER BY created_ts DESC, id DESC
        LIMIT 1
        """,
        (conversation_id,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    item = dict(row)
    item["params"] = json.loads(item.get("params_json") or "{}")
    item["result"] = json.loads(item.get("result_json") or "{}")
    return item


def recent_actions(limit: int = 40, status: str | None = None, scope: str | None = None) -> list[dict]:
    conn = get_conn()
    cur = conn.cursor()
    clean_status = (status or "").strip()
    clean_scope = (scope or "").strip().lower()
    max_limit = max(1, min(int(limit), 200))
    where = []
    params = []
    if clean_status:
        where.append("status = ?")
        params.append(clean_status)
    if clean_scope == "admin":
        where.append("tool LIKE 'admin.%'")
    elif clean_scope in {"fauxdex", "lab"}:
        where.append("tool NOT LIKE 'admin.%'")
    where_clause = f"WHERE {' AND '.join(where)}" if where else ""
    params.append(max_limit)
    if where_clause:
        cur.execute(
            f"""
            SELECT id, conversation_id, tool, intent, status, requires_confirmation,
                   params_json, result_json, created_ts, executed_ts, error
            FROM action_audit
            {where_clause}
            ORDER BY created_ts DESC, id DESC
            LIMIT ?
            """,
            tuple(params),
        )
    else:
        cur.execute(
            """
            SELECT id, conversation_id, tool, intent, status, requires_confirmation,
                   params_json, result_json, created_ts, executed_ts, error
            FROM action_audit
            ORDER BY created_ts DESC, id DESC
            LIMIT ?
            """,
            (max_limit,),
        )
    rows = []
    for row in cur.fetchall():
        item = dict(row)
        item["params"] = json.loads(item.pop("params_json") or "{}")
        item["result"] = json.loads(item.pop("result_json") or "{}")
        rows.append(item)
    conn.close()
    return rows


def allowed_roots() -> list[Path]:
    return [ARCHIVE_ROOT, KNOWLEDGEBASE_DIR, ARCHIVE_REVIEW_DIR]


def resolve_operator_path(raw_path: str, *, default_root: Path = ARCHIVE_ROOT, allow_create: bool = False) -> Path:
    text = raw_path.strip().strip('"').strip("'")
    candidate = Path(text).expanduser()
    if not candidate.is_absolute() and not candidate.drive:
        candidate = default_root / candidate
    candidate = candidate.resolve(strict=False)
    if allow_create:
        for root in allowed_roots():
            resolved_root = root.resolve(strict=False)
            if candidate == resolved_root or path_is_inside(candidate, resolved_root):
                return candidate
        raise ValueError("Path is outside allowed archive roots")
    return resolve_allowed_path(str(candidate), allowed_roots())


def extract_quoted(text: str) -> str | None:
    match = re.search(r'"([^"]+)"|' + r"'([^']+)'", text)
    if not match:
        return None
    return (match.group(1) or match.group(2) or "").strip()


def extract_path_after(query: str, keywords: list[str]) -> str:
    lower = query.lower()
    for keyword in keywords:
        idx = lower.find(keyword)
        if idx >= 0:
            return query[idx + len(keyword):].strip(" :")
    return ""


def human_file_hits(files: list[dict]) -> str:
    if not files:
        return "I did not find matching indexed files."
    lines = []
    for item in files[:12]:
        size = int(item.get("size_bytes") or 0)
        lines.append(f"- {item.get('name') or Path(item.get('path', '')).name} ({item.get('category') or 'file'}, {size:,} bytes)\n  {item.get('path')}")
    return "\n".join(lines)


def clean_search_term(term: str) -> str:
    return re.sub(r"^(about|matching|for|with)\s+", "", (term or "").strip(), flags=re.I).strip()


def file_sample(files: list[dict], limit: int = 12) -> list[str]:
    sample = []
    for item in files[:limit]:
        sample.append(str(item.get("path") or item.get("display_path") or item.get("name") or ""))
    return [item for item in sample if item]


def file_ids(files: list[dict]) -> list[int]:
    ids = []
    for item in files:
        try:
            ids.append(int(item["id"]))
        except (KeyError, TypeError, ValueError):
            continue
    return ids


def parse_tag_request(query: str) -> tuple[str, str, bool] | None:
    patterns = [
        r"\bremove\s+tag\s+(.+?)\s+from\s+files?\s+(?:about|matching|that match|with)\s+(.+)$",
        r"\btag\s+files?\s+(?:about|matching|that match|with)\s+(.+?)\s+(?:as|with)\s+(.+)$",
        r"\btag\s+search\s+(.+?)\s+(?:as|with)\s+(.+)$",
    ]
    remove = False
    for pattern in patterns:
        match = re.search(pattern, query, re.I)
        if not match:
            continue
        if pattern.startswith(r"\bremove"):
            remove = True
            return match.group(2).strip(), match.group(1).strip().lstrip("#"), remove
        return match.group(1).strip(), match.group(2).strip().lstrip("#"), remove
    return None


def preview_tag_files(query: str, conversation_id: str) -> dict:
    parsed = parse_tag_request(query)
    if not parsed:
        return {
            "handled": True,
            "answer": "Try: `tag files about taxes as finance` or `remove tag finance from files about taxes`.",
        }
    term, tag, remove = parsed
    if not term or not tag:
        return {"handled": True, "answer": "I need both a search term and a tag name."}
    result = list_files(q=term, limit=80, sort="indexed_desc")
    files = result.get("files") or []
    ids = file_ids(files)
    if not ids:
        return {"handled": True, "answer": f"I did not find indexed files matching `{term}`."}
    action_id = audit_action(
        conversation_id=conversation_id,
        tool="file.bulk_tag",
        intent="remove_tag" if remove else "apply_tag",
        status="pending_confirmation",
        requires_confirmation=True,
        params={"file_ids": ids, "tag": tag, "query": term, "remove": remove},
        result={"matched": len(ids), "total": result.get("total", len(ids)), "sample": file_sample(files)},
    )
    verb = "remove" if remove else "apply"
    answer = (
        f"Action #{action_id}: I found {len(ids):,} indexed file(s) matching `{term}`. "
        f"I can {verb} tag `{tag}` after confirmation.\n\n"
        f"Say `confirm action {action_id}` to continue.\n\nSample:\n"
        + "\n".join(f"- {path}" for path in file_sample(files))
    )
    return {"handled": True, "answer": answer, "keyword_hits": files, "operator_action": {"id": action_id, "pending": True}}


def parse_bulk_queue_request(query: str) -> str:
    patterns = [
        r"\bqueue\s+files?\s+(?:about|matching|that match|with)\s+(.+?)\s+(?:for\s+)?(?:deletion|delete)\s+review\b",
        r"\bqueue\s+delete\s+files?\s+(?:about|matching|that match|with)\s+(.+)$",
        r"\bmove\s+files?\s+(?:about|matching|that match|with)\s+(.+?)\s+to\s+(?:the\s+)?deletion\s+queue\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, query, re.I)
        if match:
            return match.group(1).strip()
    return ""


def preview_bulk_queue_delete(query: str, conversation_id: str) -> dict:
    term = parse_bulk_queue_request(query)
    if not term:
        return {"handled": True, "answer": "Try: `queue files about temp for deletion review`."}
    result = list_files(q=term, limit=80, sort="indexed_desc")
    files = [item for item in result.get("files") or [] if not item.get("deleted_candidate")]
    ids = file_ids(files)
    if not ids:
        return {"handled": True, "answer": f"I did not find unqueued indexed files matching `{term}`."}
    action_id = audit_action(
        conversation_id=conversation_id,
        tool="file.bulk_queue_delete",
        intent="queue_deletion_review",
        status="pending_confirmation",
        requires_confirmation=True,
        params={"file_ids": ids, "query": term},
        result={"matched": len(ids), "total": result.get("total", len(ids)), "sample": file_sample(files)},
    )
    answer = (
        f"Action #{action_id}: I found {len(ids):,} unqueued file(s) matching `{term}`.\n\n"
        "This will only queue them for deletion review; it will not physically delete files. "
        f"Say `confirm action {action_id}` to continue.\n\nSample:\n"
        + "\n".join(f"- {path}" for path in file_sample(files))
    )
    return {"handled": True, "answer": answer, "keyword_hits": files, "operator_action": {"id": action_id, "pending": True}}


def preview_exact_duplicate_queue(conversation_id: str) -> dict:
    groups = duplicate_groups(limit=20)
    total = int(groups.get("total") or 0)
    if total <= 0:
        return {"handled": True, "answer": "I do not see any unqueued exact SHA-256 duplicate groups right now."}
    sample = []
    reclaimable = 0
    for group in groups.get("groups") or []:
        reclaimable += int(group.get("reclaimable_bytes") or 0)
        files = group.get("files") or []
        if files:
            sample.append(str(files[-1].get("path") or files[-1].get("display_path") or ""))
    action_id = audit_action(
        conversation_id=conversation_id,
        tool="file.queue_exact_duplicates",
        intent="queue_exact_duplicates",
        status="pending_confirmation",
        requires_confirmation=True,
        params={},
        result={"groups": total, "sample": sample[:12], "preview_reclaimable_bytes": reclaimable},
    )
    answer = (
        f"Action #{action_id}: I found {total:,} unqueued exact duplicate group(s). "
        "I can queue duplicate copies for deletion review while keeping one candidate per hash.\n\n"
        f"Say `confirm action {action_id}` to continue.\n\nSample duplicate paths:\n"
        + "\n".join(f"- {path}" for path in sample[:12])
    )
    return {"handled": True, "answer": answer, "operator_action": {"id": action_id, "pending": True}}


def show_clipboard(conversation_id: str) -> dict:
    items = list_clipboard(limit=10)
    action_id = audit_action(
        conversation_id=conversation_id,
        tool="workspace.clipboard",
        intent="show_clipboard",
        status="completed",
        result={"count": len(items)},
    )
    if not items:
        return {"handled": True, "answer": f"Action #{action_id}: clipboard is empty.", "operator_action": {"id": action_id}}
    lines = []
    for item in items:
        body = item.get("content") or item.get("file_path") or item.get("original_name") or ""
        lines.append(f"- #{item['id']} {item.get('kind') or 'text'}: {body[:180]}")
    return {"handled": True, "answer": f"Action #{action_id}: recent clipboard items:\n" + "\n".join(lines), "operator_action": {"id": action_id}}


def show_notes(conversation_id: str) -> dict:
    notes = list_notes(status="active", limit=12)
    action_id = audit_action(
        conversation_id=conversation_id,
        tool="workspace.notes",
        intent="show_notes",
        status="completed",
        result={"count": len(notes)},
    )
    if not notes:
        return {"handled": True, "answer": f"Action #{action_id}: no active notes yet.", "operator_action": {"id": action_id}}
    lines = []
    for note in notes:
        body = note.get("content") or note.get("file_path") or ""
        lines.append(f"- #{note['id']} {note.get('title') or 'Untitled'}: {body[:180]}")
    return {"handled": True, "answer": f"Action #{action_id}: active notes:\n" + "\n".join(lines), "operator_action": {"id": action_id}}


def duplicate_review_summary() -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) AS count, COALESCE(SUM(size_bytes), 0) AS bytes
        FROM files
        WHERE notes = ?
        """,
        (MOVED_DUPLICATE_REASON,),
    )
    moved = dict(cur.fetchone())
    cur.execute(
        """
        SELECT COUNT(*) AS count, COALESCE(SUM(size_bytes), 0) AS bytes
        FROM files
        WHERE deleted_candidate = 1
          AND notes = ?
          AND path NOT LIKE ?
        """,
        (PRE_INDEX_DEDUPE_REASON, f"{str(ARCHIVE_DUP_REVIEW_DIR)}%"),
    )
    pending = dict(cur.fetchone())
    cur.execute("SELECT COUNT(*) AS count FROM deletion_reviews WHERE status = 'queued'")
    queued_reviews = int(cur.fetchone()["count"] or 0)
    cur.execute(
        """
        SELECT id, path, duplicate_of, size_bytes
        FROM files
        WHERE notes = ?
        ORDER BY indexed_ts DESC, id DESC
        LIMIT 8
        """,
        (MOVED_DUPLICATE_REASON,),
    )
    sample = [dict(row) for row in cur.fetchall()]
    conn.close()
    return {
        "review_count": int(moved.get("count") or 0),
        "review_bytes": int(moved.get("bytes") or 0),
        "pending_move_count": int(pending.get("count") or 0),
        "pending_move_bytes": int(pending.get("bytes") or 0),
        "queued_deletion_reviews": queued_reviews,
        "review_dir": str(ARCHIVE_DUP_REVIEW_DIR),
        "sample": sample,
    }


def show_duplicate_review_status(conversation_id: str) -> dict:
    summary = duplicate_review_summary()
    action_id = audit_action(
        conversation_id=conversation_id,
        tool="file.duplicate_review_status",
        intent="duplicate_review_status",
        status="completed",
        result=summary,
    )
    lines = [
        f"Action #{action_id}: duplicate review status:",
        f"- Review folder rows: {summary['review_count']:,} ({summary['review_bytes']:,} bytes)",
        f"- Queued duplicates still outside review: {summary['pending_move_count']:,} ({summary['pending_move_bytes']:,} bytes)",
        f"- Active deletion review queue rows: {summary['queued_deletion_reviews']:,}",
        f"- Review folder: {summary['review_dir']}",
    ]
    if summary["sample"]:
        lines.append("\nRecent reviewed duplicates:")
        lines.extend(f"- file id {item['id']}: {item['path']}" for item in summary["sample"][:6])
    return {"handled": True, "answer": "\n".join(lines), "operator_action": {"id": action_id}}


def preview_move_queued_duplicates(conversation_id: str) -> dict:
    result = move_queued_duplicates_to_review(dry_run=True, remove_empty_folders=True)
    planned = int(result.get("planned") or 0)
    if planned <= 0:
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="file.move_queued_duplicates_review",
            intent="move_queued_duplicates_review",
            status="completed",
            result=result,
        )
        return {
            "handled": True,
            "answer": f"Action #{action_id}: no queued pre-index duplicates need moving into review.",
            "operator_action": {"id": action_id},
        }
    action_id = audit_action(
        conversation_id=conversation_id,
        tool="file.move_queued_duplicates_review",
        intent="move_queued_duplicates_review",
        status="pending_confirmation",
        requires_confirmation=True,
        params={"remove_empty_folders": True},
        result=result,
    )
    answer = (
        f"Action #{action_id}: I can move {planned:,} queued duplicate file(s) into duplicate review.\n"
        f"Review size: {int(result.get('reclaimable_bytes') or 0):,} bytes.\n"
        f"Review folder: {result.get('review_dir')}\n\n"
        f"Say `confirm action {action_id}` to move them. This does not permanently delete files."
    )
    sample = result.get("sample") or []
    if sample:
        answer += "\n\nSample:\n" + "\n".join(f"- {item.get('from')} -> {item.get('to')}" for item in sample[:8])
    return {"handled": True, "answer": answer, "operator_action": {"id": action_id, "pending": True}}


def extract_file_id(query: str) -> int | None:
    match = re.search(r"\b(?:file\s*)?(?:id\s*)?#?(\d+)\b", query, re.I)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def duplicate_review_file_from_query(query: str) -> dict | None:
    file_id = extract_file_id(query)
    conn = get_conn()
    cur = conn.cursor()
    if file_id:
        cur.execute("SELECT * FROM files WHERE id = ? AND notes = ?", (file_id, MOVED_DUPLICATE_REASON))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    path_text = extract_quoted(query) or extract_path_after(
        query,
        ["restore duplicate file", "restore duplicate", "restore reviewed duplicate", "restore from duplicate review"],
    )
    if path_text:
        try:
            path = resolve_operator_path(path_text, default_root=ARCHIVE_DUP_REVIEW_DIR)
        except Exception:
            path = (ARCHIVE_DUP_REVIEW_DIR / path_text).resolve(strict=False)
        cur.execute("SELECT * FROM files WHERE path = ? AND notes = ?", (str(path), MOVED_DUPLICATE_REASON))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    cur.execute(
        """
        SELECT *
        FROM files
        WHERE notes = ?
        ORDER BY indexed_ts DESC, id DESC
        LIMIT 1
        """,
        (MOVED_DUPLICATE_REASON,),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def planned_duplicate_restore(row: dict) -> dict:
    source = Path(row["path"]).resolve(strict=False)
    review_root = ARCHIVE_DUP_REVIEW_DIR.resolve(strict=False)
    if source != review_root and not path_is_inside(source, review_root):
        raise ValueError("Selected file is not inside duplicate review")
    rel = source.relative_to(review_root)
    requested_dest = ARCHIVE_ROOT / rel
    dest = unique_path(requested_dest)
    return {
        "file_id": int(row["id"]),
        "source": str(source),
        "requested_dest": str(requested_dest),
        "dest": str(dest),
        "conflict": requested_dest.exists(),
        "duplicate_of": row.get("duplicate_of"),
        "size_bytes": int(row.get("size_bytes") or 0),
    }


def preview_restore_duplicate(query: str, conversation_id: str) -> dict:
    row = duplicate_review_file_from_query(query)
    if not row:
        summary = duplicate_review_summary()
        sample = summary.get("sample") or []
        answer = "I could not find that reviewed duplicate."
        if sample:
            answer += "\n\nTry one of these file ids:\n" + "\n".join(f"- file id {item['id']}: {item['path']}" for item in sample[:6])
        return {"handled": True, "answer": answer}
    try:
        plan = planned_duplicate_restore(row)
    except Exception as e:
        return {"handled": True, "answer": f"I could not prepare a restore preview. {e}"}
    action_id = audit_action(
        conversation_id=conversation_id,
        tool="file.restore_duplicate_review",
        intent="restore_duplicate_review",
        status="pending_confirmation",
        requires_confirmation=True,
        params=plan,
        result=plan,
    )
    conflict = " Destination exists, so I will use the unique destination shown below." if plan["conflict"] else ""
    answer = (
        f"Action #{action_id}: restore preview for reviewed duplicate file id {plan['file_id']}.{conflict}\n\n"
        f"From: {plan['source']}\n"
        f"To: {plan['dest']}\n"
        f"Duplicate of: {plan.get('duplicate_of') or '[unknown]'}\n\n"
        f"Say `confirm action {action_id}` to restore it. This will not overwrite an existing file."
    )
    return {"handled": True, "answer": answer, "operator_action": {"id": action_id, "pending": True}}


def execute_restore_duplicate(action: dict) -> dict:
    params = action.get("params") or {}
    file_id = int(params.get("file_id") or 0)
    source = Path(str(params.get("source") or "")).resolve(strict=False)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"Reviewed duplicate no longer exists: {source}")
    review_root = ARCHIVE_DUP_REVIEW_DIR.resolve(strict=False)
    if source != review_root and not path_is_inside(source, review_root):
        raise ValueError("Selected file is not inside duplicate review")
    requested_dest = Path(str(params.get("requested_dest") or params.get("dest") or "")).resolve(strict=False)
    archive_root = ARCHIVE_ROOT.resolve(strict=False)
    if requested_dest != archive_root and not path_is_inside(requested_dest, archive_root):
        raise ValueError("Restore destination is outside the archive root")
    dest = unique_path(requested_dest)
    ensure_parent(dest)
    shutil.move(str(source), str(dest))
    conn = get_conn()
    cur = conn.cursor()
    ts = now_ts()
    cur.execute(
        """
        UPDATE files
        SET path = ?, rel_path = ?, suggested_folder = ?, deleted_candidate = 0,
            notes = ?, indexed_ts = ?
        WHERE id = ?
        """,
        (
            str(dest),
            safe_rel_path(dest, ARCHIVE_ROOT),
            "Restored from duplicate review",
            "Restored from duplicate review; duplicate relationship preserved for audit",
            ts,
            file_id,
        ),
    )
    cur.execute(
        """
        UPDATE deletion_reviews
        SET status = 'restored', path = ?, updated_ts = ?
        WHERE file_id = ? AND status = 'queued'
        """,
        (str(dest), ts, file_id),
    )
    conn.commit()
    conn.close()
    try:
        from app.chat_engine import sync_file_embedding_by_id

        embedding_result = sync_file_embedding_by_id(file_id)
    except Exception as e:
        embedding_result = {"synced": False, "error": str(e)}
    return {"restored": 1, "file_id": file_id, "from": str(source), "to": str(dest), "embedding": embedding_result}


def search_files(query: str, conversation_id: str) -> dict:
    term = extract_path_after(query, ["find files", "find file", "search files", "search file", "list files"]).strip()
    term = clean_search_term(term or query)
    result = list_files(q=term, limit=12, sort="indexed_desc")
    action_id = audit_action(
        conversation_id=conversation_id,
        tool="file.search",
        intent="search_files",
        status="completed",
        params={"query": term},
        result={"total": result.get("total", 0)},
    )
    answer = f"Action #{action_id}: I searched indexed files for `{term}`.\n\n{human_file_hits(result.get('files') or [])}"
    return {"handled": True, "answer": answer, "keyword_hits": result.get("files") or [], "operator_action": {"id": action_id}}


def queue_delete(query: str, conversation_id: str) -> dict:
    path_text = extract_quoted(query) or extract_path_after(
        query,
        ["queue delete", "queue for deletion", "move to deletion queue", "delete review", "queue deletion"],
    )
    if not path_text:
        return {"handled": True, "answer": "Which file path should I queue for deletion review?"}
    try:
        path = resolve_operator_path(path_text)
        result = queue_deletion_by_path(str(path), "Queued by chat file operator")
        status = "completed" if result.get("queued") else "failed"
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="file.queue_delete",
            intent="queue_delete",
            status=status,
            params={"path": str(path)},
            result=result,
            error=None if result.get("queued") else "File is not in the current index",
        )
        if result.get("queued"):
            answer = f"Action #{action_id}: queued this file for deletion review:\n{path}"
        else:
            answer = f"Action #{action_id}: I found the path, but it is not in the current index yet:\n{path}"
    except Exception as e:
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="file.queue_delete",
            intent="queue_delete",
            status="failed",
            params={"path": path_text},
            error=str(e),
        )
        answer = f"Action #{action_id}: I could not queue that file. {e}"
    return {"handled": True, "answer": answer, "operator_action": {"id": action_id}}


def create_folder(query: str, conversation_id: str) -> dict:
    folder_text = extract_quoted(query) or extract_path_after(query, ["create folder", "make folder", "create directory", "make directory"])
    if not folder_text:
        return {"handled": True, "answer": "What folder should I create inside the archive?"}
    try:
        target = resolve_operator_path(folder_text, allow_create=True)
        target.mkdir(parents=True, exist_ok=True)
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="file.create_folder",
            intent="create_folder",
            status="completed",
            params={"path": str(target)},
            result={"created": str(target)},
        )
        answer = f"Action #{action_id}: created folder:\n{target}"
    except Exception as e:
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="file.create_folder",
            intent="create_folder",
            status="failed",
            params={"path": folder_text},
            error=str(e),
        )
        answer = f"Action #{action_id}: I could not create that folder. {e}"
    return {"handled": True, "answer": answer, "operator_action": {"id": action_id}}


def project_root() -> Path:
    candidates = [ARCHIVE_ROOT / "03-Projects", ARCHIVE_ROOT / "Projects", ARCHIVE_ROOT / "projects"]
    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_dir():
                return candidate
        except OSError:
            continue
    return ARCHIVE_ROOT / "Projects"


def extract_project_name(query: str) -> str:
    quoted = extract_quoted(query)
    if quoted:
        return quoted
    match = re.search(r"(?:named|called)\s+(.+?)(?:\s+and\s+|\s+with\s+|$)", query, re.I)
    if match:
        return match.group(1).strip()
    match = re.search(r"create\s+(?:a\s+)?project(?:\s+folder)?\s+(.+?)(?:\s+and\s+|\s+with\s+|$)", query, re.I)
    if match:
        name = match.group(1).strip()
        if name and name.lower() not in {"in projects", "in the projects folder"}:
            return name
    return ""


def scaffold_project(query: str, conversation_id: str) -> dict:
    name = extract_project_name(query)
    if not name:
        return {
            "handled": True,
            "answer": "What should I name the project folder? Try: `create project named My Project and initialize a .venv`.",
        }
    safe_name = clean_filename(name)
    root = project_root()
    try:
        target = resolve_operator_path(str(root / safe_name), allow_create=True)
        target.mkdir(parents=True, exist_ok=True)
        files = {
            "README.md": f"# {safe_name}\n\nProject notes and setup.\n",
            "notes.md": f"# {safe_name} Notes\n\n",
            ".gitignore": ".venv/\n__pycache__/\n*.pyc\n.env\n",
        }
        for filename, content in files.items():
            path = target / filename
            if not path.exists():
                path.write_text(content, encoding="utf-8")
        venv_path = target / ".venv"
        if ".venv" in query.lower() and not venv_path.exists():
            venv.EnvBuilder(with_pip=True).create(venv_path)
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="project.scaffold",
            intent="scaffold_project",
            status="completed",
            params={"name": name, "path": str(target), "venv": ".venv" in query.lower()},
            result={"path": str(target), "venv_path": str(venv_path) if venv_path.exists() else None},
        )
        answer = f"Action #{action_id}: created project workspace:\n{target}"
        if venv_path.exists():
            answer += f"\n\nInitialized virtual environment:\n{venv_path}"
    except Exception as e:
        action_id = audit_action(
            conversation_id=conversation_id,
            tool="project.scaffold",
            intent="scaffold_project",
            status="failed",
            params={"name": name},
            error=str(e),
        )
        answer = f"Action #{action_id}: I could not scaffold that project. {e}"
    return {"handled": True, "answer": answer, "operator_action": {"id": action_id}}


def empty_dirs(root: Path = ARCHIVE_ROOT, *, limit: int = 10000) -> list[Path]:
    found: list[Path] = []
    for current, dirs, files in os.walk(root, topdown=False, onerror=lambda _: None):
        path = Path(current).resolve(strict=False)
        if path in PROTECTED_EMPTY_DIRS:
            continue
        if any(path == protected or path_is_inside(protected, path) for protected in PROTECTED_EMPTY_DIRS):
            continue
        try:
            if not any(path.iterdir()):
                found.append(path)
                if len(found) >= limit:
                    break
        except OSError:
            continue
    return found


def dry_run_empty_folder_cleanup(conversation_id: str) -> dict:
    paths = empty_dirs()
    sample = [str(path) for path in paths[:20]]
    action_id = audit_action(
        conversation_id=conversation_id,
        tool="file.remove_empty_folders",
        intent="remove_empty_folders",
        status="pending_confirmation",
        requires_confirmation=True,
        params={"root": str(ARCHIVE_ROOT)},
        result={"count": len(paths), "sample": sample},
    )
    answer = (
        f"Action #{action_id}: I found {len(paths):,} empty folder(s) under the archive root.\n\n"
        "I have not removed anything yet. Say `confirm` or "
        f"`confirm action {action_id}` to remove the currently empty folders.\n\n"
    )
    if sample:
        answer += "Sample:\n" + "\n".join(f"- {item}" for item in sample)
    return {"handled": True, "answer": answer, "operator_action": {"id": action_id, "pending": True}}


def execute_empty_folder_cleanup(action: dict) -> dict:
    paths = empty_dirs()
    removed = 0
    failed: list[dict] = []
    for path in paths:
        try:
            path.rmdir()
            removed += 1
        except OSError as e:
            failed.append({"path": str(path), "error": str(e)})
    return {"removed": removed, "failed": len(failed), "failures": failed[:20]}


def execute_pending_action(action: dict) -> dict:
    if action["status"] != "pending_confirmation":
        return {
            "handled": True,
            "answer": f"Action #{action['id']} is not pending confirmation.",
            "operator_action": {"id": int(action["id"])},
        }

    if action["tool"] == "file.remove_empty_folders":
        result = execute_empty_folder_cleanup(action)
        update_action(int(action["id"]), status="completed", result=result)
        answer = (
            f"Action #{action['id']}: removed {result['removed']:,} empty folder(s). "
            f"{result['failed']:,} folder(s) could not be removed because they were no longer empty or were inaccessible."
        )
        if result["failures"]:
            answer += "\n\nFirst issues:\n" + "\n".join(f"- {item['path']}: {item['error']}" for item in result["failures"])
        return {"handled": True, "answer": answer, "operator_action": {"id": int(action["id"])}}

    if action["tool"] == "file.bulk_tag":
        params = action.get("params") or {}
        ids = [int(item) for item in params.get("file_ids") or []]
        tag = str(params.get("tag") or "")
        if params.get("remove"):
            result = remove_tag(ids, tag)
            verb = "removed"
            count = result.get("removed", 0)
        else:
            result = apply_tag(ids, tag)
            verb = "applied"
            count = result.get("applied", 0)
        update_action(int(action["id"]), status="completed", result=result)
        return {
            "handled": True,
            "answer": f"Action #{action['id']}: {verb} tag `{tag}` on {count:,} file(s).",
            "operator_action": {"id": int(action["id"])},
        }

    if action["tool"] == "file.bulk_queue_delete":
        params = action.get("params") or {}
        ids = [int(item) for item in params.get("file_ids") or []]
        result = queue_deletion(ids, "Queued by confirmed chat bulk operation")
        update_action(int(action["id"]), status="completed", result=result)
        return {
            "handled": True,
            "answer": f"Action #{action['id']}: queued {int(result.get('queued') or 0):,} file(s) for deletion review.",
            "operator_action": {"id": int(action["id"])},
        }

    if action["tool"] == "file.queue_exact_duplicates":
        result = queue_exact_duplicates_for_review()
        update_action(int(action["id"]), status="completed", result=result)
        return {
            "handled": True,
            "answer": (
                f"Action #{action['id']}: queued {int(result.get('queued') or 0):,} exact duplicate file(s) "
                f"across {int(result.get('groups') or 0):,} group(s) for deletion review."
            ),
            "operator_action": {"id": int(action["id"])},
        }

    if action["tool"] == "file.move_queued_duplicates_review":
        params = action.get("params") or {}
        try:
            result = move_queued_duplicates_to_review(
                dry_run=False,
                remove_empty_folders=bool(params.get("remove_empty_folders", True)),
            )
            update_action(int(action["id"]), status="completed", result=result)
            return {
                "handled": True,
                "answer": (
                    f"Action #{action['id']}: moved {int(result.get('moved') or 0):,} duplicate file(s) "
                    f"into review. Missing {int(result.get('missing') or 0):,}; failed {int(result.get('failed') or 0):,}; "
                    f"empty folders removed {int(result.get('empty_folders_removed') or 0):,}."
                ),
                "operator_action": {"id": int(action["id"])},
            }
        except Exception as e:
            update_action(int(action["id"]), status="failed", result=action.get("result") or {}, error=str(e))
            return {"handled": True, "answer": f"Action #{action['id']}: duplicate move failed. {e}", "operator_action": {"id": int(action["id"])}}

    if action["tool"] == "file.restore_duplicate_review":
        try:
            result = execute_restore_duplicate(action)
            update_action(int(action["id"]), status="completed", result=result)
            return {
                "handled": True,
                "answer": f"Action #{action['id']}: restored reviewed duplicate file id {result['file_id']}.\n{result['to']}",
                "operator_action": {"id": int(action["id"])},
            }
        except Exception as e:
            update_action(int(action["id"]), status="failed", result=action.get("result") or {}, error=str(e))
            return {"handled": True, "answer": f"Action #{action['id']}: restore failed. {e}", "operator_action": {"id": int(action["id"])}}

    return {
        "handled": True,
        "answer": f"Action #{action['id']} cannot be executed by this confirmation handler yet.",
        "operator_action": {"id": int(action["id"])},
    }


def confirm_action_by_id(action_id: int) -> dict:
    action = load_action(action_id)
    if not action:
        return {"handled": True, "answer": f"Action #{action_id} was not found.", "operator_action": {"id": action_id}}
    return execute_pending_action(action)


def cancel_action_by_id(action_id: int) -> dict:
    action = load_action(action_id)
    if not action:
        return {"handled": True, "answer": f"Action #{action_id} was not found.", "operator_action": {"id": action_id}}
    if action["status"] != "pending_confirmation":
        return {
            "handled": True,
            "answer": f"Action #{action_id} is not pending confirmation.",
            "operator_action": {"id": action_id},
        }
    update_action(action_id, status="cancelled", result=action.get("result") or {})
    return {
        "handled": True,
        "answer": f"Action #{action_id}: cancelled. No filesystem changes were made.",
        "operator_action": {"id": action_id},
    }


def cancel_action(query: str, conversation_id: str) -> dict:
    match = re.search(r"cancel\s+action\s+#?(\d+)", query, re.I)
    action = load_action(int(match.group(1))) if match else latest_pending_action(conversation_id)
    if not action:
        return {"handled": True, "answer": "I do not have a pending file operation to cancel."}
    return cancel_action_by_id(int(action["id"]))


def confirm_action(query: str, conversation_id: str) -> dict:
    match = re.search(r"confirm\s+action\s+#?(\d+)", query, re.I)
    action = load_action(int(match.group(1))) if match else latest_pending_action(conversation_id)
    if not action:
        return {"handled": True, "answer": "I do not have a pending file operation to confirm."}
    if not str(action.get("tool") or "").startswith(("file.", "project.", "workspace.")):
        return {"handled": False}
    return execute_pending_action(action)


def maybe_handle_file_operator(query: str, conversation_id: str) -> dict:
    lowered = query.lower().strip()
    if lowered in {"operator help", "file operator help", "what tools can you use", "what can you do with files"}:
        return {"handled": True, "answer": operator_help()}
    if lowered in {"cancel", "cancel last action", "cancel pending action"} or lowered.startswith("cancel action"):
        return cancel_action(query, conversation_id)
    if lowered in {"confirm", "confirm last action", "do it", "yes do it"} or lowered.startswith("confirm action"):
        return confirm_action(query, conversation_id)
    if any(phrase in lowered for phrase in ["show clipboard", "list clipboard", "what is in clipboard", "what's in clipboard"]):
        return show_clipboard(conversation_id)
    if any(phrase in lowered for phrase in ["show notes", "list notes", "what notes", "what are my notes"]):
        return show_notes(conversation_id)
    if any(phrase in lowered for phrase in ["duplicate review status", "duplicates review status", "duplicate queue status", "review duplicate status"]):
        return show_duplicate_review_status(conversation_id)
    if re.search(r"\b(move|stage)\b.*\bqueued duplicates?\b.*\breview\b", lowered) or re.search(r"\bmove\b.*\bduplicate.*\breview\b", lowered):
        return preview_move_queued_duplicates(conversation_id)
    if re.search(r"\brestore\b.*\b(duplicate|review)\b", lowered):
        return preview_restore_duplicate(query, conversation_id)
    if re.search(r"\b(remove|delete|clean up|cleanup)\b.*\bempty folders?\b", lowered):
        if any(word in lowered for word in ["confirm", "do it now", "execute"]):
            return confirm_action(query, conversation_id)
        return dry_run_empty_folder_cleanup(conversation_id)
    if re.search(r"\bqueue\s+exact\s+dupes?\b|\bqueue\s+exact\s+duplicates?\b|\bqueue\s+all\s+exact\s+duplicates?\b", lowered):
        return preview_exact_duplicate_queue(conversation_id)
    if parse_bulk_queue_request(query):
        return preview_bulk_queue_delete(query, conversation_id)
    if parse_tag_request(query):
        return preview_tag_files(query, conversation_id)
    if re.search(r"\b(create|make)\b.*\bproject\b", lowered):
        return scaffold_project(query, conversation_id)
    if re.search(r"\b(create|make)\b.*\b(folder|directory)\b", lowered):
        return create_folder(query, conversation_id)
    if any(phrase in lowered for phrase in ["queue delete", "queue for deletion", "move to deletion queue", "delete review", "queue deletion"]):
        return queue_delete(query, conversation_id)
    if lowered.startswith(("find files", "find file", "search files", "search file", "list files")):
        return search_files(query, conversation_id)
    return {"handled": False}
