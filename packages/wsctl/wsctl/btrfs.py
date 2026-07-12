from __future__ import annotations

import subprocess
from pathlib import Path


def btrfs_snapshot(source: Path, dest: Path, readonly: bool = False) -> None:
    cmd = ["sudo", "btrfs", "subvolume", "snapshot"]
    if readonly:
        cmd.append("-r")
    cmd.extend([str(source), str(dest)])
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def btrfs_delete(subvol: Path) -> None:
    result = subprocess.run(
        ["sudo", "btrfs", "subvolume", "delete", str(subvol)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        subprocess.run(
            ["sudo", "chattr", "-R", "-f", "-i", str(subvol)],
            capture_output=True,
        )
        subprocess.run(
            ["sudo", "rm", "-rf", str(subvol)],
            capture_output=True,
        )
        subprocess.run(
            ["sudo", "btrfs", "subvolume", "delete", str(subvol)],
            check=True, capture_output=True, text=True,
        )


def btrfs_subvolume_list(parent: Path) -> list[str]:
    result = subprocess.run(
        ["sudo", "btrfs", "subvolume", "list", str(parent)],
        check=True, capture_output=True, text=True,
    )
    names: list[str] = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split()
        path_idx = None
        for i, p in enumerate(parts):
            if p == "path":
                path_idx = i + 1
                break
        if path_idx and path_idx < len(parts):
            names.append(parts[path_idx])
    return names


def ensure_directory(path: Path) -> None:
    if not path.exists():
        subprocess.run(
            ["sudo", "mkdir", "-p", str(path)],
            check=True, capture_output=True, text=True,
        )


def copy_file(src: Path, dst: Path) -> None:
    subprocess.run(
        ["sudo", "cp", str(src), str(dst)],
        check=True, capture_output=True, text=True,
    )


def remove_path(path: Path) -> None:
    subprocess.run(
        ["sudo", "rm", "-rf", str(path)],
        check=True, capture_output=True, text=True,
    )


def create_symlink(target: str, link: Path) -> None:
    if link.exists() or link.is_symlink():
        remove_path(link)
    subprocess.run(
        ["sudo", "ln", "-sf", target, str(link)],
        check=True, capture_output=True, text=True,
    )


def read_text(path: Path) -> str:
    result = subprocess.run(
        ["sudo", "cat", str(path)],
        check=True, capture_output=True, text=True,
    )
    return result.stdout


def write_text(path: Path, content: str) -> None:
    subprocess.run(
        ["sudo", "tee", str(path)],
        input=content, check=True, capture_output=True, text=True,
    )


def path_exists(path: Path) -> bool:
    result = subprocess.run(
        ["sudo", "test", "-e", str(path)],
        capture_output=True,
    )
    return result.returncode == 0


def is_symlink(path: Path) -> bool:
    result = subprocess.run(
        ["sudo", "test", "-L", str(path)],
        capture_output=True,
    )
    return result.returncode == 0


def list_dir(path: Path) -> list[str]:
    result = subprocess.run(
        ["sudo", "ls", str(path)],
        check=True, capture_output=True, text=True,
    )
    return [l for l in result.stdout.strip().split("\n") if l]
