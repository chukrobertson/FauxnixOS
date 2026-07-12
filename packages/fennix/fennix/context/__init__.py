from __future__ import annotations

import json
import time

from fennix.context.filesystem import (
    get_foreground_process, get_active_shell_context,
    get_recently_accessed_files, get_indexed_files_near,
)
from fennix.context.system import (
    get_system_resources, get_nixos_info, get_service_status,
    get_latest_context_snapshot, get_uptime,
)
from fennix.context.clipboard import (
    get_clipboard_context, get_current_clipboard,
)


def gather_context(include_system: bool = True, include_clipboard: bool = True, include_filesystem: bool = True) -> dict:
    ctx: dict[str, object] = {
        "gathered_ts": time.time(),
    }

    if include_filesystem:
        ctx["filesystem"] = _gather_filesystem_context()

    if include_clipboard:
        ctx["clipboard"] = _gather_clipboard_context_obj()

    if include_system:
        ctx["system"] = _gather_system_context()

    return ctx


def gather_lightweight_context() -> dict:
    ctx: dict[str, object] = {
        "gathered_ts": time.time(),
    }

    foreground = get_foreground_process()
    if foreground:
        ctx["active_process"] = foreground.get("process_name", "")
        ctx["active_window"] = foreground.get("window_title", "")

    clipboard = get_current_clipboard()
    if clipboard:
        ctx["clipboard"] = clipboard[:200]

    return ctx


def format_context_for_prompt(context: dict) -> str:
    parts: list[str] = []

    fs = context.get("filesystem")
    if isinstance(fs, dict):
        fs_str = _format_filesystem_context(fs)
        if fs_str:
            parts.append(fs_str)

    clip = context.get("clipboard")
    if isinstance(clip, dict):
        clip_text = clip.get("recent", "") or ""
        if clip_text:
            parts.append(f"### Recent Clipboard\n{clip_text}")
        current = clip.get("current", "") or ""
        if current:
            parts.append(f"### Current Clipboard\n{current}")

    sys_ctx = context.get("system")
    if isinstance(sys_ctx, dict):
        sys_str = _format_system_context(sys_ctx)
        if sys_str:
            parts.append(sys_str)

    active_proc = context.get("active_process")
    if active_proc:
        active_win = context.get("active_window", "")
        parts.append(f"User is currently using: {active_proc}" + (f" ({active_win})" if active_win else ""))

    clip_short = context.get("clipboard")
    if isinstance(clip_short, str):
        parts.append(f"Current clipboard: {clip_short}")

    return "\n\n".join(parts)


def _gather_filesystem_context() -> dict:
    shell = get_active_shell_context()
    result: dict = {}

    if shell:
        result["active_app"] = shell.get("process_name", "")
        result["active_window_title"] = shell.get("window_title", "")
        result["working_directory"] = shell.get("working_directory", "")
        open_files = shell.get("open_files") or []
        result["open_files"] = open_files[:15]

        cwd = shell.get("working_directory")
        if cwd:
            nearby = get_indexed_files_near(cwd, limit=5)
            if nearby:
                result["nearby_files"] = [
                    {"path": f["path"], "name": f["name"]}
                    for f in nearby
                ]

    recent = get_recently_accessed_files(limit=10)
    if recent:
        result["recently_ingested"] = [
            {"path": f["file_path"], "title": f["title"], "updated_ts": f["updated_ts"]}
            for f in recent
        ]

    return result


def _gather_clipboard_context_obj() -> dict:
    recent_text = get_clipboard_context(max_items=3, max_length=500)
    current = get_current_clipboard()
    return {
        "recent": recent_text,
        "current": current[:1000] if current else None,
    }


def _gather_system_context() -> dict:
    result: dict = {}

    nix = get_nixos_info()
    if nix:
        result["nixos"] = nix

    resources = get_system_resources()
    if resources:
        result["resources"] = resources

    services = get_service_status()
    if services:
        result["services"] = {k: v for k, v in services.items() if v != "unknown"}

    snapshot = get_latest_context_snapshot("system_state")
    if snapshot and not resources:
        result["cached_resources"] = snapshot

    uptime = get_uptime()
    if uptime is not None:
        result["uptime_seconds"] = uptime

    return result


def _format_filesystem_context(fs: dict) -> str:
    lines: list[str] = ["### Current Context"]

    if fs.get("active_app"):
        lines.append(f"Active app: {fs['active_app']}")

    if fs.get("active_window_title"):
        lines.append(f"Window title: {fs['active_window_title']}")

    if fs.get("working_directory"):
        lines.append(f"Working directory: {fs['working_directory']}")

    open_files = fs.get("open_files") or []
    if open_files:
        lines.append("\nOpen files:" + "".join(f"\n  - {f}" for f in open_files[:10]))

    nearby = fs.get("nearby_files") or []
    if nearby:
        lines.append("\nNearby indexed files:" + "".join(f"\n  - {f['path']}" for f in nearby[:5]))

    recent = fs.get("recently_ingested") or []
    if recent:
        lines.append("\nRecently ingested files:" + "".join(f"\n  - {f['title']} ({f['path']})" for f in recent[:5]))

    return "\n".join(lines)


def _format_system_context(sys_ctx: dict) -> str:
    lines: list[str] = ["### System State"]

    resources = sys_ctx.get("resources") or sys_ctx.get("cached_resources")
    if isinstance(resources, dict):
        cpu = resources.get("cpu_percent")
        mem = resources.get("memory_percent")
        disk = resources.get("disk_percent")
        if cpu is not None:
            lines.append(f"CPU: {cpu:.1f}%")
        if mem is not None:
            lines.append(f"Memory: {mem:.1f}%")
        if disk is not None:
            lines.append(f"Disk: {disk:.1f}%")

    uptime = sys_ctx.get("uptime_seconds")
    if uptime is not None:
        h = int(uptime // 3600)
        m = int((uptime % 3600) // 60)
        lines.append(f"Uptime: {h}h {m}m")

    services = sys_ctx.get("services")
    if isinstance(services, dict):
        active = [name for name, status in services.items() if status == "active"]
        inactive = [name for name, status in services.items() if status != "active"]
        if active:
            lines.append("Active services: " + ", ".join(active))
        if inactive:
            lines.append("Inactive services: " + ", ".join(inactive))

    return "\n".join(lines)
