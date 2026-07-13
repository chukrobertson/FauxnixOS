from __future__ import annotations

import json
import os
from pathlib import Path


def generate_thread_summary(thread_name: str) -> str:
    parts = []

    title = f"🧵 {thread_name}"
    parts.append(title)

    manifest_info = _manifest_info(thread_name)
    if manifest_info:
        parts.append(manifest_info)

    git_summary = _git_summary(thread_name)
    if git_summary:
        parts.append(git_summary)

    health_info = _health_info(thread_name)
    if health_info:
        parts.append(health_info)

    event_summary = _event_summary(thread_name)
    if event_summary:
        parts.append(event_summary)

    file_summary = _file_summary(thread_name)
    if file_summary:
        parts.append(file_summary)

    return "\n".join(parts)


def _manifest_info(thread_name: str) -> str:
    ws_path = Path("/var/lib/workspaces") / thread_name
    manifest_path = ws_path / "ws-manifest.json"
    if not manifest_path.exists():
        return ""

    try:
        manifest = json.loads(manifest_path.read_text())
        template = manifest.get("nix", {}).get("template")
        profile = manifest.get("nix", {}).get("profile", "headless")
        created = manifest.get("workspace", {}).get("created", "")[:10]
        last_active = manifest.get("activity", {}).get("last_active", "")

        parts = []
        if template:
            parts.append(f"🔧 Template: {template}")
        if profile and profile != "headless":
            parts.append(f"🖥️  Profile: {profile}")

        if last_active:
            try:
                last_dt = datetime.fromisoformat(last_active)
                now = datetime.now(timezone.utc)
                delta = now - last_dt
                if delta.days > 0:
                    parts.append(f"⏱️  Last active: {delta.days}d ago")
                elif delta.seconds > 3600:
                    parts.append(f"⏱️  Last active: {delta.seconds // 3600}h ago")
                elif delta.seconds > 60:
                    parts.append(f"⏱️  Last active: {delta.seconds // 60}m ago")
                else:
                    parts.append(f"⏱️  Last active: just now")
            except Exception:
                pass

        return " · ".join(parts) if parts else ""
    except Exception:
        return ""


def _health_info(thread_name: str) -> str:
    try:
        import sys
        fauxnix_root = os.getenv("FAUXNIX_ROOT", "/home/chxk/Projects/fauxnix-core")
        sys.path.insert(0, f"{fauxnix_root}/packages/nexus")
        from nexus.db import get_health
        health = get_health(thread_name)
        if not health:
            return ""

        parts = []
        crashes = health.get("crash_count", 0)
        if crashes > 0:
            parts.append(f"⚠️  {crashes} previous crash(es)")

        status = health.get("status", "")
        if status == "running":
            started = health.get("started_at", "")[:19]
            if started:
                parts.append(f"🟢 Running since {started}")

        if parts:
            return " · ".join(parts)
    except Exception:
        pass
    return ""


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
        fauxnix_root = os.getenv("FAUXNIX_ROOT", "/home/chxk/Projects/fauxnix-core")
        sys.path.insert(0, f"{fauxnix_root}/packages/nexus")
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
