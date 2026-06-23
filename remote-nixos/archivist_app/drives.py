from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from app.config import ARCHIVE_INBOX


SYS_BLOCK = Path("/sys/block")


def _sys_val(dev: str, attr: str) -> str:
    try:
        return (SYS_BLOCK / dev / attr).read_text(encoding="utf-8").strip()
    except (OSError, FileNotFoundError):
        return ""


def _read_size_file(path: Path) -> str:
    try:
        sectors = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return ""
    bytes_ = sectors * 512
    if bytes_ < 1024:
        return f"{bytes_}B"
    for unit in ("K", "M", "G", "T"):
        bytes_ /= 1024
        if bytes_ < 1024:
            return f"{bytes_:.1f}{unit}"
    return f"{bytes_:.1f}P"


def _block_size(dev: str) -> str:
    """Read size from sysfs. Whole disks at /sys/block/<dev>/size,
    partitions at /sys/block/<parent>/<dev>/size."""
    direct = SYS_BLOCK / dev / "size"
    if direct.exists():
        return _read_size_file(direct)
    for parent in SYS_BLOCK.iterdir():
        if not parent.is_dir():
            continue
        part_size = parent / dev / "size"
        if part_size.exists():
            return _read_size_file(part_size)
    return ""


def _parse_mtab() -> dict[str, dict]:
    """Read /proc/mounts to map devices to mountpoints and fstypes.
    If a device appears multiple times (e.g. bind mounts), the shortest path wins.
    """
    mounts: dict[str, dict] = {}
    try:
        for line in Path("/proc/mounts").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            dev, mpoint, fstype = parts[0], parts[1], parts[2]
            if dev.startswith("/dev/"):
                key = dev.removeprefix("/dev/")
                existing = mounts.get(key)
                if not existing or len(mpoint) < len(existing["mountpoint"]):
                    mounts[key] = {"mountpoint": mpoint, "fstype": fstype}
    except OSError:
        pass
    return mounts


def list_drives() -> list[dict]:
    """List block devices by reading /sys/block and /proc/mounts."""
    mounts = _parse_mtab()
    drives = []
    try:
        dev_dirs = sorted(
            d for d in SYS_BLOCK.iterdir()
            if d.is_dir() and not d.name.startswith("loop") and not d.name.startswith("ram")
            and d.name != "sr0"
        )
    except OSError:
        return [{"error": "cannot read /sys/block"}]

    for dev_dir in dev_dirs:
        name = dev_dir.name
        removable = _sys_val(name, "removable") == "1"
        transport = "usb" if removable else "sata"
        model = _sys_val(name, "device/model").replace("\n", " ").strip()
        parts = sorted(
            p.name for p in dev_dir.iterdir()
            if p.name.startswith(name) and p.name != name and (p / "partition").exists()
        )
        # Check if any partition has a filesystem and is mountable
        for part in parts:
            fstype = ""
            mountpoint = ""
            if part in mounts:
                mountpoint = mounts[part]["mountpoint"]
                fstype = mounts[part]["fstype"]
            else:
                # Check for filesystem via /sys/block/.../uevent
                uevent = _sys_val(part, "uevent")
                for line in uevent.splitlines():
                    if line.startswith("ID_FS_TYPE="):
                        fstype = line.split("=", 1)[1]
                        break
            drives.append({
                "name": part,
                "device": f"/dev/{part}",
                "size": _block_size(part),
                "fstype": fstype,
                "mountpoint": mountpoint,
                "label": "",
                "model": model,
                "transport": transport,
                "mounted": bool(mountpoint),
                "mountable": bool(fstype) and not mountpoint,
            })
        if not parts:
            # Disk with no partitions (directly formatted)
            fstype = ""
            mountpoint = ""
            if name in mounts:
                mountpoint = mounts[name]["mountpoint"]
                fstype = mounts[name]["fstype"]
            drives.append({
                "name": name,
                "device": f"/dev/{name}",
                "size": _block_size(name),
                "fstype": fstype,
                "mountpoint": mountpoint,
                "label": "",
                "model": model,
                "transport": transport,
                "mounted": bool(mountpoint),
                "mountable": bool(fstype) and not mountpoint,
            })
    return drives


def mount_drive(device: str, mountpoint: str | None = None) -> dict:
    if not mountpoint:
        mountpoint = f"/mnt/{Path(device).name}"
    Path(mountpoint).mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["sudo", "mount", device, mountpoint],
            capture_output=True, text=True, timeout=15, check=True,
        )
        return {"ok": True, "device": device, "mountpoint": mountpoint}
    except subprocess.CalledProcessError as e:
        return {"ok": False, "device": device, "error": e.stderr.strip() or str(e)}
    except OSError as e:
        return {"ok": False, "device": device, "error": str(e)}


def unmount_drive(mountpoint: str) -> dict:
    try:
        subprocess.run(
            ["sudo", "umount", mountpoint],
            capture_output=True, text=True, timeout=15, check=True,
        )
        return {"ok": True, "mountpoint": mountpoint}
    except subprocess.CalledProcessError as e:
        return {"ok": False, "mountpoint": mountpoint, "error": e.stderr.strip() or str(e)}
    except OSError as e:
        return {"ok": False, "mountpoint": mountpoint, "error": str(e)}


def browse_directory(path_text: str | None = None) -> dict:
    start = Path(path_text).expanduser().resolve(strict=False) if path_text else Path("/mnt")
    if not start.is_dir():
        return {"error": "Path is not a directory", "path": str(start)}

    try:
        entries = []
        for item in sorted(start.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            try:
                stat = item.stat()
            except OSError:
                stat = None
            entries.append({
                "name": item.name,
                "path": str(item),
                "is_dir": item.is_dir(),
                "size": stat.st_size if stat else 0,
                "modified_ts": int(stat.st_mtime) if stat else 0,
            })
    except (OSError, PermissionError) as e:
        return {"error": str(e), "path": str(start)}

    parent = str(start.parent) if start.parent != start else None
    absolute = str(start.absolute())
    return {
        "path": absolute,
        "parent": parent,
        "entries": entries[:500],
        "total": len(entries),
    }


IMPORT_STATE_FILE = Path(tempfile.gettempdir()) / "fauxnix-archivist-drive-import.json"


def import_to_archive(source_paths: list[str], dest_subfolder: str = "") -> dict:
    dest = ARCHIVE_INBOX
    if dest_subfolder:
        dest = dest / dest_subfolder
    dest.mkdir(parents=True, exist_ok=True)

    results = []
    for src in source_paths:
        src_path = Path(src)
        if not src_path.exists():
            results.append({"path": src, "ok": False, "error": "not found"})
            continue
        try:
            target = dest / src_path.name
            target = _unique_path(target)
            if src_path.is_dir():
                shutil.copytree(src_path, target)
            else:
                shutil.copy2(src_path, target)
            results.append({"path": src, "ok": True, "dest": str(target), "is_dir": src_path.is_dir()})
        except (OSError, shutil.Error) as e:
            results.append({"path": src, "ok": False, "error": str(e)})

    _write_import_state(source_paths, dest)
    return {"ok": True, "dest": str(dest), "results": results}


def recent_imports(limit: int = 10) -> dict:
    try:
        state = json.loads(IMPORT_STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return {"imports": []}
    return {"imports": (state.get("history") or [])[-limit:]}


def _write_import_state(paths: list[str], dest: Path):
    try:
        data = json.loads(IMPORT_STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        data = {"history": []}
    history = data.setdefault("history", [])
    history.append({
        "ts": time.time(),
        "paths": paths,
        "dest": str(dest),
        "count": len(paths),
    })
    if len(history) > 100:
        history[:] = history[-100:]
    IMPORT_STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1
