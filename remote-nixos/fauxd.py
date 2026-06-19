#!/usr/bin/env python3
"""Tiny local API bridge for Fauxshell.

Fauxd is intentionally narrow:
- localhost only
- JSON only
- allowlisted actions
- no arbitrary shell command endpoint
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


HOST = "127.0.0.1"
PORT = int(os.environ.get("FAUXD_PORT", "8756"))
DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
STATE_HOME = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
ASSISTANT_CONFIG_PATH = Path("/etc/fauxnix/assistant.env")
USER_SETTINGS_PATH = CONFIG_HOME / "fauxnix" / "settings.env"
DB_PATH = DATA_HOME / "fennix" / "fennix.sqlite3"
FILE_PINS_PATH = DATA_HOME / "fennix" / "file-pins.json"
LOG_PATH = STATE_HOME / "fauxd" / "fauxd.log"
WEATHER_CACHE_PATH = STATE_HOME / "fauxd" / "weather.json"
FILE_INDEX_PATH = STATE_HOME / "fauxd" / "files-index.json"
WORKSPACE_ROOT = Path(os.environ.get("FAUXNIX_WORKSPACE_ROOT", Path.home() / "Fauxnix"))
THREADS_DIR = Path(os.environ.get("FAUXNIX_THREADS_DIR", WORKSPACE_ROOT / "Threads"))
REPOS_ROOT = Path(os.environ.get("FAUXNIX_REPOS_ROOT", WORKSPACE_ROOT / "Repos"))
COWRITER_ROOT = Path(os.environ.get("FAUXNIX_COWRITER_WORKSPACE", WORKSPACE_ROOT / "Cowriter"))

THREADS = [
    {"id": "fennix", "label": "Fennix", "description": "Local assistant", "action": "thread:fennix"},
    {"id": "fauxnix", "label": "Fauxnix", "description": "Workspace", "action": "thread:fauxnix"},
    {"id": "fauxdex", "label": "Fauxdex", "description": "Workspace agent loop", "action": "thread:fauxdex"},
    {"id": "cowriter", "label": "Cowriter", "description": "Notes and drafts", "action": "thread:cowriter"},
    {"id": "admin", "label": "Admin", "description": "Git-backed system state", "action": "thread:admin"},
    {"id": "root", "label": "Root", "description": "Administrator shell", "action": "thread:root"},
    {"id": "web", "label": "Web", "description": "Firefox workspace", "action": "thread:web"},
    {"id": "terminal", "label": "Terminal", "description": "Command line", "action": "thread:terminal"},
]

ACTION_COMMANDS = {
    "thread:web": ["fauxnix-thread", "web"],
    "threads:menu": ["fauxnix-thread", "menu"],
    "thread:fennix": ["fennix-gui"],
    "thread:fauxnix": ["fauxnix-thread", "fauxnix"],
    "thread:fauxdex": ["fauxnix-thread", "fauxdex"],
    "thread:cowriter": ["fauxnix-thread", "cowriter"],
    "thread:admin": ["fauxnix-thread", "admin"],
    "thread:root": ["fauxnix-thread", "root"],
    "thread:terminal": ["fauxnix-thread", "terminal"],
    "apps": ["rofi", "-show", "drun"],
    "notes": ["fennix-gui", "--notes"],
    "launcher": ["fauxshell-host", "--launcher-toggle"],
}

SHELL_EVENTS = {
    "nav:back",
    "nav:forward",
    "nav:home",
    "nav:threads",
    "zoom:in",
    "zoom:out",
    "zoom:reset",
}


def log(message: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass


def acquire_lock() -> int | None:
    try:
        import fcntl  # type: ignore[import-not-found]
    except ImportError:
        return None

    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        fd = os.open(RUNTIME_DIR / "fauxd.lock", os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BlockingIOError:
        return None


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    text = read_text(path)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_settings() -> dict[str, str]:
    values = parse_env_file(ASSISTANT_CONFIG_PATH)
    values.update(parse_env_file(USER_SETTINGS_PATH))
    return values


def cpu_times() -> tuple[int, int] | None:
    stat = read_text(Path("/proc/stat"))
    if not stat:
        return None
    parts = stat.splitlines()[0].split()
    if not parts or parts[0] != "cpu":
        return None
    try:
        values = [int(part) for part in parts[1:]]
    except ValueError:
        return None
    if len(values) < 5:
        return None
    idle = values[3] + values[4]
    return idle, sum(values)


def memory_status() -> tuple[float | None, str]:
    meminfo = read_text(Path("/proc/meminfo"))
    values: dict[str, int] = {}
    for line in meminfo.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            values[parts[0].rstrip(":")] = int(parts[1])
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    if not total:
        return None, "RAM n/a"
    used = max(total - available, 0)
    return (used / total) * 100, f"{used // 1024}/{total // 1024} MB"


def battery_status() -> tuple[float | None, str]:
    for battery in sorted(Path("/sys/class/power_supply").glob("BAT*")):
        capacity = read_text(battery / "capacity")
        status = read_text(battery / "status")
        if capacity:
            try:
                percent = float(capacity)
            except ValueError:
                percent = None
            suffix = f" {status.lower()}" if status else ""
            return percent, f"{capacity}%{suffix}"
    return None, "n/a"


def network_status() -> str:
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "dev", "wifi"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
        for line in result.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[0] == "yes":
                return f"{parts[1] or 'wifi'} {parts[-1]}%"
    except (OSError, subprocess.SubprocessError):
        pass

    try:
        result = subprocess.run(
            ["ip", "-o", "route", "show", "default"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        line = result.stdout.splitlines()[0] if result.stdout.splitlines() else ""
        parts = line.split()
        if "dev" in parts:
            return parts[parts.index("dev") + 1]
    except (OSError, subprocess.SubprocessError, IndexError):
        pass
    return "n/a"


def audio_status() -> tuple[float | None, str]:
    try:
        result = subprocess.run(
            ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        output = (result.stdout + result.stderr).strip()
        muted = "MUTED" in output.upper()
        for token in output.replace("[", " ").replace("]", " ").split():
            try:
                value = float(token)
            except ValueError:
                continue
            percent = max(0.0, min(value * 100, 100.0))
            return percent, f"{percent:.0f}%{' muted' if muted else ''}"
    except (OSError, subprocess.SubprocessError):
        pass
    return None, "n/a"


def weather_status() -> dict[str, Any]:
    location = load_settings().get("FAUXNIX_WEATHER_LOCATION", "").strip()
    if not location:
        return {
            "configured": False,
            "location": "",
            "summary": "Set weather location",
            "symbol": "--",
            "updated_at": 0,
        }

    try:
        cached = json.loads(read_text(WEATHER_CACHE_PATH) or "{}")
    except json.JSONDecodeError:
        cached = {}
    now = int(time.time())
    has_cached_weather = cached.get("location") == location and cached.get("summary")
    if (
        has_cached_weather
        and int(cached.get("updated_at") or 0) > now - 600
        and not cached.get("error")
    ):
        return cached

    encoded = urllib.parse.quote(location)
    url = f"https://wttr.in/{encoded}?format=%l|%c|%t|%C|%w|%h"
    payload: dict[str, Any]
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "fauxd-weather"})
        with urllib.request.urlopen(request, timeout=4) as response:
            text = response.read(240).decode("utf-8", errors="replace").strip()
        parts = [part.strip() for part in text.split("|")]
        while len(parts) < 6:
            parts.append("")
        place, symbol, temp, condition, wind, humidity = parts[:6]
        summary = ", ".join(part for part in [place or location, temp, condition, wind, humidity] if part)
        payload = {
            "configured": True,
            "location": location,
            "summary": summary or location,
            "symbol": symbol or "--",
            "temperature": temp,
            "condition": condition,
            "wind": wind,
            "humidity": humidity,
            "updated_at": now,
        }
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        if has_cached_weather:
            cached["stale"] = True
            cached["last_error"] = str(exc)
            return cached
        payload = {
            "configured": True,
            "location": location,
            "summary": f"{location} weather unavailable",
            "symbol": "--",
            "error": str(exc),
            "updated_at": now,
        }

    try:
        WEATHER_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        WEATHER_CACHE_PATH.write_text(json.dumps(payload), encoding="utf-8")
    except OSError as exc:
        log(f"weather cache write failed: {exc}")
    return payload


def db_connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        PRAGMA journal_mode = wal;

        CREATE TABLE IF NOT EXISTS conversations (
          id INTEGER PRIMARY KEY,
          title TEXT NOT NULL,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
          id INTEGER PRIMARY KEY,
          conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
          role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
          route TEXT NOT NULL DEFAULT 'local',
          content TEXT NOT NULL,
          created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS notes (
          id INTEGER PRIMARY KEY,
          title TEXT NOT NULL,
          content TEXT NOT NULL,
          source TEXT NOT NULL DEFAULT 'manual',
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS clipboard_items (
          id INTEGER PRIMARY KEY,
          kind TEXT NOT NULL DEFAULT 'text',
          content TEXT NOT NULL,
          source TEXT NOT NULL DEFAULT 'manual',
          note_id INTEGER,
          created_at INTEGER NOT NULL,
          FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE SET NULL
        );
        """
    )
    return conn


def db_rows(query: str, args: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    try:
        conn = db_connect()
        rows = list(conn.execute(query, args))
        conn.close()
        return rows
    except sqlite3.Error as exc:
        log(f"database query failed: {exc}")
        return []


def table_count(table: str) -> int:
    rows = db_rows(f"SELECT COUNT(*) AS count FROM {table}")
    return int(rows[0]["count"]) if rows else 0


def first_line_title(content: str, fallback: str = "Untitled note") -> str:
    for line in content.splitlines():
        title = " ".join(line.strip().split())
        if title:
            return title[:80]
    return fallback


def first_activity_line(content: str, fallback: str) -> str:
    metadata_prefixes = ("created_at:", "updated_at:", "id:", "kind:", "type:", "label:", "title:")
    for line in content.splitlines():
        title = " ".join(line.strip().split())
        lowered = title.lower()
        if not title or title.startswith("#") or lowered.startswith(metadata_prefixes):
            continue
        title = title.lstrip("-* ").strip()
        if title:
            return title[:120]
    return fallback


def compact_text(value: str, limit: int = 180) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."


def path_mtime(path: Path) -> int:
    try:
        return int(path.stat().st_mtime)
    except OSError:
        return 0


SKIP_FILE_DIRS = {
    ".cache",
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "node_modules",
    "target",
    "result",
}

FILE_KIND_BY_EXT = {
    ".c": "code",
    ".cfg": "config",
    ".css": "code",
    ".csv": "data",
    ".gif": "image",
    ".html": "code",
    ".jpeg": "image",
    ".jpg": "image",
    ".js": "code",
    ".json": "data",
    ".lock": "data",
    ".log": "log",
    ".md": "note",
    ".nix": "nix",
    ".pdf": "pdf",
    ".png": "image",
    ".py": "code",
    ".sh": "script",
    ".svg": "image",
    ".toml": "config",
    ".txt": "text",
    ".webp": "image",
    ".yaml": "config",
    ".yml": "config",
}

TEXT_PREVIEW_EXTENSIONS = {
    ".c",
    ".cfg",
    ".conf",
    ".cpp",
    ".css",
    ".csv",
    ".h",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".lock",
    ".log",
    ".md",
    ".nix",
    ".py",
    ".rs",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}


def watched_file_roots() -> list[tuple[str, Path]]:
    return [
        ("Downloads", Path.home() / "Downloads"),
        ("Pictures", Path.home() / "Pictures"),
        ("Threads", THREADS_DIR),
        ("Cowriter", COWRITER_ROOT),
        ("Repos", REPOS_ROOT),
    ]


def file_kind(path: Path) -> str:
    return FILE_KIND_BY_EXT.get(path.suffix.lower(), path.suffix.lower().lstrip(".") or "file")


def evidence_label(root_name: str, kind: str) -> str:
    if root_name == "Threads":
        return "thread memory"
    if root_name == "Cowriter":
        return "cowriter evidence"
    if root_name == "Repos":
        return "workspace source"
    if kind in {"image", "pdf"}:
        return f"{kind} evidence"
    return "local file evidence"


def source_confidence(root_name: str) -> str:
    if root_name in {"Threads", "Cowriter", "Repos"}:
        return "high"
    if root_name in {"Downloads", "Pictures"}:
        return "medium"
    return "candidate"


def file_payload(path: Path, root_name: str, root_path: Path, stat_result: os.stat_result) -> dict[str, Any]:
    try:
        relative = str(path.relative_to(root_path))
    except ValueError:
        relative = path.name
    kind = file_kind(path)
    return {
        "title": path.name,
        "path": str(path),
        "relative_path": relative,
        "root": root_name,
        "kind": kind,
        "evidence_label": evidence_label(root_name, kind),
        "source_confidence": source_confidence(root_name),
        "size": int(stat_result.st_size),
        "updated_at": int(stat_result.st_mtime),
    }


def scan_recent_files_for_root(root_name: str, root_path: Path, per_root: int = 8) -> tuple[list[dict[str, Any]], int]:
    root_path = root_path.expanduser()
    if not root_path.exists() or not root_path.is_dir():
        return [], 0

    max_depth = 4 if root_name in {"Threads", "Cowriter"} else 3
    max_seen = 900 if root_name == "Repos" else 450
    stack: list[tuple[Path, int]] = [(root_path, 0)]
    rows: list[dict[str, Any]] = []
    seen = 0

    while stack and seen < max_seen:
        current, depth = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if seen >= max_seen:
                        break
                    name = entry.name
                    if name.startswith(".") or name in SKIP_FILE_DIRS:
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if depth < max_depth:
                                stack.append((Path(entry.path), depth + 1))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        stat_result = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    seen += 1
                    rows.append(file_payload(Path(entry.path), root_name, root_path, stat_result))
        except OSError as exc:
            log(f"file scan failed: {current}: {exc}")

    rows.sort(key=lambda item: int(item.get("updated_at") or 0), reverse=True)
    return rows[:per_root], seen


def allowed_file_roots() -> dict[str, Path]:
    return {name: path.expanduser() for name, path in watched_file_roots()}


def known_thread_ids() -> set[str]:
    return {str(thread.get("id") or "") for thread in THREADS if str(thread.get("id") or "")}


def safe_thread_id(thread_id: str) -> str:
    clean = (thread_id or "").strip().lower()
    if clean not in known_thread_ids():
        raise ValueError(f"unknown thread: {thread_id or 'unset'}")
    return clean


def thread_attachments_path(thread_id: str) -> Path:
    clean = safe_thread_id(thread_id)
    return THREADS_DIR / clean / "attachments.json"


def read_json_list(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def write_json_list(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def attachment_payload(path: Path, thread_id: str) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    root_name = ""
    root_path = Path("/")
    for candidate_name, candidate_root in allowed_file_roots().items():
        try:
            resolved_root = candidate_root.resolve(strict=True)
            resolved.relative_to(resolved_root)
        except (OSError, ValueError):
            continue
        root_name = candidate_name
        root_path = resolved_root
        break
    stat_result = resolved.stat()
    payload = file_payload(resolved, root_name or "Files", root_path, stat_result)
    payload.update(
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"fauxnix:{thread_id}:{resolved}")),
            "thread": thread_id,
            "attached_at": int(time.time()),
        }
    )
    return payload


def pinned_file_payload(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    root_name = ""
    root_path = Path("/")
    for candidate_name, candidate_root in allowed_file_roots().items():
        try:
            resolved_root = candidate_root.resolve(strict=True)
            resolved.relative_to(resolved_root)
        except (OSError, ValueError):
            continue
        root_name = candidate_name
        root_path = resolved_root
        break
    stat_result = resolved.stat()
    payload = file_payload(resolved, root_name or "Files", root_path, stat_result)
    payload.update(
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"fauxnix:pinned:{resolved}")),
            "pinned_at": int(time.time()),
        }
    )
    return payload


def recent_files(limit: int = 5, root_filter: str = "") -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    roots: list[dict[str, Any]] = []
    scanned_total = 0
    for root_name, root_path in watched_file_roots():
        if root_filter and root_name.lower() != root_filter.lower():
            continue
        rows, scanned = scan_recent_files_for_root(root_name, root_path)
        scanned_total += scanned
        roots.append(
            {
                "name": root_name,
                "path": str(root_path.expanduser()),
                "exists": root_path.expanduser().is_dir(),
                "scanned": scanned,
            }
        )
        files.extend(rows)

    files.sort(key=lambda item: int(item.get("updated_at") or 0), reverse=True)
    limit = max(1, min(limit, 20))
    return {
        "count": len(files),
        "scanned": scanned_total,
        "updated_at": int(time.time()),
        "roots": roots,
        "recent": files[:limit],
    }


def build_file_index(limit: int = 24, root_filter: str = "") -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    roots: list[dict[str, Any]] = []
    kind_counts: dict[str, int] = {}
    confidence_counts: dict[str, int] = {}
    scanned_total = 0

    for root_name, root_path in watched_file_roots():
        if root_filter and root_name.lower() != root_filter.lower():
            continue
        rows, scanned = scan_recent_files_for_root(root_name, root_path, per_root=260)
        scanned_total += scanned
        for row in rows:
            kind = str(row.get("kind") or "file")
            confidence = str(row.get("source_confidence") or "candidate")
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
            confidence_counts[confidence] = confidence_counts.get(confidence, 0) + 1
        newest = max((int(row.get("updated_at") or 0) for row in rows), default=0)
        roots.append(
            {
                "name": root_name,
                "path": str(root_path.expanduser()),
                "exists": root_path.expanduser().is_dir(),
                "scanned": scanned,
                "indexed": len(rows),
                "newest": newest,
            }
        )
        files.extend(rows)

    files.sort(key=lambda item: int(item.get("updated_at") or 0), reverse=True)
    limit = max(1, min(limit, 80))
    payload = {
        "count": len(files),
        "scanned": scanned_total,
        "updated_at": int(time.time()),
        "path": str(FILE_INDEX_PATH),
        "kind_counts": kind_counts,
        "confidence_counts": confidence_counts,
        "roots": roots,
        "recent": files[:limit],
    }
    FILE_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    FILE_INDEX_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def file_index(limit: int = 24, root_filter: str = "", rebuild: bool = False) -> dict[str, Any]:
    if rebuild or root_filter or not FILE_INDEX_PATH.exists():
        return build_file_index(limit, root_filter)
    try:
        payload = json.loads(FILE_INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return build_file_index(limit, root_filter)
    if not isinstance(payload, dict):
        return build_file_index(limit, root_filter)
    payload = dict(payload)
    rows = payload.get("recent")
    if isinstance(rows, list):
        payload["recent"] = rows[: max(1, min(limit, 80))]
    return payload


def safe_file_from_request(raw_path: str) -> tuple[Path | None, str, str]:
    if not raw_path:
        return None, "", "missing path"
    try:
        requested = Path(unquote(raw_path)).expanduser().resolve(strict=True)
    except OSError as exc:
        return None, "", str(exc)
    if not requested.is_file() or requested.is_symlink():
        return None, "", "path is not a regular file"
    for root_name, root_path in allowed_file_roots().items():
        try:
            resolved_root = root_path.resolve(strict=True)
        except OSError:
            continue
        try:
            requested.relative_to(resolved_root)
        except ValueError:
            continue
        return requested, root_name, ""
    return None, "", "path is outside watched roots"


def text_preview(path: Path, limit: int = 8000) -> tuple[str, bool]:
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    truncated = len(data) > limit
    sample = data[:limit]
    if b"\x00" in sample[:1024]:
        return "", truncated
    try:
        text = sample.decode("utf-8")
    except UnicodeDecodeError:
        text = sample.decode("utf-8", errors="replace")
    return text, truncated


def is_text_previewable(path: Path) -> bool:
    kind = file_kind(path)
    return kind in {"code", "config", "data", "log", "nix", "note", "script", "text"} or path.suffix.lower() in TEXT_PREVIEW_EXTENSIONS


def search_text_snippet(path: Path, query: str) -> str:
    try:
        text, _truncated = text_preview(path, 32000)
    except OSError:
        return ""
    lower = text.lower()
    needle = query.lower()
    index = lower.find(needle)
    if index < 0:
        terms = [term for term in needle.split() if term]
        indexes = [lower.find(term) for term in terms]
        indexes = [item for item in indexes if item >= 0]
        if not indexes:
            return ""
        index = min(indexes)
    start = max(0, index - 140)
    end = min(len(text), index + max(len(query), 1) + 260)
    snippet = " ".join(text[start:end].split())
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return compact_text(snippet, 420)


def search_files(query: str, limit: int = 12, root_filter: str = "", include_content: bool = False) -> dict[str, Any]:
    clean_query = compact_text((query or "").strip(), 80)
    if not clean_query:
        return recent_files(limit, root_filter)

    needle = clean_query.lower()
    terms = [term for term in needle.split() if term]
    matches: list[dict[str, Any]] = []
    roots: list[dict[str, Any]] = []
    scanned_total = 0

    for root_name, root_path in watched_file_roots():
        if root_filter and root_name.lower() != root_filter.lower():
            continue
        rows, scanned = scan_recent_files_for_root(root_name, root_path, per_root=160)
        scanned_total += scanned
        roots.append(
            {
                "name": root_name,
                "path": str(root_path.expanduser()),
                "exists": root_path.expanduser().is_dir(),
                "scanned": scanned,
            }
        )
        for row in rows:
            haystack = " ".join(
                [
                    str(row.get("title") or ""),
                    str(row.get("relative_path") or ""),
                    str(row.get("root") or ""),
                    str(row.get("kind") or ""),
                ]
            ).lower()
            name_match = needle in haystack or bool(terms and all(term in haystack for term in terms))
            snippet = ""
            content_match = False
            path = Path(str(row.get("path") or ""))
            if include_content and is_text_previewable(path):
                snippet = search_text_snippet(path, clean_query)
                content_match = bool(snippet)
            if not name_match and not content_match:
                continue

            item = dict(row)
            item["match"] = "name" if name_match else "content"
            if snippet:
                item["snippet"] = snippet
            score = (30 if name_match else 0) + (12 if content_match else 0)
            item["_score"] = score
            matches.append(item)

    matches.sort(key=lambda item: (int(item.get("_score") or 0), int(item.get("updated_at") or 0)), reverse=True)
    for item in matches:
        item.pop("_score", None)
    limit = max(1, min(limit, 30))
    return {
        "count": len(matches),
        "scanned": scanned_total,
        "updated_at": int(time.time()),
        "query": clean_query,
        "content": include_content,
        "roots": roots,
        "recent": matches[:limit],
    }


def file_preview(raw_path: str) -> dict[str, Any]:
    path, root_name, error = safe_file_from_request(raw_path)
    if path is None:
        return {"ok": False, "error": error or "file unavailable"}
    stat_result = path.stat()
    payload = file_payload(path, root_name, allowed_file_roots()[root_name], stat_result)
    preview = ""
    preview_kind = "metadata"
    truncated = False
    if payload["kind"] == "image":
        preview_kind = "image"
        preview = "Image preview is available."
    elif payload["kind"] == "pdf":
        preview_kind = "pdf"
        preview = "PDF metadata preview is available. Inline PDF rendering is planned for a later pass."
    elif is_text_previewable(path):
        try:
            preview, truncated = text_preview(path)
            preview_kind = "markdown" if path.suffix.lower() == ".md" and preview else "text" if preview else "metadata"
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "file": payload,
        "preview": preview,
        "preview_kind": preview_kind,
        "truncated": truncated,
    }


def pinned_files(limit: int = 20) -> dict[str, Any]:
    rows = read_json_list(FILE_PINS_PATH)
    valid_rows: list[dict[str, Any]] = []
    for row in rows:
        raw_path = str(row.get("path") or "")
        safe_path, _root, _error = safe_file_from_request(raw_path)
        if safe_path is None:
            continue
        item = dict(row)
        stat_result = safe_path.stat()
        root_name = str(item.get("root") or "Files")
        root_path = allowed_file_roots().get(root_name, safe_path.parent)
        item.update(file_payload(safe_path, root_name, root_path, stat_result))
        item.setdefault("id", str(uuid.uuid5(uuid.NAMESPACE_URL, f"fauxnix:pinned:{safe_path}")))
        item.setdefault("pinned_at", int(item.get("updated_at") or 0))
        valid_rows.append(item)
    valid_rows.sort(key=lambda item: int(item.get("pinned_at") or item.get("updated_at") or 0), reverse=True)
    limit = max(1, min(limit, 80))
    return {
        "count": len(valid_rows),
        "scanned": len(rows),
        "updated_at": int(time.time()),
        "path": str(FILE_PINS_PATH),
        "recent": valid_rows[:limit],
    }


def pin_file(raw_path: str) -> dict[str, Any]:
    path, _root_name, error = safe_file_from_request(raw_path)
    if path is None:
        raise ValueError(error or "file unavailable")
    pin = pinned_file_payload(path)
    rows = read_json_list(FILE_PINS_PATH)
    rows = [row for row in rows if str(row.get("id") or "") != pin["id"]]
    rows.insert(0, pin)
    rows = rows[:160]
    write_json_list(FILE_PINS_PATH, rows)
    return pin


def unpin_file(raw_path: str) -> dict[str, Any]:
    path, _root_name, error = safe_file_from_request(raw_path)
    if path is None:
        raise ValueError(error or "file unavailable")
    pin_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"fauxnix:pinned:{path.resolve(strict=True)}"))
    rows = read_json_list(FILE_PINS_PATH)
    kept = [row for row in rows if str(row.get("id") or "") != pin_id]
    changed = len(kept) != len(rows)
    write_json_list(FILE_PINS_PATH, kept)
    return {"id": pin_id, "path": str(path), "removed": changed}


def thread_file_attachments(thread_id: str) -> dict[str, Any]:
    clean = safe_thread_id(thread_id)
    path = thread_attachments_path(clean)
    rows = read_json_list(path)
    valid_rows: list[dict[str, Any]] = []
    for row in rows:
        raw_path = str(row.get("path") or "")
        safe_path, _root, _error = safe_file_from_request(raw_path)
        if safe_path is None:
            continue
        item = dict(row)
        item.setdefault("title", safe_path.name)
        item.setdefault("kind", file_kind(safe_path))
        item.setdefault("updated_at", path_mtime(safe_path))
        item.setdefault("thread", clean)
        valid_rows.append(item)
    valid_rows.sort(key=lambda item: int(item.get("attached_at") or item.get("updated_at") or 0), reverse=True)
    return {
        "thread": clean,
        "count": len(valid_rows),
        "path": str(path),
        "recent": valid_rows,
    }


def attach_file_to_thread(raw_path: str, thread_id: str) -> dict[str, Any]:
    clean = safe_thread_id(thread_id)
    path, _root_name, error = safe_file_from_request(raw_path)
    if path is None:
        raise ValueError(error or "file unavailable")
    attachment = attachment_payload(path, clean)
    manifest_path = thread_attachments_path(clean)
    rows = read_json_list(manifest_path)
    rows = [row for row in rows if str(row.get("id") or "") != attachment["id"]]
    rows.insert(0, attachment)
    rows = rows[:120]
    write_json_list(manifest_path, rows)
    return attachment


def promote_file_to_memory(raw_path: str, thread_id: str = "") -> dict[str, Any]:
    path, root_name, error = safe_file_from_request(raw_path)
    if path is None:
        raise ValueError(error or "file unavailable")
    stat_result = path.stat()
    payload = file_payload(path, root_name, allowed_file_roots()[root_name], stat_result)
    preview = file_preview(str(path))
    preview_text = compact_text(str(preview.get("preview") or ""), 1200)
    title = f"File evidence: {payload['title']}"
    lines = [
        f"path: {payload['path']}",
        f"root: {payload['root']}",
        f"relative_path: {payload['relative_path']}",
        f"kind: {payload['kind']}",
        f"size: {payload['size']}",
        f"updated_at: {payload['updated_at']}",
    ]
    if thread_id:
        lines.append(f"thread: {safe_thread_id(thread_id)}")
    if preview_text:
        lines.extend(["", "preview:", preview_text])
    note = create_note(title, "\n".join(lines), "file-evidence")
    return {"note": note, "file": payload}


def note_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "title": str(row["title"]),
        "content": str(row["content"]),
        "source": str(row["source"]),
        "created_at": int(row["created_at"]),
        "updated_at": int(row["updated_at"]),
    }


def clipboard_payload(row: sqlite3.Row) -> dict[str, Any]:
    note_id = row["note_id"]
    return {
        "id": int(row["id"]),
        "kind": str(row["kind"]),
        "content": str(row["content"]),
        "source": str(row["source"]),
        "note_id": int(note_id) if note_id is not None else None,
        "created_at": int(row["created_at"]),
    }


def create_note(title: str, content: str, source: str = "manual") -> dict[str, Any]:
    clean_content = (content or "").strip()
    if not clean_content and not title.strip():
        raise ValueError("note content is empty")
    clean_title = (title or "").strip() or first_line_title(clean_content)
    now = int(time.time())
    conn = db_connect()
    cur = conn.execute(
        """
        INSERT INTO notes (title, content, source, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (clean_title[:120], clean_content, (source or "manual")[:32], now, now),
    )
    note_id = int(cur.lastrowid)
    row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    conn.commit()
    conn.close()
    return note_payload(row)


def update_note(note_id: int, title: str | None = None, content: str | None = None) -> dict[str, Any]:
    fields = ["updated_at = ?"]
    params: list[Any] = [int(time.time())]
    if title is not None:
        fields.insert(0, "title = ?")
        params.insert(0, (title.strip() or "Untitled note")[:120])
    if content is not None:
        fields.insert(0, "content = ?")
        params.insert(0, content.strip())
    params.append(note_id)
    conn = db_connect()
    cur = conn.execute(f"UPDATE notes SET {', '.join(fields)} WHERE id = ?", params)
    if cur.rowcount == 0:
        conn.close()
        raise ValueError("note not found")
    row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    conn.commit()
    conn.close()
    return note_payload(row)


def create_clipboard_text(content: str, source: str = "manual") -> dict[str, Any]:
    clean_content = (content or "").strip()
    if not clean_content:
        raise ValueError("clipboard content is empty")
    note = create_note(
        f"Clipboard {time.strftime('%Y-%m-%d %H:%M')}",
        clean_content,
        "clipboard",
    )
    now = int(time.time())
    conn = db_connect()
    cur = conn.execute(
        """
        INSERT INTO clipboard_items (kind, content, source, note_id, created_at)
        VALUES ('text', ?, ?, ?, ?)
        """,
        (clean_content, (source or "manual")[:32], note["id"], now),
    )
    item_id = int(cur.lastrowid)
    row = conn.execute("SELECT * FROM clipboard_items WHERE id = ?", (item_id,)).fetchone()
    conn.commit()
    conn.close()
    item = clipboard_payload(row)
    item["note"] = note
    return item


def recent_clipboard(limit: int = 4) -> list[dict[str, Any]]:
    rows = db_rows(
        """
        SELECT id, kind, content, source, note_id, created_at
        FROM clipboard_items
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [clipboard_payload(row) for row in rows]


def clear_clipboard() -> dict[str, Any]:
    conn = db_connect()
    row = conn.execute("SELECT COUNT(*) AS count FROM clipboard_items").fetchone()
    count = int(row["count"]) if row else 0
    conn.execute("DELETE FROM clipboard_items")
    conn.commit()
    conn.close()
    return {"cleared": count}


def recent_notes(limit: int = 4) -> list[dict[str, Any]]:
    rows = db_rows(
        """
        SELECT id, title, content, source, created_at, updated_at
        FROM notes
        ORDER BY updated_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [note_payload(row) for row in rows]


def recent_sessions(limit: int = 4) -> list[dict[str, Any]]:
    rows = db_rows(
        """
        SELECT id, title, updated_at
        FROM conversations
        ORDER BY updated_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [
        {
            "id": int(row["id"]),
            "title": str(row["title"]),
            "updated_at": int(row["updated_at"]),
            "action": "thread:fennix",
        }
        for row in rows
    ]


def recent_conversation_bubbles(limit: int = 3) -> list[dict[str, Any]]:
    rows = db_rows(
        """
        SELECT
          c.id,
          c.title,
          c.updated_at,
          (
            SELECT m.role
            FROM messages m
            WHERE m.conversation_id = c.id
            ORDER BY m.created_at DESC, m.id DESC
            LIMIT 1
          ) AS role,
          (
            SELECT m.content
            FROM messages m
            WHERE m.conversation_id = c.id
            ORDER BY m.created_at DESC, m.id DESC
            LIMIT 1
          ) AS content
        FROM conversations c
        ORDER BY c.updated_at DESC, c.id DESC
        LIMIT ?
        """,
        (limit,),
    )
    bubbles: list[dict[str, Any]] = []
    for row in rows:
        role = str(row["role"] or "chat")
        content = str(row["content"] or "")
        text = compact_text(content, 150)
        if not text:
            text = "Open the latest Fennix conversation"
        bubbles.append(
            {
                "id": f"chat:{int(row['id'])}",
                "source": "chat",
                "kind": role,
                "title": str(row["title"]),
                "text": text,
                "updated_at": int(row["updated_at"]),
                "action": "thread:fennix",
            }
        )
    return bubbles


def recent_note_bubbles(limit: int = 2) -> list[dict[str, Any]]:
    bubbles: list[dict[str, Any]] = []
    for note in recent_notes(limit):
        bubbles.append(
            {
                "id": f"note:{note['id']}",
                "source": "note",
                "kind": str(note.get("source") or "note"),
                "title": str(note.get("title") or "Note"),
                "text": compact_text(str(note.get("content") or ""), 130),
                "updated_at": int(note.get("updated_at") or note.get("created_at") or 0),
                "action": "notes",
            }
        )
    return bubbles


def recent_file_bubbles(limit: int = 2) -> list[dict[str, Any]]:
    bubbles: list[dict[str, Any]] = []
    for file in recent_files(limit).get("recent", []):
        bubbles.append(
            {
                "id": f"file:{file.get('path')}",
                "source": "file",
                "kind": str(file.get("evidence_label") or file.get("kind") or "evidence"),
                "title": str(file.get("title") or "File evidence"),
                "text": compact_text(str(file.get("relative_path") or file.get("path") or ""), 130),
                "updated_at": int(file.get("updated_at") or 0),
                "action": "files",
                "path": str(file.get("path") or ""),
            }
        )
    return bubbles


def pinned_file_bubbles(limit: int = 2) -> list[dict[str, Any]]:
    bubbles: list[dict[str, Any]] = []
    for file in pinned_files(limit).get("recent", []):
        bubbles.append(
            {
                "id": f"pin:{file.get('path')}",
                "source": "file",
                "kind": "pinned evidence",
                "title": str(file.get("title") or "Pinned file"),
                "text": compact_text(str(file.get("relative_path") or file.get("path") or ""), 130),
                "updated_at": int(file.get("pinned_at") or file.get("updated_at") or 0),
                "action": "files",
                "path": str(file.get("path") or ""),
            }
        )
    return bubbles


def parse_thread_metadata(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    text = read_text(path)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def thread_bubbles(limit: int = 2) -> list[dict[str, Any]]:
    bubbles: list[dict[str, Any]] = []
    if not THREADS_DIR.exists():
        return [
            {
                "id": "thread:missing",
                "source": "thread",
                "kind": "workspace",
                "title": "Threads not initialized",
                "text": str(THREADS_DIR),
                "updated_at": 0,
                "action": "thread:fauxnix",
            }
        ]

    try:
        children = [
            child
            for child in THREADS_DIR.iterdir()
            if child.is_dir() and not child.name.startswith(".")
        ]
    except OSError as exc:
        log(f"thread scan failed: {exc}")
        return []

    children.sort(key=path_mtime, reverse=True)
    for child in children[:limit]:
        metadata = parse_thread_metadata(child / "thread.toml")
        label = metadata.get("label") or metadata.get("title") or child.name
        kind = metadata.get("kind") or metadata.get("type") or "thread"
        state = first_line_title(read_text(child / "state.md"), "Ready to resume")
        bubbles.append(
            {
                "id": f"thread:{child.name}",
                "source": "thread",
                "kind": kind,
                "title": label,
                "text": compact_text(state, 130),
                "updated_at": path_mtime(child),
                "action": "threads:menu",
                "path": str(child),
            }
        )
    return bubbles


def thread_activity(thread_id: str, fallback: str) -> dict[str, Any]:
    path = THREADS_DIR / thread_id
    if not path.exists():
        return {
            "text": fallback,
            "updated_at": 0,
            "path": str(path),
            "memory_count": 0,
        }

    metadata = parse_thread_metadata(path / "thread.toml")
    state = read_text(path / "state.md")
    readme = read_text(path / "README.md")
    history_dir = path / "history"
    memory_count = 0
    history_latest = 0
    if history_dir.exists():
        try:
            history_files = [
                child
                for child in history_dir.iterdir()
                if child.is_file() and not child.name.startswith(".")
            ]
            memory_count = len(history_files)
            history_latest = max((path_mtime(child) for child in history_files), default=0)
        except OSError as exc:
            log(f"thread history scan failed: {thread_id}: {exc}")

    text = first_activity_line(state, "")
    if not text:
        text = metadata.get("summary") or metadata.get("description") or first_activity_line(readme, fallback)
    updated_at = max(path_mtime(path), path_mtime(path / "state.md"), path_mtime(path / "thread.toml"), history_latest)
    return {
        "text": compact_text(text, 170),
        "updated_at": updated_at,
        "path": str(path),
        "memory_count": memory_count,
    }


def thread_cards() -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for thread in THREADS:
        thread_id = str(thread.get("id") or "")
        if not thread_id:
            continue
        activity = thread_activity(thread_id, str(thread.get("description") or "Ready to resume"))
        cards.append(
            {
                "id": thread_id,
                "title": str(thread.get("label") or thread_id.title()),
                "description": str(thread.get("description") or ""),
                "text": activity["text"],
                "updated_at": int(activity["updated_at"]),
                "memory_count": int(activity["memory_count"]),
                "path": activity["path"],
                "action": str(thread.get("action") or f"thread:{thread_id}"),
            }
        )
    return cards


def command_output(command: list[str], timeout: int = 3, limit: int = 500) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    return result.returncode, compact_text(output, limit)


def git_spine_bubbles() -> list[dict[str, Any]]:
    repos = [
        ("admin", REPOS_ROOT / "admin", "thread:admin"),
        ("home", REPOS_ROOT / "home", "thread:fauxnix"),
        ("threads", THREADS_DIR, "threads:menu"),
    ]
    bubbles: list[dict[str, Any]] = []
    for name, path, action in repos:
        title = f"{name.title()} spine"
        if not path.exists():
            text = f"{path} is not initialized"
            updated_at = 0
        elif not (path / ".git").exists():
            text = f"{path} is not a git repo yet"
            updated_at = path_mtime(path)
        else:
            status_code, status = command_output(["git", "-C", str(path), "status", "--short"], timeout=3, limit=900)
            _log_code, last_commit = command_output(["git", "-C", str(path), "log", "-1", "--oneline"], timeout=3, limit=180)
            if status_code != 0:
                state = status or "status unavailable"
            elif status:
                changed = len([line for line in status.splitlines() if line.strip()])
                state = f"{changed} changed file{'s' if changed != 1 else ''}"
            else:
                state = "clean"
            text = state if not last_commit else f"{state}; last {last_commit}"
            updated_at = path_mtime(path)
        bubbles.append(
            {
                "id": f"git:{name}",
                "source": "git",
                "kind": name,
                "title": title,
                "text": compact_text(text, 140),
                "updated_at": updated_at,
                "action": action,
                "path": str(path),
            }
        )
    return bubbles


def continuity_constellation(limit: int = 9) -> dict[str, Any]:
    bubbles: list[dict[str, Any]] = []
    bubbles.extend(recent_conversation_bubbles(3))
    bubbles.extend(recent_note_bubbles(2))
    bubbles.extend(pinned_file_bubbles(2))
    bubbles.extend(recent_file_bubbles(2))
    bubbles.extend(thread_bubbles(2))
    bubbles.extend(git_spine_bubbles())
    bubbles.sort(key=lambda item: int(item.get("updated_at") or 0), reverse=True)
    return {
        "count": len(bubbles),
        "updated_at": int(time.time()),
        "bubbles": bubbles[:limit],
    }


def telemetry(previous_cpu: tuple[int, int] | None) -> tuple[dict[str, Any], tuple[int, int] | None]:
    cpu_count = max(os.cpu_count() or 1, 1)
    try:
        load = os.getloadavg()[0]
    except OSError:
        load = 0.0
    load_percent = max(0.0, min((load / cpu_count) * 100, 100.0))
    current_cpu = cpu_times()
    cpu_percent: float | None = None
    if previous_cpu and current_cpu:
        idle_delta = current_cpu[0] - previous_cpu[0]
        total_delta = current_cpu[1] - previous_cpu[1]
        if total_delta > 0:
            cpu_percent = max(0.0, min((1 - (idle_delta / total_delta)) * 100, 100.0))
    if cpu_percent is None and current_cpu:
        cpu_percent = load_percent

    memory_percent, memory_text = memory_status()
    battery_percent, battery_text = battery_status()
    audio_percent, audio_text = audio_status()
    network_text = network_status()

    return (
        {
            "time": int(time.time()),
            "cpu_percent": cpu_percent,
            "memory_percent": memory_percent,
            "battery_percent": battery_percent,
            "load_percent": load_percent,
            "load": load,
            "memory_text": memory_text,
            "battery_text": battery_text,
            "audio_percent": audio_percent,
            "audio_text": audio_text,
            "network_text": network_text,
        },
        current_cpu,
    )


def run_action(action: str) -> dict[str, Any]:
    command = ACTION_COMMANDS.get(action)
    if command is None:
        return {"ok": False, "error": f"action is not allowed: {action}"}
    try:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        log(f"action failed: {action}: {exc}")
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "action": action}


def chat_once(message: str, route: str = "local") -> dict[str, Any]:
    prompt = (message or "").strip()
    if not prompt:
        return {"ok": False, "error": "message is empty"}
    if route not in {"local", "parent"}:
        route = "local"
    try:
        result = subprocess.run(
            ["fennix-gui", "--route", route, "--ask"],
            input=prompt,
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"chat failed: {exc}")
        return {"ok": False, "error": str(exc)}

    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    if result.returncode != 0:
        return {
            "ok": False,
            "error": error or output or f"fennix exited with {result.returncode}",
            "response": output,
        }
    return {"ok": True, "response": output, "route": route}


class FauxdServer(ThreadingHTTPServer):
    previous_cpu: tuple[int, int] | None = None
    event_lock = threading.Lock()
    next_event_id = 1
    events: list[dict[str, Any]] = []

    def push_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.event_lock:
            event = {
                "id": self.next_event_id,
                "type": event_type,
                "payload": payload,
                "time": int(time.time()),
            }
            self.next_event_id += 1
            self.events.append(event)
            self.events = self.events[-80:]
            return event

    def events_after(self, since: int) -> list[dict[str, Any]]:
        with self.event_lock:
            return [event for event in self.events if int(event["id"]) > since]


class Handler(BaseHTTPRequestHandler):
    server: FauxdServer

    def log_message(self, fmt: str, *args: Any) -> None:
        log(fmt % args)

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_json({"ok": True})

    def read_json_body(self) -> dict[str, Any] | None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self.send_json({"ok": False, "error": "invalid json"}, status=400)
            return None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/health":
            self.send_json({"ok": True, "service": "fauxd", "time": int(time.time())})
            return
        if parsed.path == "/api/telemetry":
            data, self.server.previous_cpu = telemetry(self.server.previous_cpu)
            self.send_json({"ok": True, "telemetry": data})
            return
        if parsed.path == "/api/weather":
            self.send_json({"ok": True, "weather": weather_status()})
            return
        if parsed.path == "/api/threads":
            self.send_json({"ok": True, "threads": THREADS})
            return
        if parsed.path == "/api/thread-cards":
            self.send_json({"ok": True, "threads": thread_cards()})
            return
        if parsed.path == "/api/files/recent":
            limit = max(1, min(int(query.get("limit", ["5"])[0]), 20))
            root_filter = str(query.get("root", [""])[0] or "")
            self.send_json({"ok": True, "files": recent_files(limit, root_filter)})
            return
        if parsed.path == "/api/files/index":
            limit = max(1, min(int(query.get("limit", ["24"])[0]), 80))
            root_filter = str(query.get("root", [""])[0] or "")
            rebuild = str(query.get("rebuild", ["0"])[0] or "0").lower() in {"1", "true", "yes"}
            self.send_json({"ok": True, "index": file_index(limit, root_filter, rebuild)})
            return
        if parsed.path == "/api/files/pins":
            limit = max(1, min(int(query.get("limit", ["20"])[0]), 80))
            self.send_json({"ok": True, "pins": pinned_files(limit)})
            return
        if parsed.path == "/api/files/search":
            limit = max(1, min(int(query.get("limit", ["12"])[0]), 30))
            root_filter = str(query.get("root", [""])[0] or "")
            search_query = str(query.get("q", [""])[0] or "")
            include_content = str(query.get("content", ["0"])[0] or "0").lower() in {"1", "true", "yes"}
            self.send_json({"ok": True, "files": search_files(search_query, limit, root_filter, include_content)})
            return
        if parsed.path == "/api/files/preview":
            raw_path = str(query.get("path", [""])[0] or "")
            result = file_preview(raw_path)
            self.send_json(result, status=200 if result.get("ok") else 400)
            return
        if parsed.path == "/api/files/attachments":
            thread_id = str(query.get("thread", ["fauxnix"])[0] or "fauxnix")
            try:
                self.send_json({"ok": True, "attachments": thread_file_attachments(thread_id)})
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
            return
        if parsed.path == "/api/notes":
            limit = max(1, min(int(query.get("limit", ["4"])[0]), 120))
            self.send_json({"ok": True, "count": table_count("notes"), "notes": recent_notes(limit)})
            return
        if parsed.path == "/api/clipboard":
            limit = max(1, min(int(query.get("limit", ["4"])[0]), 100))
            self.send_json(
                {
                    "ok": True,
                    "count": table_count("clipboard_items"),
                    "items": recent_clipboard(limit),
                }
            )
            return
        if parsed.path == "/api/sessions":
            limit = max(1, min(int(query.get("limit", ["4"])[0]), 20))
            self.send_json({"ok": True, "count": table_count("conversations"), "sessions": recent_sessions(limit)})
            return
        if parsed.path == "/api/continuity":
            limit = max(1, min(int(query.get("limit", ["9"])[0]), 18))
            self.send_json({"ok": True, "continuity": continuity_constellation(limit)})
            return
        if parsed.path == "/api/summary":
            data, self.server.previous_cpu = telemetry(self.server.previous_cpu)
            self.send_json(
                {
                    "ok": True,
                    "user": os.environ.get("USER") or "chvk",
                    "telemetry": data,
                    "weather": weather_status(),
                    "threads": THREADS,
                    "thread_cards": {"count": len(THREADS), "recent": thread_cards()},
                    "notes": {"count": table_count("notes"), "recent": recent_notes(3)},
                    "clipboard": {"count": table_count("clipboard_items"), "recent": recent_clipboard(3)},
                    "sessions": {"count": table_count("conversations"), "recent": recent_sessions(4)},
                    "continuity": continuity_constellation(9),
                    "files": recent_files(5),
                }
            )
            return
        if parsed.path == "/api/events":
            try:
                since = int(query.get("since", ["0"])[0])
            except ValueError:
                since = 0
            self.send_json({"ok": True, "events": self.server.events_after(since)})
            return
        self.send_json({"ok": False, "error": "not found"}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/action":
            payload = self.read_json_body()
            if payload is None:
                return
            action = str(payload.get("action") or "")
            result = run_action(action)
            self.send_json(result, status=200 if result.get("ok") else 400)
            return

        if parsed.path == "/api/shell-event":
            payload = self.read_json_body()
            if payload is None:
                return
            event = str(payload.get("event") or "")
            if event not in SHELL_EVENTS:
                self.send_json({"ok": False, "error": f"event is not allowed: {event}"}, status=400)
                return
            queued = self.server.push_event("shell", {"event": event})
            self.send_json({"ok": True, "event": queued})
            return

        if parsed.path == "/api/chat":
            payload = self.read_json_body()
            if payload is None:
                return
            result = chat_once(
                str(payload.get("message") or ""),
                str(payload.get("route") or "local"),
            )
            self.send_json(result, status=200 if result.get("ok") else 400)
            return

        if parsed.path == "/api/files/attach":
            payload = self.read_json_body()
            if payload is None:
                return
            try:
                attachment = attach_file_to_thread(
                    str(payload.get("path") or ""),
                    str(payload.get("thread") or "fauxnix"),
                )
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
                return
            self.send_json({"ok": True, "attachment": attachment})
            return

        if parsed.path == "/api/files/promote":
            payload = self.read_json_body()
            if payload is None:
                return
            try:
                result = promote_file_to_memory(
                    str(payload.get("path") or ""),
                    str(payload.get("thread") or ""),
                )
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
                return
            self.send_json({"ok": True, **result})
            return

        if parsed.path == "/api/files/pin":
            payload = self.read_json_body()
            if payload is None:
                return
            try:
                pin = pin_file(str(payload.get("path") or ""))
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
                return
            self.send_json({"ok": True, "pin": pin, "pins": pinned_files(20)})
            return

        if parsed.path == "/api/files/unpin":
            payload = self.read_json_body()
            if payload is None:
                return
            try:
                result = unpin_file(str(payload.get("path") or ""))
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
                return
            self.send_json({"ok": True, "pin": result, "pins": pinned_files(20)})
            return

        if parsed.path == "/api/notes":
            payload = self.read_json_body()
            if payload is None:
                return
            try:
                note = create_note(
                    str(payload.get("title") or ""),
                    str(payload.get("content") or ""),
                    str(payload.get("source") or "manual"),
                )
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
                return
            self.send_json({"ok": True, "note": note, "notes": recent_notes(12)})
            return

        if parsed.path.startswith("/api/notes/"):
            payload = self.read_json_body()
            if payload is None:
                return
            try:
                note_id = int(parsed.path.rsplit("/", 1)[-1])
                note = update_note(
                    note_id,
                    str(payload["title"]) if "title" in payload else None,
                    str(payload["content"]) if "content" in payload else None,
                )
            except (ValueError, KeyError) as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
                return
            self.send_json({"ok": True, "note": note, "notes": recent_notes(12)})
            return

        if parsed.path == "/api/clipboard/text":
            payload = self.read_json_body()
            if payload is None:
                return
            try:
                item = create_clipboard_text(
                    str(payload.get("content") or ""),
                    str(payload.get("source") or "manual"),
                )
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
                return
            self.send_json(
                {
                    "ok": True,
                    "item": item,
                    "items": recent_clipboard(12),
                    "notes": recent_notes(12),
                }
            )
            return

        if parsed.path == "/api/clipboard/clear":
            result = clear_clipboard()
            self.send_json({"ok": True, **result, "items": []})
            return

        self.send_json({"ok": False, "error": "not found"}, status=404)


def main() -> int:
    lock_fd = acquire_lock()
    if lock_fd is None and (RUNTIME_DIR / "fauxd.lock").exists():
        return 0
    server = FauxdServer((HOST, PORT), Handler)
    log(f"fauxd listening on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
        if lock_fd is not None:
            os.close(lock_fd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
