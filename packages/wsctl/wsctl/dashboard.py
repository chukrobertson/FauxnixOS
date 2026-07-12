from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from wsctl import WSCI_WORKSPACE_ROOT
from wsctl.operations import list_workspaces


def run_dashboard(refresh: int = 5) -> None:
    print("\033[?1049h\033[2J\033[?25l", end="")
    try:
        while True:
            _render()
            time.sleep(refresh)
    except KeyboardInterrupt:
        pass
    finally:
        print("\033[?25h\033[?1049l", end="")


def _render() -> None:
    print("\033[H", end="")
    width = 80

    print("\033[1;36m" + "╔" + "═" * (width - 2) + "╗" + "\033[0m")
    print("\033[1;36m║\033[1;37m  FAUXNIX THREAD DASHBOARD" + " " * (width - 30) + "\033[1;36m║\033[0m")
    print("\033[1;36m" + "╠" + "═" * (width - 2) + "╣" + "\033[0m")

    _render_threads(width)
    _render_suggestions(width)
    _render_events(width)
    _render_help(width)

    print("\033[1;36m" + "╚" + "═" * (width - 2) + "╝" + "\033[0m")
    print(f"\033[90m  Refreshing every 5s · Press Ctrl+C to quit\033[0m")


def _render_threads(width: int) -> None:
    print("\033[1;36m║\033[1;33m  Threads" + " " * (width - 12) + "\033[1;36m║\033[0m")
    print("\033[1;36m║\033[0m  " + "─" * (width - 6) + "  \033[1;36m║\033[0m")

    threads = list_workspaces()
    if not threads:
        print("\033[1;36m║\033[0m  \033[90m  No threads found\033[0m" + " " * (width - 25) + "\033[1;36m║\033[0m")
    else:
        for t in threads:
            status_icon = "\033[1;32m●\033[0m" if t["status"] == "running" else "\033[1;30m○\033[0m"
            status = f"\033[1;32mrunning\033[0m" if t["status"] == "running" else "\033[90mstopped\033[0m"
            topics = ",".join(t["topics"][:2]) if t["topics"] else "-"
            parent = t["parent"] or "root"
            line = (
                f"  {status_icon} \033[1;37m{t['name']:<20}\033[0m "
                f"{status:<16} "
                f"\033[36m{t['profile']:<10}\033[0m "
                f"\033[33m{topics:<20}\033[0m "
                f"\033[90m← {parent}\033[0m"
            )
            print(f"\033[1;36m║\033[0m{line[:width-3]}\033[1;36m║\033[0m")

    print("\033[1;36m║\033[0m" + " " * (width - 2) + "\033[1;36m║\033[0m")


def _render_suggestions(width: int) -> None:
    print("\033[1;36m║\033[1;33m  Suggestions" + " " * (width - 15) + "\033[1;36m║\033[0m")
    print("\033[1;36m║\033[0m  " + "─" * (width - 6) + "  \033[1;36m║\033[0m")

    suggestions = _load_suggestions()
    if not suggestions:
        print("\033[1;36m║\033[0m  \033[90m  No pending suggestions\033[0m" + " " * (width - 31) + "\033[1;36m║\033[0m")
    else:
        for s in suggestions[:5]:
            stype = s["suggestion_type"]
            icon = "\033[1;35m⇄\033[0m" if stype == "merge" else "\033[1;33m↗\033[0m"
            title = s["title"][:width - 20]
            conf = f"\033[90m{s['confidence']:.0%}\033[0m"
            line = f"  {icon} {title} {conf}"
            print(f"\033[1;36m║\033[0m{line[:width-3]}\033[1;36m║\033[0m")

    print("\033[1;36m║\033[0m" + " " * (width - 2) + "\033[1;36m║\033[0m")


def _render_events(width: int) -> None:
    print("\033[1;36m║\033[1;33m  Event Counts" + " " * (width - 16) + "\033[1;36m║\033[0m")
    print("\033[1;36m║\033[0m  " + "─" * (width - 6) + "  \033[1;36m║\033[0m")

    counts = _load_event_counts()
    if not counts:
        print("\033[1;36m║\033[0m  \033[90m  No events recorded\033[0m" + " " * (width - 26) + "\033[1;36m║\033[0m")
    else:
        max_count = max(counts.values()) if counts else 1
        for name, cnt in sorted(counts.items(), key=lambda x: -x[1])[:8]:
            bar_len = min(40, int(cnt / max(max_count, 1) * 40))
            bar = "\033[1;34m█\033[0m" * bar_len
            line = f"  \033[1;37m{name:<18}\033[0m {bar} \033[90m{cnt}\033[0m"
            print(f"\033[1;36m║\033[0m{line[:width-3]}\033[1;36m║\033[0m")

    print("\033[1;36m║\033[0m" + " " * (width - 2) + "\033[1;36m║\033[0m")


def _render_help(width: int) -> None:
    print("\033[1;36m║\033[0m  \033[90mCommands: wsctl create | start | stop | fork | merge | snapshot | restore | delete | ask\033[0m" + " " * (width - 97) + "\033[1;36m║\033[0m")


def _load_suggestions() -> list[dict]:
    try:
        from nexus.db import get_conn
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM suggestions WHERE status = 'pending' ORDER BY confidence DESC LIMIT 10"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _load_event_counts() -> dict[str, int]:
    try:
        from nexus.db import event_counts
        return event_counts()
    except Exception:
        return {}
