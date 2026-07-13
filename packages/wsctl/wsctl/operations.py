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
from wsctl.git import init_repo, commit as git_commit, log as git_log, diff as git_diff, status as git_status


def create_workspace(name: str, profile: str = "headless", template: str | None = None) -> dict:
    ws_path = Path(WSCI_WORKSPACE_ROOT) / name
    if path_exists(ws_path):
        raise FileExistsError(f"Thread '{name}' already exists")

    _init_from_template(ws_path)

    manifest = create_manifest(ws_path, name)
    manifest["nix"]["profile"] = profile

    if template:
        manifest["nix"]["template"] = template
        manifest["tags"]["topics"] = [template]

    commit_hash = init_repo(ws_path, name, manifest["workspace"]["id"])
    manifest["git"] = {
        "initial_commit": commit_hash,
        "last_commit": commit_hash,
        "repo_path": str(ws_path),
    }

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
        raise FileNotFoundError(f"Thread '{name}' not found")

    if is_running(name):
        return

    _fix_os_release(ws_path)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    snapshot_workspace(name, f"pre-boot-{ts}")

    manifest = load_manifest(ws_path)
    profile = manifest["nix"]["profile"] if manifest else "headless"
    vnc_port = None

    if profile in ("win11", "macos"):
        vnc_port = _assign_vnc_port(name)

    shared_path = Path(WSCI_SHARED_ROOT)
    ensure_directory(shared_path)

    nspawn_boot(ws_path, shared_path, machine_name=name, vnc_port=vnc_port)

    timeout = 30
    start = time.time()
    while time.time() - start < timeout:
        if is_running(name):
            break
        time.sleep(0.5)

    manifest = load_manifest(ws_path)
    if manifest:
        manifest["activity"]["last_active"] = datetime.now(timezone.utc).isoformat()
        if vnc_port:
            manifest["network"] = manifest.get("network", {})
            manifest["network"]["vnc_port"] = vnc_port
        save_manifest(ws_path, manifest)


def _assign_vnc_port(name: str) -> int:
    ws_root = Path(WSCI_WORKSPACE_ROOT)
    used_ports: set[int] = set()
    if path_exists(ws_root):
        for entry in list_dir(ws_root):
            if entry.startswith("."):
                continue
            m = load_manifest(ws_root / entry)
            if m:
                port = m.get("network", {}).get("vnc_port")
                if port:
                    used_ports.add(port)

    for port in range(5901, 5921):
        if port not in used_ports:
            return port

    return 5901
    if manifest:
        manifest["activity"]["last_active"] = datetime.now(timezone.utc).isoformat()
        save_manifest(ws_path, manifest)


def stop_workspace(name: str) -> None:
    ws_path = Path(WSCI_WORKSPACE_ROOT) / name
    if not path_exists(ws_path):
        return
    if not is_running(name):
        return
    machinectl_poweroff(name)
    time.sleep(2)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    snapshot_workspace(name, f"post-stop-{ts}")


def fork_workspace(source_name: str, target_name: str) -> dict:
    source_path = Path(WSCI_WORKSPACE_ROOT) / source_name
    target_path = Path(WSCI_WORKSPACE_ROOT) / target_name

    if not path_exists(source_path):
        raise FileNotFoundError(f"Thread '{source_name}' not found")
    if path_exists(target_path):
        raise FileExistsError(f"Thread '{target_name}' already exists")

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
        raise FileNotFoundError(f"Thread '{name}' not found")

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
        raise FileNotFoundError(f"Thread '{name}' not found")

    if is_running(name):
        stop_workspace(name)
        time.sleep(2)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    snapshot_workspace(name, f"pre-delete-{ts}")

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


def merge_workspace(source_name: str, target_name: str, prune: bool = False) -> dict:
    source_path = Path(WSCI_WORKSPACE_ROOT) / source_name
    target_path = Path(WSCI_WORKSPACE_ROOT) / target_name

    if not path_exists(source_path):
        raise FileNotFoundError(f"Thread '{source_name}' not found")
    if not path_exists(target_path):
        raise FileNotFoundError(f"Thread '{target_name}' not found")

    source_manifest = load_manifest(source_path)
    target_manifest = load_manifest(target_path)

    snapshot_workspace(source_name, f"pre-merge-{target_name}")
    snapshot_workspace(target_name, f"pre-merge-{source_name}")

    source_was_running = is_running(source_name)
    target_was_running = is_running(target_name)

    if source_was_running:
        stop_workspace(source_name)
    if target_was_running:
        stop_workspace(target_name)

    files_copied = _copy_workspace_files(source_path, target_path)

    if source_manifest and target_manifest:
        merged_ids = list(target_manifest["merged_from"]["workspace_ids"])
        merged_ids.append(source_manifest["workspace"]["id"])
        target_manifest["merged_from"]["workspace_ids"] = merged_ids
        save_manifest(target_path, target_manifest)

        source_manifest["merged_into"] = {"workspace_id": target_manifest["workspace"]["id"]}
        save_manifest(source_path, source_manifest)

    summary = {
        "source": source_name,
        "target": target_name,
        "files_copied": files_copied,
        "snapshots_created": [
            f"{source_name}-pre-merge-{target_name}",
            f"{target_name}-pre-merge-{source_name}",
        ],
        "archived": not prune,
    }

    if prune:
        delete_workspace(source_name)
        summary["archived"] = False

    if target_was_running:
        start_workspace(target_name)

    return summary


def _copy_workspace_files(source_path: Path, target_path: Path) -> int:
    src_workspace = source_path / "workspace"
    tgt_workspace = target_path / "workspace"

    if not path_exists(src_workspace):
        return 0

    if not path_exists(tgt_workspace):
        subprocess.run(["sudo", "mkdir", "-p", str(tgt_workspace)], check=True)

    before = set()
    list_result = subprocess.run(
        ["sudo", "find", str(tgt_workspace), "-type", "f"],
        capture_output=True, text=True,
    )
    if list_result.returncode == 0:
        before = set(list_result.stdout.strip().split("\n"))

    subprocess.run(
        ["sudo", "cp", "-rn", f"{src_workspace}/.", str(tgt_workspace)],
        capture_output=True, text=True,
    )

    after = set()
    list_result = subprocess.run(
        ["sudo", "find", str(tgt_workspace), "-type", "f"],
        capture_output=True, text=True,
    )
    if list_result.returncode == 0:
        after = set(list_result.stdout.strip().split("\n"))

    return len(after - before)
