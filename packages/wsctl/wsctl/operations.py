from __future__ import annotations

import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from wsctl import WSCI_WORKSPACE_ROOT, WSCI_SHARED_ROOT, WSCI_TEMPLATE, WSCI_SNAPSHOT_ROOT
from wsctl.btrfs import (
    btrfs_snapshot, btrfs_delete, ensure_directory,
    read_text, write_text, path_exists, is_symlink, list_dir, remove_path,
)
from wsctl.manifest import create_manifest, load_manifest, add_snapshot, save_manifest
from wsctl.nspawn import nspawn_boot, machinectl_poweroff, is_running, machinectl_list


def create_workspace(name: str, profile: str = "headless") -> dict:
    ws_path = Path(WSCI_WORKSPACE_ROOT) / name
    if path_exists(ws_path):
        raise FileExistsError(f"Workspace '{name}' already exists")

    _init_from_template(ws_path)

    manifest = create_manifest(ws_path, name)
    manifest["nix"]["profile"] = profile
    save_manifest(ws_path, manifest)

    return manifest


def _init_from_template(ws_path: Path) -> None:
    template = Path(WSCI_TEMPLATE)
    if not path_exists(template):
        raise FileNotFoundError(f"Template not found: {WSCI_TEMPLATE}")

    btrfs_snapshot(template, ws_path, readonly=False)
    _fix_os_release(ws_path)

    shared_dir = ws_path / "shared"
    if not path_exists(shared_dir):
        subprocess.run(["sudo", "mkdir", "-p", str(shared_dir)], check=True)


def _fix_os_release(ws_path: Path) -> None:
    os_release = ws_path / "etc" / "os-release"
    if is_symlink(os_release):
        content = read_text(os_release)
        remove_path(os_release)
        write_text(os_release, content)


def start_workspace(name: str) -> None:
    ws_path = Path(WSCI_WORKSPACE_ROOT) / name
    if not path_exists(ws_path):
        raise FileNotFoundError(f"Workspace '{name}' not found")

    if is_running(name):
        return

    _fix_os_release(ws_path)

    shared_path = Path(WSCI_SHARED_ROOT)
    ensure_directory(shared_path)

    nspawn_boot(ws_path, shared_path)

    timeout = 30
    start = time.time()
    while time.time() - start < timeout:
        if is_running(name):
            break
        time.sleep(0.5)

    manifest = load_manifest(ws_path)
    if manifest:
        manifest["activity"]["last_active"] = datetime.now(timezone.utc).isoformat()
        save_manifest(ws_path, manifest)


def stop_workspace(name: str) -> None:
    if not is_running(name):
        return
    machinectl_poweroff(name)


def fork_workspace(source_name: str, target_name: str) -> dict:
    source_path = Path(WSCI_WORKSPACE_ROOT) / source_name
    target_path = Path(WSCI_WORKSPACE_ROOT) / target_name

    if not path_exists(source_path):
        raise FileNotFoundError(f"Source workspace '{source_name}' not found")
    if path_exists(target_path):
        raise FileExistsError(f"Target workspace '{target_name}' already exists")

    source_manifest = load_manifest(source_path)
    source_id = source_manifest["workspace"]["id"] if source_manifest else None

    btrfs_snapshot(source_path, target_path, readonly=False)
    _fix_os_release(target_path)

    manifest = create_manifest(target_path, target_name, parent_id=source_id)
    manifest["parent"]["forked_at"] = datetime.now(timezone.utc).isoformat()
    if source_manifest:
        manifest["nix"]["profile"] = source_manifest["nix"]["profile"]
    save_manifest(target_path, manifest)

    return manifest


def snapshot_workspace(name: str, label: str | None = None) -> str:
    ws_path = Path(WSCI_WORKSPACE_ROOT) / name
    if not path_exists(ws_path):
        raise FileNotFoundError(f"Workspace '{name}' not found")

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    snap_label = label or f"auto-{ts}"
    snap_name = f"{name}-{snap_label}"

    snap_dir = Path(WSCI_SNAPSHOT_ROOT)
    ensure_directory(snap_dir)

    snap_path = snap_dir / snap_name
    btrfs_snapshot(ws_path, snap_path, readonly=True)

    add_snapshot(ws_path, snap_name)

    return snap_name


def restore_workspace(name: str, snapshot_label: str) -> None:
    ws_path = Path(WSCI_WORKSPACE_ROOT) / name
    snap_path = Path(WSCI_SNAPSHOT_ROOT) / snapshot_label

    if not path_exists(snap_path):
        raise FileNotFoundError(f"Snapshot '{snapshot_label}' not found")

    was_running = is_running(name)
    if was_running:
        stop_workspace(name)

    btrfs_delete(ws_path)

    btrfs_snapshot(snap_path, ws_path, readonly=False)
    _fix_os_release(ws_path)

    if was_running:
        start_workspace(name)


def delete_workspace(name: str) -> None:
    ws_path = Path(WSCI_WORKSPACE_ROOT) / name
    if not path_exists(ws_path):
        raise FileNotFoundError(f"Workspace '{name}' not found")

    if is_running(name):
        stop_workspace(name)
        time.sleep(2)

    btrfs_delete(ws_path)


def list_workspaces() -> list[dict]:
    result: list[dict] = []
    ws_root = Path(WSCI_WORKSPACE_ROOT)
    if not path_exists(ws_root):
        return result

    try:
        running = set(machinectl_list())
    except Exception:
        running = set()

    entries = list_dir(ws_root)
    for name in entries:
        if name.startswith("."):
            continue
        entry = ws_root / name
        if not path_exists(entry):
            continue

        manifest = load_manifest(entry)
        ws_info = {
            "name": name,
            "status": "running" if name in running else "stopped",
            "profile": manifest["nix"]["profile"] if manifest else "unknown",
            "topics": manifest["tags"]["topics"] if manifest else [],
            "parent": manifest["parent"]["workspace_id"] if manifest else None,
        }
        result.append(ws_info)

    return result
