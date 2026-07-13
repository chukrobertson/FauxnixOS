from __future__ import annotations

import os
import subprocess
from pathlib import Path

FAUXNIX_ROOT = os.getenv("FAUXNIX_ROOT", "/home/chxk/Projects/fauxnix-core")


def nspawn_boot(workspace_path: Path, shared_path: Path, machine_name: str = "workspace",
                vnc_port: int | None = None) -> subprocess.Popen:
    cmd = [
        "sudo", "systemd-nspawn",
        f"--directory={workspace_path}",
        f"--machine={machine_name}",
        f"--setenv=FENNIX_THREAD_NAME={machine_name}",
        "--bind=/nix/store",
        f"--bind={shared_path}:/shared",
        "--bind=/run/nexus",
        f"--bind={FAUXNIX_ROOT}:/fauxnix-core",
        "--boot",
    ]
    if vnc_port:
        cmd.insert(4, f"--setenv=FENNIX_VNC_PORT={vnc_port}")

    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
