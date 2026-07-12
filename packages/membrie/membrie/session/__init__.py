from __future__ import annotations

import json
import time
import uuid
from datetime import datetime

from fauxnix_tools.db import get_conn as _get_fauxnix_conn
from fauxnix_tools.llm.router import model_for_task
from membrie.awareness.drift import get_drift_history, get_drift_status, get_intention
from membrie.awareness.process import get_active_process_context, _categorize_process


def _now() -> float:
    return time.time()


def start_session() -> dict:
    session_id = str(uuid.uuid4())[:12]
    now = _now()
    intention = get_intention()
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO sessions (id, started_ts) VALUES (?, ?)",
        (session_id, now),
    )
    cur.execute(
        "INSERT INTO session_events (session_id, event_type, event_data, created_ts) VALUES (?, ?, ?, ?)",
        (session_id, "session_started", json.dumps({"intention": intention}), now),
    )
    conn.commit()
    conn.close()
    return {"session_id": session_id, "started_ts": now, "intention": intention}


def end_session(session_id: str) -> dict:
    now = _now()
    conn = _get_fauxnix_conn()
    cur = conn.cursor()

    cur.execute("SELECT started_ts FROM sessions WHERE id = ?", (session_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {"ok": False, "error": "session_not_found"}

    started = row["started_ts"]
    cur.execute(
        "SELECT COALESCE(SUM(duration_seconds), 0) FROM process_log WHERE start_ts BETWEEN ? AND ?",
        (started, now),
    )
    total_active = float(cur.fetchone()[0])

    h = get_drift_history(hours=int((now - started) / 3600) + 1)
    focus_seconds = sum(item.get("duration_seconds", 0) or 0 for item in h if item.get("state") == "on_track")
    drift_count = sum(1 for item in h if item.get("state") == "drifted")

    app_summary = _build_app_summary(h)
    summary = _generate_session_summary(session_id, total_active, focus_seconds, drift_count, app_summary)

    cur.execute(
        """UPDATE sessions SET ended_ts = ?, app_summary_json = ?,
           total_active_seconds = ?, focus_seconds = ?, drift_count = ?, summary = ?
           WHERE id = ?""",
        (now, json.dumps(app_summary), total_active, focus_seconds, drift_count, summary, session_id),
    )
    cur.execute(
        "INSERT INTO session_events (session_id, event_type, event_data, created_ts) VALUES (?, ?, ?, ?)",
        (session_id, "session_ended", json.dumps({"total_active": total_active, "focus": focus_seconds}), now),
    )
    conn.commit()
    conn.close()

    return {
        "ok": True, "session_id": session_id,
        "started": datetime.fromtimestamp(started).isoformat(),
        "ended": datetime.fromtimestamp(now).isoformat(),
        "total_active_min": int(total_active // 60),
        "focus_min": int(focus_seconds // 60),
        "drift_count": drift_count,
        "summary": summary,
    }


def get_active_session() -> dict | None:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sessions WHERE ended_ts IS NULL ORDER BY started_ts DESC LIMIT 1")
    row = cur.fetchone()
    conn.close()
    if row:
        d = dict(row)
        d["elapsed_seconds"] = int(_now() - d["started_ts"])
        return d
    return None


def list_sessions(limit: int = 20) -> list[dict]:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sessions WHERE ended_ts IS NOT NULL ORDER BY started_ts DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        if r.get("app_summary_json"):
            r["app_summary"] = json.loads(r["app_summary_json"])
    return rows


def get_session_timeline(session_id: str) -> dict:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
    session = cur.fetchone()
    if not session:
        conn.close()
        return {"ok": False, "error": "session_not_found"}

    cur.execute(
        "SELECT * FROM process_log WHERE start_ts BETWEEN ? AND ? ORDER BY start_ts ASC LIMIT 500",
        (session["started_ts"], session["ended_ts"] or _now()),
    )
    events = []
    for row in cur.fetchall():
        r = dict(row)
        pn = r.get("process_name", "")
        wt = r.get("window_title", "")
        if pn.startswith("__"):
            continue
        r["category"] = _categorize_process(pn, wt)
        events.append(r)
    conn.close()

    session_d = dict(session)
    session_d["events"] = events
    if session_d.get("app_summary_json"):
        session_d["app_summary"] = json.loads(session_d["app_summary_json"])
    return {"ok": True, "session": session_d}


def _build_app_summary(history: list[dict]) -> dict:
    apps = {}
    for item in history:
        pn = item.get("process_name", "")
        if not pn or pn.startswith("__"):
            continue
        dur = item.get("duration_seconds", 0) or 60
        apps[pn] = apps.get(pn, 0) + dur
    sorted_apps = dict(sorted(apps.items(), key=lambda x: x[1], reverse=True)[:15])
    return {"apps": sorted_apps, "total_apps": len(apps)}


def _generate_session_summary(session_id: str, total_active: float, focus_seconds: float,
                               drift_count: int, app_summary: dict) -> str:
    top_apps = list(app_summary.get("apps", {}).items())[:5]
    app_names = [f"{name} ({int(dur // 60)}m)" for name, dur in top_apps]
    total_min = int(total_active // 60)

    if total_min < 1:
        return "Brief session — no significant activity recorded."

    summary = f"Session lasted {total_min}m active. "
    summary += f"Focus: {int(focus_seconds // 60)}m. "
    if drift_count > 0:
        summary += f"Drifted {drift_count} times. "
    if app_names:
        summary += f"Top apps: {', '.join(app_names)}."

    return summary
