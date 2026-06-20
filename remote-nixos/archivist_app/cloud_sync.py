from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from app.config import DATA_DIR
from app.db import get_conn
from app.utils import clean_filename, safe_rel_path, sha256_file


CLOUD_SYNC_FILE = DATA_DIR / "cloud_sync.json"
GMAIL_IMPORT_DIR = DATA_DIR / "cloud_imports" / "gmail"
GMAIL_ATTACHMENT_DIR = DATA_DIR / "cloud_imports" / "gmail_attachments"
DAV = "{DAV:}"
CALDAV = "{urn:ietf:params:xml:ns:caldav}"
GOOGLE_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
GOOGLE_GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GOOGLE_OAUTH_SCOPES = [GOOGLE_CALENDAR_SCOPE, GOOGLE_GMAIL_SCOPE]
GMAIL_IMPORT_DEFAULT_QUERY = "-in:spam -in:trash"
GMAIL_METADATA_HEADERS = ["Subject", "From", "To", "Cc", "Date"]
GMAIL_MESSAGE_MODES = {"metadata_only", "full"}
SYNC_MODES = {"cloud_index", "full_sync"}
PROVIDERS = {"icloud", "google"}
DEFAULT_SYNC_INTERVAL_MINUTES = 15
CALENDAR_SYNC_LOCK = threading.Lock()
GMAIL_IMPORT_LOCK = threading.Lock()
GMAIL_IMPORT_JOB_LOCK = threading.Lock()
GMAIL_BODY_JOB_LOCK = threading.Lock()
GMAIL_ATTACHMENT_JOB_LOCK = threading.Lock()
SCHEDULER_LOCK = threading.Lock()
SCHEDULER_STARTED = False
GMAIL_IMPORT_JOB = {
    "running": False,
    "done": False,
    "started_ts": None,
    "finished_ts": None,
    "updated_ts": None,
    "query": GMAIL_IMPORT_DEFAULT_QUERY,
    "max_results": 0,
    "message_mode": "metadata_only",
    "total_estimate": None,
    "scanned_count": 0,
    "imported_count": 0,
    "updated_count": 0,
    "skipped_count": 0,
    "failed_count": 0,
    "body_downloaded": 0,
    "embedding_synced": 0,
    "current_message": "",
    "last_error": "",
    "result": {},
}
GMAIL_BODY_JOB = {
    "running": False,
    "done": False,
    "started_ts": None,
    "finished_ts": None,
    "updated_ts": None,
    "selected_count": 0,
    "processed_count": 0,
    "downloaded_count": 0,
    "failed_count": 0,
    "current_message": "",
    "last_error": "",
    "result": {},
}
GMAIL_ATTACHMENT_JOB = {
    "running": False,
    "done": False,
    "started_ts": None,
    "finished_ts": None,
    "updated_ts": None,
    "selected_count": 0,
    "processed_count": 0,
    "downloaded_count": 0,
    "indexed_count": 0,
    "skipped_count": 0,
    "failed_count": 0,
    "current_attachment": "",
    "last_error": "",
    "result": {},
}
GMAIL_ATTACHMENT_MODES = {"metadata_only", "important_attachments", "all_attachments"}


class DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.c_void_p)]


def now_ts() -> float:
    return time.time()


def iso_utc(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts or now_ts(), tz=timezone.utc).isoformat()


def default_cloud_sync_settings() -> dict:
    return {
        "accounts": {},
        "schedule": {
            "enabled": True,
            "interval_minutes": DEFAULT_SYNC_INTERVAL_MINUTES,
            "last_auto_sync_ts": None,
            "last_auto_sync_status": "idle",
            "last_auto_sync_error": "",
        },
        "updated_ts": None,
    }


def read_cloud_sync_settings() -> dict:
    try:
        data = json.loads(CLOUD_SYNC_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        data = {}
    defaults = default_cloud_sync_settings()
    accounts = data.get("accounts") if isinstance(data.get("accounts"), dict) else {}
    schedule = {**defaults["schedule"], **(data.get("schedule") or {})}
    schedule["interval_minutes"] = max(5, min(240, int(schedule.get("interval_minutes") or DEFAULT_SYNC_INTERVAL_MINUTES)))
    schedule["enabled"] = bool(schedule.get("enabled"))
    return {"accounts": accounts, "schedule": schedule, "updated_ts": data.get("updated_ts") or defaults["updated_ts"]}


def write_cloud_sync_settings(settings: dict) -> dict:
    payload = {
        "accounts": settings.get("accounts") or {},
        "schedule": {**default_cloud_sync_settings()["schedule"], **(settings.get("schedule") or {})},
        "updated_ts": now_ts(),
    }
    CLOUD_SYNC_FILE.parent.mkdir(parents=True, exist_ok=True)
    CLOUD_SYNC_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return read_cloud_sync_settings()


def provider_label(provider: str) -> str:
    return {"icloud": "iCloud", "google": "Google"}.get(provider, provider.title())


def mode_label(mode: str) -> str:
    return "Full sync" if mode == "full_sync" else "Cloud index"


def base_account(provider: str) -> dict:
    return {
        "provider": provider,
        "label": provider_label(provider),
        "sync_mode": "cloud_index",
        "calendar_enabled": True,
        "status": "not_configured",
        "summary": f"{provider_label(provider)} is not configured.",
        "calendar": {"events": [], "status": "not_configured"},
        "secrets": {},
        "updated_ts": now_ts(),
    }


def protect_secret(value: str | None) -> str:
    text = str(value or "").strip()
    if not text or text.startswith(("dpapi:", "plain:")):
        return text
    if sys.platform != "win32":
        return f"plain:{text}"
    try:
        ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree.restype = ctypes.c_void_p
        raw = text.encode("utf-8")
        in_buffer = ctypes.create_string_buffer(raw)
        in_blob = DataBlob(len(raw), ctypes.cast(in_buffer, ctypes.c_void_p))
        out_blob = DataBlob()
        if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(out_blob),
        ):
            return f"plain:{text}"
        protected = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        ctypes.windll.kernel32.LocalFree(ctypes.c_void_p(out_blob.pbData))
        return "dpapi:" + base64.b64encode(protected).decode("ascii")
    except Exception:
        return f"plain:{text}"


def unprotect_secret(value: str | None) -> str:
    text = str(value or "")
    if not text:
        return ""
    if text.startswith("plain:"):
        return text.removeprefix("plain:")
    if not text.startswith("dpapi:"):
        return text
    if sys.platform != "win32":
        return ""
    try:
        ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree.restype = ctypes.c_void_p
        raw = base64.b64decode(text.removeprefix("dpapi:"))
        in_buffer = ctypes.create_string_buffer(raw)
        in_blob = DataBlob(len(raw), ctypes.cast(in_buffer, ctypes.c_void_p))
        out_blob = DataBlob()
        if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            0,
            ctypes.byref(out_blob),
        ):
            return ""
        unprotected = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        ctypes.windll.kernel32.LocalFree(ctypes.c_void_p(out_blob.pbData))
        return unprotected.decode("utf-8")
    except Exception:
        return ""


def get_secret(account: dict, key: str) -> str:
    return unprotect_secret((account.get("secrets") or {}).get(key))


def account_ready_for_google(account: dict) -> bool:
    return bool(account.get("client_id") and get_secret(account, "client_secret") and get_secret(account, "refresh_token"))


def account_ready_for_calendar(account: dict) -> bool:
    provider = account.get("provider")
    if provider == "icloud":
        return bool(account.get("username") and get_secret(account, "app_password"))
    if provider == "google":
        return account_ready_for_google(account)
    return False


def account_ready_for_gmail(account: dict) -> bool:
    if account.get("provider") != "google":
        return False
    return account_ready_for_google(account)


def gmail_import_job_snapshot() -> dict:
    with GMAIL_IMPORT_JOB_LOCK:
        return dict(GMAIL_IMPORT_JOB)


def update_gmail_import_job(**fields) -> dict:
    with GMAIL_IMPORT_JOB_LOCK:
        GMAIL_IMPORT_JOB.update(fields)
        GMAIL_IMPORT_JOB["updated_ts"] = now_ts()
        return dict(GMAIL_IMPORT_JOB)


def reset_gmail_import_job(options: dict | None = None) -> dict:
    opts = options or {}
    with GMAIL_IMPORT_JOB_LOCK:
        GMAIL_IMPORT_JOB.update(
            {
                "running": True,
                "done": False,
                "started_ts": now_ts(),
                "finished_ts": None,
                "updated_ts": now_ts(),
                "query": str(opts.get("query") if opts.get("query") is not None else GMAIL_IMPORT_DEFAULT_QUERY),
                "max_results": int(opts.get("max_results") if opts.get("max_results") is not None else 0),
                "message_mode": str(opts.get("message_mode") or "metadata_only"),
                "total_estimate": None,
                "scanned_count": 0,
                "imported_count": 0,
                "updated_count": 0,
                "skipped_count": 0,
                "failed_count": 0,
                "body_downloaded": 0,
                "embedding_synced": 0,
                "attachment_mode": str(opts.get("attachment_mode") or "metadata_only"),
                "attachment_downloaded": 0,
                "attachment_indexed": 0,
                "attachment_failed": 0,
                "current_message": "",
                "last_error": "",
                "result": {},
            }
        )
        return dict(GMAIL_IMPORT_JOB)


def finish_gmail_import_job(result: dict | None = None, error: str = "") -> dict:
    return update_gmail_import_job(
        running=False,
        done=True,
        finished_ts=now_ts(),
        last_error=str(error or "")[:1000],
        result=result or {},
    )


def gmail_body_job_snapshot() -> dict:
    with GMAIL_BODY_JOB_LOCK:
        return dict(GMAIL_BODY_JOB)


def update_gmail_body_job(**fields) -> dict:
    with GMAIL_BODY_JOB_LOCK:
        GMAIL_BODY_JOB.update(fields)
        GMAIL_BODY_JOB["updated_ts"] = now_ts()
        return dict(GMAIL_BODY_JOB)


def reset_gmail_body_job(options: dict | None = None, *, selected_count: int = 0) -> dict:
    with GMAIL_BODY_JOB_LOCK:
        GMAIL_BODY_JOB.update(
            {
                "running": True,
                "done": False,
                "started_ts": now_ts(),
                "finished_ts": None,
                "updated_ts": now_ts(),
                "selected_count": int(selected_count or 0),
                "processed_count": 0,
                "downloaded_count": 0,
                "failed_count": 0,
                "current_message": "",
                "last_error": "",
                "options": dict(options or {}),
                "result": {},
            }
        )
        return dict(GMAIL_BODY_JOB)


def finish_gmail_body_job(result: dict | None = None, error: str = "") -> dict:
    return update_gmail_body_job(
        running=False,
        done=True,
        finished_ts=now_ts(),
        last_error=str(error or "")[:1000],
        result=result or {},
    )


def gmail_attachment_job_snapshot() -> dict:
    with GMAIL_ATTACHMENT_JOB_LOCK:
        return dict(GMAIL_ATTACHMENT_JOB)


def update_gmail_attachment_job(**fields) -> dict:
    with GMAIL_ATTACHMENT_JOB_LOCK:
        GMAIL_ATTACHMENT_JOB.update(fields)
        GMAIL_ATTACHMENT_JOB["updated_ts"] = now_ts()
        return dict(GMAIL_ATTACHMENT_JOB)


def reset_gmail_attachment_job(options: dict | None = None, *, selected_count: int = 0) -> dict:
    with GMAIL_ATTACHMENT_JOB_LOCK:
        GMAIL_ATTACHMENT_JOB.update(
            {
                "running": True,
                "done": False,
                "started_ts": now_ts(),
                "finished_ts": None,
                "updated_ts": now_ts(),
                "selected_count": int(selected_count or 0),
                "processed_count": 0,
                "downloaded_count": 0,
                "indexed_count": 0,
                "skipped_count": 0,
                "failed_count": 0,
                "current_attachment": "",
                "last_error": "",
                "options": dict(options or {}),
                "result": {},
            }
        )
        return dict(GMAIL_ATTACHMENT_JOB)


def finish_gmail_attachment_job(result: dict | None = None, error: str = "") -> dict:
    return update_gmail_attachment_job(
        running=False,
        done=True,
        finished_ts=now_ts(),
        last_error=str(error or "")[:1000],
        result=result or {},
    )


def gmail_import_summary(account: dict) -> dict:
    gmail = dict(account.get("gmail") or {})
    if not gmail:
        gmail = {"status": "not_started", "summary": "Gmail has not been imported yet."}
    messages = gmail_message_summary()
    if messages.get("total_count"):
        if gmail.get("status") == "not_started":
            gmail["status"] = "connected"
            gmail["message_mode"] = "metadata_only"
            gmail["summary"] = f"Gmail metadata indexed for {int(messages.get('total_count') or 0)} message(s)."
        gmail.setdefault("imported_count", messages.get("total_count"))
        gmail["message_summary"] = messages
    return gmail


def gmail_import_status_label(account: dict) -> str:
    gmail = gmail_import_summary(account)
    if gmail.get("status") in {"connected", "partial"}:
        count = int(gmail.get("imported_count") or 0)
        failed = int(gmail.get("failed_count") or 0)
        mode = str(gmail.get("message_mode") or "metadata_only")
        noun = "message metadata record(s)" if mode == "metadata_only" else "message body record(s)"
        if failed:
            return f"Gmail archive imported {count} {noun}; {failed} failed."
        return f"Gmail archive imported {count} {noun}."
    if gmail.get("status") == "error":
        return f"Gmail archive import issue: {gmail.get('last_error') or 'unknown error'}"
    if account_ready_for_gmail(account):
        return "Gmail archive is ready to import."
    return "Google OAuth is not connected for Gmail import."


def gmail_message_row(row) -> dict:
    try:
        labels = json.loads(row["labels_json"] or "[]")
    except ValueError:
        labels = []
    return {
        "id": int(row["id"]),
        "message_id": row["message_id"],
        "thread_id": row["thread_id"] or "",
        "file_id": row["file_id"],
        "subject": row["subject"] or "",
        "sender": row["sender"] or "",
        "recipients": row["recipients"] or "",
        "cc": row["cc"] or "",
        "message_date": row["message_date"] or "",
        "message_ts": row["message_ts"],
        "labels": labels if isinstance(labels, list) else [],
        "snippet": row["snippet"] or "",
        "body_status": row["body_status"] or "metadata_only",
        "attachment_status": row["attachment_status"] or "unknown",
        "attachment_count": int(row["attachment_count"] or 0),
        "body_local_path": row["body_local_path"] or "",
        "error": row["error"] or "",
        "created_ts": row["created_ts"],
        "updated_ts": row["updated_ts"],
    }


def gmail_message_summary() -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT body_status, COUNT(*) AS count
        FROM gmail_messages
        GROUP BY body_status
        """
    )
    by_body_status = {row["body_status"] or "metadata_only": int(row["count"] or 0) for row in cur.fetchall()}
    cur.execute(
        """
        SELECT attachment_status, COUNT(*) AS count, COALESCE(SUM(attachment_count), 0) AS attachments
        FROM gmail_messages
        GROUP BY attachment_status
        """
    )
    by_attachment_status = {
        row["attachment_status"] or "unknown": {
            "count": int(row["count"] or 0),
            "attachments": int(row["attachments"] or 0),
        }
        for row in cur.fetchall()
    }
    cur.execute("SELECT COUNT(*) AS count FROM gmail_messages")
    total = cur.fetchone()
    cur.execute(
        """
        SELECT *
        FROM gmail_messages
        ORDER BY updated_ts DESC, id DESC
        LIMIT 8
        """
    )
    recent = [gmail_message_row(row) for row in cur.fetchall()]
    conn.close()
    return {
        "total_count": int(total["count"] or 0),
        "by_body_status": by_body_status,
        "by_attachment_status": by_attachment_status,
        "recent": recent,
    }


def list_gmail_messages(
    *,
    status: str | None = None,
    query: str | None = None,
    limit: int = 80,
    ids: list[int] | None = None,
) -> dict:
    clauses = []
    params: list = []
    if ids:
        placeholders = ",".join("?" for _ in ids)
        clauses.append(f"id IN ({placeholders})")
        params.extend(int(item) for item in ids)
    if status:
        clauses.append("body_status = ?")
        params.append(status)
    q = str(query or "").strip()
    if q:
        like = f"%{q}%"
        clauses.append(
            "(message_id LIKE ? OR subject LIKE ? OR sender LIKE ? OR recipients LIKE ? OR cc LIKE ? OR snippet LIKE ? OR labels_json LIKE ?)"
        )
        params.extend([like, like, like, like, like, like, like])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT *
        FROM gmail_messages
        {where}
        ORDER BY message_ts DESC, id DESC
        LIMIT ?
        """,
        [*params, max(1, min(int(limit or 80), 1000))],
    )
    rows = [gmail_message_row(row) for row in cur.fetchall()]
    conn.close()
    return {"messages": rows, "summary": gmail_message_summary(), "job": gmail_body_job_snapshot()}


def upsert_gmail_message_manifest(
    *,
    message: dict,
    headers: dict,
    message_ts: float,
    file_id: int | None,
    body_status: str,
    attachment_status: str = "unknown",
    attachment_count: int = 0,
    body_local_path: str = "",
    error: str = "",
) -> dict:
    message_id = str(message.get("id") or "").strip()
    if not message_id:
        return {}
    labels = message.get("labelIds") or []
    now = now_ts()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM gmail_messages WHERE message_id = ?", (message_id,))
    existing = cur.fetchone()
    final_body_status = str(body_status or "metadata_only")
    final_attachment_status = str(attachment_status or "unknown")
    final_attachment_count = int(attachment_count or 0)
    final_file_id = file_id
    final_path = body_local_path or ""
    if existing:
        existing_body_status = existing["body_status"] or "metadata_only"
        if existing_body_status == "downloaded" and final_body_status != "downloaded":
            final_body_status = existing_body_status
        existing_attachment_status = existing["attachment_status"] or "unknown"
        if final_attachment_status == "unknown" and existing_attachment_status != "unknown":
            final_attachment_status = existing_attachment_status
        if final_attachment_status == "unknown" and int(existing["attachment_count"] or 0) > final_attachment_count:
            final_attachment_count = int(existing["attachment_count"] or 0)
        final_file_id = final_file_id or existing["file_id"]
        final_path = final_path or existing["body_local_path"] or ""
    cur.execute(
        """
        INSERT INTO gmail_messages (
            message_id, thread_id, file_id, subject, sender, recipients, cc,
            message_date, message_ts, labels_json, snippet, body_status,
            attachment_status, attachment_count, body_local_path, error,
            created_ts, updated_ts
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(message_id) DO UPDATE SET
            thread_id=excluded.thread_id,
            file_id=excluded.file_id,
            subject=excluded.subject,
            sender=excluded.sender,
            recipients=excluded.recipients,
            cc=excluded.cc,
            message_date=excluded.message_date,
            message_ts=excluded.message_ts,
            labels_json=excluded.labels_json,
            snippet=excluded.snippet,
            body_status=excluded.body_status,
            attachment_status=excluded.attachment_status,
            attachment_count=excluded.attachment_count,
            body_local_path=excluded.body_local_path,
            error=excluded.error,
            updated_ts=excluded.updated_ts
        """,
        (
            message_id,
            str(message.get("threadId") or ""),
            final_file_id,
            headers.get("subject") or "(no subject)",
            headers.get("from") or "",
            headers.get("to") or "",
            headers.get("cc") or "",
            headers.get("date") or "",
            message_ts,
            json.dumps(labels),
            str(message.get("snippet") or ""),
            final_body_status,
            final_attachment_status,
            final_attachment_count,
            final_path,
            str(error or "")[:1000],
            existing["created_ts"] if existing else now,
            now,
        ),
    )
    conn.commit()
    cur.execute("SELECT * FROM gmail_messages WHERE message_id = ?", (message_id,))
    row = cur.fetchone()
    conn.close()
    return gmail_message_row(row) if row else {}


def gmail_attachment_row(row) -> dict:
    return {
        "id": int(row["id"]),
        "message_id": row["message_id"],
        "attachment_id": row["attachment_id"] or "",
        "parent_file_id": row["parent_file_id"],
        "file_id": row["file_id"],
        "subject": row["subject"] or "",
        "sender": row["sender"] or "",
        "message_date": row["message_date"] or "",
        "message_ts": row["message_ts"],
        "filename": row["filename"] or "",
        "mime_type": row["mime_type"] or "",
        "size_bytes": int(row["size_bytes"] or 0),
        "local_path": row["local_path"] or "",
        "status": row["status"] or "pending",
        "error": row["error"] or "",
        "created_ts": row["created_ts"],
        "updated_ts": row["updated_ts"],
    }


def gmail_attachment_summary() -> dict:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT status, COUNT(*) AS count, COALESCE(SUM(size_bytes), 0) AS bytes
        FROM gmail_attachments
        GROUP BY status
        """
    )
    by_status = {
        row["status"] or "pending": {"count": int(row["count"] or 0), "bytes": int(row["bytes"] or 0)}
        for row in cur.fetchall()
    }
    cur.execute("SELECT COUNT(*) AS count, COALESCE(SUM(size_bytes), 0) AS bytes FROM gmail_attachments")
    total = cur.fetchone()
    cur.execute(
        """
        SELECT *
        FROM gmail_attachments
        ORDER BY updated_ts DESC, id DESC
        LIMIT 8
        """
    )
    recent = [gmail_attachment_row(row) for row in cur.fetchall()]
    conn.close()
    return {
        "total_count": int(total["count"] or 0),
        "total_bytes": int(total["bytes"] or 0),
        "by_status": by_status,
        "recent": recent,
    }


def list_gmail_attachments(
    *,
    status: str | None = None,
    query: str | None = None,
    message_id: str | None = None,
    limit: int = 80,
    ids: list[int] | None = None,
) -> dict:
    clauses = []
    params: list = []
    if ids:
        placeholders = ",".join("?" for _ in ids)
        clauses.append(f"id IN ({placeholders})")
        params.extend(int(item) for item in ids)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if message_id:
        clauses.append("message_id = ?")
        params.append(str(message_id))
    q = str(query or "").strip()
    if q:
        like = f"%{q}%"
        clauses.append("(filename LIKE ? OR subject LIKE ? OR sender LIKE ? OR mime_type LIKE ?)")
        params.extend([like, like, like, like])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT *
        FROM gmail_attachments
        {where}
        ORDER BY message_ts DESC, id DESC
        LIMIT ?
        """,
        [*params, max(1, min(int(limit or 80), 1000))],
    )
    rows = [gmail_attachment_row(row) for row in cur.fetchall()]
    conn.close()
    return {"attachments": rows, "summary": gmail_attachment_summary(), "job": gmail_attachment_job_snapshot()}


def ready_calendar_accounts(settings: dict | None = None) -> list[str]:
    data = settings or read_cloud_sync_settings()
    return [
        provider
        for provider, account in (data.get("accounts") or {}).items()
        if account.get("calendar_enabled", True) and account_ready_for_calendar(account)
    ]


def redact_account(account: dict) -> dict:
    clean = {k: v for k, v in account.items() if k != "secrets"}
    secret = account.get("secrets") or {}
    clean["credential_status"] = {
        "app_password": "stored" if secret.get("app_password") else "missing",
        "client_secret": "stored" if secret.get("client_secret") else "missing",
        "refresh_token": "stored" if secret.get("refresh_token") else "missing",
    }
    clean["secret_storage"] = "windows_dpapi" if any(str(value).startswith("dpapi:") for value in secret.values()) else "local_file"
    clean["calendar_ready"] = account_ready_for_calendar(account)
    if account.get("provider") == "google":
        clean["gmail_ready"] = account_ready_for_gmail(account)
        clean["gmail"] = {**gmail_import_summary(account), "summary": gmail_import_status_label(account)}
        if account.get("granted_scopes"):
            clean["granted_scopes"] = account.get("granted_scopes")
    clean["file_policy"] = (
        "Download/copy cloud files locally before indexing. Not active until a file sync worker exists."
        if clean.get("sync_mode") == "full_sync"
        else "Index cloud metadata/context only. Do not download cloud files."
    )
    return clean


def cloud_sync_status() -> dict:
    settings = read_cloud_sync_settings()
    accounts = {provider: redact_account(account) for provider, account in (settings.get("accounts") or {}).items()}
    schedule = dict(settings.get("schedule") or {})
    calendar_accounts = [item for item in accounts.values() if item.get("calendar_enabled")]
    connected = [item for item in calendar_accounts if item.get("calendar", {}).get("status") == "connected"]
    ready = [item for item in calendar_accounts if item.get("calendar_ready")]
    upcoming = []
    for item in accounts.values():
        upcoming.extend(item.get("calendar", {}).get("events") or [])
    upcoming.sort(key=lambda event: event.get("start_ts") or 0)
    last_auto = schedule.get("last_auto_sync_ts")
    interval_seconds = int(schedule.get("interval_minutes") or DEFAULT_SYNC_INTERVAL_MINUTES) * 60
    schedule["next_auto_sync_ts"] = (float(last_auto) + interval_seconds) if schedule.get("enabled") and last_auto else None
    schedule["ready_provider_count"] = len(ready_calendar_accounts(settings))
    return {
        "accounts": accounts,
        "schedule": schedule,
        "summary": (
            f"{len(connected)} calendar provider(s) synced; {len(ready)} ready."
            if calendar_accounts
            else "No cloud sync accounts configured."
        ),
        "sync_modes": [
            {"value": "cloud_index", "label": "Cloud index", "summary": "Metadata/context only; no cloud file download."},
            {"value": "full_sync", "label": "Full sync", "summary": "Download/copy cloud files locally before indexing."},
        ],
        "upcoming_events": upcoming[:20],
        "gmail_import_job": gmail_import_job_snapshot(),
        "gmail_body_job": gmail_body_job_snapshot(),
        "gmail_messages": gmail_message_summary(),
        "gmail_attachment_job": gmail_attachment_job_snapshot(),
        "gmail_attachments": gmail_attachment_summary(),
        "updated_ts": settings.get("updated_ts"),
    }


def update_cloud_sync_schedule(enabled: bool | None = None, interval_minutes: int | None = None) -> dict:
    settings = read_cloud_sync_settings()
    schedule = dict(settings.get("schedule") or default_cloud_sync_settings()["schedule"])
    if enabled is not None:
        schedule["enabled"] = bool(enabled)
    if interval_minutes is not None:
        schedule["interval_minutes"] = max(5, min(240, int(interval_minutes)))
    settings["schedule"] = schedule
    write_cloud_sync_settings(settings)
    return cloud_sync_status()


def save_cloud_account(payload: dict) -> dict:
    provider = str(payload.get("provider") or "").strip().lower()
    if provider not in PROVIDERS:
        raise ValueError("Provider must be `icloud` or `google`.")
    settings = read_cloud_sync_settings()
    accounts = settings.setdefault("accounts", {})
    account = {**base_account(provider), **(accounts.get(provider) or {})}
    sync_mode = str(payload.get("sync_mode") or account.get("sync_mode") or "cloud_index").strip()
    if sync_mode not in SYNC_MODES:
        raise ValueError("Sync mode must be `cloud_index` or `full_sync`.")
    account.update(
        {
            "provider": provider,
            "label": (payload.get("label") or account.get("label") or provider_label(provider)).strip(),
            "sync_mode": sync_mode,
            "calendar_enabled": bool(payload.get("calendar_enabled", account.get("calendar_enabled", True))),
            "updated_ts": now_ts(),
        }
    )
    secret = dict(account.get("secrets") or {})
    if provider == "icloud":
        if payload.get("username") is not None:
            account["username"] = str(payload.get("username") or "").strip()
        if payload.get("app_password"):
            secret["app_password"] = protect_secret(payload.get("app_password"))
    if provider == "google":
        if payload.get("client_id") is not None:
            account["client_id"] = str(payload.get("client_id") or "").strip()
        if payload.get("client_secret"):
            secret["client_secret"] = protect_secret(payload.get("client_secret"))
    account["secrets"] = secret
    ready = account_ready_for_calendar(account)
    if provider == "google" and not ready:
        has_client = bool(account.get("client_id"))
        has_secret = bool(get_secret(account, "client_secret"))
        account["status"] = "needs_refresh_token" if has_client and has_secret else "needs_credentials"
        account["summary"] = (
            "Google OAuth client saved; click Open Google sign-in to grant Calendar/Gmail read-only access."
            if has_client and has_secret
            else "Google OAuth client credentials are incomplete."
        )
        account["calendar"] = {
            **(account.get("calendar") or {}),
            "status": "pending_oauth",
            "last_error": "",
        }
    else:
        account["status"] = "configured" if ready else "needs_credentials"
        account["summary"] = (
            f"{provider_label(provider)} calendar is ready for sync."
            if ready
            else f"{provider_label(provider)} saved; calendar credentials are incomplete."
        )
    accounts[provider] = account
    write_cloud_sync_settings(settings)
    return cloud_sync_status()


def disconnect_cloud_account(provider: str) -> dict:
    provider = str(provider or "").strip().lower()
    if provider not in PROVIDERS:
        raise ValueError("Provider must be `icloud` or `google`.")
    settings = read_cloud_sync_settings()
    settings.setdefault("accounts", {}).pop(provider, None)
    write_cloud_sync_settings(settings)
    return cloud_sync_status()


class MethodRequest(urllib.request.Request):
    def __init__(self, *args, method: str = "GET", **kwargs):
        self._method = method
        super().__init__(*args, **kwargs)

    def get_method(self) -> str:
        return self._method


def http_request(method: str, url: str, *, body: bytes | None = None, headers: dict | None = None, timeout: int = 20) -> tuple[str, str]:
    req = MethodRequest(url, data=body, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        final_url = response.geturl()
        text = response.read().decode("utf-8", errors="replace")
    return final_url, text


def basic_auth_header(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def caldav_xml_request(method: str, url: str, username: str, password: str, body: str, *, depth: str = "0") -> tuple[str, ET.Element]:
    headers = {
        "Authorization": basic_auth_header(username, password),
        "Content-Type": "application/xml; charset=utf-8",
        "Depth": depth,
        "User-Agent": "Archivist/0.1",
    }
    current_url = url
    for _ in range(4):
        try:
            final_url, text = http_request(method, current_url, body=body.encode("utf-8"), headers=headers, timeout=25)
            return final_url, ET.fromstring(text)
        except urllib.error.HTTPError as error:
            if error.code in {301, 302, 307, 308} and error.headers.get("Location"):
                current_url = urllib.parse.urljoin(current_url, error.headers["Location"])
                continue
            raise
    raise RuntimeError("Too many CalDAV redirects.")


def xml_href(node: ET.Element | None) -> str:
    href = node.find(f"{DAV}href") if node is not None else None
    return (href.text or "").strip() if href is not None else ""


def discover_icloud_calendars(username: str, password: str) -> list[dict]:
    root_url = "https://caldav.icloud.com/"
    _, principal_doc = caldav_xml_request(
        "PROPFIND",
        root_url,
        username,
        password,
        """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/></d:prop></d:propfind>""",
    )
    principal_href = xml_href(principal_doc.find(f".//{DAV}current-user-principal"))
    if not principal_href:
        raise RuntimeError("iCloud did not return a CalDAV principal.")
    principal_url = urllib.parse.urljoin(root_url, principal_href)
    _, home_doc = caldav_xml_request(
        "PROPFIND",
        principal_url,
        username,
        password,
        """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop><c:calendar-home-set/></d:prop>
</d:propfind>""",
    )
    home_href = xml_href(home_doc.find(f".//{CALDAV}calendar-home-set"))
    if not home_href:
        raise RuntimeError("iCloud did not return a calendar home.")
    home_url = urllib.parse.urljoin(principal_url, home_href)
    _, calendars_doc = caldav_xml_request(
        "PROPFIND",
        home_url,
        username,
        password,
        """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop><d:displayname/><d:resourcetype/></d:prop>
</d:propfind>""",
        depth="1",
    )
    calendars = []
    for response in calendars_doc.findall(f"{DAV}response"):
        prop = response.find(f".//{DAV}prop")
        resource_type = prop.find(f"{DAV}resourcetype") if prop is not None else None
        if resource_type is None or resource_type.find(f"{CALDAV}calendar") is None:
            continue
        href = response.find(f"{DAV}href")
        display = prop.find(f"{DAV}displayname") if prop is not None else None
        calendar_url = urllib.parse.urljoin(home_url, (href.text or "").strip()) if href is not None else ""
        if calendar_url:
            calendars.append({"url": calendar_url, "name": (display.text or "iCloud Calendar") if display is not None else "iCloud Calendar"})
    return calendars


def unfold_ics(text: str) -> list[str]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    unfolded: list[str] = []
    for line in lines:
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def ics_value(line: str) -> tuple[str, str]:
    left, _, value = line.partition(":")
    name = left.split(";", 1)[0].upper()
    return name, value.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").strip()


def parse_ics_datetime(value: str) -> tuple[float, str]:
    raw = (value or "").strip()
    formats = [
        ("%Y%m%dT%H%M%SZ", True),
        ("%Y%m%dT%H%M%S", False),
        ("%Y%m%d", False),
    ]
    for fmt, utc in formats:
        try:
            dt = datetime.strptime(raw, fmt)
            if utc:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp(), dt.isoformat()
        except ValueError:
            continue
    return 0.0, raw


def parse_ics_events(text: str, source: str, calendar_name: str) -> list[dict]:
    events = []
    current: dict[str, str] | None = None
    for line in unfold_ics(text):
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current:
                start_ts, start_iso = parse_ics_datetime(current.get("DTSTART", ""))
                end_ts, end_iso = parse_ics_datetime(current.get("DTEND", ""))
                events.append(
                    {
                        "provider": source,
                        "calendar": calendar_name,
                        "uid": current.get("UID") or f"{source}:{calendar_name}:{start_iso}:{current.get('SUMMARY', '')}",
                        "title": current.get("SUMMARY") or "(Untitled event)",
                        "start": start_iso,
                        "start_ts": start_ts,
                        "end": end_iso,
                        "end_ts": end_ts,
                        "location": current.get("LOCATION") or "",
                        "description": (current.get("DESCRIPTION") or "")[:500],
                    }
                )
            current = None
            continue
        if current is not None and ":" in line:
            name, value = ics_value(line)
            if name in {"UID", "SUMMARY", "DTSTART", "DTEND", "LOCATION", "DESCRIPTION"}:
                current[name] = value
    return events


def fetch_icloud_events(account: dict, *, days: int = 45) -> list[dict]:
    username = account.get("username") or ""
    password = get_secret(account, "app_password")
    calendars = discover_icloud_calendars(username, password)
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=max(1, min(int(days), 180)))
    start_text = start.strftime("%Y%m%dT%H%M%SZ")
    end_text = end.strftime("%Y%m%dT%H%M%SZ")
    events = []
    for calendar in calendars[:20]:
        _, report_doc = caldav_xml_request(
            "REPORT",
            calendar["url"],
            username,
            password,
            f"""<?xml version="1.0" encoding="utf-8"?>
<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop><d:getetag/><c:calendar-data/></d:prop>
  <c:filter>
    <c:comp-filter name="VCALENDAR">
      <c:comp-filter name="VEVENT"><c:time-range start="{start_text}" end="{end_text}"/></c:comp-filter>
    </c:comp-filter>
  </c:filter>
</c:calendar-query>""",
            depth="1",
        )
        for data_node in report_doc.findall(f".//{CALDAV}calendar-data"):
            events.extend(parse_ics_events(data_node.text or "", "icloud", calendar["name"]))
    return sorted([event for event in events if event.get("start_ts", 0) >= start.timestamp() - 86400], key=lambda item: item.get("start_ts") or 0)[:80]


def google_redirect_uri(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/api/cloud-sync/google/callback"


def google_auth_url(base_url: str) -> dict:
    settings = read_cloud_sync_settings()
    account = (settings.get("accounts") or {}).get("google") or {}
    client_id = account.get("client_id")
    if not client_id:
        raise ValueError("Save a Google desktop OAuth client ID first.")
    state = secrets.token_urlsafe(24)
    account["oauth_state"] = state
    account["redirect_uri"] = google_redirect_uri(base_url)
    settings.setdefault("accounts", {})["google"] = account
    write_cloud_sync_settings(settings)
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": account["redirect_uri"],
            "response_type": "code",
            "scope": " ".join(GOOGLE_OAUTH_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
    )
    return {"auth_url": f"https://accounts.google.com/o/oauth2/v2/auth?{query}", "redirect_uri": account["redirect_uri"], **cloud_sync_status()}


def form_post(url: str, payload: dict, timeout: int = 20) -> dict:
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def complete_google_oauth(code: str, state: str | None, base_url: str) -> dict:
    settings = read_cloud_sync_settings()
    accounts = settings.setdefault("accounts", {})
    account = accounts.get("google") or {}
    if state and account.get("oauth_state") and state != account.get("oauth_state"):
        raise ValueError("Google OAuth state did not match.")
    secret = account.get("secrets") or {}
    client_secret = get_secret(account, "client_secret")
    token = form_post(
        "https://oauth2.googleapis.com/token",
        {
            "code": code,
            "client_id": account.get("client_id") or "",
            "client_secret": client_secret,
            "redirect_uri": account.get("redirect_uri") or google_redirect_uri(base_url),
            "grant_type": "authorization_code",
        },
    )
    if token.get("refresh_token"):
        secret["refresh_token"] = protect_secret(token["refresh_token"])
    if token.get("access_token"):
        secret["access_token"] = protect_secret(token["access_token"])
        secret["access_token_expires_at"] = now_ts() + int(token.get("expires_in") or 3600)
    if token.get("scope"):
        account["granted_scopes"] = token.get("scope")
    account["secrets"] = secret
    account["oauth_state"] = None
    account["status"] = "configured" if account_ready_for_calendar(account) else "needs_refresh_token"
    account["summary"] = "Google Calendar authorization complete." if account_ready_for_calendar(account) else "Google authorized, but no refresh token was returned."
    account["updated_ts"] = now_ts()
    accounts["google"] = account
    write_cloud_sync_settings(settings)
    return sync_calendar("google")


def google_access_token(account: dict, *, force_refresh: bool = False) -> str:
    secret = account.get("secrets") or {}
    access_token = get_secret(account, "access_token")
    if not force_refresh and access_token and float(secret.get("access_token_expires_at") or 0) > now_ts() + 60:
        return access_token
    token = form_post(
        "https://oauth2.googleapis.com/token",
        {
            "client_id": account.get("client_id") or "",
            "client_secret": get_secret(account, "client_secret"),
            "refresh_token": get_secret(account, "refresh_token"),
            "grant_type": "refresh_token",
        },
    )
    secret["access_token"] = protect_secret(token.get("access_token") or "")
    secret["access_token_expires_at"] = now_ts() + int(token.get("expires_in") or 3600)
    if token.get("scope"):
        account["granted_scopes"] = token.get("scope")
    account["secrets"] = secret
    return token.get("access_token") or ""


def google_api_unauthorized(error: Exception) -> bool:
    return str(error).startswith("Google API 401:")


def google_get_json(url: str, token: str, timeout: int = 20) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "User-Agent": "Archivist/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        message = detail
        try:
            payload = json.loads(detail)
            message = ((payload.get("error") or {}).get("message")) or detail
        except ValueError:
            pass
        raise RuntimeError(f"Google API {error.code}: {message}") from error


def fetch_google_events(account: dict, *, days: int = 45) -> list[dict]:
    token = google_access_token(account)
    calendars = google_get_json("https://www.googleapis.com/calendar/v3/users/me/calendarList", token).get("items") or []
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=max(1, min(int(days), 180)))
    events = []
    for calendar in calendars[:20]:
        calendar_id = calendar.get("id")
        if not calendar_id or calendar.get("hidden"):
            continue
        query = urllib.parse.urlencode(
            {
                "timeMin": start.isoformat().replace("+00:00", "Z"),
                "timeMax": end.isoformat().replace("+00:00", "Z"),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": 20,
            }
        )
        url = f"https://www.googleapis.com/calendar/v3/calendars/{urllib.parse.quote(calendar_id, safe='')}/events?{query}"
        for item in google_get_json(url, token).get("items") or []:
            start_value = (item.get("start") or {}).get("dateTime") or (item.get("start") or {}).get("date") or ""
            end_value = (item.get("end") or {}).get("dateTime") or (item.get("end") or {}).get("date") or ""
            start_ts, start_iso = parse_google_datetime(start_value)
            end_ts, end_iso = parse_google_datetime(end_value)
            events.append(
                {
                    "provider": "google",
                    "calendar": calendar.get("summary") or "Google Calendar",
                    "uid": item.get("id") or item.get("iCalUID") or "",
                    "title": item.get("summary") or "(Untitled event)",
                    "start": start_iso,
                    "start_ts": start_ts,
                    "end": end_iso,
                    "end_ts": end_ts,
                    "location": item.get("location") or "",
                    "description": (item.get("description") or "")[:500],
                }
            )
    account["secrets"] = account.get("secrets") or {}
    return sorted(events, key=lambda item: item.get("start_ts") or 0)[:80]


def parse_google_datetime(value: str) -> tuple[float, str]:
    text = (value or "").strip()
    if not text:
        return 0.0, ""
    try:
        normalized = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp(), dt.isoformat()
    except ValueError:
        try:
            dt = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return dt.timestamp(), dt.date().isoformat()
        except ValueError:
            return 0.0, text


def gmail_b64decode_bytes(data: str | None) -> bytes:
    raw = str(data or "")
    if not raw:
        return b""
    padded = raw + ("=" * (-len(raw) % 4))
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except Exception:
        return b""


def gmail_b64decode(data: str | None) -> str:
    try:
        return gmail_b64decode_bytes(data).decode("utf-8", errors="replace")
    except Exception:
        return ""


def html_to_text(value: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", value or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def gmail_payload_headers(payload: dict | None) -> dict:
    out = {}
    for item in (payload or {}).get("headers") or []:
        name = str(item.get("name") or "").strip().lower()
        if name:
            out[name] = str(item.get("value") or "").strip()
    return out


def gmail_payload_text(payload: dict | None) -> tuple[str, list[dict]]:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[dict] = []

    def visit(part: dict | None) -> None:
        if not part:
            return
        filename = str(part.get("filename") or "").strip()
        body = part.get("body") or {}
        mime = str(part.get("mimeType") or "").lower()
        if filename:
            attachments.append(
                {
                    "filename": filename,
                    "mime_type": mime,
                    "size": int(body.get("size") or 0),
                    "attachment_id": body.get("attachmentId") or "",
                    "inline_data": bool(body.get("data")),
                }
            )
        data = gmail_b64decode(body.get("data"))
        if data and not filename:
            if mime.startswith("text/plain"):
                plain_parts.append(data.strip())
            elif mime.startswith("text/html"):
                html_parts.append(html_to_text(data))
        for child in part.get("parts") or []:
            visit(child)

    visit(payload)
    body_text = "\n\n".join(part for part in plain_parts if part).strip()
    if not body_text:
        body_text = "\n\n".join(part for part in html_parts if part).strip()
    return body_text, attachments


def gmail_internal_ts(message: dict) -> float:
    raw = message.get("internalDate")
    try:
        return int(raw) / 1000 if raw else now_ts()
    except (TypeError, ValueError):
        return now_ts()


def gmail_message_path(message_id: str) -> Path:
    digest = hashlib.sha256(message_id.encode("utf-8")).hexdigest()
    return GMAIL_IMPORT_DIR / digest[:2] / f"{message_id}.txt"


def gmail_attachment_path(message_id: str, attachment_id: str, filename: str) -> Path:
    cleaned = clean_filename(filename or "attachment")
    digest = hashlib.sha256(f"{message_id}:{attachment_id}:{cleaned}".encode("utf-8")).hexdigest()
    return GMAIL_ATTACHMENT_DIR / digest[:2] / digest[:12] / cleaned


def gmail_display_name(headers: dict, message_id: str) -> str:
    subject = headers.get("subject") or "(no subject)"
    cleaned = clean_filename(subject)[:96].strip("._")
    if not cleaned:
        cleaned = message_id
    return f"{cleaned}.txt"


def gmail_label_tags(labels: list[str]) -> list[str]:
    tag_map = {
        "INBOX": "gmail:inbox",
        "SENT": "gmail:sent",
        "DRAFT": "gmail:draft",
        "TRASH": "gmail:trash",
        "SPAM": "gmail:spam",
        "STARRED": "gmail:starred",
        "IMPORTANT": "gmail:important",
        "CATEGORY_PERSONAL": "gmail:personal",
        "CATEGORY_SOCIAL": "gmail:social",
        "CATEGORY_PROMOTIONS": "gmail:promotions",
        "CATEGORY_UPDATES": "gmail:updates",
        "CATEGORY_FORUMS": "gmail:forums",
    }
    tags = ["email", "gmail"]
    for label in labels or []:
        tags.append(tag_map.get(label, f"gmail:{str(label).lower().replace('_', '-')}"))
    return tags[:20]


def gmail_attachment_status(attachment_manifest: dict) -> str:
    count = int(attachment_manifest.get("count") or 0)
    if count <= 0:
        return "none"
    if int(attachment_manifest.get("pending") or 0) > 0:
        return "pending"
    return "metadata_only"


def gmail_metadata_text(message: dict) -> tuple[str, dict]:
    payload = message.get("payload") or {}
    headers = gmail_payload_headers(payload)
    labels = message.get("labelIds") or []
    snippet = str(message.get("snippet") or "").strip()
    header_lines = [
        "Gmail Message (metadata only)",
        f"Gmail ID: {message.get('id') or ''}",
        f"Thread ID: {message.get('threadId') or ''}",
        f"Subject: {headers.get('subject') or '(no subject)'}",
        f"From: {headers.get('from') or ''}",
        f"To: {headers.get('to') or ''}",
        f"Cc: {headers.get('cc') or ''}",
        f"Date: {headers.get('date') or ''}",
        f"Labels: {', '.join(labels)}",
        f"Snippet: {snippet}",
        "",
        "Body: Not downloaded yet. Pull this Gmail body when the email looks relevant.",
        "Attachments: Not inspected yet. Pull the body first to discover attachment metadata.",
    ]
    meta = {"headers": headers, "labels": labels, "attachments": [], "body_text": snippet}
    return "\n".join(header_lines).strip()[:8000], meta


def gmail_message_text(message: dict) -> tuple[str, dict]:
    payload = message.get("payload") or {}
    headers = gmail_payload_headers(payload)
    labels = message.get("labelIds") or []
    body_text, attachments = gmail_payload_text(payload)
    if not body_text:
        body_text = str(message.get("snippet") or "").strip()
    attachment_lines = [
        f"- {item['filename']} ({item.get('mime_type') or 'attachment'}, {item.get('size') or 0} bytes)"
        for item in attachments
    ]
    header_lines = [
        "Gmail Message",
        f"Gmail ID: {message.get('id') or ''}",
        f"Thread ID: {message.get('threadId') or ''}",
        f"Subject: {headers.get('subject') or '(no subject)'}",
        f"From: {headers.get('from') or ''}",
        f"To: {headers.get('to') or ''}",
        f"Cc: {headers.get('cc') or ''}",
        f"Date: {headers.get('date') or ''}",
        f"Labels: {', '.join(labels)}",
        f"Snippet: {message.get('snippet') or ''}",
    ]
    if attachment_lines:
        header_lines.extend(["", "Attachments:", *attachment_lines])
    full_text = "\n".join(header_lines).strip() + "\n\nBody:\n" + body_text.strip()
    meta = {"headers": headers, "labels": labels, "attachments": attachments, "body_text": body_text}
    return full_text[:300000], meta


def upsert_gmail_attachment_manifest(
    *,
    message_id: str,
    parent_file_id: int | None,
    headers: dict,
    message_ts: float,
    attachments: list[dict],
) -> dict:
    if not attachments:
        return {"count": 0, "pending": 0, "metadata_only": 0}
    now = now_ts()
    pending = metadata_only = 0
    conn = get_conn()
    cur = conn.cursor()
    for item in attachments:
        filename = clean_filename(item.get("filename") or "attachment")
        attachment_id = str(item.get("attachment_id") or "").strip()
        status = "pending" if attachment_id else "metadata_only"
        error = "" if attachment_id else "Attachment has inline data but no Gmail attachment id to fetch later."
        if status == "pending":
            pending += 1
        else:
            metadata_only += 1
        cur.execute(
            """
            INSERT INTO gmail_attachments (
                message_id, attachment_id, parent_file_id, file_id,
                subject, sender, message_date, message_ts,
                filename, mime_type, size_bytes, local_path, status, error,
                created_ts, updated_ts
            )
            VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?)
            ON CONFLICT(message_id, attachment_id, filename) DO UPDATE SET
                parent_file_id=excluded.parent_file_id,
                subject=excluded.subject,
                sender=excluded.sender,
                message_date=excluded.message_date,
                message_ts=excluded.message_ts,
                mime_type=excluded.mime_type,
                size_bytes=excluded.size_bytes,
                updated_ts=excluded.updated_ts
            """,
            (
                message_id,
                attachment_id,
                parent_file_id,
                headers.get("subject") or "(no subject)",
                headers.get("from") or "",
                headers.get("date") or "",
                message_ts,
                filename,
                item.get("mime_type") or "",
                int(item.get("size") or 0),
                status,
                error,
                now,
                now,
            ),
        )
    conn.commit()
    conn.close()
    return {"count": len(attachments), "pending": pending, "metadata_only": metadata_only}


def gmail_message_is_important(message: dict) -> bool:
    labels = {str(label).upper() for label in (message.get("labelIds") or [])}
    return bool(labels & {"IMPORTANT", "STARRED"})


def gmail_summary(message: dict, meta: dict) -> str:
    headers = meta.get("headers") or {}
    subject = headers.get("subject") or "(no subject)"
    sender = headers.get("from") or "unknown sender"
    to = headers.get("to") or "unknown recipient"
    date = headers.get("date") or ""
    snippet = str(message.get("snippet") or meta.get("body_text") or "").strip()
    if len(snippet) > 260:
        snippet = snippet[:257].rstrip() + "..."
    bits = [f"Email from {sender} to {to}"]
    if date:
        bits.append(f"dated {date}")
    bits.append(f"about {subject}.")
    if snippet:
        bits.append(snippet)
    return " ".join(bits)[:900]


def archive_gmail_metadata_message(message: dict, *, sync_embeddings: bool = True) -> dict:
    message_id = str(message.get("id") or "").strip()
    if not message_id:
        return {"imported": False, "reason": "missing_message_id"}

    text, meta = gmail_metadata_text(message)
    headers = meta.get("headers") or {}
    path = gmail_message_path(message_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    stat = path.stat()
    ts = gmail_internal_ts(message)
    record = {
        "path": str(path),
        "rel_path": safe_rel_path(path, DATA_DIR),
        "name": gmail_display_name(headers, message_id),
        "ext": ".txt",
        "mime_type": "text/plain",
        "size_bytes": stat.st_size,
        "sha256": sha256_file(path),
        "created_ts": ts,
        "modified_ts": ts,
        "indexed_ts": now_ts(),
        "category": "email",
        "summary": gmail_summary(message, meta),
        "extracted_text": text[:200000],
        "suggested_folder": "Cloud/Gmail",
        "preview_path": str(path),
        "thumb_path": None,
        "duplicate_of": None,
        "deleted_candidate": 0,
        "notes": "gmail_metadata_import",
    }
    from app.autotagging import apply_auto_tags
    from app.indexer import upsert_file_record

    file_id = upsert_file_record(record)
    record["id"] = file_id
    tags = apply_auto_tags(record, extra_tags=gmail_label_tags(meta.get("labels") or []))
    embedding = {"synced": False, "reason": "sync_disabled"}
    if sync_embeddings:
        from app.chat_engine import sync_file_embedding_by_id

        embedding = sync_file_embedding_by_id(file_id)
    message_manifest = upsert_gmail_message_manifest(
        message=message,
        headers=headers,
        message_ts=ts,
        file_id=file_id,
        body_status="metadata_only",
        attachment_status="unknown",
        attachment_count=0,
        body_local_path=str(path),
    )
    return {
        "imported": True,
        "file_id": file_id,
        "path": str(path),
        "subject": headers.get("subject") or "(no subject)",
        "body_status": "metadata_only",
        "message": message_manifest,
        "tags": tags,
        "embedding": embedding,
        "attachments": {"count": 0, "pending": 0, "metadata_only": 0},
        "attachment_download": {"selected": 0, "downloaded": 0, "indexed": 0, "failed": 0},
    }


def archive_gmail_message(
    message: dict,
    *,
    sync_embeddings: bool = True,
    attachment_mode: str = "metadata_only",
    attachment_max_bytes: int | None = None,
    body_status: str = "downloaded",
) -> dict:
    message_id = str(message.get("id") or "").strip()
    if not message_id:
        return {"imported": False, "reason": "missing_message_id"}

    text, meta = gmail_message_text(message)
    headers = meta.get("headers") or {}
    path = gmail_message_path(message_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    stat = path.stat()
    ts = gmail_internal_ts(message)
    record = {
        "path": str(path),
        "rel_path": safe_rel_path(path, DATA_DIR),
        "name": gmail_display_name(headers, message_id),
        "ext": ".txt",
        "mime_type": "text/plain",
        "size_bytes": stat.st_size,
        "sha256": sha256_file(path),
        "created_ts": ts,
        "modified_ts": ts,
        "indexed_ts": now_ts(),
        "category": "email",
        "summary": gmail_summary(message, meta),
        "extracted_text": text[:200000],
        "suggested_folder": "Cloud/Gmail",
        "preview_path": str(path),
        "thumb_path": None,
        "duplicate_of": None,
        "deleted_candidate": 0,
        "notes": "gmail_import",
    }
    from app.autotagging import apply_auto_tags
    from app.indexer import upsert_file_record

    file_id = upsert_file_record(record)
    record["id"] = file_id
    attachment_manifest = upsert_gmail_attachment_manifest(
        message_id=message_id,
        parent_file_id=file_id,
        headers=headers,
        message_ts=ts,
        attachments=meta.get("attachments") or [],
    )
    message_manifest = upsert_gmail_message_manifest(
        message=message,
        headers=headers,
        message_ts=ts,
        file_id=file_id,
        body_status=body_status or "downloaded",
        attachment_status=gmail_attachment_status(attachment_manifest),
        attachment_count=int(attachment_manifest.get("count") or 0),
        body_local_path=str(path),
    )
    tags = apply_auto_tags(record, extra_tags=gmail_label_tags(meta.get("labels") or []))
    embedding = {"synced": False, "reason": "sync_disabled"}
    if sync_embeddings:
        from app.chat_engine import sync_file_embedding_by_id

        embedding = sync_file_embedding_by_id(file_id)
    attachment_download = {"selected": 0, "downloaded": 0, "indexed": 0, "failed": 0}
    mode = attachment_mode if attachment_mode in GMAIL_ATTACHMENT_MODES else "metadata_only"
    if mode == "all_attachments" or (mode == "important_attachments" and gmail_message_is_important(message)):
        attachment_download = download_gmail_attachments(
            {
                "message_id": message_id,
                "status": "pending",
                "max_bytes": attachment_max_bytes,
                "sync_embeddings": sync_embeddings,
                "limit": 100,
            },
            account=None,
        )
    return {
        "imported": True,
        "file_id": file_id,
        "path": str(path),
        "subject": headers.get("subject") or "(no subject)",
        "body_status": body_status or "downloaded",
        "message": message_manifest,
        "tags": tags,
        "embedding": embedding,
        "attachments": attachment_manifest,
        "attachment_download": attachment_download,
    }


def gmail_list_url(page_size: int, page_token: str | None, query: str, include_spam_trash: bool) -> str:
    params = {
        "maxResults": max(1, min(int(page_size), 500)),
        "includeSpamTrash": "true" if include_spam_trash else "false",
    }
    if page_token:
        params["pageToken"] = page_token
    if query:
        params["q"] = query
    return f"https://gmail.googleapis.com/gmail/v1/users/me/messages?{urllib.parse.urlencode(params)}"


def fetch_gmail_message(
    token: str,
    message_id: str,
    *,
    fmt: str = "full",
    metadata_headers: list[str] | None = None,
) -> dict:
    params: dict[str, object] = {"format": fmt}
    if metadata_headers:
        params["metadataHeaders"] = list(metadata_headers)
    url = (
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/"
        f"{urllib.parse.quote(message_id, safe='')}?{urllib.parse.urlencode(params, doseq=True)}"
    )
    return google_get_json(url, token, timeout=35)


def fetch_gmail_attachment(token: str, message_id: str, attachment_id: str) -> dict:
    url = (
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/"
        f"{urllib.parse.quote(message_id, safe='')}/attachments/{urllib.parse.quote(attachment_id, safe='')}"
    )
    return google_get_json(url, token, timeout=35)


def fetch_gmail_message_with_refresh(account: dict, token: str, message_id: str, **kwargs) -> tuple[dict, str]:
    try:
        return fetch_gmail_message(token, message_id, **kwargs), token
    except Exception as error:
        if not google_api_unauthorized(error):
            raise
        token = google_access_token(account, force_refresh=True)
        return fetch_gmail_message(token, message_id, **kwargs), token


def fetch_gmail_attachment_with_refresh(account: dict, token: str, message_id: str, attachment_id: str) -> tuple[dict, str]:
    try:
        return fetch_gmail_attachment(token, message_id, attachment_id), token
    except Exception as error:
        if not google_api_unauthorized(error):
            raise
        token = google_access_token(account, force_refresh=True)
        return fetch_gmail_attachment(token, message_id, attachment_id), token


def _select_gmail_message_rows(options: dict) -> list[dict]:
    ids = options.get("ids")
    clean_ids = [int(item) for item in ids] if isinstance(ids, list) and ids else None
    payload = list_gmail_messages(
        status=options.get("status") if options.get("status") is not None else "metadata_only",
        query=options.get("query"),
        limit=int(options.get("limit") or 25),
        ids=clean_ids,
    )
    return payload["messages"]


def _mark_gmail_message(row_id: int, **fields) -> None:
    if not fields:
        return
    fields["updated_ts"] = now_ts()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    params = [*fields.values(), int(row_id)]
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"UPDATE gmail_messages SET {assignments} WHERE id = ?", params)
    conn.commit()
    conn.close()


def download_gmail_message_bodies(options: dict | None = None, *, account: dict | None = None) -> dict:
    opts = options or {}
    settings = read_cloud_sync_settings()
    google_account = account or (settings.get("accounts") or {}).get("google") or {}
    if not account_ready_for_gmail(google_account):
        raise ValueError("Connect Google OAuth before downloading Gmail message bodies.")
    rows = _select_gmail_message_rows(opts)
    sync_embeddings = bool(opts.get("sync_embeddings", True))
    attachment_mode = str(opts.get("attachment_mode") or "metadata_only")
    if attachment_mode not in GMAIL_ATTACHMENT_MODES:
        attachment_mode = "metadata_only"
    attachment_max_mb = opts.get("attachment_max_mb")
    attachment_max_bytes = opts.get("attachment_max_bytes")
    if attachment_max_bytes is None and attachment_max_mb is not None:
        attachment_max_bytes = int(float(attachment_max_mb or 0) * 1024 * 1024)
    token = google_access_token(google_account)
    selected = len(rows)
    processed = downloaded = failed = embedding_synced = 0
    attachment_downloaded = attachment_indexed = attachment_failed = 0
    errors: list[dict] = []

    for row in rows:
        processed += 1
        label = row.get("subject") or row.get("message_id") or ""
        update_gmail_body_job(processed_count=processed, current_message=label)
        row_id = int(row["id"])
        message_id = str(row.get("message_id") or "").strip()
        if not message_id:
            failed += 1
            _mark_gmail_message(row_id, body_status="failed", error="Gmail message id is missing.")
            update_gmail_body_job(failed_count=failed, last_error="Gmail message id is missing.")
            continue
        try:
            message, token = fetch_gmail_message_with_refresh(google_account, token, message_id, fmt="full")
            archived = archive_gmail_message(
                message,
                sync_embeddings=sync_embeddings,
                attachment_mode=attachment_mode,
                attachment_max_bytes=attachment_max_bytes,
                body_status="downloaded",
            )
            if archived.get("imported"):
                downloaded += 1
                if (archived.get("embedding") or {}).get("synced"):
                    embedding_synced += 1
                attachment_result = archived.get("attachment_download") or {}
                attachment_downloaded += int(attachment_result.get("downloaded") or 0)
                attachment_indexed += int(attachment_result.get("indexed") or 0)
                attachment_failed += int(attachment_result.get("failed") or 0)
                update_gmail_body_job(downloaded_count=downloaded)
            else:
                failed += 1
                reason = str(archived.get("reason") or "Gmail body was not archived.")[:1000]
                _mark_gmail_message(row_id, body_status="failed", error=reason)
                update_gmail_body_job(failed_count=failed, last_error=reason)
        except Exception as error:
            failed += 1
            message = str(error)[:1000]
            errors.append({"id": row_id, "message_id": message_id, "error": message})
            _mark_gmail_message(row_id, body_status="failed", error=message)
            update_gmail_body_job(failed_count=failed, last_error=message)

    return {
        "selected": selected,
        "processed": processed,
        "downloaded": downloaded,
        "failed": failed,
        "embedding_synced": embedding_synced,
        "attachment_mode": attachment_mode,
        "attachment_downloaded": attachment_downloaded,
        "attachment_indexed": attachment_indexed,
        "attachment_failed": attachment_failed,
        "errors": errors[:10],
        "summary": gmail_message_summary(),
    }


def gmail_body_download_worker(options: dict) -> None:
    try:
        selected = len(_select_gmail_message_rows(options))
        reset_gmail_body_job(options, selected_count=selected)
        result = download_gmail_message_bodies(options)
        finish_gmail_body_job(result=result)
    except Exception as error:
        finish_gmail_body_job(error=str(error))


def start_gmail_body_download(options: dict | None = None) -> dict:
    if gmail_body_job_snapshot().get("running"):
        status = cloud_sync_status()
        status["started"] = False
        return status
    opts = options or {}
    settings = read_cloud_sync_settings()
    account = (settings.get("accounts") or {}).get("google") or {}
    if not account_ready_for_gmail(account):
        raise ValueError("Connect Google OAuth before downloading Gmail message bodies.")
    selected = len(_select_gmail_message_rows(opts))
    if selected <= 0:
        status = cloud_sync_status()
        status["started"] = False
        status["body_download_result"] = {"selected": 0, "reason": "No matching Gmail metadata records need body download."}
        return status
    reset_gmail_body_job(opts, selected_count=selected)
    thread = threading.Thread(target=gmail_body_download_worker, args=(dict(opts),), daemon=True)
    thread.start()
    status = cloud_sync_status()
    status["started"] = True
    return status


def _select_gmail_attachment_rows(options: dict) -> list[dict]:
    ids = options.get("ids")
    clean_ids = [int(item) for item in ids] if isinstance(ids, list) and ids else None
    payload = list_gmail_attachments(
        status=options.get("status") if options.get("status") is not None else "pending",
        query=options.get("query"),
        message_id=options.get("message_id"),
        limit=int(options.get("limit") or 25),
        ids=clean_ids,
    )
    return payload["attachments"]


def _mark_gmail_attachment(row_id: int, **fields) -> None:
    if not fields:
        return
    fields["updated_ts"] = now_ts()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    params = [*fields.values(), int(row_id)]
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"UPDATE gmail_attachments SET {assignments} WHERE id = ?", params)
    conn.commit()
    conn.close()


def _index_gmail_attachment(path: Path, row: dict, *, sync_embeddings: bool) -> dict:
    from app.indexer import index_file

    record = index_file(path, force=True) or {}
    file_id = int(record.get("id") or 0)
    linked_duplicate_keeper = False
    duplicate_of = str(record.get("duplicate_of") or "").strip()
    if file_id and duplicate_of and int(record.get("deleted_candidate") or 0):
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM files WHERE path = ? AND COALESCE(deleted_candidate, 0) = 0", (duplicate_of,))
        keeper = cur.fetchone()
        conn.close()
        if keeper:
            record = dict(keeper)
            file_id = int(record.get("id") or 0)
            linked_duplicate_keeper = True
    if file_id and not linked_duplicate_keeper:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE files
            SET suggested_folder = 'Cloud/Gmail Attachments',
                notes = ?
            WHERE id = ?
            """,
            (f"gmail_attachment:{row.get('message_id')}", file_id),
        )
        conn.commit()
        conn.close()
    if file_id and sync_embeddings and not (record.get("embedding") or {}).get("synced"):
        from app.chat_engine import sync_file_embedding_by_id

        record["embedding"] = sync_file_embedding_by_id(file_id)
    return record


def download_gmail_attachments(options: dict | None = None, *, account: dict | None = None) -> dict:
    opts = options or {}
    settings = read_cloud_sync_settings()
    google_account = account or (settings.get("accounts") or {}).get("google") or {}
    if not account_ready_for_gmail(google_account):
        raise ValueError("Connect Google OAuth before downloading Gmail attachments.")
    rows = _select_gmail_attachment_rows(opts)
    max_bytes = opts.get("max_bytes")
    if max_bytes is None and opts.get("max_mb") is not None:
        max_bytes = int(float(opts.get("max_mb") or 0) * 1024 * 1024)
    max_bytes = int(max_bytes or 0)
    sync_embeddings = bool(opts.get("sync_embeddings", True))
    token = google_access_token(google_account)
    selected = len(rows)
    downloaded = indexed = skipped = failed = processed = 0
    errors: list[dict] = []

    for row in rows:
        processed += 1
        update_gmail_attachment_job(processed_count=processed, current_attachment=row.get("filename") or "")
        row_id = int(row["id"])
        size = int(row.get("size_bytes") or 0)
        if max_bytes > 0 and size > max_bytes:
            skipped += 1
            _mark_gmail_attachment(row_id, status="skipped", error=f"Attachment exceeds max size ({size} > {max_bytes}).")
            update_gmail_attachment_job(skipped_count=skipped)
            continue
        attachment_id = str(row.get("attachment_id") or "").strip()
        if not attachment_id:
            skipped += 1
            _mark_gmail_attachment(row_id, status="metadata_only", error="Attachment has no downloadable Gmail attachment id.")
            update_gmail_attachment_job(skipped_count=skipped)
            continue
        try:
            payload, token = fetch_gmail_attachment_with_refresh(google_account, token, row["message_id"], attachment_id)
            content = gmail_b64decode_bytes(payload.get("data"))
            if not content:
                raise RuntimeError("Gmail attachment payload was empty.")
            path = gmail_attachment_path(row["message_id"], attachment_id, row.get("filename") or "attachment")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            record = _index_gmail_attachment(path, row, sync_embeddings=sync_embeddings)
            file_id = int(record.get("id") or 0) if record else 0
            downloaded += 1
            indexed += 1 if file_id else 0
            _mark_gmail_attachment(
                row_id,
                status="downloaded" if file_id else "downloaded_unindexed",
                local_path=str(path),
                file_id=file_id or None,
                error="",
            )
            update_gmail_attachment_job(downloaded_count=downloaded, indexed_count=indexed)
        except Exception as error:
            failed += 1
            message = str(error)[:1000]
            errors.append({"id": row_id, "filename": row.get("filename") or "", "error": message})
            _mark_gmail_attachment(row_id, status="failed", error=message)
            update_gmail_attachment_job(failed_count=failed, last_error=message)

    return {
        "selected": selected,
        "processed": processed,
        "downloaded": downloaded,
        "indexed": indexed,
        "skipped": skipped,
        "failed": failed,
        "errors": errors[:10],
        "summary": gmail_attachment_summary(),
    }


def gmail_attachment_download_worker(options: dict) -> None:
    try:
        selected = len(_select_gmail_attachment_rows(options))
        reset_gmail_attachment_job(options, selected_count=selected)
        result = download_gmail_attachments(options)
        finish_gmail_attachment_job(result=result)
    except Exception as error:
        finish_gmail_attachment_job(error=str(error))


def start_gmail_attachment_download(options: dict | None = None) -> dict:
    if gmail_attachment_job_snapshot().get("running"):
        status = cloud_sync_status()
        status["started"] = False
        return status
    opts = options or {}
    settings = read_cloud_sync_settings()
    account = (settings.get("accounts") or {}).get("google") or {}
    if not account_ready_for_gmail(account):
        raise ValueError("Connect Google OAuth before downloading Gmail attachments.")
    selected = len(_select_gmail_attachment_rows(opts))
    if selected <= 0:
        status = cloud_sync_status()
        status["started"] = False
        status["attachment_download_result"] = {"selected": 0, "reason": "No matching Gmail attachments are pending download."}
        return status
    reset_gmail_attachment_job(opts, selected_count=selected)
    thread = threading.Thread(target=gmail_attachment_download_worker, args=(dict(opts),), daemon=True)
    thread.start()
    status = cloud_sync_status()
    status["started"] = True
    return status


def import_gmail_archive(options: dict | None = None) -> dict:
    opts = options or {}
    settings = read_cloud_sync_settings()
    accounts = settings.setdefault("accounts", {})
    account = accounts.get("google") or {}
    if not account_ready_for_gmail(account):
        raise ValueError("Connect Google OAuth before importing Gmail.")

    query = str(opts.get("query") if opts.get("query") is not None else GMAIL_IMPORT_DEFAULT_QUERY).strip()
    max_results = int(opts.get("max_results") if opts.get("max_results") is not None else 0)
    include_spam_trash = bool(opts.get("include_spam_trash"))
    sync_embeddings = bool(opts.get("sync_embeddings", True))
    message_mode = str(opts.get("message_mode") or "metadata_only")
    if message_mode not in GMAIL_MESSAGE_MODES:
        message_mode = "metadata_only"
    attachment_mode = str(opts.get("attachment_mode") or "metadata_only")
    if attachment_mode not in GMAIL_ATTACHMENT_MODES:
        attachment_mode = "metadata_only"
    attachment_max_mb = opts.get("attachment_max_mb")
    attachment_max_bytes = opts.get("attachment_max_bytes")
    if attachment_max_bytes is None and attachment_max_mb is not None:
        attachment_max_bytes = int(float(attachment_max_mb or 0) * 1024 * 1024)
    should_stop = opts.get("should_stop") if callable(opts.get("should_stop")) else None
    page_size = max(1, min(int(opts.get("page_size") or 100), 500))
    remaining = None if max_results <= 0 else max_results
    token = google_access_token(account)
    page_token = str(opts.get("page_token") or "").strip() or None
    start_page_token = page_token
    next_page_token = None
    scanned = imported = updated = skipped = failed = embedding_synced = body_downloaded = 0
    attachment_downloaded = attachment_indexed = attachment_failed = 0
    errors: list[dict] = []
    total_estimate = None
    stopped = False

    while True:
        if remaining is not None and remaining <= 0:
            break
        if should_stop and should_stop():
            stopped = True
            break
        current_page_size = min(page_size, remaining) if remaining is not None else page_size
        current_page_token = page_token
        list_url = gmail_list_url(current_page_size, page_token, query, include_spam_trash)
        try:
            listing = google_get_json(list_url, token, timeout=35)
        except Exception as error:
            if not google_api_unauthorized(error):
                raise
            token = google_access_token(account, force_refresh=True)
            listing = google_get_json(list_url, token, timeout=35)
        next_page_token = listing.get("nextPageToken")
        if total_estimate is None:
            total_estimate = listing.get("resultSizeEstimate")
            update_gmail_import_job(total_estimate=total_estimate)
        refs = listing.get("messages") or []
        if not refs:
            break
        for ref in refs:
            if should_stop and should_stop():
                stopped = True
                break
            message_id = str(ref.get("id") or "").strip()
            if not message_id:
                skipped += 1
                continue
            scanned += 1
            update_gmail_import_job(scanned_count=scanned, current_message=message_id)
            try:
                try:
                    if message_mode == "full":
                        message = fetch_gmail_message(token, message_id, fmt="full")
                        archived = archive_gmail_message(
                            message,
                            sync_embeddings=sync_embeddings,
                            attachment_mode=attachment_mode,
                            attachment_max_bytes=attachment_max_bytes,
                            body_status="downloaded",
                        )
                    else:
                        message = fetch_gmail_message(
                            token,
                            message_id,
                            fmt="metadata",
                            metadata_headers=GMAIL_METADATA_HEADERS,
                        )
                        archived = archive_gmail_metadata_message(message, sync_embeddings=sync_embeddings)
                except Exception as error:
                    if not google_api_unauthorized(error):
                        raise
                    token = google_access_token(account, force_refresh=True)
                    if message_mode == "full":
                        message = fetch_gmail_message(token, message_id, fmt="full")
                        archived = archive_gmail_message(
                            message,
                            sync_embeddings=sync_embeddings,
                            attachment_mode=attachment_mode,
                            attachment_max_bytes=attachment_max_bytes,
                            body_status="downloaded",
                        )
                    else:
                        message = fetch_gmail_message(
                            token,
                            message_id,
                            fmt="metadata",
                            metadata_headers=GMAIL_METADATA_HEADERS,
                        )
                        archived = archive_gmail_metadata_message(message, sync_embeddings=sync_embeddings)
                if archived.get("imported"):
                    imported += 1
                    updated += 1
                    if archived.get("body_status") == "downloaded":
                        body_downloaded += 1
                    if (archived.get("embedding") or {}).get("synced"):
                        embedding_synced += 1
                    attachment_result = archived.get("attachment_download") or {}
                    attachment_downloaded += int(attachment_result.get("downloaded") or 0)
                    attachment_indexed += int(attachment_result.get("indexed") or 0)
                    attachment_failed += int(attachment_result.get("failed") or 0)
                    update_gmail_import_job(
                        imported_count=imported,
                        updated_count=updated,
                        body_downloaded=body_downloaded,
                        embedding_synced=embedding_synced,
                        attachment_downloaded=attachment_downloaded,
                        attachment_indexed=attachment_indexed,
                        attachment_failed=attachment_failed,
                        current_message=archived.get("subject") or message_id,
                    )
                else:
                    skipped += 1
                    update_gmail_import_job(skipped_count=skipped)
            except Exception as error:
                failed += 1
                errors.append({"message_id": message_id, "error": str(error)[:500]})
                update_gmail_import_job(failed_count=failed, last_error=str(error)[:1000])
            if remaining is not None:
                remaining -= 1
                if remaining <= 0:
                    break
            if should_stop and should_stop():
                stopped = True
                break
        if stopped:
            next_page_token = current_page_token
            break
        if remaining is not None and remaining <= 0:
            break
        page_token = next_page_token
        if not page_token:
            break

    status = "partial" if stopped else ("connected" if failed == 0 else ("partial" if imported else "error"))
    result = {
        "status": status,
        "query": query,
        "max_results": max_results,
        "page_token": start_page_token,
        "next_page_token": next_page_token,
        "has_more": bool(next_page_token or stopped),
        "stopped": stopped,
        "include_spam_trash": include_spam_trash,
        "sync_embeddings": sync_embeddings,
        "message_mode": message_mode,
        "body_downloaded": body_downloaded,
        "attachment_mode": attachment_mode,
        "attachment_max_bytes": attachment_max_bytes,
        "total_estimate": total_estimate,
        "scanned_count": scanned,
        "imported_count": imported,
        "updated_count": updated,
        "skipped_count": skipped,
        "failed_count": failed,
        "embedding_synced": embedding_synced,
        "attachment_downloaded": attachment_downloaded,
        "attachment_indexed": attachment_indexed,
        "attachment_failed": attachment_failed,
        "errors": errors[:10],
        "last_import_ts": now_ts(),
        "import_dir": str(GMAIL_IMPORT_DIR),
    }
    account["gmail"] = {
        **result,
        "summary": (
            f"Gmail import scanned {scanned} message(s), indexed {imported}, failed {failed}. "
            f"Bodies downloaded {body_downloaded}. "
            f"Attachments downloaded {attachment_downloaded}, indexed {attachment_indexed}."
        ),
        "last_error": "; ".join(item["error"] for item in errors[:3]),
    }
    accounts["google"] = account
    write_cloud_sync_settings(settings)
    return result


def gmail_import_worker(options: dict) -> None:
    try:
        with GMAIL_IMPORT_LOCK:
            result = import_gmail_archive(options)
        finish_gmail_import_job(result=result)
    except Exception as error:
        settings = read_cloud_sync_settings()
        account = (settings.setdefault("accounts", {}).get("google") or {})
        account["gmail"] = {
            **(account.get("gmail") or {}),
            "status": "error",
            "summary": f"Gmail archive import issue: {error}",
            "last_error": str(error)[:1000],
            "last_import_ts": now_ts(),
        }
        settings.setdefault("accounts", {})["google"] = account
        write_cloud_sync_settings(settings)
        finish_gmail_import_job(error=str(error))


def start_gmail_import(options: dict | None = None) -> dict:
    opts = options or {}
    settings = read_cloud_sync_settings()
    account = (settings.get("accounts") or {}).get("google") or {}
    if not account_ready_for_gmail(account):
        raise ValueError("Connect Google OAuth before importing Gmail.")
    if gmail_import_job_snapshot().get("running"):
        status = cloud_sync_status()
        status["started"] = False
        return status
    reset_gmail_import_job(opts)
    thread = threading.Thread(target=gmail_import_worker, args=(dict(opts),), daemon=True)
    thread.start()
    status = cloud_sync_status()
    status["started"] = True
    return status


def sync_provider_calendar(account: dict) -> list[dict]:
    provider = account.get("provider")
    if provider == "icloud":
        return fetch_icloud_events(account)
    if provider == "google":
        return fetch_google_events(account)
    raise ValueError(f"Unsupported calendar provider `{provider}`.")


def sync_calendar(provider: str | None = None) -> dict:
    if not CALENDAR_SYNC_LOCK.acquire(blocking=False):
        status = cloud_sync_status()
        status["sync_running"] = True
        return status
    try:
        return _sync_calendar(provider)
    finally:
        CALENDAR_SYNC_LOCK.release()


def _sync_calendar(provider: str | None = None) -> dict:
    settings = read_cloud_sync_settings()
    accounts = settings.setdefault("accounts", {})
    selected = [provider.strip().lower()] if provider else list(accounts.keys())
    for key in selected:
        account = accounts.get(key)
        if not account or not account.get("calendar_enabled", True):
            continue
        try:
            if not account_ready_for_calendar(account):
                raise RuntimeError("Calendar credentials are incomplete.")
            events = sync_provider_calendar(account)
            account["calendar"] = {
                "status": "connected",
                "last_sync_ts": now_ts(),
                "events": events,
                "event_count": len(events),
            }
            account["status"] = "connected"
            account["summary"] = f"{provider_label(key)} Calendar synced {len(events)} upcoming event(s)."
        except Exception as error:
            account["calendar"] = {
                **(account.get("calendar") or {}),
                "status": "error",
                "last_error": str(error),
                "last_sync_ts": now_ts(),
            }
            account["status"] = "error"
            account["summary"] = f"{provider_label(key)} Calendar sync issue: {error}"
        account["updated_ts"] = now_ts()
        accounts[key] = account
    write_cloud_sync_settings(settings)
    return cloud_sync_status()


def scheduler_due(settings: dict | None = None) -> bool:
    data = settings or read_cloud_sync_settings()
    schedule = data.get("schedule") or {}
    if not schedule.get("enabled"):
        return False
    if not ready_calendar_accounts(data):
        return False
    last_auto = schedule.get("last_auto_sync_ts")
    if not last_auto:
        return True
    interval_seconds = int(schedule.get("interval_minutes") or DEFAULT_SYNC_INTERVAL_MINUTES) * 60
    return now_ts() >= float(last_auto) + interval_seconds


def record_scheduler_result(status: str, error: str = "") -> dict:
    settings = read_cloud_sync_settings()
    schedule = dict(settings.get("schedule") or default_cloud_sync_settings()["schedule"])
    schedule.update(
        {
            "last_auto_sync_ts": now_ts(),
            "last_auto_sync_status": status,
            "last_auto_sync_error": str(error or "")[:500],
        }
    )
    settings["schedule"] = schedule
    write_cloud_sync_settings(settings)
    return cloud_sync_status()


def run_scheduled_calendar_sync_once() -> dict:
    settings = read_cloud_sync_settings()
    if not scheduler_due(settings):
        return cloud_sync_status()
    try:
        result = sync_calendar()
        errors = [
            account.get("calendar", {}).get("last_error")
            for account in (result.get("accounts") or {}).values()
            if account.get("calendar", {}).get("status") == "error"
        ]
        record_scheduler_result("error" if errors else "synced", "; ".join(error for error in errors if error))
        return cloud_sync_status()
    except Exception as error:
        return record_scheduler_result("error", str(error))


def calendar_sync_scheduler_loop() -> None:
    time.sleep(15)
    while True:
        run_scheduled_calendar_sync_once()
        time.sleep(60)


def start_calendar_sync_scheduler() -> bool:
    global SCHEDULER_STARTED
    with SCHEDULER_LOCK:
        if SCHEDULER_STARTED:
            return False
        SCHEDULER_STARTED = True
    thread = threading.Thread(target=calendar_sync_scheduler_loop, daemon=True)
    thread.start()
    return True


def calendar_event_brief(event: dict) -> str:
    bits = []
    if event.get("start"):
        bits.append(str(event.get("start")))
    bits.append(str(event.get("title") or "(Untitled event)"))
    if event.get("location"):
        bits.append(str(event.get("location")))
    return " | ".join(bits)


def calendar_schedule_groups(accounts: dict, provider_filter: str | None = None, *, limit_per_calendar: int = 8) -> list[dict]:
    grouped: dict[tuple[str, str], dict] = {}
    for provider, account in (accounts or {}).items():
        if provider_filter and provider != provider_filter:
            continue
        if not account.get("calendar_enabled", True):
            continue
        calendar = account.get("calendar") or {}
        if calendar.get("status") != "connected":
            continue
        for event in calendar.get("events") or []:
            calendar_name = event.get("calendar") or provider_label(provider)
            key = (provider, calendar_name)
            group = grouped.setdefault(
                key,
                {
                    "provider": provider,
                    "provider_label": account.get("label") or provider_label(provider),
                    "calendar": calendar_name,
                    "events": [],
                },
            )
            group["events"].append(event)

    groups = []
    for group in grouped.values():
        events = sorted(group["events"], key=lambda item: item.get("start_ts") or 0)
        next_event = events[0] if events else None
        groups.append(
            {
                **group,
                "event_count": len(events),
                "next_event": next_event,
                "next_start_ts": next_event.get("start_ts") if next_event else None,
                "next_summary": calendar_event_brief(next_event) if next_event else "",
                "events": events[: max(1, min(int(limit_per_calendar), 20))],
            }
        )
    return sorted(groups, key=lambda item: item.get("next_start_ts") or 0)


def calendar_context() -> dict:
    status = cloud_sync_status()
    accounts = status.get("accounts") or {}
    providers = [account.get("label") or provider_label(key) for key, account in accounts.items() if account.get("calendar_enabled")]
    connected = [account for account in accounts.values() if account.get("calendar", {}).get("status") == "connected"]
    upcoming = status.get("upcoming_events") or []
    calendar_groups = calendar_schedule_groups(accounts)
    icloud_calendar_groups = calendar_schedule_groups(accounts, "icloud")
    if connected:
        summary = f"{len(upcoming)} upcoming synced calendar event(s) from {len(connected)} provider(s)."
        state = "connected"
    elif providers:
        summary = "Calendar providers are configured but need a successful sync."
        state = "needs_sync"
    else:
        summary = "Calendar provider not connected yet."
        state = "not_connected"
    return {
        "providers": providers,
        "sync_enabled": bool(providers),
        "chat_aware": True,
        "status": state,
        "summary": summary,
        "upcoming_events": upcoming[:12],
        "primary_provider": "icloud" if icloud_calendar_groups else (calendar_groups[0]["provider"] if calendar_groups else None),
        "calendar_names": [group["calendar"] for group in (icloud_calendar_groups or calendar_groups)],
        "calendar_groups": calendar_groups,
        "icloud_calendar_groups": icloud_calendar_groups,
        "can_create_events": False,
        "write_policy": "read_only_context",
        "accounts": accounts,
        "updated_ts": status.get("updated_ts"),
    }
