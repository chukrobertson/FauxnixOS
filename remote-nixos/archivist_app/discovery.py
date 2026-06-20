from __future__ import annotations

import os
import string
import time
from pathlib import Path

from app.archive_locations import archive_location_status
from app.config import ARCHIVE_ROOT, KNOWLEDGEBASE_DIR
from app.source_safety import path_available, source_policy


def _node_id(prefix: str, value: str) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    return f"{prefix}-{safe or 'empty'}"


def _path_node(
    *,
    node_id: str,
    label: str,
    path: str,
    group: str,
    preferred_policy: str,
    slot: str | None = None,
    configured: bool = False,
) -> dict:
    policy = source_policy(path, preferred_policy)
    kind = policy.get("source_kind") or "unknown"
    actions: list[dict] = []
    if path and policy.get("health_status") == "available":
        if policy.get("chat_safe"):
            actions.extend(
                [
                    {"key": "set_archive_root", "label": "Set archive root", "slot": "archive_root"},
                    {"key": "set_knowledgebase_root", "label": "Set knowledgebase", "slot": "knowledgebase_root"},
                ]
            )
        ignored_slot = "external_usb_root" if kind == "removable" else "ignored_network_root" if kind == "network" else "ignored_archive_root"
        actions.append({"key": "save_chat_ignored", "label": "Save chat ignored", "slot": ignored_slot})
    return {
        "id": node_id,
        "label": label,
        "path": path,
        "group": group,
        "slot": slot,
        "configured": configured,
        "source_kind": kind,
        "source_kind_label": policy.get("source_kind_label"),
        "health_status": policy.get("health_status"),
        "health_label": policy.get("health_label"),
        "chat_policy": policy.get("chat_policy"),
        "chat_policy_label": policy.get("chat_policy_label"),
        "index_policy": policy.get("index_policy"),
        "index_policy_label": policy.get("index_policy_label"),
        "badges": policy.get("badges") or [],
        "policy_reason": policy.get("policy_reason") or "",
        "actions": actions,
    }


def _drive_candidates() -> list[dict]:
    nodes = []
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if path_available(root):
                policy = source_policy(root, "chat_aware")
                group = "removable" if policy["source_kind"] == "removable" else "network" if policy["source_kind"] == "network" else "drive"
                nodes.append(
                    _path_node(
                        node_id=_node_id("drive", root),
                        label=root,
                        path=root,
                        group=group,
                        preferred_policy="chat_aware",
                    )
                )
        return nodes

    for root in ["/", str(Path.home())]:
        if path_available(root):
            nodes.append(
                _path_node(
                    node_id=_node_id("path", root),
                    label=root,
                    path=root,
                    group="drive",
                    preferred_policy="chat_aware",
                )
            )
    return nodes


def _service_nodes() -> list[dict]:
    return [
        {
            "id": "service-calendar",
            "label": "Calendar",
            "group": "service",
            "health_status": "planned",
            "health_label": "Planned",
            "badges": ["Planned", "Chat aware later"],
            "policy_reason": "Calendar sync is planned, but not connected yet.",
            "actions": [{"key": "planned", "label": "Planned"}],
        },
        {
            "id": "service-cloud",
            "label": "Cloud files",
            "group": "service",
            "health_status": "planned",
            "health_label": "Planned",
            "badges": ["Planned", "Chat ignored first"],
            "policy_reason": "Google, iCloud, and provider sync should land behind explicit connectors.",
            "actions": [{"key": "planned", "label": "Planned"}],
        },
        {
            "id": "device-scanner",
            "label": "Scanners",
            "group": "device",
            "health_status": "planned",
            "health_label": "Planned",
            "badges": ["Planned", "External source"],
            "policy_reason": "Scanner/printer discovery is staged for a later hardware pass.",
            "actions": [{"key": "planned", "label": "Planned"}],
        },
    ]


def discovery_constellation() -> dict:
    locations = archive_location_status()
    nodes = [
        {
            "id": "core-archivist",
            "label": "Archivist",
            "group": "core",
            "health_status": "available",
            "health_label": "Online",
            "badges": ["Control", "Local first"],
            "policy_reason": "Local control surface for archive discovery and source setup.",
            "actions": [],
        }
    ]

    configured_nodes = []
    for slot in [*(locations.get("chat_aware") or []), *(locations.get("chat_ignored") or []), *(locations.get("external_sources") or [])]:
        path = slot.get("path") or ""
        if not path:
            continue
        preferred = "chat_aware" if slot.get("chat_policy") == "chat_aware" else "chat_ignored"
        configured_nodes.append(
            _path_node(
                node_id=f"slot-{slot.get('key')}",
                label=slot.get("label") or slot.get("key", "Source"),
                path=path,
                group="configured",
                preferred_policy=preferred,
                slot=slot.get("key"),
                configured=True,
            )
        )
    nodes.extend(configured_nodes)

    configured_paths = {str(node.get("path") or "").lower() for node in configured_nodes}
    for node in _drive_candidates():
        path = str(node.get("path") or "").lower()
        if path and path not in configured_paths:
            nodes.append(node)
    nodes.extend(_service_nodes())

    links = []
    for node in nodes:
        if node["id"] == "core-archivist":
            continue
        links.append(
            {
                "source": "core-archivist",
                "target": node["id"],
                "kind": node.get("group") or "source",
                "chat_policy": node.get("chat_policy") or "planned",
            }
        )

    available = sum(1 for node in nodes if node.get("health_status") == "available")
    planned = sum(1 for node in nodes if node.get("health_status") == "planned")
    return {
        "generated_ts": time.time(),
        "summary": {
            "nodes": len(nodes),
            "available": available,
            "planned": planned,
            "configured": len(configured_nodes),
            "drives": sum(1 for node in nodes if node.get("group") in {"drive", "removable", "network"}),
        },
        "nodes": nodes,
        "links": links,
        "locations": locations,
        "active_archive_root": str(ARCHIVE_ROOT),
        "active_knowledgebase_root": str(KNOWLEDGEBASE_DIR),
    }
