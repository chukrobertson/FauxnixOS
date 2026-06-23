from __future__ import annotations

import ctypes
import os
import time
from pathlib import Path

DRIVE_UNKNOWN = 0
DRIVE_NO_ROOT_DIR = 1
DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
DRIVE_CDROM = 5
DRIVE_RAMDISK = 6

KIND_LABELS = {
    "empty": "Empty",
    "local_fixed": "Local",
    "removable": "Removable",
    "network": "Network",
    "unavailable": "Unavailable",
    "unknown": "Unknown",
}

HEALTH_LABELS = {
    "available": "Available",
    "unavailable": "Unavailable",
    "empty": "Empty",
}

CHAT_POLICY_LABELS = {
    "chat_aware": "Chat aware",
    "chat_ignored": "Chat ignored",
}

INDEX_POLICY_LABELS = {
    "full": "Full index",
    "metadata_only": "Metadata only",
    "skip": "Skipped",
}

METADATA_ONLY_NOTE = "Metadata-only source; excluded from chat-aware indexing"


def normalize_source_path(path_text: str | Path) -> str:
    return str(Path(path_text).expanduser().resolve(strict=False))


def unc_root(path_text: str) -> str:
    text = str(path_text).replace("/", "\\")
    if not text.startswith("\\\\"):
        return ""
    parts = [part for part in text.strip("\\").split("\\") if part]
    if len(parts) < 2:
        return "\\\\"
    return f"\\\\{parts[0]}\\{parts[1]}\\"


def drive_probe_root(path_text: str | Path) -> str:
    text = str(path_text)
    unc = unc_root(text)
    if unc:
        return unc
    anchor = Path(text).anchor
    if anchor:
        return anchor
    return str(Path(text).expanduser().resolve(strict=False).anchor or text)


def windows_drive_type(path_text: str | Path) -> int | None:
    if os.name != "nt":
        return None
    root = drive_probe_root(path_text)
    if not root:
        return None
    try:
        return int(ctypes.windll.kernel32.GetDriveTypeW(str(root)))
    except Exception:
        return None


def source_kind(path_text: str | Path) -> str:
    text = str(path_text or "").strip()
    if not text:
        return "empty"
    if unc_root(text):
        return "network"

    drive_type = windows_drive_type(text)
    if drive_type == DRIVE_FIXED:
        return "local_fixed"
    if drive_type == DRIVE_REMOVABLE:
        return "removable"
    if drive_type == DRIVE_REMOTE:
        return "network"
    if drive_type in {DRIVE_NO_ROOT_DIR, DRIVE_CDROM}:
        return "unavailable"
    if drive_type in {DRIVE_UNKNOWN, None}:
        if os.name != "nt":
            return "local_fixed" if Path(text).expanduser().exists() else "unavailable"
        return "unknown"
    return "unknown"


def path_available(path_text: str | Path) -> bool:
    try:
        return bool(str(path_text or "").strip()) and Path(path_text).expanduser().exists()
    except OSError:
        return False


def source_policy(path_text: str | Path, preferred_chat_policy: str = "chat_aware") -> dict:
    text = str(path_text or "").strip()
    kind = source_kind(text)
    exists = path_available(text)
    health = "available" if exists else "unavailable"
    if kind == "empty":
        health = "empty"

    chat_safe = kind == "local_fixed" and health == "available"
    chat_policy = "chat_aware" if preferred_chat_policy == "chat_aware" and chat_safe else "chat_ignored"
    if kind == "empty":
        index_policy = "skip"
    elif health != "available":
        index_policy = "skip"
    elif chat_safe:
        index_policy = "full"
    else:
        index_policy = "metadata_only"

    badges = []
    if kind != "empty":
        badges.append(KIND_LABELS.get(kind, "Unknown"))
    if health != "available" and HEALTH_LABELS.get(health) not in badges:
        badges.append(HEALTH_LABELS.get(health, "Unavailable"))
    if kind != "empty":
        badges.append(CHAT_POLICY_LABELS[chat_policy])
        badges.append(INDEX_POLICY_LABELS[index_policy])

    reason = ""
    if kind in {"network", "removable"}:
        reason = "Non-local sources default to chat ignored. Indexing should run closest to the files."
    elif health != "available" and kind != "empty":
        reason = "Source is not currently reachable."
    elif kind == "unknown":
        reason = "Source type could not be verified."

    return {
        "source_kind": kind,
        "source_kind_label": KIND_LABELS.get(kind, "Unknown"),
        "health_status": health,
        "health_label": HEALTH_LABELS.get(health, "Unavailable"),
        "chat_safe": chat_safe,
        "chat_policy": chat_policy,
        "chat_policy_label": CHAT_POLICY_LABELS[chat_policy],
        "index_policy": index_policy,
        "index_policy_label": INDEX_POLICY_LABELS[index_policy],
        "last_seen": time.time() if exists else None,
        "badges": badges,
        "policy_reason": reason,
    }


def policy_key(path_text: str | Path) -> str:
    return normalize_source_path(path_text).lower()


CHAT_AWARE_MAX_FILE_BYTES = 100 * 1024 * 1024

CHAT_IGNORED_PARTS: set[str] = {
    "_ARCHIVE_REVIEW", "_ARCHIVE_DUP_REVIEW", "_INBOX",
    ".git", "__pycache__", ".venv", "node_modules",
    ".trash", "$recycle.bin", "System Volume Information",
}


def is_chat_aware_content_path(path_text: str) -> bool:
    if not path_text or not is_chat_safe_source(path_text):
        return False
    parts = set(Path(path_text).parts)
    if parts & CHAT_IGNORED_PARTS:
        return False
    return True


def is_chat_aware_embedding_candidate(path_text: str, *, category: str = "", size_bytes: int = 0) -> bool:
    if not path_text or not is_chat_aware_content_path(path_text):
        return False
    if size_bytes:
        return size_bytes <= CHAT_AWARE_MAX_FILE_BYTES
    try:
        return Path(path_text).stat().st_size <= CHAT_AWARE_MAX_FILE_BYTES
    except OSError:
        return False


def is_chat_aware_text_content_path(path_text: str) -> bool:
    return is_chat_aware_content_path(path_text)


def is_chat_safe_source(path_text: str | Path) -> bool:
    return bool(source_policy(path_text).get("chat_safe"))
