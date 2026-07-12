from __future__ import annotations

import shutil
import subprocess
import time

from pathlib import Path


def _which(binary: str) -> str | None:
    return shutil.which(binary)


def _run(args: list[str], timeout: int = 5) -> tuple[int, str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return result.returncode, (result.stdout or "").strip()
    except Exception:
        return -1, ""


def get_foreground_process() -> dict | None:
    xdotool = _which("xdotool")
    if not xdotool:
        return None
    code, window_id = _run([xdotool, "getactivewindow"])
    if code != 0 or not window_id:
        return None
    code, pid_str = _run([xdotool, "getwindowpid", window_id])
    pid = int(pid_str) if code == 0 and pid_str.isdigit() else None
    code, title = _run([xdotool, "getwindowname", window_id])

    process_name = ""
    if pid:
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").strip().decode("utf-8", errors="ignore")
            process_name = Path(cmdline.split()[0]).name if cmdline else ""
        except Exception:
            try:
                process_name = Path(f"/proc/{pid}/comm").read_text(encoding="utf-8", errors="ignore").strip()
            except Exception:
                pass

    return {
        "process_name": process_name or "unknown",
        "window_title": title or "",
        "pid": pid,
        "window_id": window_id,
    }


def get_open_files(pid: int) -> list[str]:
    open_files: list[str] = []
    try:
        proc_fd = Path("/proc") / str(pid) / "fd"
        if not proc_fd.exists():
            return open_files
        for entry in proc_fd.iterdir():
            try:
                target = entry.resolve()
                if target.is_file():
                    open_files.append(str(target))
            except OSError:
                continue
    except Exception:
        pass
    return open_files[:50]


def get_cwd_from_pid(pid: int) -> str | None:
    try:
        cwd_link = Path("/proc") / str(pid) / "cwd"
        if cwd_link.exists():
            return str(cwd_link.resolve())
    except Exception:
        pass
    return None


def get_active_shell_context() -> dict | None:
    foreground = get_foreground_process()
    if not foreground:
        return None

    pid = foreground.get("pid")
    if not pid:
        return foreground

    cwd = get_cwd_from_pid(pid)
    open_files = get_open_files(pid)

    return {
        "process_name": foreground.get("process_name", ""),
        "window_title": foreground.get("window_title", ""),
        "pid": pid,
        "working_directory": cwd,
        "open_files": open_files[:20],
    }


def get_recently_accessed_files(limit: int = 10) -> list[dict]:
    from fauxnix_tools.db import get_conn
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT file_path, title, updated_ts FROM fennix_ingested_files ORDER BY updated_ts DESC LIMIT ?",
            (limit,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def get_indexed_files_near(path: str, limit: int = 5) -> list[dict]:
    from fauxnix_tools.db import get_conn
    try:
        conn = get_conn()
        cur = conn.cursor()
        parent = str(Path(path).parent)
        cur.execute(
            "SELECT path, name, modified_ts FROM files WHERE source_dir = ? ORDER BY modified_ts DESC LIMIT ?",
            (parent, limit),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []
