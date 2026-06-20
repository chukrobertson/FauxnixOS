from __future__ import annotations

import json

from app.db import get_conn
from app.utils import now_ts


VALID_STATUSES = {"queued", "active", "blocked", "paused", "done"}
VALID_PRIORITIES = {"high", "medium", "low"}
STATUS_ORDER = {"active": 0, "queued": 1, "blocked": 2, "paused": 3, "done": 4}
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


SEED_TASKS = [
    {
        "title": "Add model-authored unified diff retry loop",
        "description": "Teach Intelligent Admin to request a model-authored unified diff, validate it, feed validation failures back into retry prompts, and stop before apply gates.",
        "priority": "high",
        "recommended_tools": ["admin.patch_proposal", "admin.diff_validation", "admin.patch_snapshot", "admin.apply_readiness", "admin.verification_checks"],
        "verification": ["Invalid diffs produce retry feedback.", "Valid diffs remain pending until snapshot/readiness/apply confirmation.", "No model-authored diff applies without explicit gates."],
        "rollback": ["Disable model-authored diff proposals from the Admin tool catalog.", "Keep existing manual unified-diff apply and rollback paths intact."],
    },
    {
        "title": "Add guarded Admin command runner",
        "description": "Expose a small allowlisted command runner for checks that Intelligent Admin can execute without arbitrary shell access.",
        "priority": "high",
        "recommended_tools": ["admin.verification_checks", "admin.codebase_inspection"],
        "verification": ["Allowed commands reject unknown binaries.", "Command output is stored in action_audit.", "UI shows pass/fail without hanging the app."],
        "rollback": ["Disable the runner by removing it from the Admin tool catalog.", "Keep command execution fixed to explicit specs."],
    },
    {
        "title": "Create Admin project memory ledger",
        "description": "Persist ArchivistOS development decisions, blockers, next tasks, and definitions separately from personal archive memory.",
        "priority": "medium",
        "recommended_tools": ["admin.project_brief", "admin.codex_handoff", "admin.self_development_status"],
        "verification": ["Admin project memory can be listed without archive search.", "Personal memories are not mixed into technical status.", "Handoff includes active blockers and latest task ids."],
        "rollback": ["Keep records in a separate table or file namespace.", "Allow pausing the ledger from the Admin UI."],
    },
    {
        "title": "Connect task queue to patch proposals",
        "description": "Let a development task own its proposal action id, validation action id, snapshot action id, readiness report, and verification results.",
        "priority": "medium",
        "recommended_tools": ["admin.patch_proposal", "admin.diff_validation", "admin.patch_snapshot", "admin.apply_readiness"],
        "verification": ["Task detail shows linked audit actions.", "Next task chooses the highest priority non-done task.", "Status updates preserve audit ids."],
        "rollback": ["Tasks can be marked paused or blocked without deleting history.", "Linked action ids remain read-only references."],
    },
]


def _json_list(value) -> list:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _clean_status(status: str | None, fallback: str = "queued") -> str:
    clean = (status or fallback).strip().lower()
    return clean if clean in VALID_STATUSES else fallback


def _clean_priority(priority: str | None, fallback: str = "medium") -> str:
    clean = (priority or fallback).strip().lower()
    return clean if clean in VALID_PRIORITIES else fallback


def _default_tools(title: str, description: str) -> list[str]:
    text = f"{title} {description}".lower()
    tools = ["admin.project_brief"]
    if any(word in text for word in ["patch", "apply", "diff"]):
        tools.extend(["admin.patch_proposal", "admin.diff_validation", "admin.patch_snapshot", "admin.apply_readiness"])
    if any(word in text for word in ["verify", "test", "check", "command"]):
        tools.append("admin.verification_checks")
    if any(word in text for word in ["inspect", "code", "source", "module"]):
        tools.append("admin.codebase_inspection")
    return list(dict.fromkeys(tools))


def _default_verification(title: str, description: str) -> list[str]:
    tools = _default_tools(title, description)
    checks = []
    if "admin.verification_checks" in tools:
        checks.extend(["Run fixed Admin verification checks.", "Review action audit output for failures."])
    if "admin.patch_proposal" in tools:
        checks.extend(["Validate draft hunks against current files.", "Snapshot affected files before any apply step."])
    return checks or ["Confirm affected files and update this task with verification notes."]


def _default_rollback(title: str, description: str) -> list[str]:
    if "patch" in f"{title} {description}".lower():
        return ["Use the pre-apply snapshot manifest to restore touched files.", "Re-run fixed verification after rollback."]
    return ["Mark the task paused or blocked and keep audit history intact."]


def _row_to_task(row) -> dict:
    item = dict(row)
    item["plan"] = _json_list(item.pop("plan_json", None))
    item["recommended_tools"] = _json_list(item.pop("recommended_tools_json", None))
    item["verification"] = _json_list(item.pop("verification_json", None))
    item["rollback"] = _json_list(item.pop("rollback_json", None))
    return item


def _task_exists(title: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM admin_development_tasks WHERE lower(title) = lower(?) LIMIT 1", (title.strip(),))
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def create_development_task(
    *,
    title: str,
    description: str | None = None,
    priority: str = "medium",
    status: str = "queued",
    source: str = "manual",
    recommended_tools: list[str] | None = None,
    verification: list[str] | None = None,
    rollback: list[str] | None = None,
    last_action_id: int | None = None,
) -> dict:
    clean_title = (title or "").strip()
    if len(clean_title) < 3:
        raise ValueError("Development task title is too short.")
    clean_description = (description or "").strip()
    now = now_ts()
    tools = recommended_tools or _default_tools(clean_title, clean_description)
    checks = verification or _default_verification(clean_title, clean_description)
    rollback_steps = rollback or _default_rollback(clean_title, clean_description)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO admin_development_tasks (
            title, description, status, priority, source, plan_json,
            recommended_tools_json, verification_json, rollback_json,
            notes, last_action_id, created_ts, updated_ts
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            clean_title,
            clean_description,
            _clean_status(status),
            _clean_priority(priority),
            source or "manual",
            json.dumps([]),
            json.dumps(tools),
            json.dumps(checks),
            json.dumps(rollback_steps),
            "",
            last_action_id,
            now,
            now,
        ),
    )
    task_id = int(cur.lastrowid)
    conn.commit()
    conn.close()
    task = get_development_task(task_id)
    if not task:
        raise ValueError("Development task was not created.")
    return task


def update_development_task(
    task_id: int,
    *,
    status: str | None = None,
    priority: str | None = None,
    notes: str | None = None,
    last_action_id: int | None = None,
) -> dict:
    task = get_development_task(task_id)
    if not task:
        raise ValueError(f"Development task #{task_id} was not found.")
    next_status = _clean_status(status, task["status"]) if status is not None else task["status"]
    next_priority = _clean_priority(priority, task["priority"]) if priority is not None else task["priority"]
    next_notes = task.get("notes") or ""
    if notes is not None:
        next_notes = notes.strip()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE admin_development_tasks
        SET status = ?, priority = ?, notes = ?, last_action_id = COALESCE(?, last_action_id), updated_ts = ?
        WHERE id = ?
        """,
        (next_status, next_priority, next_notes, last_action_id, now_ts(), task_id),
    )
    conn.commit()
    conn.close()
    updated = get_development_task(task_id)
    if not updated:
        raise ValueError(f"Development task #{task_id} was not found.")
    return updated


def attach_action_to_task(task_id: int, action_id: int) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE admin_development_tasks SET last_action_id = ?, updated_ts = ? WHERE id = ?",
        (action_id, now_ts(), task_id),
    )
    conn.commit()
    conn.close()


def get_development_task(task_id: int) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM admin_development_tasks WHERE id = ?", (task_id,))
    row = cur.fetchone()
    conn.close()
    return _row_to_task(row) if row else None


def list_development_tasks(limit: int = 40, status: str | None = None) -> list[dict]:
    clean_status = (status or "").strip().lower()
    max_limit = max(1, min(int(limit or 40), 200))
    conn = get_conn()
    cur = conn.cursor()
    if clean_status in VALID_STATUSES:
        cur.execute(
            """
            SELECT * FROM admin_development_tasks
            WHERE status = ?
            ORDER BY updated_ts DESC, id DESC
            LIMIT ?
            """,
            (clean_status, max_limit),
        )
    else:
        cur.execute("SELECT * FROM admin_development_tasks ORDER BY updated_ts DESC, id DESC LIMIT ?", (max_limit,))
    rows = [_row_to_task(row) for row in cur.fetchall()]
    conn.close()
    return sorted(
        rows,
        key=lambda item: (
            STATUS_ORDER.get(item.get("status"), 9),
            PRIORITY_ORDER.get(item.get("priority"), 9),
            item.get("id") or 0,
        ),
    )


def next_development_task() -> dict | None:
    tasks = [task for task in list_development_tasks(100) if task.get("status") in {"active", "queued", "blocked"}]
    return tasks[0] if tasks else None


def seed_development_tasks() -> dict:
    created = []
    skipped = []
    for seed in SEED_TASKS:
        if _task_exists(seed["title"]):
            skipped.append(seed["title"])
            continue
        created.append(create_development_task(source="seed", **seed))
    return {"created": created, "skipped": skipped, "total": len(list_development_tasks(200))}


def development_task_summary() -> dict:
    tasks = list_development_tasks(200)
    by_status = {}
    for task in tasks:
        by_status[task["status"]] = by_status.get(task["status"], 0) + 1
    return {"total": len(tasks), "by_status": by_status, "next": next_development_task()}
