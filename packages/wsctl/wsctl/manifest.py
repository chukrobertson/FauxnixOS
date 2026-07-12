from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from wsctl.btrfs import write_text, read_text, path_exists


META_FILENAME = "ws-manifest.json"


def create_manifest(workspace_path: Path, name: str, parent_id: str | None = None) -> dict:
    manifest = {
        "workspace": {
            "name": name,
            "id": uuid.uuid4().hex[:12],
            "created": datetime.now(timezone.utc).isoformat(),
        },
        "parent": {
            "workspace_id": parent_id,
            "forked_at": None,
        },
        "nix": {
            "closure_hash": None,
            "profile": "headless",
        },
        "snapshots": {
            "history": [],
        },
        "merged_from": {"workspace_ids": []},
        "tags": {"topics": []},
        "activity": {
            "last_active": None,
        },
    }
    save_manifest(workspace_path, manifest)
    return manifest


def load_manifest(workspace_path: Path) -> dict | None:
    meta_file = workspace_path / META_FILENAME
    if not path_exists(meta_file):
        return None
    content = read_text(meta_file)
    if content:
        return json.loads(content)
    return None


def save_manifest(workspace_path: Path, manifest: dict) -> None:
    meta_file = workspace_path / META_FILENAME
    write_text(meta_file, json.dumps(manifest, indent=2))


def update_profile(workspace_path: Path, profile: str) -> None:
    manifest = load_manifest(workspace_path)
    if manifest:
        manifest["nix"]["profile"] = profile
        save_manifest(workspace_path, manifest)


def add_snapshot(workspace_path: Path, snapshot_label: str) -> None:
    manifest = load_manifest(workspace_path)
    if manifest:
        manifest["snapshots"]["history"].append(snapshot_label)
        save_manifest(workspace_path, manifest)
