from __future__ import annotations

import json
import os
from pathlib import Path


def generate_thread_summary(thread_name: str) -> str:
    parts = []

    title = f"🧵 {thread_name}"
    parts.append(title)

    git_summary = _git_summary(thread_name)
    if git_summary:
        parts.append(git_summary)

    event_summary = _event_summary(thread_name)
    if event_summary:
        parts.append(event_summary)

    file_summary = _file_summary(thread_name)
    if file_summary:
        parts.append(file_summary)

    return "\n".join(parts)


def _git_summary(thread_name: str) -> str:
    ws_path = Path("/var/lib/workspaces") / thread_name
    if not ws_path.exists():
        return ""

    try:
        import subprocess
        result = subprocess.run(
            ["sudo", "git", "-C", str(ws_path), "log", "--oneline", "-5"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            commits = result.stdout.strip().split("\n")
            lines = ["📝 Recent commits:"]
            for c in commits[:3]:
                parts = c.split(" ", 1)
                hash_short = parts[0][:7]
                msg = parts[1][:60] if len(parts) > 1 else ""
                lines.append(f"  {hash_short}  {msg}")
            return "\n".join(lines)
    except Exception:
        pass
    return ""


def _event_summary(thread_name: str) -> str:
    try:
        import sys
        sys.path.insert(0, "/home/chxk/Projects/fauxnix-core/packages/nexus")
        from nexus.db import recent_events

        events = recent_events(thread_name, 10)
        if not events:
            return ""

        sources = {}
        for e in events:
            src = e["source"]
            try:
                data = json.loads(e["event_data"])
            except Exception:
                continue
            if src == "window":
                app = data.get("app", "?")
                sources[f"📱 Used {app}"] = sources.get(f"📱 Used {app}", 0) + 1
            elif src == "git":
                branch = data.get("branch", "main")
                sources[f"🔀 Branch: {branch}"] = 1

        if sources:
            return "\n".join(list(sources.keys())[:4])
    except Exception:
        pass
    return ""


def _file_summary(thread_name: str) -> str:
    ws_path = Path("/var/lib/workspaces") / thread_name / "workspace"
    if not ws_path.exists():
        return ""

    try:
        import subprocess
        result = subprocess.run(
            ["sudo", "find", str(ws_path), "-type", "f", "-not", "-name", ".*",
             "-not", "-path", "*/.git/*"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            files = result.stdout.strip().split("\n")
            if files:
                recent = [Path(f).name for f in files[-5:]]
                return "📂 Files: " + ", ".join(recent)
    except Exception:
        pass
    return ""


def show_resume(thread_name: str) -> None:
    summary = generate_thread_summary(thread_name)
    if summary:
        try:
            import subprocess
            subprocess.run(
                ["notify-send", "-a", "Fennix", "-i", "dialog-information",
                 "Welcome back", summary,
                 "--hint=int:transient:0",
                 "-t", "10000"],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass
