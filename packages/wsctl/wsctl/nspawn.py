from __future__ import annotations

import subprocess
from pathlib import Path


def nspawn_boot(workspace_path: Path, shared_path: Path, machine_name: str = "workspace") -> subprocess.Popen:
    return subprocess.Popen(
        [
            "sudo", "systemd-nspawn",
            f"--directory={workspace_path}",
            f"--machine={machine_name}",
            f"--setenv=FENNIX_THREAD_NAME={machine_name}",
            "--bind=/nix/store",
            f"--bind={shared_path}:/shared",
            "--bind=/run/nexus",
            "--bind=/home/chxk/Projects/fauxnix-core:/fauxnix-core",
            "--boot",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def machinectl_list() -> list[str]:
    result = subprocess.run(
        ["sudo", "machinectl", "list", "--no-legend"],
        check=True, capture_output=True, text=True,
    )
    names: list[str] = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split()
        if parts:
            names.append(parts[0])
    return names


def machinectl_poweroff(name: str) -> None:
    subprocess.run(
        ["sudo", "machinectl", "poweroff", name],
        check=True, capture_output=True, text=True,
    )


def is_running(name: str) -> bool:
    return name in machinectl_list()
