#!/usr/bin/env python3
"""Fennix desktop chat shell.

Layer goals:
- local/parent Ollama routing
- persisted conversations
- simple explicit memories
- read-only bounded workspace inspection
- no non-stdlib Python dependencies
"""

from __future__ import annotations

import argparse
import calendar
import getpass
import json
import os
import queue
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import tkinter as tk
from tkinter import messagebox, ttk


APP_NAME = "Fennix"
CONFIG_PATH = Path("/etc/fauxnix/assistant.env")
DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
STATE_HOME = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
USER_SETTINGS_PATH = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "fauxnix" / "settings.env"
DB_PATH = DATA_HOME / "fennix" / "fennix.sqlite3"
LOG_PATH = STATE_HOME / "fennix" / "gui.log"
RUNTIME_PATH = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "fennix"
LAUNCHER_COMMAND_PATH = RUNTIME_PATH / "launcher-command"


@dataclass(frozen=True)
class Route:
    name: str
    base_url: str
    model: str


def log(message: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_assistant_env() -> dict[str, str]:
    values = parse_env_file(CONFIG_PATH)
    values.update(parse_env_file(USER_SETTINGS_PATH))
    return values


def load_routes() -> dict[str, Route]:
    env = load_assistant_env()
    local = Route(
        "local",
        env.get("FAUXNIX_LOCAL_OLLAMA_URL", "http://127.0.0.1:11434"),
        env.get("FAUXNIX_LOCAL_MODEL", "fennix-local"),
    )
    local_code = Route(
        "local-code",
        env.get("FAUXNIX_LOCAL_CODE_OLLAMA_URL", env.get("FAUXNIX_LOCAL_OLLAMA_URL", "http://127.0.0.1:11434")),
        env.get("FAUXNIX_LOCAL_CODE_MODEL", ""),
    )
    parent = Route(
        "parent",
        env.get("FAUXNIX_PARENT_OLLAMA_URL", ""),
        env.get("FAUXNIX_PARENT_MODEL", ""),
    )
    return {"local": local, "local-code": local_code, "parent": parent}


def load_cowriter_workspace() -> Path:
    env = load_assistant_env()
    return Path(env.get("FAUXNIX_COWRITER_WORKSPACE", "/home/chvk/Fauxnix/Cowriter")).expanduser()


def load_workspace_root() -> Path:
    env = load_assistant_env()
    return Path(env.get("FAUXNIX_WORKSPACE_ROOT", "/home/chvk/Fauxnix")).expanduser()


def load_knowledge_root() -> Path:
    env = load_assistant_env()
    return Path(env.get("FAUXNIX_KNOWLEDGE_ROOT", "/home/chvk/Fauxnix/Knowledge")).expanduser()


def load_threads_dir() -> Path:
    env = load_assistant_env()
    return Path(env.get("FAUXNIX_THREADS_DIR", "/home/chvk/Fauxnix/Threads")).expanduser()


def load_repos_root() -> Path:
    env = load_assistant_env()
    return Path(env.get("FAUXNIX_REPOS_ROOT", "/home/chvk/Fauxnix/Repos")).expanduser()


def load_snapshots_dir() -> Path:
    env = load_assistant_env()
    return Path(env.get("FAUXNIX_SNAPSHOTS_DIR", "/home/chvk/Fauxnix/Snapshots")).expanduser()


class FennixStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.migrate()

    def migrate(self) -> None:
        self.db.executescript(
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

            CREATE TABLE IF NOT EXISTS memories (
              id INTEGER PRIMARY KEY,
              content TEXT NOT NULL,
              category TEXT NOT NULL DEFAULT 'note',
              pinned INTEGER NOT NULL DEFAULT 0,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_state (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL,
              updated_at INTEGER NOT NULL
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
        self.ensure_column("memories", "category", "TEXT NOT NULL DEFAULT 'note'")
        self.ensure_column("memories", "pinned", "INTEGER NOT NULL DEFAULT 0")
        self.db.commit()

    def ensure_column(self, table: str, column: str, ddl: str) -> None:
        columns = {
            row["name"]
            for row in self.db.execute(f"PRAGMA table_info({table})")
        }
        if column not in columns:
            self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def now(self) -> int:
        return int(time.time())

    def ensure_conversation(self) -> int:
        row = self.db.execute(
            "SELECT id FROM conversations ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        if row:
            return int(row["id"])
        return self.create_conversation("First conversation")

    def conversation_exists(self, conversation_id: int) -> bool:
        row = self.db.execute(
            "SELECT id FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        return row is not None

    def create_conversation(self, title: str = "New conversation") -> int:
        now = self.now()
        cur = self.db.execute(
            "INSERT INTO conversations (title, created_at, updated_at) VALUES (?, ?, ?)",
            (title, now, now),
        )
        self.db.commit()
        return int(cur.lastrowid)

    def rename_conversation(self, conversation_id: int, title: str) -> None:
        self.db.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title[:120] or "Conversation", self.now(), conversation_id),
        )
        self.db.commit()

    def conversations(self, query: str = "") -> list[sqlite3.Row]:
        query = query.strip()
        if not query:
            return list(
                self.db.execute(
                    "SELECT id, title, updated_at FROM conversations ORDER BY updated_at DESC, id DESC"
                )
            )

        like = f"%{query}%"
        return list(
            self.db.execute(
                """
                SELECT c.id, c.title, c.updated_at
                FROM conversations c
                WHERE c.title LIKE ?
                   OR EXISTS (
                        SELECT 1
                        FROM messages m
                        WHERE m.conversation_id = c.id
                          AND m.content LIKE ?
                   )
                ORDER BY c.updated_at DESC, c.id DESC
                """,
                (like, like),
            )
        )

    def messages(self, conversation_id: int, limit: int = 80) -> list[sqlite3.Row]:
        rows = list(
            self.db.execute(
                """
                SELECT role, route, content, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (conversation_id, limit),
            )
        )
        rows.reverse()
        return rows

    def add_message(self, conversation_id: int, role: str, route: str, content: str) -> None:
        now = self.now()
        self.db.execute(
            """
            INSERT INTO messages (conversation_id, role, route, content, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (conversation_id, role, route, content, now),
        )
        self.db.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, conversation_id),
        )
        self.db.commit()

        if role == "user":
            row = self.db.execute(
                "SELECT COUNT(*) AS count FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            if row and int(row["count"]) <= 1:
                self.rename_conversation(conversation_id, content.replace("\n", " ")[:60])

    def memories(self, query: str = "") -> list[sqlite3.Row]:
        query = query.strip()
        if not query:
            return list(
                self.db.execute(
                    """
                    SELECT id, content, category, pinned
                    FROM memories
                    ORDER BY pinned DESC, updated_at DESC, id DESC
                    """
                )
            )

        like = f"%{query}%"
        return list(
            self.db.execute(
                """
                SELECT id, content, category, pinned
                FROM memories
                WHERE content LIKE ? OR category LIKE ?
                ORDER BY pinned DESC, updated_at DESC, id DESC
                """,
                (like, like),
            )
        )

    def memory_text(self, limit: int = 12) -> str:
        rows = self.memories()[:limit]
        return "\n".join(
            f"- [{'pinned ' if row['pinned'] else ''}{row['category']}] {row['content']}"
            for row in rows
        )

    def prompt_memory_text(self, user_text: str, limit: int = 8) -> str:
        terms = prompt_terms(user_text)
        durable: list[str] = []
        relevant: list[str] = []

        for row in self.memories():
            category = str(row["category"] or "note").lower()
            content = str(row["content"] or "").strip()
            if not content:
                continue

            pinned = bool(row["pinned"])
            item = f"- [{category}{', pinned' if pinned else ''}] {clamp_text(content, 360)}"

            if category in {"fact", "preference", "system"} or (pinned and category not in {"summary", "task"}):
                durable.append(item)
            elif terms and category not in {"summary", "task"} and any(term in content.lower() for term in terms):
                relevant.append(item)
            elif terms and category in {"summary", "task"} and any(term in content.lower() for term in terms):
                relevant.append(item)

            if len(durable) + len(relevant) >= limit:
                break

        sections: list[str] = []
        if durable:
            sections.append("Durable memory:\n" + "\n".join(durable[:limit]))
        remaining = max(limit - len(durable), 0)
        if relevant and remaining:
            sections.append("Possibly relevant memory:\n" + "\n".join(relevant[:remaining]))
        return "\n\n".join(sections)

    def add_memory(self, content: str, category: str = "note", pinned: bool = False) -> None:
        content = content.strip()
        if not content:
            return
        category = (category or "note").strip().lower()[:32]
        now = self.now()
        self.db.execute(
            """
            INSERT INTO memories (content, category, pinned, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (content, category, 1 if pinned else 0, now, now),
        )
        self.db.commit()

    def toggle_memory_pin(self, memory_id: int) -> None:
        self.db.execute(
            """
            UPDATE memories
            SET pinned = CASE pinned WHEN 0 THEN 1 ELSE 0 END,
                updated_at = ?
            WHERE id = ?
            """,
            (self.now(), memory_id),
        )
        self.db.commit()

    def delete_memory(self, memory_id: int) -> None:
        self.db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self.db.commit()

    def notes(self, limit: int = 40, query: str = "") -> list[sqlite3.Row]:
        query = query.strip()
        if not query:
            return list(
                self.db.execute(
                    """
                    SELECT id, title, content, source, created_at, updated_at
                    FROM notes
                    ORDER BY updated_at DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            )

        like = f"%{query}%"
        return list(
            self.db.execute(
                """
                SELECT id, title, content, source, created_at, updated_at
                FROM notes
                WHERE title LIKE ? OR content LIKE ? OR source LIKE ?
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (like, like, like, limit),
            )
        )

    def get_note(self, note_id: int) -> sqlite3.Row | None:
        return self.db.execute(
            """
            SELECT id, title, content, source, created_at, updated_at
            FROM notes
            WHERE id = ?
            """,
            (note_id,),
        ).fetchone()

    def add_note(self, title: str, content: str, source: str = "manual") -> int:
        content = content.strip()
        title = title.strip() or first_line_title(content) or "Untitled note"
        now = self.now()
        cur = self.db.execute(
            """
            INSERT INTO notes (title, content, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (title[:120], content, (source or "manual")[:32], now, now),
        )
        self.db.commit()
        return int(cur.lastrowid)

    def clipboard_items(self, limit: int = 20) -> list[sqlite3.Row]:
        return list(
            self.db.execute(
                """
                SELECT id, kind, content, source, note_id, created_at
                FROM clipboard_items
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(limit, 100)),),
            )
        )

    def add_clipboard_text(self, content: str, source: str = "manual") -> int:
        content = content.strip()
        if not content:
            return 0
        title = f"Clipboard {time.strftime('%Y-%m-%d %H:%M')}"
        note_id = self.add_note(title, content, "clipboard")
        now = self.now()
        self.db.execute(
            """
            INSERT INTO clipboard_items (kind, content, source, note_id, created_at)
            VALUES ('text', ?, ?, ?, ?)
            """,
            (content, (source or "manual")[:32], note_id, now),
        )
        self.db.commit()
        return note_id

    def clear_clipboard(self) -> int:
        row = self.db.execute("SELECT COUNT(*) AS count FROM clipboard_items").fetchone()
        count = int(row["count"]) if row else 0
        self.db.execute("DELETE FROM clipboard_items")
        self.db.commit()
        return count

    def update_note(self, note_id: int, title: str, content: str) -> None:
        self.db.execute(
            """
            UPDATE notes
            SET title = ?, content = ?, updated_at = ?
            WHERE id = ?
            """,
            ((title.strip() or "Untitled note")[:120], content.strip(), self.now(), note_id),
        )
        self.db.commit()

    def delete_note(self, note_id: int) -> None:
        self.db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        self.db.commit()

    def note_count(self) -> int:
        row = self.db.execute("SELECT COUNT(*) AS count FROM notes").fetchone()
        return int(row["count"]) if row else 0

    def get_state(self, key: str, default: str = "") -> str:
        row = self.db.execute("SELECT value FROM task_state WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def set_state(self, key: str, value: str) -> None:
        self.db.execute(
            """
            INSERT INTO task_state (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, self.now()),
        )
        self.db.commit()


def ollama_generate_once(route: Route, prompt: str) -> Iterable[str]:
    if not route.base_url or not route.model:
        raise RuntimeError(f"{route.name} route is not configured")

    payload = json.dumps({"model": route.model, "prompt": prompt, "stream": True}).encode("utf-8")
    request = urllib.request.Request(
        route.base_url.rstrip("/") + "/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=240) as response:
        for raw_line in response:
            if not raw_line.strip():
                continue
            data = json.loads(raw_line.decode("utf-8"))
            if "error" in data:
                raise RuntimeError(data["error"])
            chunk = data.get("response", "")
            if chunk:
                yield chunk
            if data.get("done"):
                break


def fallback_route_for(route: Route) -> Route | None:
    if route.name != "parent":
        return None
    fallback = load_routes().get("local-code")
    if fallback and fallback.base_url and fallback.model:
        return fallback
    return None


def ollama_generate(route: Route, prompt: str) -> Iterable[str]:
    try:
        yield from ollama_generate_once(route, prompt)
    except (OSError, urllib.error.URLError, RuntimeError, json.JSONDecodeError) as exc:
        fallback = fallback_route_for(route)
        if fallback is None:
            raise
        log(f"parent route failed; falling back to {fallback.model}: {exc!r}")
        yield (
            f"Nexus is unavailable or could not serve `{route.model}`. "
            f"Using local fallback `{fallback.model}` on this ThinkPad.\n\n"
        )
        yield from ollama_generate_once(fallback, prompt)


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = "".join(char if char.isalnum() else "-" for char in value)
    value = "-".join(part for part in value.split("-") if part)
    return value[:64] or "untitled"


def first_line_title(content: str, limit: int = 60) -> str:
    for line in content.splitlines():
        title = line.strip()
        if title:
            return title[:limit]
    return ""


def cowriter_overview(root: Path, limit: int = 20) -> str:
    if not root.exists():
        return f"Cowriter workspace: {root} (not initialized yet)"

    files = sorted(
        root.glob("*/*.md"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    lines = [f"Cowriter workspace: {root}"]
    for path in files[:limit]:
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        lines.append(f"- {relative}")
    if len(files) > limit:
        lines.append(f"- ... {len(files) - limit} more")
    return "\n".join(lines)


def cowriter_doc(root: Path, kind: str, title: str, body: str) -> Path:
    folders = {
        "draft": "drafts",
        "note": "notes",
        "session": "sessions",
        "outline": "outlines",
        "inbox": "inbox",
    }
    folder = folders[kind]
    target_dir = root / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{time.strftime('%Y%m%d-%H%M%S')}-{slugify(title)}.md"
    path = (target_dir / filename).resolve()
    root_resolved = root.resolve()
    try:
        path.relative_to(root_resolved)
    except ValueError as exc:
        raise RuntimeError("Cowriter target escaped the workspace") from exc

    content = (
        "---\n"
        f"title: {title}\n"
        f"kind: {kind}\n"
        f"created: {time.strftime('%Y-%m-%d %H:%M:%S %z')}\n"
        "source: fennix-gui\n"
        "status: active\n"
        "tags: []\n"
        "---\n\n"
        f"# {title}\n\n"
        f"{body.strip()}\n"
    )
    path.write_text(content, encoding="utf-8")
    return path


def bounded_path(root: Path, candidate: Path) -> Path:
    root_resolved = root.resolve()
    path = candidate.resolve()
    try:
        path.relative_to(root_resolved)
    except ValueError as exc:
        raise RuntimeError("path escapes the workspace root") from exc
    return path


def workspace_projects(root: Path) -> list[Path]:
    root.mkdir(parents=True, exist_ok=True)
    projects = [
        path for path in root.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    ]
    return sorted(projects, key=lambda path: path.name.lower())


def workspace_project(root: Path, name: str) -> Path:
    name = name.strip()
    if not name:
        projects = workspace_projects(root)
        return projects[0] if projects else root
    return bounded_path(root, root / name)


def skip_workspace_path(path: Path) -> bool:
    ignored = {".git", "__pycache__", ".direnv", ".venv", "node_modules", "result"}
    return any(part in ignored or part.startswith(".cache") for part in path.parts)


def workspace_tree(project: Path, limit: int = 220) -> str:
    project = project.resolve()
    lines = [f"{project.name}/"]
    count = 0
    for path in sorted(project.rglob("*"), key=lambda item: str(item).lower()):
        if skip_workspace_path(path.relative_to(project)):
            continue
        rel = path.relative_to(project)
        depth = len(rel.parts)
        if depth > 4:
            continue
        marker = "/" if path.is_dir() else ""
        lines.append("  " * depth + rel.name + marker)
        count += 1
        if count >= limit:
            lines.append("  ...")
            break
    return "\n".join(lines)


def workspace_read_file(project: Path, relative: str, max_bytes: int = 65536) -> str:
    path = bounded_path(project, project / relative)
    if not path.is_file():
        raise RuntimeError("selected path is not a file")
    data = path.read_bytes()[:max_bytes]
    return data.decode("utf-8", errors="replace")


def workspace_search(project: Path, query: str, limit: int = 80) -> str:
    query = query.strip().lower()
    if not query:
        return "Enter search text first."

    matches: list[str] = []
    for path in sorted(project.rglob("*"), key=lambda item: str(item).lower()):
        if len(matches) >= limit:
            break
        rel = path.relative_to(project)
        if skip_workspace_path(rel) or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if query in line.lower():
                matches.append(f"{rel}:{number}: {line.strip()}")
                if len(matches) >= limit:
                    break
    return "\n".join(matches) if matches else "No matches."


def workspace_git_status(project: Path) -> str:
    if not (project / ".git").exists():
        return "No .git directory in this project."

    try:
        result = subprocess.run(
            ["git", "-C", str(project), "status", "--short", "--branch"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"Git status failed: {exc}"

    output = (result.stdout + result.stderr).strip()
    return output or "Git status is clean."


def workspace_index(project: Path) -> str:
    project = project.resolve()
    file_count = 0
    dir_count = 0
    recent: list[tuple[float, Path, int]] = []

    for path in project.rglob("*"):
        rel = path.relative_to(project)
        if skip_workspace_path(rel):
            continue
        try:
            if path.is_dir():
                dir_count += 1
                continue
            if not path.is_file():
                continue
            stat = path.stat()
        except OSError:
            continue
        file_count += 1
        recent.append((stat.st_mtime, rel, stat.st_size))

    recent.sort(reverse=True)
    lines = [
        f"Project: {project.name}",
        f"Path: {project}",
        f"Files: {file_count}",
        f"Directories: {dir_count}",
        "",
        "Git:",
        workspace_git_status(project),
        "",
        "Recent files:",
    ]
    if recent:
        for mtime, rel, size in recent[:12]:
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
            lines.append(f"- {rel} ({size} bytes, {stamp})")
    else:
        lines.append("- none")

    lines.extend(["", "Tree:", workspace_tree(project, limit=140)])
    return "\n".join(lines)


def workspace_overview(store: FennixStore) -> str:
    root = load_workspace_root()
    projects = workspace_projects(root)
    active = store.get_state("active_project")
    goal = store.get_state("current_goal")
    indexed_at = store.get_state("workspace_indexed_at")
    lines = [f"Workspace root: {root}"]
    if projects:
        lines.append("Projects: " + ", ".join(path.name for path in projects[:12]))
    if active:
        lines.append(f"Active project: {active}")
    elif projects:
        lines.append(f"Default project candidate: {projects[0].name}")
    if goal:
        lines.append(f"Current goal: {goal}")
    if indexed_at:
        lines.append(f"Last index: {indexed_at}")
    return "\n".join(lines)


def clamp_text(value: str, limit: int = 900) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: max(limit - 24, 0)].rstrip() + "\n[truncated]"


def command_output(command: list[str], timeout: int = 3, limit: int = 900) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return 127, f"{command[0]} is not installed"
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"{command[0]} failed: {exc}"

    output = (result.stdout + result.stderr).strip()
    return result.returncode, clamp_text(output, limit) if output else ""


def parse_thread_metadata(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def thread_catalog_summary(limit: int = 10) -> str:
    root = load_threads_dir()
    if not root.exists():
        return f"Threads: {root} is not initialized"

    entries: list[str] = []
    for child in sorted(root.iterdir(), key=lambda path: path.name.lower()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        metadata = parse_thread_metadata(child / "thread.toml")
        label = metadata.get("label", child.name)
        kind = metadata.get("kind", metadata.get("type", "thread"))
        entries.append(f"- {child.name}: {label} ({kind})")
        if len(entries) >= limit:
            break

    if not entries:
        return f"Threads: {root} exists but has no thread directories"

    return "Threads:\n" + "\n".join(entries)


def git_repo_summary(name: str, path: Path) -> str:
    if not path.exists():
        return f"- {name}: {path} missing"
    if not (path / ".git").exists():
        return f"- {name}: {path} is not a git repo"

    status_code, status = command_output(["git", "-C", str(path), "status", "--short"], timeout=3, limit=600)
    _log_code, last_commit = command_output(["git", "-C", str(path), "log", "-1", "--oneline"], timeout=3, limit=180)

    if status_code != 0:
        state = status or "status failed"
    elif status:
        state = status.replace("\n", "; ")
    else:
        state = "clean"

    if last_commit:
        return f"- {name}: {state}; last {last_commit}"
    return f"- {name}: {state}; no commits yet"


def git_spine_summary() -> str:
    repos_root = load_repos_root()
    lines = ["Git spine:"]
    lines.append(git_repo_summary("admin", repos_root / "admin"))
    lines.append(git_repo_summary("home", repos_root / "home"))
    lines.append(git_repo_summary("threads", load_threads_dir()))
    return "\n".join(lines)


def route_summary() -> str:
    env = load_assistant_env()
    routes = load_routes()
    local = routes["local"]
    local_code = routes["local-code"]
    parent = routes["parent"]
    parent_label = f"{parent.base_url} model={parent.model}" if parent.base_url else "not configured"
    fallback_label = (
        f"{local_code.base_url} model={local_code.model}"
        if local_code.base_url and local_code.model
        else "not configured"
    )
    alternate = env.get("FAUXNIX_PARENT_ALT_MODEL", "").strip()
    return "\n".join(
        [
            "Model routes:",
            f"- local: {local.base_url} model={local.model}",
            f"- parent/Nexus: {parent_label}",
            f"- parent alternate: {alternate or 'unset'}",
            f"- parent fallback/local code: {fallback_label}",
        ]
    )


def task_state_summary(store: FennixStore) -> str:
    active_project = store.get_state("active_project")
    current_goal = store.get_state("current_goal")
    indexed_at = store.get_state("workspace_indexed_at")
    lines = ["Task state:"]
    lines.append(f"- active project: {active_project or 'unset'}")
    lines.append(f"- current goal: {current_goal or 'unset'}")
    if indexed_at:
        lines.append(f"- last workspace index: {indexed_at}")
    return "\n".join(lines)


def machine_summary() -> str:
    load = "n/a"
    try:
        one, five, fifteen = os.getloadavg()
        load = f"{one:.2f}, {five:.2f}, {fifteen:.2f}"
    except OSError:
        pass

    _ram_percent, ram = memory_status()
    net = network_status()
    _battery_percent, battery = battery_status()
    _power_code, power = command_output(["fauxnix-power", "status"], timeout=2, limit=500)
    lines = [
        "Machine:",
        f"- user: {getpass.getuser()}",
        f"- load: {load}",
        f"- {ram}",
        f"- {battery}",
        f"- network: {net}",
    ]
    if power:
        lines.append("- screen dimming: " + "; ".join(power.splitlines()))
    return "\n".join(lines)


def assistant_runtime_context(store: FennixStore, user_text: str = "") -> str:
    sections = [
        task_state_summary(store),
        workspace_overview(store),
        thread_catalog_summary(),
        git_spine_summary(),
        route_summary(),
    ]
    terms = prompt_terms(user_text)
    if not user_text or terms & {"network", "wifi", "wireless", "battery", "load", "ram", "status", "system"}:
        sections.append(machine_summary())
    return "\n\n".join(section for section in sections if section)


def assistant_status_response(store: FennixStore) -> str:
    context = assistant_runtime_context(store, "status system git threads network")
    return (
        "Here is the live Fauxnix status I can see right now.\n\n"
        + clamp_text(context, 2600)
        + "\n\n"
        "I will treat this live status as stronger than older chat memory."
    )


def prompt_terms(value: str) -> set[str]:
    return {
        part
        for part in re.findall(r"[a-z0-9][a-z0-9_-]{3,}", value.lower())
        if part
        not in {
            "this",
            "that",
            "with",
            "from",
            "have",
            "just",
            "please",
            "would",
            "could",
            "should",
            "want",
            "need",
            "about",
        }
    }


def wants_workspace_context(user_text: str) -> bool:
    terms = prompt_terms(user_text)
    context_terms = {
        "admin",
        "assistant",
        "browser",
        "clipboard",
        "code",
        "config",
        "cowriter",
        "desktop",
        "dashboard",
        "file",
        "fennix",
        "fauxnix",
        "firefox",
        "git",
        "memory",
        "model",
        "nix",
        "nixos",
        "notes",
        "ollama",
        "project",
        "reboot",
        "restart",
        "root",
        "service",
        "snapshot",
        "status",
        "sway",
        "thread",
        "threads",
        "workspace",
    }
    return bool(terms & context_terms)


def wants_recent_chat_context(user_text: str, rows: list[sqlite3.Row]) -> bool:
    lowered = user_text.lower()
    phrase_markers = {"where we left off"}
    word_markers = {"above", "continue", "earlier", "it", "last", "previous", "resume", "same", "that", "this"}
    if any(marker in lowered for marker in phrase_markers):
        return True
    words = set(re.findall(r"[a-z0-9]+", lowered))
    if words & word_markers:
        return True

    terms = prompt_terms(user_text)
    if not terms:
        return False

    recent_text = " ".join(str(row["content"] or "") for row in rows[-6:])
    return bool(terms & prompt_terms(recent_text))


def build_prompt(store: FennixStore, conversation_id: int, user_text: str) -> str:
    memory = store.prompt_memory_text(user_text)
    recent = store.messages(conversation_id, limit=10)
    if recent and recent[-1]["role"] == "user" and recent[-1]["content"].strip() == user_text.strip():
        recent = recent[:-1]
    transcript_lines: list[str] = []

    for row in recent[-8:]:
        role = row["role"]
        if role == "system":
            continue
        content = row["content"].strip()
        if content:
            transcript_lines.append(f"{role}: {clamp_text(content, 700)}")

    blocks = [
        "You are Fennix, the local assistant and operator for the Fauxnix project.",
        "You are running on the ThinkPad edge node. Nexus is the heavier parent route when configured.",
        "The section CURRENT USER REQUEST is the highest priority. If older memory or chat conflicts with it, follow the current request.",
        "The section LIVE FAUXNIX CONTEXT is current machine/workspace evidence. Trust it over BACKGROUND MEMORY and RECENT CHAT.",
        "Do not continue an older task unless the current request explicitly asks to continue, resume, or revisit it.",
        "If the user asks for a local machine action such as reboot, shutdown, restart, service changes, file edits, root access, snapshots, or destructive commands, explain the needed confirmation or limitation. Do not invent code or continue unrelated coding tasks.",
        "If a request should use a deterministic Fauxnix command or thread, name the command/thread plainly and ask for confirmation when the action is disruptive.",
        "For Codex-like workspace work, use the Fauxdex loop: observe, plan, inspect, propose, verify, summarize. Fauxdex starts read-only and bounded to the Fauxnix workspace.",
        "Answer conversationally, practically, and briefly.",
        "CURRENT USER REQUEST:\n<<<\n" + user_text.strip() + "\n>>>",
    ]
    runtime_context = assistant_runtime_context(store, user_text)
    if runtime_context:
        blocks.append("LIVE FAUXNIX CONTEXT:\n" + clamp_text(runtime_context, 2600))
    if memory:
        blocks.append("BACKGROUND MEMORY (may be stale; use only if relevant):\n" + memory)
    if wants_workspace_context(user_text):
        cowriter = cowriter_overview(load_cowriter_workspace(), limit=8)
        workspace = workspace_overview(store)
        if cowriter:
            blocks.append("WORKSPACE BACKGROUND:\n" + clamp_text(cowriter, 1200))
        if workspace:
            blocks.append("PROJECT BACKGROUND:\n" + clamp_text(workspace, 1200))
    if transcript_lines and wants_recent_chat_context(user_text, recent):
        blocks.append("RECENT CHAT BACKGROUND (may be stale; never outranks current request):\n" + "\n".join(transcript_lines))
    blocks.append("Respond to CURRENT USER REQUEST now. Fennix:")
    return "\n\n".join(blocks)


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def memory_status() -> tuple[float | None, str]:
    meminfo = read_text_file(Path("/proc/meminfo"))
    if not meminfo:
        return None, "RAM n/a"

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
    percent = (used / total) * 100
    return percent, f"RAM {used // 1024}/{total // 1024} MB"


def battery_status() -> tuple[float | None, str]:
    for battery in sorted(Path("/sys/class/power_supply").glob("BAT*")):
        capacity = read_text_file(battery / "capacity")
        status = read_text_file(battery / "status")
        if capacity:
            try:
                percent = float(capacity)
            except ValueError:
                percent = None
            label = f"BAT {capacity}%"
            if status:
                label += f" {status.lower()}"
            return percent, label
    return None, "BAT n/a"


def default_network_device() -> str:
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
    return ""


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
                ssid = parts[1] or "wifi"
                signal = parts[-1]
                return f"W {ssid} {signal}%"
    except (OSError, subprocess.SubprocessError):
        pass

    device = default_network_device()
    return f"net {device}" if device else "net n/a"


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
            label = f"VOL {percent:.0f}%"
            if muted:
                label += " muted"
            return percent, label
    except (OSError, subprocess.SubprocessError):
        pass
    return None, "VOL n/a"


def cpu_times() -> tuple[int, int] | None:
    stat = read_text_file(Path("/proc/stat"))
    if not stat:
        return None
    first = stat.splitlines()[0].split()
    if not first or first[0] != "cpu":
        return None
    try:
        values = [int(value) for value in first[1:]]
    except ValueError:
        return None
    if len(values) < 5:
        return None
    idle = values[3] + values[4]
    total = sum(values)
    return idle, total


def cpu_percent(previous: tuple[int, int] | None, current: tuple[int, int] | None, load_percent: float) -> float | None:
    if previous and current:
        idle_delta = current[0] - previous[0]
        total_delta = current[1] - previous[1]
        if total_delta > 0:
            return max(0.0, min((1 - (idle_delta / total_delta)) * 100, 100.0))
    return max(0.0, min(load_percent, 100.0)) if current else None


def telemetry_snapshot(previous_cpu: tuple[int, int] | None = None) -> dict[str, object]:
    now = time.strftime("%a %H:%M")
    cpu_count = max(os.cpu_count() or 1, 1)
    try:
        load = os.getloadavg()[0]
        load_percent = max(0.0, min((load / cpu_count) * 100, 100.0))
    except (AttributeError, OSError):
        load = 0.0
        load_percent = 0.0

    current_cpu = cpu_times()
    cpu_value = cpu_percent(previous_cpu, current_cpu, load_percent)
    memory_value, memory_text = memory_status()
    battery_value, battery_text = battery_status()
    audio_value, audio_text = audio_status()
    network_text = network_status()

    return {
        "time": now,
        "load": load,
        "load_percent": load_percent,
        "cpu_percent": cpu_value,
        "memory_percent": memory_value,
        "memory_text": memory_text,
        "battery_percent": battery_value,
        "battery_text": battery_text,
        "audio_percent": audio_value,
        "audio_text": audio_text,
        "network_text": network_text,
        "cpu_sample": current_cpu,
    }


def system_telemetry() -> str:
    snapshot = telemetry_snapshot()
    cpu = snapshot["cpu_percent"]
    cpu_text = f"CPU {cpu:.0f}%" if isinstance(cpu, float) else "CPU n/a"

    return (
        f"{snapshot['time']}   {cpu_text}   load {snapshot['load']:.2f}   "
        f"{snapshot['memory_text']}   {snapshot['battery_text']}   {snapshot['network_text']}"
    )


def launch_detached(command: list[str]) -> None:
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def request_launcher_toggle() -> None:
    lock_fd = acquire_runtime_lock("fennix-launcher")
    launcher_running = lock_fd is False
    if isinstance(lock_fd, int) and lock_fd is not False:
        try:
            os.close(lock_fd)
        except OSError:
            pass
    command = "toggle" if launcher_running else "show"
    try:
        RUNTIME_PATH.mkdir(parents=True, exist_ok=True)
        LAUNCHER_COMMAND_PATH.write_text(f"{command} {time.time()}\n", encoding="utf-8")
    except OSError as exc:
        log(f"launcher toggle request failed: {exc!r}")
    if not launcher_running:
        try:
            launch_detached(["fennix-gui", "--launcher"])
        except OSError as exc:
            log(f"launcher fallback start failed: {exc!r}")


def sway_json(kind: str) -> object | None:
    if not os.environ.get("SWAYSOCK"):
        return None
    try:
        result = subprocess.run(
            ["swaymsg", "-t", kind],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def sway_command(*parts: str) -> bool:
    if not os.environ.get("SWAYSOCK"):
        return False
    try:
        result = subprocess.run(
            ["swaymsg", *parts],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def tree_children(node: dict[str, object]) -> Iterable[dict[str, object]]:
    for key in ("nodes", "floating_nodes"):
        children = node.get(key, [])
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    yield child


def walk_tree(node: dict[str, object]) -> Iterable[dict[str, object]]:
    yield node
    for child in tree_children(node):
        yield from walk_tree(child)


def focused_workspace_name(workspaces: object) -> str:
    if not isinstance(workspaces, list):
        return ""
    for workspace in workspaces:
        if isinstance(workspace, dict) and workspace.get("focused"):
            return str(workspace.get("name") or "")
    return ""


def workspace_node(tree: object, name: str) -> dict[str, object] | None:
    if not isinstance(tree, dict) or not name:
        return None
    for node in walk_tree(tree):
        if node.get("type") == "workspace" and node.get("name") == name:
            return node
    return None


def workspace_for_window(tree: object, title: str) -> str:
    if not isinstance(tree, dict):
        return ""

    def search(node: dict[str, object], current_workspace: str = "") -> str:
        node_type = str(node.get("type") or "")
        if node_type == "workspace":
            current_workspace = str(node.get("name") or current_workspace)
        if str(node.get("name") or "") == title:
            return current_workspace
        for child in tree_children(node):
            found = search(child, current_workspace)
            if found:
                return found
        return ""

    return search(tree)


def workspace_app_count(workspace: dict[str, object] | None) -> int:
    if workspace is None:
        return 0
    ignored_titles = {"Fennix Desktop", "Fennix Launcher", "Fennix Panel"}
    count = 0
    for node in walk_tree(workspace):
        title = str(node.get("name") or "")
        if title in ignored_titles:
            continue
        if node.get("type") != "con":
            continue
        if list(tree_children(node)):
            continue
        if title and (node.get("pid") or node.get("app_id") or node.get("window")):
            count += 1
    return count


def acquire_runtime_lock(name: str) -> int | bool | None:
    try:
        import fcntl  # type: ignore[import-not-found]
    except ImportError:
        return None

    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
    try:
        runtime.mkdir(parents=True, exist_ok=True)
        fd = os.open(runtime / f"{name}.lock", os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BlockingIOError:
        try:
            os.close(fd)
        except (NameError, OSError):
            pass
        return False
    except OSError:
        return None


@dataclass(frozen=True)
class LocalAction:
    response: str
    status: str = "Ready"
    commands: tuple[tuple[str, ...], ...] = ()
    reboot: bool = False


def normalize_command_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def has_any_phrase(normalized: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in normalized for phrase in phrases)


NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "forty-five": 45,
    "sixty": 60,
}


def parse_number_token(token: str) -> int | None:
    token = token.strip().lower()
    if token.isdigit():
        return int(token)
    return NUMBER_WORDS.get(token)


def duration_seconds_from_text(normalized: str) -> int | None:
    pattern = (
        r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|"
        r"twenty|thirty|forty|forty-five|sixty)\s*"
        r"(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h)\b"
    )
    match = re.search(pattern, normalized)
    if not match:
        return None

    value = parse_number_token(match.group(1))
    if value is None:
        return None
    unit = match.group(2)
    if unit.startswith(("hour", "hr", "h")):
        return value * 3600
    if unit.startswith(("minute", "min", "m")):
        return value * 60
    return value


def format_duration(seconds: int) -> str:
    if seconds >= 3600 and seconds % 3600 == 0:
        value = seconds // 3600
        return f"{value} hour" if value == 1 else f"{value} hours"
    if seconds >= 60 and seconds % 60 == 0:
        value = seconds // 60
        return f"{value} minute" if value == 1 else f"{value} minutes"
    return f"{seconds} seconds"


def screen_power_status_response() -> str:
    code, output = command_output(["fauxnix-power", "status"], timeout=3, limit=1200)
    if code != 0:
        return "I could not read the screen dimming settings yet: " + (output or "fauxnix-power failed")
    if not output:
        return "Screen dimming is installed, but it did not return a status."
    return "Screen dimming settings:\n" + "\n".join(f"- {line}" for line in output.splitlines())


def display_status_response() -> str:
    code, output = command_output(["fauxnix-display", "status"], timeout=4, limit=1800)
    if code != 0:
        return "I could not read the display mode yet: " + (output or "fauxnix-display failed")
    if not output:
        return "Display mode support is installed, but it did not return a status."
    return "Display mode status:\n" + "\n".join(f"- {line}" for line in output.splitlines())


def display_modes_response() -> str:
    code, output = command_output(["fauxnix-display", "modes"], timeout=4, limit=1800)
    if code != 0:
        return "I could not read the supported display modes yet: " + (output or "fauxnix-display failed")
    if not output:
        return "No supported display modes were reported."
    return "Supported display modes:\n" + "\n".join(f"- {line}" for line in output.splitlines())


def display_mode_from_text(user_text: str) -> str:
    match = re.search(
        r"\b(\d{3,5})\s*(?:x|by)\s*(\d{3,5})(?:\s*(?:@|at)\s*([0-9]+(?:\.[0-9]+)?)\s*(?:hz)?)?\b",
        user_text,
        flags=re.IGNORECASE,
    )
    if not match:
        return ""
    mode = f"{match.group(1)}x{match.group(2)}"
    if match.group(3):
        mode += f"@{match.group(3)}Hz"
    return mode


def fauxdex_status_response() -> str:
    code, output = command_output(["fauxdex", "status"], timeout=8, limit=3200)
    if code != 0:
        return "I could not read Fauxdex status yet: " + (output or "fauxdex failed")
    if not output:
        return "Fauxdex is installed, but it did not return status."
    return output


FAUX_PASS_APP_ALIASES: dict[str, tuple[str, ...]] = {
    "web": ("web", "firefox", "browser"),
    "terminal": ("terminal", "shell"),
    "fennix": ("fennix", "assistant", "chat"),
    "fauxdex": ("fauxdex", "code thread", "coding thread", "workspace agent"),
    "cowriter": ("cowriter", "co-writer", "writer"),
    "notepad": ("notepad",),
    "calc": ("calc", "calculator"),
    "powershell": ("powershell", "power shell"),
    "vscode": ("vscode", "vs code", "visual studio code", "code editor"),
}


def faux_pass_status_response() -> str:
    code, output = command_output(["faux-pass", "status"], timeout=4, limit=1800)
    if code != 0:
        return "I could not read Faux-pass status yet: " + (output or "faux-pass failed")
    if not output:
        return "Faux-pass is installed, but it did not return status."
    return output


def faux_pass_apps_payload() -> tuple[list[dict[str, object]], str]:
    code, output = command_output(["faux-pass", "--json", "apps"], timeout=4, limit=6000)
    if code != 0:
        return [], output or "faux-pass failed"
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return [], "faux-pass returned unreadable app data"
    rows = payload.get("apps", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return [], "faux-pass returned an unexpected app list"
    return [row for row in rows if isinstance(row, dict)], ""


def faux_pass_apps_response() -> str:
    rows, error = faux_pass_apps_payload()
    if error:
        return "I could not read Faux-pass apps yet: " + error
    if not rows:
        return "Faux-pass has no registered apps yet."
    lines = ["Faux-pass registered apps:"]
    for app in rows:
        provider = str(app.get("provider") or "unknown")
        mode = "remote" if app.get("remote") else "local"
        state = "launchable" if app.get("launchable") else "planned"
        lines.append(f"- {app.get('name') or app.get('id')} ({app.get('id')}, {provider}, {mode}, {state})")
    return "\n".join(lines)


def faux_pass_alias_match(normalized: str, alias: str) -> bool:
    return re.search(rf"\b{re.escape(alias)}\b", normalized) is not None


def faux_pass_app_from_text(normalized: str) -> str:
    if not re.search(r"\b(open|launch|run|start)\b", normalized) and not has_any_phrase(
        normalized, ("faux-pass", "faux pass")
    ):
        return ""
    for app_id, aliases in FAUX_PASS_APP_ALIASES.items():
        if any(faux_pass_alias_match(normalized, alias) for alias in aliases):
            return app_id
    return ""


def faux_pass_launch_action(app_id: str) -> LocalAction:
    rows, error = faux_pass_apps_payload()
    if error:
        return LocalAction("I could not check Faux-pass before launching: " + error, status="Faux-pass unavailable")
    for app in rows:
        if str(app.get("id") or "").lower() != app_id:
            continue
        name = str(app.get("name") or app_id)
        provider = str(app.get("provider") or "unknown")
        if not app.get("launchable"):
            return LocalAction(
                f"{name} is registered in Faux-pass under {provider}, but that provider is still planned and has no launch action yet.",
                status="Faux-pass app planned",
            )
        return LocalAction(
            f"Launching {name} through Faux-pass.",
            status=f"Opening {name}",
            commands=(("faux-pass", "run", app_id),),
        )
    return LocalAction(f"I do not see `{app_id}` in the Faux-pass registry yet.", status="Faux-pass app missing")


PENDING_REBOOT_STATE_KEY = "pending_reboot_requested_at"
REBOOT_CONFIRM_PHRASES = {
    "/reboot confirm",
    "reboot confirm",
    "confirm reboot",
    "confirm",
    "yes",
    "yes reboot",
    "do it",
    "do the reboot",
    "reboot now",
}
REBOOT_CANCEL_PHRASES = {
    "/reboot cancel",
    "reboot cancel",
    "cancel reboot",
    "cancel",
    "no",
    "never mind",
    "nevermind",
}


def reboot_confirmation_pending(store: FennixStore | None) -> bool:
    if store is None:
        return False
    raw = store.get_state(PENDING_REBOOT_STATE_KEY, "")
    try:
        requested_at = int(raw)
    except ValueError:
        return False
    return requested_at > 0 and (int(time.time()) - requested_at) <= 300


def set_reboot_confirmation_pending(store: FennixStore | None, pending: bool) -> None:
    if store is not None:
        store.set_state(PENDING_REBOOT_STATE_KEY, str(int(time.time())) if pending else "")


def weather_location_status_response() -> str:
    code, output = command_output(["fauxnix-settings", "weather-location"], timeout=3, limit=600)
    if code != 0:
        return "I could not read the weather location yet: " + (output or "fauxnix-settings failed")
    return "Weather location: " + (output or "not set")


def clean_weather_location(value: str) -> str:
    value = value.strip(" .!?\t\r\n\"'")
    value = re.sub(r"^(?:to|as|for|is)\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:80]


def weather_location_from_text(user_text: str) -> str:
    stripped = user_text.strip()
    normalized = normalize_command_text(stripped)

    if "weather" in normalized and any(word in normalized for word in ("zip", "zipcode", "postal")):
        zip_match = re.search(r"\b\d{5}(?:-\d{4})?\b", stripped)
        if zip_match:
            return zip_match.group(0)

    patterns = (
        r"\b(?:set|change|update|configure|setup|set up)\s+(?:my\s+)?weather(?:\s+location)?\s+(?:to|as|for)\s+(.+)$",
        r"\bweather\s+location\s+(?:to|is|as|for)\s+(.+)$",
        r"\b(?:set|change|update|configure|setup|set up)\s+(?:my\s+|the\s+)?(?:weather\s+)?(?:zip\s*code|zipcode|postal\s+code)(?:\s+for\s+weather)?\s+(?:to|is|as|for)\s+(.+)$",
        r"\b(?:weather\s+)?(?:zip\s*code|zipcode|postal\s+code)\s+(?:to|is|as|for)\s+(.+)$",
        r"\buse\s+(.+?)\s+(?:for|as)\s+(?:my\s+)?weather(?:\s+location)?$",
        r"\buse\s+(.+?)\s+(?:for|as)\s+(?:my\s+)?(?:weather\s+)?(?:zip\s*code|zipcode|postal\s+code)$",
    )
    for pattern in patterns:
        match = re.search(pattern, stripped, flags=re.IGNORECASE)
        if match:
            location = clean_weather_location(match.group(1))
            if location:
                return location
    return ""


def local_action_for_text(user_text: str, store: FennixStore | None = None) -> LocalAction | None:
    normalized = normalize_command_text(user_text)
    if not normalized:
        return None

    if normalized in REBOOT_CANCEL_PHRASES and (
        normalized in {"/reboot cancel", "reboot cancel", "cancel reboot"} or reboot_confirmation_pending(store)
    ):
        set_reboot_confirmation_pending(store, False)
        return LocalAction("Reboot cancelled.")

    if normalized in REBOOT_CONFIRM_PHRASES and (
        normalized in {"/reboot confirm", "reboot confirm", "confirm reboot"} or reboot_confirmation_pending(store)
    ):
        set_reboot_confirmation_pending(store, False)
        return LocalAction(
            "Reboot confirmed. I am asking systemd to reboot this machine now.",
            status="Reboot requested",
            reboot=True,
        )

    weather_location = weather_location_from_text(user_text)
    if weather_location:
        return LocalAction(
            f"Setting the weather location to {weather_location}. The dashboard and lock screen will use it on their next refresh.",
            status="Weather location saved",
            commands=(("fauxnix-settings", "weather-location", weather_location),),
        )

    if "weather" in normalized and "location" in normalized and any(word in normalized for word in ("status", "show", "current", "what")):
        return LocalAction(weather_location_status_response(), status="Weather location ready")

    if normalized in {"lock", "lock screen", "lock the screen", "lock computer", "lock the computer"}:
        return LocalAction(
            "Locking the screen with the Fauxnix lock screen.",
            status="Screen lock requested",
            commands=(("fauxnix-power", "lock-now"),),
        )

    mode_request = display_mode_from_text(user_text)
    display_mode_terms = (
        "resolution",
        "display mode",
        "screen mode",
        "refresh rate",
        "supported resolution",
        "supported resolutions",
        "supported display mode",
        "supported display modes",
    )
    display_action_terms = ("set", "change", "switch", "use", "make", "apply")
    wants_display_mode = has_any_phrase(normalized, display_mode_terms) or (
        bool(mode_request) and "display" in normalized and any(word in normalized for word in display_action_terms)
    )
    if wants_display_mode:
        if mode_request and any(word in normalized for word in display_action_terms):
            return LocalAction(
                f"Setting the display mode to {mode_request}. I will only apply it if Sway reports that mode as supported.",
                status="Display mode update",
                commands=(("fauxnix-display", "set", mode_request),),
            )
        if any(word in normalized for word in ("supported", "available", "list", "modes", "resolutions")):
            return LocalAction(display_modes_response(), status="Display modes")
        if any(word in normalized for word in ("status", "show", "current", "what", "which", "using", "set")):
            return LocalAction(display_status_response(), status="Display mode status")
        if mode_request:
            return LocalAction(
                f"I can set the display mode to {mode_request}. Say `set resolution to {mode_request}` to apply it."
            )

    screen_terms = ("screen", "display", "brightness", "dimming", "dim")
    timeout_terms = ("timeout", "dimming", "dim", "sleep", "fade")
    if has_any_phrase(normalized, screen_terms) and has_any_phrase(normalized, timeout_terms):
        seconds = duration_seconds_from_text(normalized)
        if "status" in normalized or (("setting" in normalized or "settings" in normalized) and seconds is None):
            return LocalAction(screen_power_status_response(), status="Screen dimming status")
        if "pause" in normalized or "suspend" in normalized:
            if seconds is None:
                return LocalAction("How long should I pause screen dimming? For example: `pause screen dimming for one hour`.")
            return LocalAction(
                f"Pausing screen dimming for {format_duration(seconds)}.",
                status="Screen dimming paused",
                commands=(("fauxnix-power", "pause", str(seconds)),),
            )
        if any(word in normalized for word in ("resume", "unpause", "restart", "enable")) and seconds is None:
            return LocalAction(
                "Resuming screen dimming.",
                status="Screen dimming resumed",
                commands=(("fauxnix-power", "resume"), ("fauxnix-power", "restart")),
            )
        if "fade" in normalized and seconds is not None:
            return LocalAction(
                f"Setting screen fade duration to {format_duration(seconds)}.",
                status="Screen fade updated",
                commands=(("fauxnix-power", "set-fade", str(seconds)),),
            )
        if any(word in normalized for word in ("set", "change", "make", "timeout")) and seconds is not None:
            return LocalAction(
                f"Setting screen dimming timeout to {format_duration(seconds)}.",
                status="Screen timeout updated",
                commands=(("fauxnix-power", "set-timeout", str(seconds)),),
            )

    status_phrases = (
        "/status",
        "status",
        "system status",
        "assistant status",
        "fennix status",
        "fauxnix status",
        "git status",
        "where are we",
        "where did we leave off",
        "pick up where we left off",
        "pick up where you left off",
        "what changed",
        "what is the status",
        "what's the status",
    )
    if normalized in status_phrases or has_any_phrase(
        normalized,
        (
            "show status",
            "show me status",
            "show me the status",
            "where we left off",
            "where you left off",
        ),
    ):
        if store is None:
            return LocalAction("Fennix status needs the local database. Open Fennix from the GUI or run `fennix-gui --self-test`.")
        return LocalAction(assistant_status_response(store), status="Status ready")

    fauxdex_status_phrases = (
        "/fauxdex",
        "fauxdex status",
        "codex status",
        "workspace agent status",
        "workspace status",
        "observe workspace",
        "inspect workspace",
        "index workspace",
        "show workspace",
        "show fauxdex",
    )
    if normalized in fauxdex_status_phrases or has_any_phrase(normalized, fauxdex_status_phrases):
        return LocalAction(
            fauxdex_status_response(),
            status="Fauxdex status ready",
        )

    faux_pass_terms = ("faux-pass", "faux pass")
    if has_any_phrase(normalized, faux_pass_terms):
        if has_any_phrase(normalized, ("app", "apps", "catalog", "list", "show", "registered")):
            return LocalAction(faux_pass_apps_response(), status="Faux-pass apps ready")
        if has_any_phrase(normalized, ("status", "provider", "providers", "what is", "what's", "health")):
            return LocalAction(faux_pass_status_response(), status="Faux-pass status ready")

    if has_any_phrase(normalized, ("provider apps", "pass-through apps", "pass through apps")):
        return LocalAction(faux_pass_apps_response(), status="Faux-pass apps ready")

    faux_pass_app = faux_pass_app_from_text(normalized)
    if faux_pass_app:
        return faux_pass_launch_action(faux_pass_app)

    if has_any_phrase(
        normalized,
        (
            "open fauxdex",
            "fauxdex thread",
            "open code thread",
            "open coding thread",
            "codex mode",
            "codex-like mode",
            "codex like mode",
            "workspace agent",
        ),
    ):
        return LocalAction(
            "Opening the Fauxdex thread. This is Fennix's bounded workspace loop for observe, plan, inspect, propose, verify, and summarize.",
            status="Opened Fauxdex thread",
            commands=(("fauxnix-thread", "fauxdex"),),
        )

    browse_phrases = (
        "browse the web",
        "browse web",
        "open the web",
        "open web",
        "open browser",
        "launch browser",
        "start browser",
        "launch firefox",
        "open firefox",
        "use the internet",
        "go online",
    )
    if has_any_phrase(normalized, browse_phrases):
        return LocalAction(
            "Opening the Web thread on workspace 5 and launching Firefox.",
            status="Opened Web thread",
            commands=(("fauxnix-thread", "web"),),
        )

    if has_any_phrase(normalized, ("open apps", "show apps", "app launcher", "launch apps", "open launcher")):
        return LocalAction(
            "Opening the app launcher.",
            status="Opened apps",
            commands=(("rofi", "-show", "drun"),),
        )

    if has_any_phrase(normalized, ("open notes", "show notes", "notes app", "open clipboard", "show clipboard")):
        return LocalAction(
            "Opening Fennix notes and clipboard.",
            status="Opened notes",
            commands=(("fennix-gui", "--notes"),),
        )

    if has_any_phrase(normalized, ("open admin thread", "admin thread", "admin shell", "open ops")):
        return LocalAction(
            "Opening the Admin thread with the git-backed system status.",
            status="Opened Admin thread",
            commands=(("fauxnix-thread", "admin"),),
        )

    if has_any_phrase(normalized, ("open root thread", "root thread", "root shell", "administrator shell")):
        return LocalAction(
            "Opening the Root thread. This shell has full administrator privileges, so use it deliberately.",
            status="Opened Root thread",
            commands=(("fauxnix-thread", "root"),),
        )

    if has_any_phrase(normalized, ("open terminal", "terminal thread", "new terminal")):
        return LocalAction(
            "Opening the Terminal thread.",
            status="Opened Terminal thread",
            commands=(("fauxnix-thread", "terminal"),),
        )

    asks_reboot = "reboot" in normalized or (
        "restart" in normalized
        and any(word in normalized for word in ("computer", "laptop", "machine", "system", "nixos", "os"))
    )
    if asks_reboot:
        set_reboot_confirmation_pending(store, True)
        return LocalAction(
            "I can reboot this machine, but I need explicit confirmation because it will close the current session. "
            "Type `yes` or `/reboot confirm` to reboot now, or `no` to cancel."
        )

    return None


def execute_local_action(action: LocalAction, root: tk.Misc | None = None) -> str:
    errors: list[str] = []
    for command in action.commands:
        try:
            launch_detached(list(command))
        except OSError as exc:
            errors.append(f"{' '.join(command)}: {exc}")
    if action.reboot:
        error = request_system_reboot()
        if error:
            errors.append(error)
    return "; ".join(errors)


def request_system_reboot() -> str:
    commands = (
        ("systemctl", "reboot", "--no-wall"),
        ("loginctl", "reboot"),
        ("sudo", "-n", "systemctl", "reboot", "--no-wall"),
    )
    errors: list[str] = []
    for command in commands:
        try:
            result = subprocess.run(
                list(command),
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(f"{' '.join(command)}: {exc}")
            continue
        if result.returncode == 0:
            log(f"reboot requested via {' '.join(command)}")
            return ""
        output = (result.stderr or result.stdout or "").strip()
        errors.append(f"{' '.join(command)} exited {result.returncode}: {output or 'no output'}")
    error = "Reboot request failed. " + " | ".join(errors)
    log(error)
    return error


def read_system_clipboard(widget: tk.Misc | None = None) -> str:
    try:
        result = subprocess.run(
            ["wl-paste", "--no-newline"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout
    except (OSError, subprocess.SubprocessError):
        pass

    if widget is not None:
        try:
            value = widget.clipboard_get()
            return str(value)
        except tk.TclError:
            pass
    return ""


def write_system_clipboard(text: str, widget: tk.Misc | None = None) -> None:
    if widget is not None:
        try:
            widget.clipboard_clear()
            widget.clipboard_append(text)
        except tk.TclError:
            pass
    try:
        subprocess.run(
            ["wl-copy"],
            input=text,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        pass


class FennixNotesWindow:
    def __init__(self, parent: tk.Misc, store: FennixStore, initial_note_id: int | None = None) -> None:
        self.parent = parent
        self.store = store
        self.note_ids: list[int] = []
        self.selected_note_id = initial_note_id
        self.query_var = tk.StringVar()
        self.title_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")

        self.window = tk.Toplevel(parent)
        self.window.title("Fennix Notes")
        self.window.geometry("820x560")
        self.window.minsize(680, 440)
        self.window.configure(bg="#0b0b0b")
        self.window.columnconfigure(1, weight=1)
        self.window.rowconfigure(0, weight=1)

        self.build_ui()
        self.refresh_list(select_id=initial_note_id)
        self.refresh_clipboard()
        self.window.lift()

    def build_ui(self) -> None:
        left = ttk.Frame(self.window, padding=10)
        left.grid(row=0, column=0, sticky="ns")
        left.rowconfigure(2, weight=1)

        ttk.Label(left, text="Notes").grid(row=0, column=0, sticky="w")
        search = ttk.Entry(left, textvariable=self.query_var, width=28)
        search.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        self.query_var.trace_add("write", lambda *_args: self.refresh_list())

        self.note_list = tk.Listbox(left, width=30, exportselection=False)
        self.note_list.grid(row=2, column=0, sticky="ns")
        self.note_list.bind("<<ListboxSelect>>", self.select_note)

        note_actions = ttk.Frame(left)
        note_actions.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(note_actions, text="New", command=self.new_note).pack(side="left")
        ttk.Button(note_actions, text="Delete", command=self.delete_selected_note).pack(side="right")

        right = ttk.Frame(self.window, padding=(0, 10, 10, 10))
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)

        clipboard_header = ttk.Frame(right)
        clipboard_header.grid(row=0, column=0, sticky="ew")
        ttk.Label(clipboard_header, text="Clipboard").pack(side="left")
        ttk.Button(clipboard_header, text="Refresh", command=self.refresh_clipboard).pack(side="right", padx=(6, 0))
        ttk.Button(clipboard_header, text="Save Clip", command=self.save_clipboard_note).pack(side="right")

        self.clipboard_text = tk.Text(right, height=4, wrap="word", padx=8, pady=6, borderwidth=0)
        self.clipboard_text.grid(row=1, column=0, sticky="ew", pady=(6, 12))

        title_row = ttk.Frame(right)
        title_row.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        title_row.columnconfigure(1, weight=1)
        ttk.Label(title_row, text="Title").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(title_row, textvariable=self.title_var).grid(row=0, column=1, sticky="ew")

        self.content_text = tk.Text(right, wrap="word", padx=10, pady=10, borderwidth=0)
        self.content_text.grid(row=3, column=0, sticky="nsew")

        actions = ttk.Frame(right)
        actions.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(actions, textvariable=self.status_var).pack(side="left")
        ttk.Button(actions, text="Copy Note", command=self.copy_note).pack(side="right", padx=(6, 0))
        ttk.Button(actions, text="Save", command=self.save_note).pack(side="right")

        self.apply_colors()

    def apply_colors(self) -> None:
        for widget in (self.note_list, self.clipboard_text, self.content_text):
            widget.configure(
                bg="#1f2124",
                fg="#eeeeee",
                insertbackground="#eeeeee",
                selectbackground="#ff7800",
                selectforeground="#111111",
            )

    def refresh_list(self, select_id: int | None = None) -> None:
        query = self.query_var.get()
        rows = self.store.notes(limit=80, query=query)
        self.note_ids = []
        self.note_list.delete(0, tk.END)
        for index, row in enumerate(rows):
            note_id = int(row["id"])
            self.note_ids.append(note_id)
            stamp = time.strftime("%m/%d %H:%M", time.localtime(int(row["updated_at"])))
            self.note_list.insert(tk.END, f"{row['title']}  -  {stamp}  {row['source']}")
            if select_id == note_id:
                self.note_list.selection_set(index)
                self.note_list.see(index)
        if select_id:
            self.load_note(select_id)

    def selected_list_note_id(self) -> int | None:
        selection = self.note_list.curselection()
        if not selection:
            return None
        index = int(selection[0])
        if index >= len(self.note_ids):
            return None
        return self.note_ids[index]

    def select_note(self, _event: tk.Event | None = None) -> None:
        note_id = self.selected_list_note_id()
        if note_id is not None:
            self.load_note(note_id)

    def load_note(self, note_id: int) -> None:
        row = self.store.get_note(note_id)
        if row is None:
            return
        self.selected_note_id = note_id
        self.title_var.set(str(row["title"]))
        self.content_text.delete("1.0", tk.END)
        self.content_text.insert(tk.END, str(row["content"]))
        self.status_var.set(f"Loaded {row['source']} note")

    def new_note(self) -> None:
        self.selected_note_id = None
        self.note_list.selection_clear(0, tk.END)
        self.title_var.set("")
        self.content_text.delete("1.0", tk.END)
        self.content_text.focus_set()
        self.status_var.set("New note")

    def save_note(self) -> None:
        title = self.title_var.get()
        content = self.content_text.get("1.0", tk.END).strip()
        if self.selected_note_id is None:
            self.selected_note_id = self.store.add_note(title, content, "manual")
            self.status_var.set("Saved new note")
        else:
            self.store.update_note(self.selected_note_id, title, content)
            self.status_var.set("Saved note")
        self.refresh_list(select_id=self.selected_note_id)

    def delete_selected_note(self) -> None:
        note_id = self.selected_note_id or self.selected_list_note_id()
        if note_id is None:
            self.status_var.set("No note selected")
            return
        if not messagebox.askyesno("Delete note", "Delete this note?", parent=self.window):
            return
        self.store.delete_note(note_id)
        self.selected_note_id = None
        self.title_var.set("")
        self.content_text.delete("1.0", tk.END)
        self.refresh_list()
        self.status_var.set("Deleted note")

    def refresh_clipboard(self) -> None:
        text = read_system_clipboard(self.window)
        self.clipboard_text.delete("1.0", tk.END)
        self.clipboard_text.insert(tk.END, text)
        self.status_var.set("Clipboard refreshed" if text else "Clipboard empty")

    def save_clipboard_note(self) -> None:
        content = self.clipboard_text.get("1.0", tk.END).strip()
        if not content:
            self.refresh_clipboard()
            content = self.clipboard_text.get("1.0", tk.END).strip()
        if not content:
            self.status_var.set("Clipboard empty")
            return
        note_id = self.store.add_clipboard_text(content, "notes_window")
        self.refresh_list(select_id=note_id)
        self.status_var.set("Saved clipboard note")

    def copy_note(self) -> None:
        content = self.content_text.get("1.0", tk.END).strip()
        if not content:
            self.status_var.set("Nothing to copy")
            return
        write_system_clipboard(content, self.window)
        self.status_var.set("Copied note")


class FennixApp:
    def __init__(
        self,
        root: tk.Tk,
        store: FennixStore,
        routes: dict[str, Route],
        initial_conversation: int | None = None,
    ) -> None:
        self.root = root
        self.store = store
        self.routes = routes
        self.cowriter_root = load_cowriter_workspace()
        self.workspace_root = load_workspace_root()
        if initial_conversation is not None and store.conversation_exists(initial_conversation):
            self.current_conversation = initial_conversation
        else:
            self.current_conversation = store.ensure_conversation()
        self.memory_ids: list[int] = []
        self.conversation_ids: list[int] = []
        self.outbox: queue.Queue[tuple[str, str]] = queue.Queue()
        self.busy = False
        self.workspace_window: tk.Toplevel | None = None

        root.title("Fennix")
        root.geometry("1100x720")
        root.minsize(860, 560)

        self.route_var = tk.StringVar(value="local")
        self.status_var = tk.StringVar(value="Ready")
        self.conversation_search_var = tk.StringVar()
        self.memory_search_var = tk.StringVar()
        self.memory_category_var = tk.StringVar(value="note")
        self.memory_pinned_var = tk.BooleanVar(value=False)
        self._streaming = False
        self._stream_route = "local"
        self._stream_conversation = self.current_conversation

        self.build_ui()
        self.refresh_all()
        self.root.after(80, self.drain_outbox)

    def build_ui(self) -> None:
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        left = ttk.Frame(self.root, padding=8)
        left.grid(row=0, column=0, sticky="nsew")
        left.rowconfigure(3, weight=1)

        ttk.Label(left, text="Conversations").grid(row=0, column=0, sticky="w")
        ttk.Button(left, text="New", command=self.new_conversation).grid(row=1, column=0, sticky="ew", pady=(6, 6))
        conversation_search = ttk.Entry(left, textvariable=self.conversation_search_var)
        conversation_search.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        conversation_search.insert(0, "")
        self.conversation_search_var.trace_add("write", lambda *_args: self.refresh_conversations())
        self.conversation_list = tk.Listbox(left, width=28, exportselection=False)
        self.conversation_list.grid(row=3, column=0, sticky="nsew")
        self.conversation_list.bind("<<ListboxSelect>>", self.select_conversation)

        center = ttk.Frame(self.root, padding=(0, 8, 0, 8))
        center.grid(row=0, column=1, sticky="nsew")
        center.columnconfigure(0, weight=1)
        center.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(center)
        toolbar.grid(row=0, column=0, sticky="ew", padx=8)
        self.build_fox_mark(toolbar).pack(side="left", padx=(0, 8))
        ttk.Label(toolbar, text="Fennix").pack(side="left", padx=(0, 14))
        ttk.Label(toolbar, text="Route").pack(side="left")
        ttk.Radiobutton(toolbar, text="Local", variable=self.route_var, value="local").pack(side="left", padx=(8, 0))
        ttk.Radiobutton(toolbar, text="Parent", variable=self.route_var, value="parent").pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="Status", command=self.check_status).pack(side="right")
        ttk.Button(toolbar, text="Summarize", command=self.summarize_conversation).pack(side="right", padx=(0, 8))

        chat_frame = ttk.Frame(center)
        chat_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)
        chat_frame.columnconfigure(0, weight=1)
        chat_frame.rowconfigure(0, weight=1)

        self.chat = tk.Text(chat_frame, wrap="word", state="disabled", padx=12, pady=12)
        chat_scroll = ttk.Scrollbar(chat_frame, orient="vertical", command=self.chat.yview)
        self.chat.configure(yscrollcommand=chat_scroll.set)
        self.chat.grid(row=0, column=0, sticky="nsew")
        chat_scroll.grid(row=0, column=1, sticky="ns")
        self.chat.tag_configure("user", foreground="#173b7a", spacing1=8, spacing3=8)
        self.chat.tag_configure("assistant", foreground="#1d5f3f", spacing1=8, spacing3=8)
        self.chat.tag_configure("system", foreground="#666666", spacing1=8, spacing3=8)

        input_frame = ttk.Frame(center)
        input_frame.grid(row=2, column=0, sticky="ew", padx=8)
        input_frame.columnconfigure(0, weight=1)
        self.input = tk.Text(input_frame, height=4, wrap="word")
        self.input.grid(row=0, column=0, sticky="ew")
        self.input.bind("<Control-Return>", lambda _event: self.send())
        ttk.Button(input_frame, text="Send", command=self.send).grid(row=0, column=1, sticky="ns", padx=(8, 0))

        right = ttk.Frame(self.root, padding=8)
        right.grid(row=0, column=2, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.columnconfigure(1, weight=1)
        right.rowconfigure(2, weight=1)
        ttk.Label(right, text="Memory").grid(row=0, column=0, columnspan=2, sticky="w")
        memory_search = ttk.Entry(right, textvariable=self.memory_search_var)
        memory_search.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 6))
        self.memory_search_var.trace_add("write", lambda *_args: self.refresh_memories())
        self.memory_list = tk.Listbox(right, width=34, exportselection=False)
        self.memory_list.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(0, 6))
        self.memory_entry = ttk.Entry(right)
        self.memory_entry.grid(row=3, column=0, columnspan=2, sticky="ew")
        category = ttk.Combobox(
            right,
            textvariable=self.memory_category_var,
            values=("note", "fact", "preference", "task", "summary", "system"),
            state="readonly",
            width=14,
        )
        category.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        ttk.Checkbutton(right, text="Pinned", variable=self.memory_pinned_var).grid(
            row=4, column=1, sticky="w", pady=(6, 0), padx=(6, 0)
        )
        ttk.Button(right, text="Add", command=self.add_memory).grid(row=5, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(right, text="Promote", command=self.promote_selection).grid(row=5, column=1, sticky="ew", pady=(6, 0), padx=(6, 0))
        ttk.Button(right, text="Delete", command=self.delete_memory).grid(row=6, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(right, text="Pin", command=self.toggle_memory_pin).grid(row=6, column=1, sticky="ew", pady=(6, 0), padx=(6, 0))
        ttk.Button(right, text="Save Draft", command=lambda: self.save_cowriter("draft")).grid(row=7, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(right, text="Save Note", command=lambda: self.save_cowriter("note")).grid(row=7, column=1, sticky="ew", pady=(12, 0), padx=(6, 0))
        ttk.Button(right, text="Save Session", command=lambda: self.save_cowriter("session")).grid(row=8, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(right, text="Workspace", command=self.show_workspace_status).grid(row=8, column=1, sticky="ew", pady=(6, 0), padx=(6, 0))

        status = ttk.Label(self.root, textvariable=self.status_var, anchor="w", padding=(8, 4))
        status.grid(row=1, column=0, columnspan=3, sticky="ew")

    def build_fox_mark(self, parent: tk.Widget) -> tk.Canvas:
        canvas = tk.Canvas(parent, width=42, height=34, bg="#0b0b0b", highlightthickness=0)
        orange = "#ff7800"
        canvas.create_line(4, 3, 16, 23, 21, 17, 26, 23, 38, 3, width=3, fill=orange, joinstyle=tk.MITER)
        canvas.create_line(16, 23, 20, 31, 21, 18, 22, 31, 26, 23, width=3, fill=orange, joinstyle=tk.MITER)
        canvas.create_line(12, 17, 18, 21, width=3, fill=orange)
        canvas.create_line(30, 17, 24, 21, width=3, fill=orange)
        return canvas

    def refresh_all(self) -> None:
        self.refresh_conversations()
        self.refresh_chat()
        self.refresh_memories()

    def refresh_conversations(self) -> None:
        rows = self.store.conversations(self.conversation_search_var.get())
        self.conversation_ids = [int(row["id"]) for row in rows]
        self.conversation_list.delete(0, tk.END)
        for row in rows:
            self.conversation_list.insert(tk.END, row["title"])
        if self.current_conversation in self.conversation_ids:
            index = self.conversation_ids.index(self.current_conversation)
            self.conversation_list.selection_set(index)

    def refresh_chat(self) -> None:
        self.chat.configure(state="normal")
        self.chat.delete("1.0", tk.END)
        for row in self.store.messages(self.current_conversation):
            self.append_chat(row["role"], row["content"], row["route"], persist=False)
        self.chat.configure(state="disabled")
        self.chat.see(tk.END)

    def refresh_memories(self) -> None:
        rows = self.store.memories(self.memory_search_var.get())
        self.memory_ids = [int(row["id"]) for row in rows]
        self.memory_list.delete(0, tk.END)
        for row in rows:
            pin = "* " if row["pinned"] else ""
            self.memory_list.insert(tk.END, f"{pin}[{row['category']}] {row['content']}")

    def append_chat(self, role: str, content: str, route: str = "", persist: bool = False) -> None:
        if persist:
            self.store.add_message(self.current_conversation, role, route, content)
        label = role.capitalize()
        if route:
            label += f" [{route}]"
        self.chat.configure(state="normal")
        self.chat.insert(tk.END, f"{label}: ", role)
        self.chat.insert(tk.END, content.rstrip() + "\n\n", role)
        self.chat.configure(state="disabled")
        self.chat.see(tk.END)

    def new_conversation(self) -> None:
        if self.busy:
            self.status_var.set("Wait for the current response first")
            return
        self.current_conversation = self.store.create_conversation()
        self.refresh_all()
        self.input.focus_set()

    def select_conversation(self, _event: object) -> None:
        if self.busy:
            self.status_var.set("Wait for the current response first")
            return
        selection = self.conversation_list.curselection()
        if not selection:
            return
        self.current_conversation = self.conversation_ids[selection[0]]
        self.refresh_chat()

    def add_memory(self) -> None:
        content = self.memory_entry.get().strip()
        if not content:
            content = self.selected_chat_text()
        self.store.add_memory(
            content,
            self.memory_category_var.get(),
            self.memory_pinned_var.get(),
        )
        self.memory_entry.delete(0, tk.END)
        self.refresh_memories()

    def selected_chat_text(self) -> str:
        if not self.chat.tag_ranges(tk.SEL):
            return ""
        try:
            return self.chat.selection_get().strip()
        except tk.TclError:
            return ""

    def promote_selection(self) -> None:
        content = self.selected_chat_text()
        if not content:
            self.status_var.set("Select chat text first")
            return
        self.store.add_memory(
            content,
            self.memory_category_var.get(),
            self.memory_pinned_var.get(),
        )
        self.refresh_memories()
        self.status_var.set("Promoted selection to memory")

    def delete_memory(self) -> None:
        selection = self.memory_list.curselection()
        if not selection:
            return
        self.store.delete_memory(self.memory_ids[selection[0]])
        self.refresh_memories()

    def toggle_memory_pin(self) -> None:
        selection = self.memory_list.curselection()
        if not selection:
            return
        self.store.toggle_memory_pin(self.memory_ids[selection[0]])
        self.refresh_memories()

    def check_status(self) -> None:
        route = self.routes[self.route_var.get()]
        self.status_var.set(f"{route.name}: {route.base_url} / {route.model}")

    def latest_assistant_text(self) -> str:
        rows = self.store.messages(self.current_conversation, limit=20)
        for row in reversed(rows):
            if row["role"] == "assistant" and row["content"].strip():
                return row["content"].strip()
        return ""

    def current_transcript_text(self, limit: int = 80) -> str:
        rows = self.store.messages(self.current_conversation, limit=limit)
        return "\n\n".join(
            f"{row['role'].capitalize()} [{row['route']}]:\n{row['content'].strip()}"
            for row in rows
            if row["content"].strip()
        )

    def save_cowriter(self, kind: str) -> None:
        if kind == "session":
            content = self.current_transcript_text()
            title = "Fennix session"
        else:
            content = self.selected_chat_text() or self.latest_assistant_text()
            title = f"Fennix {kind}"

        if not content:
            self.status_var.set("Nothing to save yet")
            return

        try:
            path = cowriter_doc(self.cowriter_root, kind, title, content)
        except OSError as exc:
            self.status_var.set(f"Workspace save failed: {exc}")
            return
        except RuntimeError as exc:
            self.status_var.set(str(exc))
            return

        relative = path.relative_to(self.cowriter_root)
        self.store.add_memory(f"Saved {kind} to Cowriter: {relative}", "system", False)
        self.refresh_memories()
        self.status_var.set(f"Saved {relative}")

    def show_workspace_status(self) -> None:
        self.open_workspace_manager()

    def workspace_project_names(self) -> list[str]:
        return [path.name for path in workspace_projects(self.workspace_root)]

    def current_workspace_project(self) -> Path:
        name = self.workspace_project_var.get().strip()
        project = workspace_project(self.workspace_root, name)
        root_resolved = self.workspace_root.resolve()
        project_resolved = project.resolve()
        if project_resolved != root_resolved and project_resolved.parent != root_resolved:
            raise RuntimeError("Select a direct project under the workspace root.")
        if not project.is_dir():
            raise RuntimeError(f"Project not found: {project}")
        self.store.set_state("active_project", project.name)
        return project

    def open_workspace_manager(self) -> None:
        if self.workspace_window is not None and self.workspace_window.winfo_exists():
            self.workspace_window.lift()
            return

        names = self.workspace_project_names()
        active = self.store.get_state("active_project", names[0] if names else "")
        if names and active not in names:
            active = names[0]

        self.workspace_project_var = tk.StringVar(value=active)
        self.workspace_goal_var = tk.StringVar(value=self.store.get_state("current_goal"))
        self.workspace_path_var = tk.StringVar()
        self.workspace_search_var = tk.StringVar()

        win = tk.Toplevel(self.root)
        self.workspace_window = win
        win.title("Fennix Workspace")
        win.geometry("900x620")
        win.minsize(720, 480)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(4, weight=1)
        win.protocol("WM_DELETE_WINDOW", self.close_workspace_manager)

        header = ttk.Frame(win, padding=(10, 10, 10, 4))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(2, weight=1)
        self.build_fox_mark(header).grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 10))
        ttk.Label(header, text="Workspace").grid(row=0, column=1, sticky="w")
        ttk.Label(header, text=str(self.workspace_root)).grid(row=1, column=1, columnspan=2, sticky="w")
        ttk.Label(header, text="Project").grid(row=0, column=3, sticky="e", padx=(12, 6))
        self.workspace_project_combo = ttk.Combobox(
            header,
            textvariable=self.workspace_project_var,
            values=names,
            state="readonly" if names else "normal",
            width=24,
        )
        self.workspace_project_combo.grid(row=0, column=4, sticky="ew")
        ttk.Button(header, text="Refresh", command=self.workspace_refresh_projects).grid(row=0, column=5, padx=(6, 0))

        task = ttk.Frame(win, padding=(10, 4))
        task.grid(row=1, column=0, sticky="ew")
        task.columnconfigure(1, weight=1)
        ttk.Label(task, text="Current task").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(task, textvariable=self.workspace_goal_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(task, text="Save", command=self.workspace_save_goal).grid(row=0, column=2, sticky="e", padx=(8, 0))

        selectors = ttk.Frame(win, padding=(10, 4))
        selectors.grid(row=2, column=0, sticky="ew")
        selectors.columnconfigure(1, weight=1)
        selectors.columnconfigure(4, weight=1)
        ttk.Label(selectors, text="Path").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(selectors, textvariable=self.workspace_path_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(selectors, text="Read", command=self.workspace_read_path).grid(row=0, column=2, padx=(8, 16))
        ttk.Label(selectors, text="Search").grid(row=0, column=3, sticky="w", padx=(0, 8))
        ttk.Entry(selectors, textvariable=self.workspace_search_var).grid(row=0, column=4, sticky="ew")
        ttk.Button(selectors, text="Find", command=self.workspace_search_text).grid(row=0, column=5, padx=(8, 0))

        actions = ttk.Frame(win, padding=(10, 4, 10, 8))
        actions.grid(row=3, column=0, sticky="ew")
        ttk.Button(actions, text="Overview", command=self.workspace_show_overview).pack(side="left")
        ttk.Button(actions, text="Index", command=self.workspace_index_project).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Tree", command=self.workspace_show_tree).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Git Status", command=self.workspace_show_git).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Cowriter", command=self.workspace_show_cowriter).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Use in Chat", command=self.workspace_send_to_chat).pack(side="right")

        output_frame = ttk.Frame(win, padding=(10, 0, 10, 10))
        output_frame.grid(row=4, column=0, sticky="nsew")
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)
        self.workspace_output = tk.Text(output_frame, wrap="none", state="disabled", padx=10, pady=10)
        yscroll = ttk.Scrollbar(output_frame, orient="vertical", command=self.workspace_output.yview)
        xscroll = ttk.Scrollbar(output_frame, orient="horizontal", command=self.workspace_output.xview)
        self.workspace_output.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.workspace_output.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")

        self.workspace_show_overview()

    def close_workspace_manager(self) -> None:
        if self.workspace_window is not None:
            self.workspace_window.destroy()
            self.workspace_window = None

    def workspace_set_output(self, title: str, body: str) -> None:
        text = body.rstrip()
        if title:
            text = f"{title}\n{'=' * len(title)}\n\n{text}"
        self.workspace_output.configure(state="normal")
        self.workspace_output.delete("1.0", tk.END)
        self.workspace_output.insert(tk.END, text + "\n")
        self.workspace_output.configure(state="disabled")
        self.workspace_output.see("1.0")

    def workspace_refresh_projects(self) -> None:
        names = self.workspace_project_names()
        self.workspace_project_combo.configure(values=names, state="readonly" if names else "normal")
        if names and self.workspace_project_var.get() not in names:
            self.workspace_project_var.set(names[0])
        self.workspace_show_overview()

    def workspace_save_goal(self) -> None:
        goal = self.workspace_goal_var.get().strip()
        self.store.set_state("current_goal", goal)
        self.status_var.set("Workspace task saved")
        self.workspace_show_overview()

    def workspace_index_project(self) -> None:
        try:
            project = self.current_workspace_project()
            index = workspace_index(project)
            indexed_at = time.strftime("%Y-%m-%d %H:%M:%S %z")
            self.store.set_state("workspace_indexed_at", f"{project.name} at {indexed_at}")
            self.store.set_state("workspace_index", index[:12000])
            self.workspace_set_output(f"{project.name} Index", index)
            self.status_var.set("Workspace index refreshed")
        except (OSError, RuntimeError) as exc:
            self.workspace_set_output("Workspace Error", str(exc))

    def workspace_show_overview(self) -> None:
        try:
            body = workspace_overview(self.store)
            body += "\n\n" + cowriter_overview(self.cowriter_root, limit=8)
        except OSError as exc:
            body = f"Workspace overview failed: {exc}"
        self.workspace_set_output("Fennix Workspace Manager v0", body)

    def workspace_show_tree(self) -> None:
        try:
            project = self.current_workspace_project()
            self.workspace_set_output(f"{project.name} Tree", workspace_tree(project))
        except (OSError, RuntimeError) as exc:
            self.workspace_set_output("Workspace Error", str(exc))

    def workspace_show_git(self) -> None:
        try:
            project = self.current_workspace_project()
            self.workspace_set_output(f"{project.name} Git Status", workspace_git_status(project))
        except (OSError, RuntimeError) as exc:
            self.workspace_set_output("Workspace Error", str(exc))

    def workspace_show_cowriter(self) -> None:
        self.workspace_set_output("Cowriter Workspace", cowriter_overview(self.cowriter_root, limit=24))

    def workspace_read_path(self) -> None:
        try:
            relative = self.workspace_path_var.get().strip()
            if not relative:
                self.workspace_set_output("Read File", "Enter a relative file path first.")
                return
            project = self.current_workspace_project()
            content = workspace_read_file(project, relative)
            self.workspace_set_output(f"{project.name}/{relative}", content)
        except (OSError, RuntimeError) as exc:
            self.workspace_set_output("Workspace Error", str(exc))

    def workspace_search_text(self) -> None:
        try:
            project = self.current_workspace_project()
            query = self.workspace_search_var.get()
            self.workspace_set_output(f"{project.name} Search", workspace_search(project, query))
        except (OSError, RuntimeError) as exc:
            self.workspace_set_output("Workspace Error", str(exc))

    def workspace_send_to_chat(self) -> None:
        try:
            project = self.current_workspace_project()
        except (OSError, RuntimeError) as exc:
            self.workspace_set_output("Workspace Error", str(exc))
            return
        content = self.workspace_output.get("1.0", tk.END).strip()
        if not content:
            self.status_var.set("No workspace context selected")
            return
        if len(content) > 14000:
            content = content[:14000] + "\n\n[truncated]"
        snippet = f"Workspace context from {project.name}:\n\n{content}\n\n"
        self.input.insert(tk.END, snippet)
        self.input.focus_set()
        self.status_var.set("Workspace context copied to chat input")

    def summarize_conversation(self) -> None:
        if self.busy:
            return
        messages = self.store.messages(self.current_conversation, limit=40)
        if not messages:
            self.status_var.set("Nothing to summarize yet")
            return

        route_name = self.route_var.get()
        route = self.routes[route_name]
        self._stream_route = route_name
        self._stream_conversation = self.current_conversation
        transcript = "\n".join(
            f"{row['role']}: {row['content'].strip()}"
            for row in messages
            if row["content"].strip()
        )
        prompt = (
            "Summarize this conversation as durable memory for Fennix. "
            "Keep it under 120 words. Include decisions, user preferences, "
            "open tasks, and important project facts.\n\n"
            f"{transcript}\n\nSummary:"
        )
        self.busy = True
        self.status_var.set(f"Summarizing via {route_name}...")
        thread = threading.Thread(
            target=self.summary_worker,
            args=(route, prompt),
            daemon=True,
        )
        thread.start()

    def summary_worker(self, route: Route, prompt: str) -> None:
        try:
            summary = "".join(ollama_generate(route, prompt)).strip()
            self.outbox.put(("summary_done", summary))
        except (OSError, urllib.error.URLError, RuntimeError, json.JSONDecodeError) as exc:
            self.outbox.put(("error", str(exc)))

    def send(self) -> None:
        if self.busy:
            return
        user_text = self.input.get("1.0", tk.END).strip()
        if not user_text:
            return

        route_name = self.route_var.get()
        route = self.routes[route_name]
        self._stream_route = route_name
        self._stream_conversation = self.current_conversation
        self.input.delete("1.0", tk.END)
        self.append_chat("user", user_text, route_name, persist=True)
        self.refresh_conversations()

        local_action = local_action_for_text(user_text, self.store)
        if local_action:
            self.append_chat("assistant", local_action.response, "local-action", persist=True)
            self.refresh_conversations()
            error = execute_local_action(local_action, self.root)
            self.status_var.set(error or local_action.status)
            if error:
                self.append_chat("system", f"Local action failed: {error}", "local-action", persist=True)
            return

        self.status_var.set(f"Thinking via {route_name}...")
        self.busy = True

        prompt = build_prompt(self.store, self.current_conversation, user_text)
        thread = threading.Thread(target=self.generate_worker, args=(route, prompt), daemon=True)
        thread.start()

    def generate_worker(self, route: Route, prompt: str) -> None:
        try:
            chunks = []
            for chunk in ollama_generate(route, prompt):
                chunks.append(chunk)
                self.outbox.put(("chunk", chunk))
            self.outbox.put(("done", "".join(chunks)))
        except (OSError, urllib.error.URLError, RuntimeError, json.JSONDecodeError) as exc:
            self.outbox.put(("error", str(exc)))

    def drain_outbox(self) -> None:
        try:
            while True:
                kind, payload = self.outbox.get_nowait()
                if kind == "chunk":
                    self.chat.configure(state="normal")
                    if not getattr(self, "_streaming", False):
                        self._streaming = True
                        self.chat.insert(tk.END, f"Assistant [{self._stream_route}]: ", "assistant")
                    self.chat.insert(tk.END, payload, "assistant")
                    self.chat.configure(state="disabled")
                    self.chat.see(tk.END)
                elif kind == "done":
                    self._streaming = False
                    self.chat.configure(state="normal")
                    self.chat.insert(tk.END, "\n\n", "assistant")
                    self.chat.configure(state="disabled")
                    self.store.add_message(self._stream_conversation, "assistant", self._stream_route, payload)
                    self.refresh_conversations()
                    if self.current_conversation == self._stream_conversation:
                        self.refresh_chat()
                    self.status_var.set("Ready")
                    self.busy = False
                elif kind == "summary_done":
                    self.store.add_memory(payload, "summary", True)
                    self.store.add_message(
                        self._stream_conversation,
                        "system",
                        "system",
                        f"Saved summary memory:\n{payload}",
                    )
                    if self.current_conversation == self._stream_conversation:
                        self.refresh_chat()
                    self.refresh_memories()
                    self.status_var.set("Summary saved to memory")
                    self.busy = False
                elif kind == "error":
                    self._streaming = False
                    self.store.add_message(
                        self._stream_conversation,
                        "system",
                        "system",
                        f"Error: {payload}",
                    )
                    if self.current_conversation == self._stream_conversation:
                        self.refresh_chat()
                    self.status_var.set("Error")
                    self.busy = False
        except queue.Empty:
            pass
        self.root.after(80, self.drain_outbox)


class FennixDesktop:
    CARD_BG = "#151515"
    CARD_BORDER = "#303236"
    PAGE_BG = "#090909"
    TEXT = "#eeeeee"
    MUTED = "#a3a7ad"
    ORANGE = "#ff7800"
    CYAN = "#00c8ff"
    HOME_WORKSPACE = "1:Fennix"

    def __init__(self, root: tk.Tk, store: FennixStore, routes: dict[str, Route]) -> None:
        self.root = root
        self.store = store
        self.routes = routes
        self.lock_fd = acquire_runtime_lock("fennix-desktop")
        if self.lock_fd is False:
            root.after(0, root.destroy)
            return
        self.workspace_root = load_workspace_root()
        self.env = load_assistant_env()
        self.status_var = tk.StringVar(value="Ready")
        self.clock_var = tk.StringVar()
        self.weather_var = tk.StringVar(value="Weather needs setup")
        self.telemetry_var = tk.StringVar(value="Starting telemetry")
        self.telemetry_detail_var = tk.StringVar()
        self.tray_clock_var = tk.StringVar()
        self.tray_network_var = tk.StringVar(value="net n/a")
        self.tray_battery_var = tk.StringVar(value="BAT n/a")
        self.tray_audio_var = tk.StringVar(value="VOL n/a")
        self.notes_summary_var = tk.StringVar(value="No notes yet")
        self.session_frame: tk.Frame | None = None
        self.notes_frame: tk.Frame | None = None
        self.telemetry_canvas: tk.Canvas | None = None
        self.cpu_sample = cpu_times()
        self.weather_busy = False
        self.empty_workspace_name = ""
        self.empty_workspace_since = 0.0

        root.title("Fennix Desktop")
        root.configure(bg=self.PAGE_BG)
        root.minsize(980, 680)
        width = max(root.winfo_screenwidth() - 8, 980)
        height = max(root.winfo_screenheight() - 42, 680)
        root.geometry(f"{width}x{height}+0+0")

        self.build_ui()
        self.refresh_clock()
        self.refresh_sessions()
        self.refresh_notes()
        self.root.after(300, self.refresh_telemetry)
        self.refresh_weather()
        self.root.after(1200, self.refresh_desktop_surface)

    def label(
        self,
        parent: tk.Widget,
        text: str = "",
        *,
        variable: tk.StringVar | None = None,
        size: int = 11,
        weight: str = "normal",
        color: str | None = None,
        bg: str | None = None,
        anchor: str = "w",
        justify: str = "left",
        wraplength: int = 0,
    ) -> tk.Label:
        return tk.Label(
            parent,
            text=text,
            textvariable=variable,
            bg=bg or self.CARD_BG,
            fg=color or self.TEXT,
            anchor=anchor,
            justify=justify,
            font=("TkDefaultFont", size, weight),
            wraplength=wraplength,
        )

    def card(
        self,
        parent: tk.Widget,
        title: str,
        row: int,
        column: int,
        *,
        columnspan: int = 1,
        rowspan: int = 1,
        sticky: str = "nsew",
    ) -> tk.Frame:
        outer = tk.Frame(parent, bg=self.CARD_BORDER)
        outer.grid(row=row, column=column, columnspan=columnspan, rowspan=rowspan, sticky=sticky, padx=8, pady=8)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        inner = tk.Frame(outer, bg=self.CARD_BG, padx=16, pady=14)
        inner.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        inner.columnconfigure(0, weight=1)
        inner.rowconfigure(1, weight=1)

        self.label(inner, title, size=10, weight="bold", color=self.ORANGE).grid(row=0, column=0, sticky="ew")
        body = tk.Frame(inner, bg=self.CARD_BG)
        body.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        body.columnconfigure(0, weight=1)
        return body

    def action_button(self, parent: tk.Widget, text: str, command: callable) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg="#22252a",
            fg=self.TEXT,
            activebackground="#333842",
            activeforeground=self.TEXT,
            relief="flat",
            padx=10,
            pady=7,
            cursor="hand2",
            highlightthickness=1,
            highlightbackground="#3a3e45",
        )

    def build_ui(self) -> None:
        shell = tk.Frame(self.root, bg=self.PAGE_BG, padx=18, pady=18)
        shell.pack(fill="both", expand=True)
        for column, weight in enumerate((3, 3, 2, 2)):
            shell.columnconfigure(column, weight=weight, uniform="desktop")
        for row, weight in enumerate((2, 2, 2, 2)):
            shell.rowconfigure(row, weight=weight, uniform="desktop")

        self.build_greeting(self.card(shell, "FauxnixOS", 0, 0, columnspan=2))
        self.build_weather(self.card(shell, "Weather", 0, 2))
        self.build_tray(self.card(shell, "Taskbar / Tray", 0, 3))
        self.build_pickup(self.card(shell, "Pick Up Where You Left Off", 1, 0, columnspan=2, rowspan=2))
        self.build_calendar(self.card(shell, "Calendar", 1, 2))
        self.build_apps(self.card(shell, "Apps", 1, 3))
        self.build_notes(self.card(shell, "Notes / Clipboard", 2, 2, columnspan=2))
        self.build_telemetry(self.card(shell, "Telemetry", 3, 0, columnspan=4))

        footer = tk.Frame(self.root, bg=self.PAGE_BG, padx=26, pady=0)
        footer.pack(fill="x", pady=(0, 10))
        self.label(footer, variable=self.status_var, bg=self.PAGE_BG, color=self.MUTED).pack(side="left", fill="x", expand=True)
        self.action_button(footer, "Refresh", self.refresh_all).pack(side="right")

    def build_greeting(self, parent: tk.Frame) -> None:
        user = self.env.get("FAUXNIX_USER") or os.environ.get("USER") or getpass.getuser()
        self.label(parent, f"Hello, {user}.", size=30, weight="bold").pack(anchor="w")
        self.label(parent, variable=self.clock_var, size=13, color=self.MUTED).pack(anchor="w", pady=(8, 18))

        actions = tk.Frame(parent, bg=self.CARD_BG)
        actions.pack(fill="x")
        self.action_button(actions, "Fennix Chat", self.open_chat).pack(side="left", padx=(0, 8))
        self.action_button(actions, "Workspace", lambda: self.open_thread("fauxnix")).pack(side="left", padx=(0, 8))
        self.action_button(actions, "Cowriter", lambda: self.open_thread("cowriter")).pack(side="left")

    def build_weather(self, parent: tk.Frame) -> None:
        self.label(
            parent,
            variable=self.weather_var,
            size=15,
            weight="bold",
            color=self.CYAN,
            justify="left",
            wraplength=260,
        ).pack(anchor="w", fill="x")
        location = self.env.get("FAUXNIX_WEATHER_LOCATION", "").strip()
        helper = f"Location: {location}" if location else "Ask Fennix to set a weather location"
        self.label(parent, helper, size=10, color=self.MUTED).pack(anchor="w", pady=(12, 0))

    def build_tray(self, parent: tk.Frame) -> None:
        self.label(parent, variable=self.tray_clock_var, size=12, weight="bold", color=self.CYAN).pack(anchor="w", pady=(0, 8))
        status = tk.Frame(parent, bg=self.CARD_BG)
        status.pack(fill="x", pady=(0, 10))
        for index, (name, variable) in enumerate(
            (
                ("Network", self.tray_network_var),
                ("Audio", self.tray_audio_var),
                ("Battery", self.tray_battery_var),
            )
        ):
            status.columnconfigure(1, weight=1)
            self.label(status, name, size=9, color=self.MUTED).grid(row=index, column=0, sticky="w", pady=2)
            self.label(status, variable=variable, size=10, color=self.TEXT, anchor="e").grid(row=index, column=1, sticky="ew", pady=2)

        grid = tk.Frame(parent, bg=self.CARD_BG)
        grid.pack(fill="x")
        for index, (text, command) in enumerate(
            (
                ("Network", lambda: self.launch(["nm-connection-editor"], "Network settings")),
                ("Audio", lambda: self.launch(["pavucontrol"], "Audio mixer")),
                ("Lock", lambda: self.launch(["fauxnix-power", "lock-now"], "Screen lock")),
                ("Apps", self.open_apps),
            )
        ):
            grid.columnconfigure(index % 2, weight=1)
            self.action_button(grid, text, command).grid(row=index // 2, column=index % 2, sticky="ew", padx=4, pady=4)

    def build_calendar(self, parent: tk.Frame) -> None:
        now = time.localtime()
        month = calendar.TextCalendar(calendar.SUNDAY).formatmonth(now.tm_year, now.tm_mon)
        tk.Label(
            parent,
            text=month,
            bg=self.CARD_BG,
            fg=self.TEXT,
            justify="left",
            anchor="nw",
            font=("TkFixedFont", 10),
        ).pack(anchor="nw", fill="both", expand=True)

    def build_apps(self, parent: tk.Frame) -> None:
        apps = (
            ("Terminal", lambda: self.open_thread("terminal")),
            ("Firefox", lambda: self.open_thread("web")),
            ("Rofi", self.open_apps),
            ("Fennix", self.open_chat),
            ("Fauxnix", lambda: self.open_thread("fauxnix")),
            ("Cowriter", lambda: self.open_thread("cowriter")),
        )
        for index, (text, command) in enumerate(apps):
            parent.columnconfigure(index % 2, weight=1)
            self.action_button(parent, text, command).grid(row=index // 2, column=index % 2, sticky="ew", padx=4, pady=4)

    def build_notes(self, parent: tk.Frame) -> None:
        summary = self.label(parent, variable=self.notes_summary_var, size=12, color=self.CYAN, wraplength=520)
        summary.pack(anchor="w", fill="x")
        summary.configure(cursor="hand2")
        summary.bind("<Button-1>", lambda _event: self.open_notes())

        self.notes_frame = tk.Frame(parent, bg=self.CARD_BG)
        self.notes_frame.pack(fill="both", expand=True, pady=(8, 8))

        actions = tk.Frame(parent, bg=self.CARD_BG)
        actions.pack(fill="x")
        self.action_button(actions, "Open Notes", self.open_notes).pack(side="left", padx=(0, 8))
        self.action_button(actions, "Capture Clip", self.capture_clipboard_note).pack(side="left")

    def build_telemetry(self, parent: tk.Frame) -> None:
        self.telemetry_canvas = tk.Canvas(parent, height=148, bg=self.CARD_BG, highlightthickness=0)
        self.telemetry_canvas.pack(fill="x", expand=True)
        self.label(parent, variable=self.telemetry_detail_var, size=10, color=self.MUTED, wraplength=560).pack(
            anchor="w", fill="x", pady=(8, 0)
        )
        self.label(parent, f"Workspace: {self.workspace_root}", size=10, color=self.MUTED).pack(anchor="w", pady=(4, 0))

    def build_pickup(self, parent: tk.Frame) -> None:
        self.label(
            parent,
            "Recent Fennix sessions are resumable. Click one to reopen the conversation.",
            color=self.MUTED,
        ).pack(anchor="w", fill="x")
        self.session_frame = tk.Frame(parent, bg=self.CARD_BG)
        self.session_frame.pack(fill="both", expand=True, pady=(12, 0))

    def refresh_all(self) -> None:
        self.refresh_sessions()
        self.refresh_notes()
        self.refresh_telemetry()
        self.refresh_weather()
        self.status_var.set("Refreshed")

    def refresh_clock(self) -> None:
        self.clock_var.set(time.strftime("%A, %B %d  %I:%M %p"))
        self.tray_clock_var.set(time.strftime("%I:%M %p  %a %b %d"))
        self.root.after(15000, self.refresh_clock)

    def refresh_telemetry(self) -> None:
        snapshot = telemetry_snapshot(self.cpu_sample)
        sample = snapshot.get("cpu_sample")
        self.cpu_sample = sample if isinstance(sample, tuple) else self.cpu_sample
        self.telemetry_var.set(system_telemetry())
        self.tray_network_var.set(str(snapshot["network_text"]))
        self.tray_battery_var.set(str(snapshot["battery_text"]))
        self.tray_audio_var.set(str(snapshot["audio_text"]))
        self.telemetry_detail_var.set(
            f"{snapshot['time']}  {snapshot['network_text']}  {snapshot['audio_text']}"
        )
        self.draw_telemetry_gauges(snapshot)
        self.root.after(3000, self.refresh_telemetry)

    def draw_telemetry_gauges(self, snapshot: dict[str, object]) -> None:
        if self.telemetry_canvas is None:
            return

        canvas = self.telemetry_canvas
        canvas.delete("all")
        canvas.update_idletasks()
        width = max(canvas.winfo_width(), 520)
        size = min(88, max(66, int((width - 90) / 4)))
        gap = max(14, int((width - (size * 4)) / 5))
        top = 8
        colors = (
            ("CPU", snapshot["cpu_percent"], self.ORANGE),
            ("RAM", snapshot["memory_percent"], self.CYAN),
            ("BAT", snapshot["battery_percent"], "#71e6b2"),
            ("LOAD", snapshot["load_percent"], "#ff5aa5"),
        )

        for index, (label, raw_value, color) in enumerate(colors):
            value = raw_value if isinstance(raw_value, float) else None
            left = gap + index * (size + gap)
            right = left + size
            bottom = top + size
            center_x = left + size / 2
            center_y = top + size / 2

            canvas.create_arc(left, top, right, bottom, start=90, extent=-359.9, style="arc", width=10, outline="#2a2d32")
            if value is not None:
                extent = -max(0.0, min(value, 100.0)) * 3.599
                canvas.create_arc(left, top, right, bottom, start=90, extent=extent, style="arc", width=10, outline=color)
                center_text = f"{value:.0f}%"
            else:
                center_text = "n/a"

            canvas.create_text(center_x, center_y - 4, text=center_text, fill=self.TEXT, font=("TkDefaultFont", 13, "bold"))
            canvas.create_text(center_x, bottom + 18, text=label, fill=self.MUTED, font=("TkDefaultFont", 9, "bold"))

    def refresh_sessions(self) -> None:
        if self.session_frame is None:
            return
        for child in self.session_frame.winfo_children():
            child.destroy()

        rows = self.store.conversations()[:7]
        if not rows:
            self.label(self.session_frame, "No sessions yet.", color=self.MUTED).pack(anchor="w")
            return

        for row in rows:
            conversation_id = int(row["id"])
            updated = time.strftime("%a %H:%M", time.localtime(int(row["updated_at"])))
            title = str(row["title"])
            text = f"{title}\n{updated}"
            button = self.action_button(
                self.session_frame,
                text,
                lambda cid=conversation_id: self.open_session(cid),
            )
            button.configure(anchor="w", justify="left")
            button.pack(fill="x", pady=4)

    def refresh_desktop_surface(self) -> None:
        try:
            self.sync_desktop_surface()
        except (OSError, RuntimeError, tk.TclError) as exc:
            log(f"desktop surface sync failed: {exc!r}")
        self.root.after(1000, self.refresh_desktop_surface)

    def sync_desktop_surface(self) -> None:
        workspaces = sway_json("get_workspaces")
        tree = sway_json("get_tree")
        focused = focused_workspace_name(workspaces)
        if not focused or not isinstance(tree, dict):
            return

        focused_node = workspace_node(tree, focused)
        app_count = workspace_app_count(focused_node)
        dashboard_workspace = workspace_for_window(tree, "Fennix Desktop")
        now = time.monotonic()

        if app_count == 0:
            if self.empty_workspace_name != focused:
                self.empty_workspace_name = focused
                self.empty_workspace_since = now
                return
            if now - self.empty_workspace_since < 1.4:
                return
            if dashboard_workspace and dashboard_workspace != focused:
                if sway_command(f'[title="^Fennix Desktop$"] move to workspace "{focused}"'):
                    sway_command(f'workspace "{focused}"')
                    log(f"desktop surface moved to empty workspace {focused}")
            return

        self.empty_workspace_name = ""
        self.empty_workspace_since = 0.0
        if dashboard_workspace == focused and focused != self.HOME_WORKSPACE:
            if sway_command(f'[title="^Fennix Desktop$"] move to workspace "{self.HOME_WORKSPACE}"'):
                sway_command(f'workspace "{focused}"')
                log(f"desktop surface parked on {self.HOME_WORKSPACE} while {focused} is active")

    def refresh_notes(self) -> None:
        rows = self.store.notes(limit=3)
        count = self.store.note_count()
        if not rows:
            self.notes_summary_var.set("No notes yet. Capture the clipboard or open notes to start.")
        else:
            latest = str(rows[0]["title"])
            self.notes_summary_var.set(f"{count} note{'s' if count != 1 else ''}. Latest: {latest}")

        if self.notes_frame is None:
            return
        for child in self.notes_frame.winfo_children():
            child.destroy()
        if not rows:
            self.label(self.notes_frame, "Clipboard captures and notes will appear here.", color=self.MUTED).pack(anchor="w")
            return
        for row in rows:
            stamp = time.strftime("%a %H:%M", time.localtime(int(row["updated_at"])))
            text = f"{row['title']}  -  {stamp}"
            button = self.action_button(self.notes_frame, text, lambda note_id=int(row["id"]): self.open_notes(note_id))
            button.configure(anchor="w", justify="left")
            button.pack(fill="x", pady=3)

    def refresh_weather(self) -> None:
        if self.weather_busy:
            return
        self.env = load_assistant_env()
        location = self.env.get("FAUXNIX_WEATHER_LOCATION", "").strip()
        if not location:
            self.weather_var.set("Weather needs setup")
            return

        self.weather_busy = True
        self.weather_var.set("Checking weather...")
        thread = threading.Thread(target=self.fetch_weather, args=(location,), daemon=True)
        thread.start()

    def fetch_weather(self, location: str) -> None:
        try:
            encoded = urllib.parse.quote(location)
            url = f"https://wttr.in/{encoded}?format=%l:+%c+%t,+%w,+%h"
            request = urllib.request.Request(url, headers={"User-Agent": "fennix-desktop"})
            with urllib.request.urlopen(request, timeout=5) as response:
                text = response.read(240).decode("utf-8", errors="replace").strip()
            if not text:
                text = "Weather unavailable"
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            text = f"Weather unavailable\n{exc}"

        def finish() -> None:
            self.weather_busy = False
            self.weather_var.set(text)

        self.root.after(0, finish)

    def launch(self, command: list[str], label: str) -> None:
        try:
            launch_detached(command)
            self.status_var.set(f"Opened {label}")
        except OSError as exc:
            self.status_var.set(f"{label}: {exc}")

    def open_apps(self) -> None:
        self.launch(["rofi", "-show", "drun"], "Apps")

    def open_thread(self, name: str) -> None:
        self.launch(["fauxnix-thread", name], name)

    def open_chat(self) -> None:
        self.launch(["fennix-gui"], "Fennix Chat")

    def open_session(self, conversation_id: int) -> None:
        self.store.set_state("last_opened_session", str(conversation_id))
        self.launch(["fennix-gui", "--conversation", str(conversation_id)], "Fennix session")

    def open_notes(self, note_id: int | None = None) -> None:
        FennixNotesWindow(self.root, self.store, note_id)
        self.status_var.set("Opened notes")

    def capture_clipboard_note(self) -> None:
        content = read_system_clipboard(self.root).strip()
        if not content:
            self.status_var.set("Clipboard empty")
            return
        note_id = self.store.add_clipboard_text(content, "dashboard")
        self.refresh_notes()
        self.open_notes(note_id)
        self.status_var.set("Captured clipboard")


class FennixLauncher:
    TAB_SIZE = 1
    PANEL_WIDTH = 420
    PANEL_HEIGHT = 520

    def __init__(self, root: tk.Tk, store: FennixStore, routes: dict[str, Route]) -> None:
        self.root = root
        self.store = store
        self.routes = routes
        self.lock_fd = acquire_runtime_lock("fennix-launcher")
        if self.lock_fd is False:
            root.after(0, root.destroy)
            return
        self.command_started_after = time.time() - 2.0
        self.current_conversation = store.ensure_conversation()
        self.outbox: queue.Queue[tuple[str, str]] = queue.Queue()
        self.busy = False
        self.drag_start: tuple[int, int, int, int] | None = None
        self.drag_moved = False
        self.slide_job: str | None = None

        self.edge = "top"
        self.edge_position = 0
        self.store.set_state("launcher_edge", self.edge)
        self.store.set_state("launcher_position", str(self.edge_position))
        self.theme = store.get_state("launcher_theme", "dark") or "dark"
        self.panel_open = store.get_state("launcher_open", "1") != "0"

        self.route_var = tk.StringVar(value="local")
        self.status_var = tk.StringVar(value="Ready")
        self.telemetry_var = tk.StringVar(value=system_telemetry())
        self.theme_var = tk.StringVar(value=self.theme)
        self.clipboard_preview: tk.Text | None = None

        root.title("Fennix Launcher")
        root.withdraw()
        root.resizable(False, False)
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        try:
            root.wm_attributes("-type", "toolbar")
        except tk.TclError:
            pass
        root.protocol("WM_DELETE_WINDOW", self.hide_panel)

        self.canvas = tk.Canvas(root, width=self.TAB_SIZE, height=self.TAB_SIZE, highlightthickness=0)

        self.panel = tk.Toplevel(root)
        self.panel.withdraw()
        self.panel.title("Fennix Panel")
        self.panel.resizable(False, False)
        self.panel.overrideredirect(True)
        self.panel.attributes("-topmost", True)
        try:
            self.panel.wm_attributes("-type", "utility")
        except tk.TclError:
            pass
        self.panel.protocol("WM_DELETE_WINDOW", self.hide_panel)
        self.panel.bind("<Escape>", lambda _event: self.hide_panel())

        self.build_panel()
        self.apply_theme()
        self.position_windows()
        if self.panel_open:
            self.show_panel()
        else:
            self.panel.withdraw()

        self.refresh_chat()
        self.root.after(500, self.update_telemetry)
        self.root.after(80, self.drain_outbox)
        self.root.after(120, self.poll_launcher_command)

    def palette(self) -> dict[str, str]:
        if self.theme == "light":
            return {
                "bg": "#f7f7f3",
                "panel": "#ffffff",
                "fg": "#111111",
                "muted": "#5d6269",
                "field": "#f0f1f2",
                "accent": "#ff7800",
                "cyan": "#008aa0",
                "user": "#154b8b",
                "assistant": "#126044",
            }
        return {
            "bg": "#0b0b0b",
            "panel": "#141414",
            "fg": "#eeeeee",
            "muted": "#a3a7ad",
            "field": "#1f2124",
            "accent": "#ff7800",
            "cyan": "#00c8ff",
            "user": "#8fbeff",
            "assistant": "#71e6b2",
        }

    def build_panel(self) -> None:
        self.panel.columnconfigure(0, weight=1)
        self.panel.rowconfigure(5, weight=1)

        header = ttk.Frame(self.panel, padding=(12, 10, 12, 6), style="Launcher.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        self.header_mark = tk.Canvas(header, width=42, height=34, highlightthickness=0)
        self.header_mark.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 10))
        ttk.Label(header, text="Fennix", style="LauncherTitle.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(header, textvariable=self.telemetry_var, style="LauncherMuted.TLabel").grid(row=1, column=1, sticky="w")
        ttk.Button(header, text="Theme", command=self.toggle_theme).grid(row=0, column=2, padx=(8, 0))
        ttk.Button(header, text="Hide", command=self.hide_panel).grid(row=1, column=2, padx=(8, 0), pady=(4, 0))

        routes = ttk.Frame(self.panel, padding=(12, 0, 12, 6), style="Launcher.TFrame")
        routes.grid(row=1, column=0, sticky="ew")
        ttk.Label(routes, text="Route", style="LauncherMuted.TLabel").pack(side="left")
        ttk.Radiobutton(routes, text="Local", variable=self.route_var, value="local").pack(side="left", padx=(10, 0))
        ttk.Radiobutton(routes, text="Nexus", variable=self.route_var, value="parent").pack(side="left", padx=(8, 0))
        ttk.Label(routes, textvariable=self.status_var, style="LauncherMuted.TLabel").pack(side="right")

        actions = ttk.Frame(self.panel, padding=(12, 0, 12, 8), style="Launcher.TFrame")
        actions.grid(row=2, column=0, sticky="ew")
        for label, command in (
            ("Fennix", lambda: self.launch_thread("fennix")),
            ("Web", lambda: self.launch_thread("web")),
            ("Fauxnix", lambda: self.launch_thread("fauxnix")),
            ("Cowriter", lambda: self.launch_thread("cowriter")),
            ("Terminal", lambda: self.launch_thread("terminal")),
            ("Apps", self.launch_apps),
        ):
            ttk.Button(actions, text=label, command=command).pack(side="left", padx=(0, 6))

        tools = ttk.Frame(self.panel, padding=(12, 0, 12, 8), style="Launcher.TFrame")
        tools.grid(row=3, column=0, sticky="ew")
        ttk.Button(tools, text="Full Chat", command=self.open_full_chat).pack(side="left", padx=(0, 6))
        ttk.Button(tools, text="Fauxdex", command=self.open_fauxdex_thread).pack(side="left", padx=(0, 6))
        ttk.Button(tools, text="Workspace", command=self.open_workspace_chat).pack(side="left", padx=(0, 6))
        ttk.Button(tools, text="Notes", command=self.open_notes).pack(side="left", padx=(0, 6))
        ttk.Button(tools, text="New", command=self.new_chat).pack(side="right")

        clipboard = ttk.Frame(self.panel, padding=(12, 0, 12, 8), style="Launcher.TFrame")
        clipboard.grid(row=4, column=0, sticky="ew")
        clipboard.columnconfigure(0, weight=1)
        header = ttk.Frame(clipboard, style="Launcher.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        ttk.Label(header, text="Clipboard", style="LauncherMuted.TLabel").pack(side="left")
        ttk.Button(header, text="Refresh", command=self.refresh_clipboard_preview).pack(side="right", padx=(6, 0))
        ttk.Button(header, text="Save", command=self.save_clipboard_note).pack(side="right")
        self.clipboard_preview = tk.Text(clipboard, height=3, wrap="word", padx=8, pady=6, borderwidth=0)
        self.clipboard_preview.grid(row=1, column=0, sticky="ew")

        chat_frame = ttk.Frame(self.panel, padding=(12, 0, 12, 8), style="Launcher.TFrame")
        chat_frame.grid(row=5, column=0, sticky="nsew")
        chat_frame.columnconfigure(0, weight=1)
        chat_frame.rowconfigure(0, weight=1)
        self.chat = tk.Text(chat_frame, wrap="word", state="disabled", height=12, padx=10, pady=10, borderwidth=0)
        chat_scroll = ttk.Scrollbar(chat_frame, orient="vertical", command=self.chat.yview)
        self.chat.configure(yscrollcommand=chat_scroll.set)
        self.chat.grid(row=0, column=0, sticky="nsew")
        chat_scroll.grid(row=0, column=1, sticky="ns")

        input_frame = ttk.Frame(self.panel, padding=(12, 0, 12, 12), style="Launcher.TFrame")
        input_frame.grid(row=6, column=0, sticky="ew")
        input_frame.columnconfigure(0, weight=1)
        self.input = tk.Text(input_frame, height=3, wrap="word", borderwidth=0)
        self.input.grid(row=0, column=0, sticky="ew")
        self.input.bind("<Control-Return>", lambda _event: self.send())
        ttk.Button(input_frame, text="Send", command=self.send).grid(row=0, column=1, sticky="ns", padx=(8, 0))

    def apply_theme(self) -> None:
        colors = self.palette()
        self.root.configure(bg=colors["bg"])
        self.panel.configure(bg=colors["panel"])
        style = ttk.Style()
        style.configure("Launcher.TFrame", background=colors["panel"])
        style.configure("LauncherTitle.TLabel", background=colors["panel"], foreground=colors["fg"], font=("TkDefaultFont", 13, "bold"))
        style.configure("LauncherMuted.TLabel", background=colors["panel"], foreground=colors["muted"])
        style.configure("TButton", padding=(8, 4))

        self.canvas.configure(bg=colors["bg"])
        self.header_mark.configure(bg=colors["panel"])
        self.draw_mark(self.header_mark, 42, 34)
        self.chat.configure(bg=colors["field"], fg=colors["fg"], insertbackground=colors["fg"])
        self.input.configure(bg=colors["field"], fg=colors["fg"], insertbackground=colors["fg"])
        if self.clipboard_preview is not None:
            self.clipboard_preview.configure(bg=colors["field"], fg=colors["fg"], insertbackground=colors["fg"])
        self.chat.tag_configure("user", foreground=colors["user"], spacing1=6, spacing3=6)
        self.chat.tag_configure("assistant", foreground=colors["assistant"], spacing1=6, spacing3=6)
        self.chat.tag_configure("system", foreground=colors["muted"], spacing1=6, spacing3=6)

    def draw_mark(self, canvas: tk.Canvas, width: int, height: int) -> None:
        colors = self.palette()
        canvas.delete("all")
        scale_x = width / 42
        scale_y = height / 34

        def point(x: int, y: int) -> tuple[int, int]:
            return int(x * scale_x), int(y * scale_y)

        lines = [
            (4, 4, 16, 23, 21, 17, 26, 23, 38, 4),
            (16, 23, 20, 31, 21, 18, 22, 31, 26, 23),
            (12, 17, 18, 21),
            (30, 17, 24, 21),
        ]
        for raw in lines:
            coords: list[int] = []
            for index in range(0, len(raw), 2):
                coords.extend(point(raw[index], raw[index + 1]))
            canvas.create_line(*coords, width=max(3, int(width / 16)), fill=colors["accent"], joinstyle=tk.MITER)
        canvas.create_oval(3, 3, width - 3, height - 3, outline=colors["cyan"], width=1)

    def screen_size(self) -> tuple[int, int]:
        self.root.update_idletasks()
        return self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def geometry_string(self, width: int, height: int, x: int, y: int) -> str:
        sw, sh = self.screen_size()
        if x < 0:
            x_token = f"-{max(sw - width - x, 0)}"
        else:
            x_token = f"+{x}"
        if y < 0:
            y_token = f"-{max(sh - height - y, 0)}"
        else:
            y_token = f"+{y}"
        return f"{width}x{height}{x_token}{y_token}"

    def set_window_geometry(self, window: tk.Toplevel | tk.Tk, width: int, height: int, x: int, y: int) -> None:
        window.geometry(self.geometry_string(width, height, x, y))

    def tab_rect(self) -> tuple[int, int, int, int]:
        return self.TAB_SIZE, self.TAB_SIZE, -2, -2

    def panel_rect(self, opened: bool) -> tuple[int, int, int, int]:
        sw, sh = self.screen_size()
        if self.edge == "left":
            width, height = self.PANEL_WIDTH, sh
            return width, height, (0 if opened else -width), 0
        elif self.edge == "right":
            width, height = self.PANEL_WIDTH, sh
            return width, height, (max(sw - width, 0) if opened else sw), 0
        elif self.edge == "top":
            width, height = sw, self.PANEL_HEIGHT
            return width, height, 0, (0 if opened else -height)

        width, height = sw, self.PANEL_HEIGHT
        return width, height, 0, (max(sh - height, 0) if opened else sh)

    def position_windows(self) -> None:
        self.set_window_geometry(self.root, *self.tab_rect())
        self.root.withdraw()
        if self.panel_open and not self.slide_job:
            self.set_window_geometry(self.panel, *self.panel_rect(True))

    def cancel_slide(self) -> None:
        if self.slide_job:
            try:
                self.root.after_cancel(self.slide_job)
            except tk.TclError:
                pass
            self.slide_job = None

    def animate_panel(
        self,
        start: tuple[int, int, int, int],
        end: tuple[int, int, int, int],
        on_done: callable | None = None,
    ) -> None:
        self.cancel_slide()
        steps = 12
        width, height, sx, sy = start
        _end_width, _end_height, ex, ey = end

        def ease(value: float) -> float:
            return 1 - (1 - value) * (1 - value)

        def step(index: int = 0) -> None:
            t = ease(index / steps)
            x = round(sx + (ex - sx) * t)
            y = round(sy + (ey - sy) * t)
            self.set_window_geometry(self.panel, width, height, x, y)
            self.panel.lift()
            if index >= steps:
                self.slide_job = None
                self.set_window_geometry(self.panel, *end)
                if on_done:
                    on_done()
                return
            self.slide_job = self.root.after(14, lambda: step(index + 1))

        step()

    def start_drag(self, event: tk.Event) -> None:
        self.drag_start = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())
        self.drag_moved = False

    def drag_tab(self, event: tk.Event) -> None:
        if self.drag_start is None:
            return
        sx, sy, wx, wy = self.drag_start
        dx = event.x_root - sx
        dy = event.y_root - sy
        if abs(dx) + abs(dy) > 6:
            self.drag_moved = True
        self.root.geometry(f"{self.TAB_SIZE}x{self.TAB_SIZE}+{wx + dx}+{wy + dy}")

    def release_tab(self, _event: tk.Event) -> None:
        if self.drag_start is None:
            return
        if not self.drag_moved:
            self.toggle_panel()
            self.drag_start = None
            return

        sw, sh = self.screen_size()
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        distances = {
            "left": x,
            "right": sw - (x + self.TAB_SIZE),
            "top": y,
            "bottom": sh - (y + self.TAB_SIZE),
        }
        self.edge = min(distances, key=distances.get)
        self.edge_position = y if self.edge in {"left", "right"} else x
        self.store.set_state("launcher_edge", self.edge)
        self.store.set_state("launcher_position", str(max(0, self.edge_position)))
        self.position_windows()
        if self.panel_open:
            self.show_panel()
        self.drag_start = None

    def toggle_panel(self) -> None:
        if self.panel_open:
            self.hide_panel()
        else:
            self.show_panel()

    def poll_launcher_command(self) -> None:
        try:
            stat = LAUNCHER_COMMAND_PATH.stat()
            if stat.st_mtime < self.command_started_after:
                LAUNCHER_COMMAND_PATH.unlink(missing_ok=True)
            else:
                command = LAUNCHER_COMMAND_PATH.read_text(encoding="utf-8").strip().split(" ", 1)[0]
                LAUNCHER_COMMAND_PATH.unlink(missing_ok=True)
                if command == "show":
                    self.show_panel()
                elif command == "hide":
                    self.hide_panel()
                else:
                    self.toggle_panel()
        except FileNotFoundError:
            pass
        except OSError as exc:
            log(f"launcher command poll failed: {exc!r}")
        self.root.after(120, self.poll_launcher_command)

    def show_panel(self) -> None:
        self.cancel_slide()
        self.panel_open = True
        self.store.set_state("launcher_open", "1")
        self.position_windows()
        start = self.panel_rect(False)
        end = self.panel_rect(True)
        self.set_window_geometry(self.panel, *start)
        self.panel.attributes("-topmost", True)
        self.panel.deiconify()
        self.panel.lift()
        self.refresh_clipboard_preview()
        self.animate_panel(start, end, on_done=self.input.focus_set)
        self.input.focus_set()

    def hide_panel(self) -> None:
        self.cancel_slide()
        self.panel_open = False
        self.store.set_state("launcher_open", "0")
        start = self.panel_rect(True)
        end = self.panel_rect(False)
        self.animate_panel(start, end, on_done=self.panel.withdraw)

    def toggle_theme(self) -> None:
        self.theme = "light" if self.theme == "dark" else "dark"
        self.theme_var.set(self.theme)
        self.store.set_state("launcher_theme", self.theme)
        self.apply_theme()
        self.refresh_chat()

    def update_telemetry(self) -> None:
        self.telemetry_var.set(system_telemetry())
        self.root.after(3000, self.update_telemetry)

    def launch_thread(self, name: str) -> None:
        try:
            launch_detached(["fauxnix-thread", name])
            self.status_var.set(f"Opened {name}")
        except OSError as exc:
            self.status_var.set(str(exc))

    def launch_apps(self) -> None:
        try:
            launch_detached(["rofi", "-show", "drun"])
            self.status_var.set("Apps")
        except OSError as exc:
            self.status_var.set(str(exc))

    def open_notes(self) -> None:
        FennixNotesWindow(self.panel, self.store)
        self.status_var.set("Opened notes")

    def refresh_clipboard_preview(self) -> None:
        if self.clipboard_preview is None:
            return
        text = read_system_clipboard(self.panel)
        self.clipboard_preview.delete("1.0", tk.END)
        self.clipboard_preview.insert(tk.END, clamp_text(text, 600) if text else "")
        self.status_var.set("Clipboard refreshed" if text else "Clipboard empty")

    def save_clipboard_note(self) -> None:
        if self.clipboard_preview is None:
            return
        content = read_system_clipboard(self.panel).strip()
        if not content:
            content = self.clipboard_preview.get("1.0", tk.END).strip()
        if not content:
            self.refresh_clipboard_preview()
            content = read_system_clipboard(self.panel).strip() or self.clipboard_preview.get("1.0", tk.END).strip()
        if not content:
            self.status_var.set("Clipboard empty")
            return
        self.store.add_clipboard_text(content, "launcher")
        self.status_var.set("Saved clipboard note")

    def open_full_chat(self) -> None:
        try:
            launch_detached(["fennix-gui"])
            self.status_var.set("Opened full chat")
        except OSError as exc:
            self.status_var.set(str(exc))

    def open_fauxdex_thread(self) -> None:
        try:
            launch_detached(["fauxnix-thread", "fauxdex"])
            self.status_var.set("Opened Fauxdex")
        except OSError as exc:
            self.status_var.set(str(exc))

    def open_workspace_chat(self) -> None:
        self.input.insert(tk.END, "Use Fauxdex to observe the active workspace and propose the next safe step.\n")
        self.input.focus_set()

    def new_chat(self) -> None:
        if self.busy:
            return
        self.current_conversation = self.store.create_conversation()
        self.refresh_chat()
        self.status_var.set("New chat")

    def refresh_chat(self) -> None:
        self.chat.configure(state="normal")
        self.chat.delete("1.0", tk.END)
        for row in self.store.messages(self.current_conversation, limit=18):
            self.append_chat(row["role"], row["content"], row["route"], persist=False)
        self.chat.configure(state="disabled")
        self.chat.see(tk.END)

    def append_chat(self, role: str, content: str, route: str = "", persist: bool = False) -> None:
        if persist:
            self.store.add_message(self.current_conversation, role, route, content)
        label = role.capitalize()
        if route:
            label += f" [{route}]"
        self.chat.configure(state="normal")
        self.chat.insert(tk.END, f"{label}: ", role)
        self.chat.insert(tk.END, content.rstrip() + "\n\n", role)
        self.chat.configure(state="disabled")
        self.chat.see(tk.END)

    def send(self) -> None:
        if self.busy:
            return
        user_text = self.input.get("1.0", tk.END).strip()
        if not user_text:
            return

        route_name = self.route_var.get()
        route = self.routes[route_name]
        if route_name == "parent" and not route.base_url:
            self.status_var.set("Nexus route is not configured")
            return

        self.input.delete("1.0", tk.END)
        self.append_chat("user", user_text, route_name, persist=True)

        local_action = local_action_for_text(user_text, self.store)
        if local_action:
            self.append_chat("assistant", local_action.response, "local-action", persist=True)
            self.refresh_chat()
            error = execute_local_action(local_action, self.root)
            self.status_var.set(error or local_action.status)
            if error:
                self.append_chat("system", f"Local action failed: {error}", "local-action", persist=True)
            return

        self.status_var.set(f"Thinking via {route_name}...")
        self.busy = True
        prompt = build_prompt(self.store, self.current_conversation, user_text)
        thread = threading.Thread(target=self.generate_worker, args=(route, prompt, route_name), daemon=True)
        thread.start()

    def generate_worker(self, route: Route, prompt: str, route_name: str) -> None:
        try:
            chunks = []
            for chunk in ollama_generate(route, prompt):
                chunks.append(chunk)
                self.outbox.put(("chunk", chunk))
            self.outbox.put(("done", route_name + "\n" + "".join(chunks)))
        except (OSError, urllib.error.URLError, RuntimeError, json.JSONDecodeError) as exc:
            self.outbox.put(("error", str(exc)))

    def drain_outbox(self) -> None:
        try:
            while True:
                kind, payload = self.outbox.get_nowait()
                if kind == "chunk":
                    self.chat.configure(state="normal")
                    if not getattr(self, "_streaming", False):
                        self._streaming = True
                        self.chat.insert(tk.END, f"Assistant [{self.route_var.get()}]: ", "assistant")
                    self.chat.insert(tk.END, payload, "assistant")
                    self.chat.configure(state="disabled")
                    self.chat.see(tk.END)
                elif kind == "done":
                    route_name, content = payload.split("\n", 1)
                    self._streaming = False
                    self.chat.configure(state="normal")
                    self.chat.insert(tk.END, "\n\n", "assistant")
                    self.chat.configure(state="disabled")
                    self.store.add_message(self.current_conversation, "assistant", route_name, content)
                    self.refresh_chat()
                    self.status_var.set("Ready")
                    self.busy = False
                elif kind == "error":
                    self._streaming = False
                    self.store.add_message(self.current_conversation, "system", "system", f"Error: {payload}")
                    self.refresh_chat()
                    self.status_var.set("Error")
                    self.busy = False
        except queue.Empty:
            pass
        self.root.after(80, self.drain_outbox)


def self_test() -> int:
    routes = load_routes()
    store = FennixStore(DB_PATH)
    cid = store.ensure_conversation()
    print(f"database={DB_PATH}")
    print(f"conversation={cid}")
    for route in routes.values():
        print(f"{route.name}={route.base_url} model={route.model}")
    print(f"cowriter={load_cowriter_workspace()}")
    print(f"workspace={load_workspace_root()}")
    print(f"active_project={store.get_state('active_project')}")
    print(f"current_goal={store.get_state('current_goal')}")
    print(f"memories={len(store.memories())}")
    print(clamp_text(assistant_runtime_context(store, "status system git threads network"), 2600))
    return 0


def prompt_from_args(parts: list[str]) -> str:
    prompt = " ".join(parts).strip()
    if prompt:
        return prompt
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    return ""


def ask_once(user_text: str, route_name: str = "local") -> int:
    if not user_text.strip():
        print("No prompt provided.", file=sys.stderr)
        return 2

    store = FennixStore(DB_PATH)
    conversation_id = store.ensure_conversation()
    store.add_message(conversation_id, "user", route_name, user_text)

    local_action = local_action_for_text(user_text, store)
    if local_action:
        print(local_action.response)
        error = execute_local_action(local_action)
        store.add_message(conversation_id, "assistant", "local-action", local_action.response)
        if error:
            print(f"Local action failed: {error}", file=sys.stderr)
            store.add_message(conversation_id, "system", "local-action", f"Local action failed: {error}")
            return 1
        return 0

    routes = load_routes()
    route = routes.get(route_name)
    if route is None:
        print(f"Unknown route: {route_name}", file=sys.stderr)
        return 2
    if not route.base_url or not route.model:
        print(f"{route_name} route is not configured", file=sys.stderr)
        return 2

    prompt = build_prompt(store, conversation_id, user_text)
    chunks: list[str] = []
    try:
        for chunk in ollama_generate(route, prompt):
            chunks.append(chunk)
            print(chunk, end="", flush=True)
    except (OSError, urllib.error.URLError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"\nFennix error: {exc}", file=sys.stderr)
        store.add_message(conversation_id, "system", route_name, f"Error: {exc}")
        return 1

    response = "".join(chunks).strip()
    if response:
        print()
        store.add_message(conversation_id, "assistant", route_name, response)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Fennix Tkinter assistant")
    parser.add_argument("--desktop", action="store_true", help="start the FauxnixOS desktop dashboard")
    parser.add_argument("--launcher", action="store_true", help="start the FauxnixOS launcher sidebar")
    parser.add_argument("--launcher-toggle", action="store_true", help="toggle the FauxnixOS launcher sidebar")
    parser.add_argument("--notes", action="store_true", help="open the Fennix notes and clipboard window")
    parser.add_argument("--capture-clipboard", action="store_true", help="save the current clipboard as a note")
    parser.add_argument("--conversation", type=int, help="open a specific conversation id")
    parser.add_argument("--self-test", action="store_true", help="initialize state and print route info")
    parser.add_argument("--route", choices=("local", "parent"), default="local", help="model route for --ask")
    parser.add_argument("--ask", nargs=argparse.REMAINDER, help="ask Fennix without opening the GUI")
    parser.add_argument("--print-prompt", nargs=argparse.REMAINDER, help="print the prompt that would be sent")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if args.launcher_toggle:
        request_launcher_toggle()
        return 0
    if args.capture_clipboard:
        store = FennixStore(DB_PATH)
        content = read_system_clipboard().strip()
        if not content:
            print("Clipboard empty")
            return 1
        note_id = store.add_clipboard_text(content, "cli")
        print(f"Captured clipboard note {note_id}")
        return 0
    if args.print_prompt is not None:
        user_text = prompt_from_args(args.print_prompt)
        store = FennixStore(DB_PATH)
        cid = store.ensure_conversation()
        print(build_prompt(store, cid, user_text))
        return 0
    if args.ask is not None:
        return ask_once(prompt_from_args(args.ask), args.route)

    try:
        store = FennixStore(DB_PATH)
        routes = load_routes()
        root = tk.Tk()
        ttk.Style().theme_use("clam")
        if args.desktop:
            FennixDesktop(root, store, routes)
        elif args.launcher:
            FennixLauncher(root, store, routes)
        elif args.notes:
            root.withdraw()
            FennixNotesWindow(root, store)
        else:
            FennixApp(root, store, routes, initial_conversation=args.conversation)
        root.mainloop()
        return 0
    except Exception as exc:  # noqa: BLE001 - GUI entrypoint should show failures.
        log(f"fatal: {exc!r}")
        try:
            messagebox.showerror(APP_NAME, str(exc))
        except Exception:
            print(f"{APP_NAME}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
