from __future__ import annotations

import json
import os
import subprocess
import time

from pathlib import Path


def get_system_resources() -> dict:
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.3)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        top_procs: list[str] = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                info = proc.info
                if info["cpu_percent"] and info["cpu_percent"] > 0.5:
                    top_procs.append(f"{info['name']} (cpu={info['cpu_percent']:.1f}%, mem={info['memory_percent']:.1f}%)")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return {
            "cpu_percent": cpu,
            "memory_percent": mem.percent,
            "memory_used_gb": round(mem.used / (1024**3), 2),
            "memory_total_gb": round(mem.total / (1024**3), 2),
            "disk_percent": disk.percent,
            "disk_free_gb": round(disk.free / (1024**3), 2),
            "top_processes": sorted(top_procs, key=lambda x: float(x.split("cpu=")[1].split("%")[0]) if "cpu=" in x else 0, reverse=True)[:10],
        }
    except ImportError:
        return {}
    except Exception:
        return {}


def get_nixos_info() -> dict | None:
    current_system = Path("/run/current-system")
    if not current_system.exists():
        return None

    try:
        target = current_system.resolve()
        profile_path = Path("/nix/var/nix/profiles/system")
        profile_target = profile_path.resolve() if profile_path.exists() else None

        booted_config = "/run/booted-system/kernel"
        kernel = ""
        try:
            for entry in os.listdir("/run/booted-system/kernel-modules/lib/modules"):
                kernel = entry
                break
        except Exception:
            pass

        return {
            "current_system": str(target),
            "profile": str(profile_target) if profile_target else None,
            "kernel": kernel,
        }
    except Exception:
        return None


def get_service_status(services: list[str] | None = None) -> dict[str, str]:
    if services is None:
        services = [
            "ollama.service",
            "membrie-daemon.service",
            "archivist-daemon.service",
            "fennix-daemon.service",
        ]

    statuses: dict[str, str] = {}
    for svc in services:
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", svc],
                capture_output=True, text=True, timeout=3,
            )
            statuses[svc] = result.stdout.strip() if result.returncode == 0 else "inactive"
        except Exception:
            statuses[svc] = "unknown"
    return statuses


def get_latest_context_snapshot(snapshot_type: str = "system_state") -> dict | None:
    from fauxnix_tools.db import get_conn
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT snapshot_data, captured_ts FROM fennix_context_snapshots WHERE snapshot_type = ? ORDER BY captured_ts DESC LIMIT 1",
            (snapshot_type,),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            snapshot = json.loads(row["snapshot_data"])
            snapshot["captured_ts"] = row["captured_ts"]
            return snapshot
    except Exception:
        pass
    return None


def get_uptime() -> float | None:
    try:
        return float(Path("/proc/uptime").read_text().split()[0])
    except Exception:
        return None
