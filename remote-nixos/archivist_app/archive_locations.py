from __future__ import annotations

import json
import string
import time
from pathlib import Path

from app.config import ARCHIVE_REVIEW_DIR, ARCHIVE_ROOT, ARCHIVE_SOURCES_FILE, KNOWLEDGEBASE_DIR
from app.source_safety import path_available, policy_key, source_policy

SOURCE_SLOT_LABELS = {
    "archive_root": "Archive root",
    "knowledgebase_root": "Knowledgebase root",
    "network_root": "Network root",
    "ignored_archive_root": "Archive root",
    "ignored_network_root": "Network root",
    "external_usb_root": "USB storage root",
    "scanner_inbox": "Scanner inbox",
    "printer_network_root": "Printer/network share",
}

CHAT_AWARE_SLOTS = {"archive_root", "knowledgebase_root", "network_root"}


def normalize_path(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


def read_sources() -> dict:
    try:
        data = json.loads(ARCHIVE_SOURCES_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        data = {}
    additional = data.get("additional_roots") or []
    source_policies = data.get("source_policies") or {}
    if not isinstance(additional, list):
        additional = []
    if not isinstance(source_policies, dict):
        source_policies = {}
    archive_root = data.get("archive_root") or str(ARCHIVE_ROOT)
    return {
        "archive_root": archive_root,
        "knowledgebase_root": data.get("knowledgebase_root") or str(Path(archive_root) / "_KNOWLEDGEBASE"),
        "chat_aware_network_root": data.get("chat_aware_network_root") or "",
        "chat_ignored_archive_root": data.get("chat_ignored_archive_root") or str(Path(archive_root) / "_ARCHIVE_REVIEW"),
        "chat_ignored_network_root": data.get("chat_ignored_network_root") or "",
        "external_usb_root": data.get("external_usb_root") or "",
        "scanner_inbox": data.get("scanner_inbox") or "",
        "printer_network_root": data.get("printer_network_root") or "",
        "additional_roots": [
            {
                "path": str(item.get("path") or ""),
                "label": str(item.get("label") or Path(str(item.get("path") or "")).name or "Folder"),
                "enabled": bool(item.get("enabled", True)),
                **source_policy(str(item.get("path") or ""), "chat_ignored"),
            }
            for item in additional
            if item.get("path")
        ],
        "source_policies": source_policies,
        "last_policy_notice": data.get("last_policy_notice") or "",
        "updated_ts": data.get("updated_ts"),
    }


def write_sources(data: dict) -> None:
    ARCHIVE_SOURCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "archive_root": data.get("archive_root") or str(ARCHIVE_ROOT),
        "knowledgebase_root": data.get("knowledgebase_root") or str(Path(data.get("archive_root") or ARCHIVE_ROOT) / "_KNOWLEDGEBASE"),
        "chat_aware_network_root": data.get("chat_aware_network_root") or "",
        "chat_ignored_archive_root": data.get("chat_ignored_archive_root") or str(Path(data.get("archive_root") or ARCHIVE_ROOT) / "_ARCHIVE_REVIEW"),
        "chat_ignored_network_root": data.get("chat_ignored_network_root") or "",
        "external_usb_root": data.get("external_usb_root") or "",
        "scanner_inbox": data.get("scanner_inbox") or "",
        "printer_network_root": data.get("printer_network_root") or "",
        "additional_roots": data.get("additional_roots") or [],
        "source_policies": data.get("source_policies") or {},
        "last_policy_notice": data.get("last_policy_notice") or "",
        "updated_ts": time.time(),
    }
    text = json.dumps(payload, indent=2)
    ARCHIVE_SOURCES_FILE.write_text(text, encoding="utf-8")


def validate_directory(path_text: str) -> Path:
    path = Path(path_text).expanduser().resolve(strict=False)
    try:
        exists = path.exists()
        is_directory = path.is_dir() if exists else False
    except OSError:
        raise ValueError("Folder is not reachable") from None
    if not exists:
        raise ValueError("Folder does not exist")
    if not is_directory:
        raise ValueError("Path is not a folder")
    return path


def preferred_policy_for_slot(slot: str) -> str:
    return "chat_aware" if slot in CHAT_AWARE_SLOTS else "chat_ignored"


def remember_source_policy(data: dict, path: str | Path, preferred_chat_policy: str) -> dict:
    policy = source_policy(str(path), preferred_chat_policy)
    data.setdefault("source_policies", {})[policy_key(path)] = {
        "source_kind": policy["source_kind"],
        "health_status": policy["health_status"],
        "chat_policy": policy["chat_policy"],
        "index_policy": policy["index_policy"],
        "last_seen": policy["last_seen"],
        "policy_reason": policy["policy_reason"],
    }
    return policy


def enforce_chat_aware_source(root: Path, slot: str) -> dict:
    policy = source_policy(str(root), "chat_aware")
    if policy["chat_safe"]:
        return policy
    if slot == "network_root":
        return policy
    raise ValueError(
        f"{policy['source_kind_label']} sources cannot be saved as chat-aware roots yet. "
        "Save this path in Chat ignored or External sources, or run an Archivist worker on that machine later."
    )


def archive_location_status() -> dict:
    data = read_sources()
    configured = normalize_path(data["archive_root"])
    active = normalize_path(ARCHIVE_ROOT)
    configured_kb = normalize_path(data["knowledgebase_root"])
    active_kb = normalize_path(KNOWLEDGEBASE_DIR)
    chat_aware = [
        source_slot("archive_root", data["archive_root"], active_path=str(ARCHIVE_ROOT), restart_applies=True),
        source_slot("knowledgebase_root", data["knowledgebase_root"], active_path=str(KNOWLEDGEBASE_DIR), restart_applies=True),
        source_slot("network_root", data["chat_aware_network_root"]),
    ]
    chat_ignored = [
        source_slot("ignored_archive_root", data["chat_ignored_archive_root"], active_path=str(ARCHIVE_REVIEW_DIR)),
        source_slot("ignored_network_root", data["chat_ignored_network_root"]),
    ]
    external_sources = [
        source_slot("external_usb_root", data["external_usb_root"]),
        source_slot("scanner_inbox", data["scanner_inbox"]),
        source_slot("printer_network_root", data["printer_network_root"]),
    ]
    return {
        "active_archive_root": active,
        "configured_archive_root": configured,
        "active_knowledgebase_root": active_kb,
        "configured_knowledgebase_root": configured_kb,
        "restart_required": configured.lower() != active.lower() or configured_kb.lower() != active_kb.lower(),
        "chat_aware": chat_aware,
        "chat_ignored": chat_ignored,
        "external_sources": external_sources,
        "additional_roots": data["additional_roots"],
        "source_policies": data["source_policies"],
        "policy_notice": data.get("last_policy_notice") or "",
        "settings_file": str(ARCHIVE_SOURCES_FILE),
    }


def source_slot(key: str, path: str, *, active_path: str | None = None, restart_applies: bool = False) -> dict:
    path_text = str(path or "")
    exists = path_available(path_text)
    policy = source_policy(path_text, preferred_policy_for_slot(key))
    return {
        "key": key,
        "label": SOURCE_SLOT_LABELS.get(key, key.replace("_", " ").title()),
        "path": path_text,
        "active_path": active_path,
        "exists": exists,
        **policy,
        "restart_applies": restart_applies,
        "restart_required": restart_applies and active_path is not None and normalize_path(path_text).lower() != normalize_path(active_path).lower(),
    }


def set_archive_root(path_text: str) -> dict:
    root = validate_directory(path_text)
    enforce_chat_aware_source(root, "archive_root")
    data = read_sources()
    data["archive_root"] = str(root)
    data["last_policy_notice"] = ""
    remember_source_policy(data, root, "chat_aware")
    write_sources(data)
    return archive_location_status()


def set_source_slot(slot: str, path_text: str) -> dict:
    root = validate_directory(path_text)
    data = read_sources()
    data["last_policy_notice"] = ""
    policy = remember_source_policy(data, root, preferred_policy_for_slot(slot))
    if slot == "archive_root":
        enforce_chat_aware_source(root, slot)
        data["archive_root"] = str(root)
    elif slot == "knowledgebase_root":
        enforce_chat_aware_source(root, slot)
        data["knowledgebase_root"] = str(root)
    elif slot == "network_root":
        if policy["chat_safe"]:
            data["chat_aware_network_root"] = str(root)
        else:
            data["chat_aware_network_root"] = ""
            data["chat_ignored_network_root"] = str(root)
            remember_source_policy(data, root, "chat_ignored")
            data["last_policy_notice"] = (
                f"{policy['source_kind_label']} network slot was saved as Chat ignored. "
                "Non-local roots are not chat-aware by default."
            )
    elif slot == "ignored_archive_root":
        data["chat_ignored_archive_root"] = str(root)
    elif slot == "ignored_network_root":
        data["chat_ignored_network_root"] = str(root)
    elif slot == "external_usb_root":
        data["external_usb_root"] = str(root)
    elif slot == "scanner_inbox":
        data["scanner_inbox"] = str(root)
    elif slot == "printer_network_root":
        data["printer_network_root"] = str(root)
    else:
        raise ValueError("Unknown archive location slot")
    write_sources(data)
    return archive_location_status()


def add_additional_root(path_text: str, label: str | None = None) -> dict:
    root = validate_directory(path_text)
    data = read_sources()
    normalized = normalize_path(root)
    policy = remember_source_policy(data, root, "chat_ignored")
    existing = {normalize_path(item["path"]).lower() for item in data["additional_roots"]}
    if normalized.lower() not in existing:
        data["additional_roots"].append(
            {
                "path": normalized,
                "label": label or root.name or normalized,
                "enabled": True,
                "chat_policy": policy["chat_policy"],
                "index_policy": policy["index_policy"],
                "source_kind": policy["source_kind"],
                "health_status": policy["health_status"],
            }
        )
        write_sources(data)
    return archive_location_status()


def remove_additional_root(path_text: str) -> dict:
    data = read_sources()
    target = normalize_path(path_text).lower()
    data["additional_roots"] = [
        item
        for item in data["additional_roots"]
        if normalize_path(item["path"]).lower() != target
    ]
    write_sources(data)
    return archive_location_status()


def drive_roots() -> list[dict]:
    roots = []
    for letter in string.ascii_uppercase:
        path = Path(f"{letter}:\\")
        if path_available(path):
            roots.append({"name": str(path), "path": str(path)})
    return roots


def directory_available(path: Path) -> bool:
    try:
        return path.exists() and path.is_dir()
    except OSError:
        return False


def browse_directories(path_text: str | None = None) -> dict:
    status = archive_location_status()
    start = Path(status["configured_archive_root"] or status["active_archive_root"])
    current = Path(path_text).expanduser().resolve(strict=False) if path_text else start
    if not directory_available(current):
        current = start if directory_available(start) else Path.cwd()

    directories = []
    try:
        for item in sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if item.is_dir():
                directories.append({"name": item.name, "path": str(item)})
    except (OSError, PermissionError):
        directories = []

    parent = current.parent if current.parent != current else None
    return {
        "current_path": str(current),
        "parent_path": str(parent) if parent else None,
        "directories": directories[:300],
        "drives": drive_roots(),
        "selected_root": status["configured_archive_root"],
    }
