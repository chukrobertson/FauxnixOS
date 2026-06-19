#!/usr/bin/env python3
"""Fauxdex: bounded workspace loop for Fennix.

This is the first local Codex-like layer for FauxnixOS. It is intentionally
small and read-heavy: observe the workspace, track task state, and prepare
context for Fennix without exposing an arbitrary shell endpoint.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


CONFIG_PATH = Path("/etc/fauxnix/assistant.env")
DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
DB_PATH = DATA_HOME / "fennix" / "fennix.sqlite3"


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


ENV = parse_env_file(CONFIG_PATH)
WORKSPACE_ROOT = Path(ENV.get("FAUXNIX_WORKSPACE_ROOT", "/home/chvk/Fauxnix")).expanduser()
THREADS_DIR = Path(ENV.get("FAUXNIX_THREADS_DIR", str(WORKSPACE_ROOT / "Threads"))).expanduser()
REPOS_ROOT = Path(ENV.get("FAUXNIX_REPOS_ROOT", str(WORKSPACE_ROOT / "Repos"))).expanduser()


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS task_state (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL,
          updated_at INTEGER NOT NULL
        )
        """
    )
    db.commit()
    return db


def get_state(key: str, default: str = "") -> str:
    with connect_db() as db:
        row = db.execute("SELECT value FROM task_state WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else default


def set_state(key: str, value: str) -> None:
    now = int(time.time())
    with connect_db() as db:
        db.execute(
            """
            INSERT INTO task_state (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        db.commit()


def clamp_text(value: str, limit: int = 1800) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: max(limit - 24, 0)].rstrip() + "\n[truncated]"


def bounded_path(root: Path, candidate: Path) -> Path:
    root_resolved = root.resolve()
    path = candidate.resolve()
    try:
        path.relative_to(root_resolved)
    except ValueError as exc:
        raise RuntimeError(f"path escapes workspace root: {path}") from exc
    return path


def workspace_projects() -> list[Path]:
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
    return sorted(
        [path for path in WORKSPACE_ROOT.iterdir() if path.is_dir() and not path.name.startswith(".")],
        key=lambda path: path.name.lower(),
    )


def workspace_project(name: str = "") -> Path:
    requested = name.strip() or get_state("active_project")
    if requested:
        return bounded_path(WORKSPACE_ROOT, WORKSPACE_ROOT / requested)
    projects = workspace_projects()
    return projects[0] if projects else WORKSPACE_ROOT


def skip_path(path: Path) -> bool:
    ignored = {".git", "__pycache__", ".direnv", ".venv", "node_modules", "result"}
    return any(part in ignored or part.startswith(".cache") for part in path.parts)


def command_output(command: list[str], timeout: int = 6, limit: int = 1600) -> tuple[int, str]:
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


def git_status(path: Path, limit: int = 1200) -> str:
    if not (path / ".git").exists():
        return "No .git directory."
    code, output = command_output(["git", "-C", str(path), "status", "--short", "--branch"], limit=limit)
    if code != 0:
        return output or "Git status failed."
    return output or "Git status is clean."


def repo_line(label: str, path: Path) -> str:
    if not path.exists():
        return f"- {label}: missing at {path}"
    status = git_status(path, limit=500).replace("\n", "; ")
    _code, last = command_output(["git", "-C", str(path), "log", "-1", "--oneline"], timeout=3, limit=160)
    suffix = f"; last {last}" if last else ""
    return f"- {label}: {status}{suffix}"


def git_spine() -> str:
    return "\n".join(
        [
            "Git spine:",
            repo_line("admin", REPOS_ROOT / "admin"),
            repo_line("home", REPOS_ROOT / "home"),
            repo_line("threads", THREADS_DIR),
        ]
    )


def workspace_tree(project: Path, limit: int = 120) -> str:
    project = project.resolve()
    lines = [f"{project.name}/"]
    count = 0
    for path in sorted(project.rglob("*"), key=lambda item: str(item).lower()):
        rel = path.relative_to(project)
        if skip_path(rel):
            continue
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


def project_index(project: Path) -> str:
    file_count = 0
    dir_count = 0
    recent: list[tuple[float, Path, int]] = []
    for path in project.rglob("*"):
        rel = path.relative_to(project)
        if skip_path(rel):
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
        git_status(project),
        "",
        "Recent files:",
    ]
    if recent:
        for mtime, rel, size in recent[:12]:
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
            lines.append(f"- {rel} ({size} bytes, {stamp})")
    else:
        lines.append("- none")
    lines.extend(["", "Tree:", workspace_tree(project)])
    return "\n".join(lines)


def thread_summary(limit: int = 8) -> str:
    if not THREADS_DIR.exists():
        return f"Threads: {THREADS_DIR} missing"
    entries = []
    for path in sorted(THREADS_DIR.iterdir(), key=lambda item: item.name.lower()):
        if path.is_dir() and not path.name.startswith("."):
            entries.append(f"- {path.name}")
        if len(entries) >= limit:
            break
    return "Threads:\n" + ("\n".join(entries) if entries else "- none yet")


def observe(project_name: str = "") -> str:
    project = workspace_project(project_name)
    active = get_state("active_project") or project.name
    goal = get_state("current_goal") or "unset"
    projects = ", ".join(path.name for path in workspace_projects()[:12]) or "none"
    lines = [
        "Fauxdex Observe",
        "===============",
        "",
        f"Workspace root: {WORKSPACE_ROOT}",
        f"Projects: {projects}",
        f"Active project: {active}",
        f"Current goal: {goal}",
        "",
        git_spine(),
        "",
        thread_summary(),
        "",
        project_index(project),
    ]
    set_state("workspace_indexed_at", f"{project.name} at {time.strftime('%Y-%m-%d %H:%M:%S %z')}")
    set_state("workspace_index", "\n".join(lines)[:12000])
    return "\n".join(lines)


def plan_text(request: str = "", project_name: str = "") -> str:
    project = workspace_project(project_name)
    if request:
        set_state("current_goal", request)
    goal = request or get_state("current_goal") or "No task set yet."
    return "\n".join(
        [
            "Fauxdex Plan",
            "============",
            "",
            f"Project: {project.name}",
            f"Goal: {goal}",
            "",
            "Loop:",
            "1. Observe current workspace, git status, and task state.",
            "2. Read/search only the files needed for the task.",
            "3. Propose the smallest patch that solves the request.",
            "4. Ask before applying destructive or administrator-level changes.",
            "5. Build, test, or run focused checks.",
            "6. Snapshot useful state through fauxnix-git.",
            "",
            "Boundaries:",
            "- No arbitrary shell command endpoint.",
            "- Prefer read-only inspection first.",
            "- Use Nexus for heavy reasoning or broad code changes.",
        ]
    )


def start_text(request: str = "", project_name: str = "") -> str:
    project = workspace_project(project_name)
    if request:
        set_state("current_goal", request)
    goal = request or get_state("current_goal") or "Pick a bounded workspace task."
    return "\n".join(
        [
            "Fennix Code",
            "===========",
            "",
            "A local OpenCode-style workspace loop for FauxnixOS.",
            "",
            f"Project: {project.name}",
            f"Goal: {goal}",
            "",
            "Start here:",
            f"1. fennix-code observe --project {project.name}",
            f"2. fennix-code plan --project {project.name} {goal}",
            f"3. fennix-code prompt --project {project.name} {goal}",
            "",
            "Current boundaries:",
            "- Read/search/observe/plan are implemented.",
            "- Edits are still proposed through Fennix, Nexus, or Codex.",
            "- Destructive or admin actions stay gated.",
            "- The next layer is a patch proposal/apply-review flow.",
        ]
    )


def prompt_text(request: str, project_name: str = "") -> str:
    return "\n".join(
        [
            "Use this Fauxdex context with Fennix or Nexus.",
            "",
            "CURRENT REQUEST:",
            request.strip() or get_state("current_goal") or "Observe the workspace and propose next steps.",
            "",
            observe(project_name),
            "",
            plan_text(request, project_name),
        ]
    )


def propose_text(request: str = "", project_name: str = "") -> str:
    project = workspace_project(project_name)
    if request:
        set_state("current_goal", request)
    goal = request or get_state("current_goal") or "No patch goal set yet."
    return "\n".join(
        [
            "Fennix Code Patch Proposal v0",
            "=============================",
            "",
            f"Project: {project.name}",
            f"Goal: {goal}",
            "",
            "Use this contract before any edit:",
            "",
            "1. Observe",
            "- Run `fennix-code observe --project {project}`.",
            "- Identify dirty git state and relevant files.",
            "",
            "2. Inspect",
            "- Read only the smallest set of files needed.",
            "- Search before guessing names, APIs, or config paths.",
            "",
            "3. Propose",
            "- List files to change.",
            "- Describe the exact behavior change.",
            "- Name risks, rollback path, and verification command.",
            "",
            "4. Gate",
            "- Ask for approval before applying patches.",
            "- Never perform destructive filesystem/admin actions silently.",
            "",
            "5. Verify",
            "- Run the narrowest useful check.",
            "- Summarize result and any remaining risk.",
        ]
    ).format(project=project.name)


def read_file(project_name: str, relative: str) -> str:
    project = workspace_project(project_name)
    path = bounded_path(project, project / relative)
    if not path.is_file():
        raise RuntimeError(f"not a file: {relative}")
    return path.read_bytes()[:65536].decode("utf-8", errors="replace")


def search_text(project_name: str, query: str, limit: int = 80) -> str:
    query = query.strip().lower()
    if not query:
        return "Search query is empty."
    project = workspace_project(project_name)
    matches: list[str] = []
    for path in sorted(project.rglob("*"), key=lambda item: str(item).lower()):
        if len(matches) >= limit:
            break
        rel = path.relative_to(project)
        if skip_path(rel) or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if query in line.lower():
                matches.append(f"{rel}:{number}: {line.strip()}")
                if len(matches) >= limit:
                    break
    return "\n".join(matches) if matches else "No matches."


def parse_project_arg(args: list[str]) -> tuple[str, str]:
    if args and args[0] == "--project":
        if len(args) < 2:
            raise RuntimeError("--project needs a project name")
        return args[1], " ".join(args[2:])
    return "", " ".join(args)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fauxdex bounded workspace loop")
    parser.add_argument("command", nargs="?", default="status")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    ns = parser.parse_args()

    try:
        command = ns.command
        if command in {"start", "open"}:
            project, request = parse_project_arg(ns.args)
            print(start_text(request, project))
        elif command in {"status", "observe", "index"}:
            project, _rest = parse_project_arg(ns.args)
            print(observe(project))
        elif command == "plan":
            project, request = parse_project_arg(ns.args)
            print(plan_text(request, project))
        elif command == "prompt":
            project, request = parse_project_arg(ns.args)
            print(prompt_text(request, project))
        elif command == "propose":
            project, request = parse_project_arg(ns.args)
            print(propose_text(request, project))
        elif command == "set-project":
            if not ns.args:
                raise RuntimeError("usage: fauxdex set-project <project>")
            project = workspace_project(ns.args[0])
            set_state("active_project", project.name)
            print(f"active_project={project.name}")
        elif command == "set-goal":
            goal = " ".join(ns.args).strip()
            set_state("current_goal", goal)
            print(f"current_goal={goal or 'unset'}")
        elif command == "threads":
            print(thread_summary(limit=40))
        elif command == "read":
            if len(ns.args) < 2:
                raise RuntimeError("usage: fauxdex read <project> <relative-path>")
            print(read_file(ns.args[0], ns.args[1]))
        elif command == "search":
            if len(ns.args) < 2:
                raise RuntimeError("usage: fauxdex search <project> <query>")
            print(search_text(ns.args[0], " ".join(ns.args[1:])))
        elif command in {"help", "-h", "--help"}:
            parser.print_help()
        else:
            raise RuntimeError(f"unknown command: {command}")
    except RuntimeError as exc:
        print(f"fauxdex: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
