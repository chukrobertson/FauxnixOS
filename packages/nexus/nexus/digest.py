from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone

from nexus.db import get_conn


def daily_digest() -> dict:
    now = datetime.now(timezone.utc).isoformat()

    conn = get_conn()
    rows = conn.execute(
        """SELECT thread_name, source, event_data, created_at
           FROM thread_context ORDER BY id DESC LIMIT 500"""
    ).fetchall()
    conn.close()

    threads: dict[str, dict] = {}
    for r in rows:
        name = r["thread_name"]
        if name not in threads:
            threads[name] = {
                "events": 0,
                "sources": Counter(),
                "apps": set(),
                "files": set(),
                "commands": [],
                "last_seen": r["created_at"] or "",
                "first_seen": r["created_at"] or "",
            }
        t = threads[name]
        t["events"] += 1
        t["sources"][r["source"]] += 1
        t["first_seen"] = r["created_at"] or t["first_seen"]

        try:
            data = json.loads(r["event_data"])
        except Exception:
            continue

        if r["source"] == "window":
            app = data.get("app", "")
            if app:
                t["apps"].add(app)
        elif r["source"] == "file":
            path = data.get("path", "")
            if path:
                t["files"].add(path.split("/")[-1])
        elif r["source"] == "terminal":
            cmd = data.get("cmd", "")
            if cmd and len(t["commands"]) < 5:
                t["commands"].append(cmd)

    result: dict = {"threads": {}, "total_events": 0, "generated_at": now}
    for name, t in threads.items():
        result["threads"][name] = {
            "events": t["events"],
            "top_sources": [s for s, _ in t["sources"].most_common(3)],
            "apps": list(t["apps"])[:5],
            "files": list(t["files"])[:5],
            "commands": t["commands"][:3],
            "last_seen": t["last_seen"][:19] if t["last_seen"] else "",
        }
        result["total_events"] += t["events"]

    return result


def digest_text() -> str:
    digest = daily_digest()
    threads = digest.get("threads", {})
    if not threads:
        return "No activity yet. Create your first thread to get started!"

    lines = []
    for name, info in sorted(threads.items(), key=lambda x: -x[1]["events"]):
        apps = ", ".join(info["apps"][:3]) or "headless"
        sources = ", ".join(info["top_sources"][:2])
        files = ", ".join(info["files"][:3])

        line = f"🧵 {name}: {info['events']} events"
        if apps:
            line += f" · {apps}"
        if files:
            line += f"\n   📂 {files}"

        lines.append(line)

    return "\n".join(lines)
