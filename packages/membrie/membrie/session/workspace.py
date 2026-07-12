from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from fauxnix_tools.config import config
from fauxnix_tools.db import get_conn as _get_fauxnix_conn
from fauxnix_tools.files.snapshot import snapshot_directory
from membrie.session import get_session_timeline, list_sessions


def create_workspace_from_session(session_id: str, name: str | None = None) -> dict:
    session = get_session_timeline(session_id)
    if not session.get("ok"):
        return session

    s = session["session"]
    name = name or f"Workspace from {s.get('started_ts', 'unknown')}"
    ws_dir = config.data_dir / "workspaces" / _slugify(name)
    ws_dir.mkdir(parents=True, exist_ok=True)

    apps = s.get("app_summary", {}).get("apps", {})
    events = s.get("events", [])

    nodes = []
    for ev in events:
        pn = ev.get("process_name", "")
        wt = ev.get("window_title", "")
        cat = ev.get("category", "other")
        dur = ev.get("duration_seconds", 0)
        if not pn or pn.startswith("__") or dur < 5:
            continue
        nodes.append({
            "process": pn,
            "window": wt[:120],
            "category": cat,
            "duration_s": int(dur),
            "start": ev.get("start_ts"),
        })

    manifest = {
        "name": name,
        "session_id": session_id,
        "duration_s": int(s.get("total_active_seconds", 0)),
        "focus_s": int(s.get("focus_seconds", 0)),
        "drift_count": s.get("drift_count", 0),
        "summary": s.get("summary", ""),
        "top_apps": {k: int(v) for k, v in list(apps.items())[:10]},
        "nodes": nodes[:200],
        "created_ts": time.time(),
    }

    manifest_path = ws_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    workspace_json = json.dumps(manifest)
    ts = time.time()
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO workspace_snapshots (name, workspace_json, node_count, created_ts, updated_ts) VALUES (?, ?, ?, ?, ?)",
        (name, workspace_json, len(nodes), ts, ts),
    )
    conn.commit()
    conn.close()

    return {
        "ok": True,
        "workspace_dir": str(ws_dir),
        "name": name,
        "node_count": len(nodes),
        "manifest": manifest,
    }


def browse_workspaces(limit: int = 20) -> list[dict]:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM workspace_snapshots ORDER BY updated_ts DESC LIMIT ?", (limit,))
    rows = []
    for r in cur.fetchall():
        d = dict(r)
        try:
            d["workspace"] = json.loads(d.pop("workspace_json"))
        except Exception:
            d["workspace"] = {}
        rows.append(d)
    conn.close()
    return rows


def search_in_workspaces(query: str) -> list[dict]:
    results = []
    for ws in browse_workspaces():
        w = ws.get("workspace", {})
        nodes = w.get("nodes", [])
        matches = []
        q = query.lower()
        for node in nodes:
            if q in (node.get("process", "") + node.get("window", "")).lower():
                matches.append(node)
        if matches:
            results.append({"workspace": w.get("name", ""), "session_id": w.get("session_id", ""), "matches": matches[:10], "total_matches": len(matches)})
    return results


def export_workspace(workspace_id: int, target_dir: str) -> dict:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM workspace_snapshots WHERE id = ?", (workspace_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return {"ok": False, "error": "workspace_not_found"}
    workspace = json.loads(row["workspace_json"])
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    (target / "workspace.json").write_text(json.dumps(workspace, indent=2, ensure_ascii=False), encoding="utf-8")
    readme = _generate_workspace_readme(workspace)
    (target / "README.md").write_text(readme, encoding="utf-8")
    return {"ok": True, "target_dir": str(target), "name": workspace.get("name"), "node_count": workspace.get("node_count", 0)}


def _generate_workspace_readme(workspace: dict) -> str:
    name = workspace.get("name", "Untitled Workspace")
    summary = workspace.get("summary", "")
    top_apps = workspace.get("top_apps", {})
    nodes = workspace.get("nodes", [])
    lines = [
        f"# {name}",
        "",
        f"**Summary:** {summary}",
        "",
        f"**Duration:** {workspace.get('duration_s', 0) // 60} min active",
        f"**Focus time:** {workspace.get('focus_s', 0) // 60} min",
        f"**Drifts:** {workspace.get('drift_count', 0)}",
        "",
        "## Top Applications",
        "",
    ]
    for app, dur in list(top_apps.items())[:10]:
        lines.append(f"- {app}: {dur // 60} min")
    lines.append("")
    lines.append("## Activity Log")
    lines.append("")
    for n in nodes[:50]:
        lines.append(f"- [{n.get('category', '?')}] {n.get('process', '')} — {n.get('window', '')[:80]} ({n.get('duration_s', 0)}s)")
    return "\n".join(lines)


def _slugify(text: str) -> str:
    import re
    return re.sub(r"[^a-zA-Z0-9_-]", "_", text.lower())[:64]
