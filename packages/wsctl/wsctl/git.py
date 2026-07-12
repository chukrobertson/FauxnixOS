from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path


def init_repo(workspace_path: Path, thread_name: str, thread_id: str) -> str:
    workspace_dir = workspace_path / "workspace"
    subprocess.run(
        ["sudo", "mkdir", "-p", str(workspace_dir)],
        check=True, capture_output=True, text=True,
    )

    subprocess.run(
        ["sudo", "git", "init", str(workspace_path)],
        check=True, capture_output=True, text=True,
    )

    subprocess.run(
        ["sudo", "git", "-C", str(workspace_path), "config", "user.name", f"fauxnix-{thread_name}"],
        check=True, capture_output=True, text=True,
    )
    subprocess.run(
        ["sudo", "git", "-C", str(workspace_path), "config", "user.email", f"{thread_id}@fauxnix.thread"],
        check=True, capture_output=True, text=True,
    )

    gitignore = workspace_path / ".gitignore"
    gitignore_content = "\n".join([
        "proc/", "sys/", "dev/", "run/", "tmp/",
        "etc/", "nix/", "root/", "var/", "mnt/",
        "lost+found/", "sbin/", "usr/", "lib/", "lib64/",
        "boot/", "home/", "bin/",
        "*.pyc", "__pycache__/",
    ]) + "\n"
    subprocess.run(
        ["sudo", "tee", str(gitignore)],
        input=gitignore_content, check=True, capture_output=True, text=True,
    )

    readme = workspace_dir / "README.md"
    ts = datetime.now(timezone.utc).isoformat()
    readme_content = f"# {thread_name}\n\nThread ID: `{thread_id}`\nCreated: {ts}\n"
    subprocess.run(
        ["sudo", "tee", str(readme)],
        input=readme_content, check=True, capture_output=True, text=True,
    )

    subprocess.run(
        ["sudo", "git", "-C", str(workspace_path), "add", "-A"],
        check=True, capture_output=True, text=True,
    )
    result = subprocess.run(
        ["sudo", "git", "-C", str(workspace_path), "commit", "-m", f"init: {thread_name}"],
        check=True, capture_output=True, text=True,
    )

    commit_hash = result.stdout.strip().split("\n")[-1].split()[1][:7] if result.stdout else "unknown"
    return commit_hash


def commit(workspace_path: Path, message: str) -> str:
    subprocess.run(
        ["sudo", "git", "-C", str(workspace_path), "add", "-A"],
        check=True, capture_output=True, text=True,
    )
    result = subprocess.run(
        ["sudo", "git", "-C", str(workspace_path), "commit", "--allow-empty", "-m", message],
        check=True, capture_output=True, text=True,
    )
    return _parse_commit_hash(result.stdout)


def log(workspace_path: Path, n: int = 20) -> list[dict]:
    result = subprocess.run(
        ["sudo", "git", "-C", str(workspace_path), "log", f"-{n}", "--format=%H|%s|%ai|%an"],
        check=True, capture_output=True, text=True,
    )
    entries: list[dict] = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("|", 3)
        if len(parts) >= 4:
            entries.append({
                "hash": parts[0][:7],
                "message": parts[1],
                "date": parts[2],
                "author": parts[3],
            })
    return entries


def diff(ws_a: Path, ws_b: Path) -> str:
    result = subprocess.run(
        ["sudo", "git", "diff", "--stat", str(ws_a), str(ws_b)],
        capture_output=True, text=True,
    )
    return result.stdout


def status(workspace_path: Path) -> str:
    result = subprocess.run(
        ["sudo", "git", "-C", str(workspace_path), "status", "--short"],
        capture_output=True, text=True,
    )
    return result.stdout


def _parse_commit_hash(stdout: str) -> str:
    for line in stdout.strip().split("\n"):
        if line.startswith("[") and "]" in line:
            return line.split()[1][:7]
    return "unknown"
