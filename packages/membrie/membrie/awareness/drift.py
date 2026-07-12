from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from fauxnix_tools.config import config
from fauxnix_tools.db import get_conn as _get_fauxnix_conn
from membrie.awareness.process import get_foreground_process, get_idle_seconds, get_idle_state, _categorize_process, category_color

DRIFT_FILE = config.data_dir / "drift_state.json"


def _load_drift_state() -> dict:
    try:
        return json.loads(DRIFT_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_drift_state(state: dict):
    DRIFT_FILE.parent.mkdir(parents=True, exist_ok=True)
    DRIFT_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def set_intention(text: str):
    state = _load_drift_state()
    state["intention"] = text
    state["set_at"] = time.time()
    _save_drift_state(state)


def clear_intention():
    state = _load_drift_state()
    state.pop("intention", None)
    state.pop("set_at", None)
    _save_drift_state(state)


def get_intention() -> str | None:
    state = _load_drift_state()
    return state.get("intention")


_DISTRACTION_CATEGORIES = {"entertainment", "browsing"}


def check_drift() -> dict:
    idle_state = get_idle_state()
    idle_secs = int(get_idle_seconds())
    fg = get_foreground_process()
    state = _load_drift_state()
    intention = state.get("intention")
    proc_name = fg.get("process_name", "").lower() if fg else ""
    window = (fg.get("window_title") or "").lower() if fg else ""

    if idle_state in ("away", "locked"):
        result = {
            "state": idle_state, "process": proc_name or "unknown",
            "window": window if idle_state != "locked" else "Workstation locked",
            "idle_seconds": idle_secs, "intention": intention,
            "category": "idle", "category_color": "#888",
        }
        _save_drift(result)
        return result

    if not intention or not fg:
        cat = _categorize_process(proc_name, window)
        result = {
            "state": "idle", "process": proc_name, "window": window,
            "idle_seconds": idle_secs, "category": cat,
            "category_color": category_color(cat),
        }
        _save_drift(result)
        return result

    intention_lower = intention.lower()
    productive_keywords = [w for w in intention_lower.split() if len(w) > 3]
    is_productive = any(kw in proc_name or kw in window for kw in productive_keywords)
    cat = _categorize_process(proc_name, window)

    if is_productive:
        result = {
            "state": "on_track", "process": proc_name, "window": window,
            "idle_seconds": idle_secs, "category": cat,
            "category_color": category_color(cat),
        }
    elif cat in _DISTRACTION_CATEGORIES and not is_productive:
        result = {
            "state": "drifted", "process": proc_name, "window": window,
            "idle_seconds": idle_secs, "intention": intention,
            "category": cat, "category_color": category_color(cat),
        }
    elif cat == "communication":
        result = {
            "state": "neutral", "process": proc_name, "window": window,
            "idle_seconds": idle_secs, "category": cat,
            "category_color": category_color(cat),
        }
    else:
        result = {
            "state": "on_track", "process": proc_name, "window": window,
            "idle_seconds": idle_secs, "category": cat,
            "category_color": category_color(cat),
        }

    _save_drift(result)
    return result


_FOCUS_MIN_CONSECUTIVE = 600
_focus_state = {"in_focus": False, "focus_start": 0.0, "total_today": 0}


def update_focus():
    global _focus_state
    now = time.time()
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    today_start = now - (now % 86400)

    cur.execute(
        "SELECT COALESCE(SUM(duration_seconds), 0) FROM process_log "
        "WHERE start_ts > ? AND process_name NOT LIKE '__%'",
        (today_start,),
    )
    total_today = int(cur.fetchone()[0])

    cur.execute(
        "SELECT COALESCE(SUM(duration_seconds), 0) FROM process_log "
        "WHERE start_ts > ? AND process_name IN ('chrome','chromium','firefox','brave','spotify','vlc','mpv','steam')",
        (today_start,),
    )
    distraction_today = int(cur.fetchone()[0])
    conn.close()

    focused_today = max(0, total_today - distraction_today)

    drift = get_drift_status()
    parts = []
    for item in [drift.get("process", ""), drift.get("window_title", ""), drift.get("window", "")]:
        if item and str(item).strip():
            parts.append(str(item).strip())
    full_text = " ".join(parts).lower()

    cat = drift.get("category", "other")
    in_productive = (drift.get("state") == "on_track" and
                     cat in ("work", "utilities", "other") and
                     not any(d in full_text for d in {"youtube", "netflix", "spotify", "reddit", "twitter", "instagram"}))

    if in_productive and not _focus_state["in_focus"]:
        history = get_drift_history(hours=1)
        consecutive = 0
        for h in history:
            h_cat = h.get("category", "")
            if h.get("state") == "on_track" and h_cat in ("work", "utilities", "other"):
                consecutive += h.get("duration_seconds", 0) or 60
            else:
                break
        if consecutive >= _FOCUS_MIN_CONSECUTIVE:
            _focus_state["in_focus"] = True
            _focus_state["focus_start"] = now
    elif not in_productive and _focus_state["in_focus"]:
        _focus_state["in_focus"] = False
        _focus_state["focus_start"] = 0.0

    _focus_state["total_today"] = focused_today
    _focus_state["focused_today"] = focused_today
    _focus_state["distraction_today"] = distraction_today


def get_focus_state() -> dict:
    global _focus_state
    now = time.time()
    d = dict(_focus_state)
    if d["in_focus"] and d["focus_start"] > 0:
        d["current_streak"] = int(now - d["focus_start"])
    else:
        d["current_streak"] = 0
    d["total_today_min"] = d.get("focused_today", d.get("total_today", 0)) // 60
    return d


_last_drift = {"state": "unknown"}


def _save_drift(result: dict | None = None):
    global _last_drift
    if result:
        _last_drift = result


def get_drift_status() -> dict:
    return dict(_last_drift)


def get_drift_history(hours: int = 24) -> list[dict]:
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cutoff = time.time() - (hours * 3600)
    cur.execute(
        "SELECT process_name, window_title, start_ts, end_ts, duration_seconds FROM process_log WHERE start_ts > ? ORDER BY start_ts DESC LIMIT 200",
        (cutoff,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    fmt = lambda ts: datetime.fromtimestamp(ts).strftime("%H:%M") if ts else "?"
    for r in rows:
        r["time"] = fmt(r["start_ts"])
        pn = r.get("process_name", "")
        wt = r.get("window_title", "")
        r["category"] = _categorize_process(pn, wt)
        r["category_color"] = category_color(r["category"])
        r["state"] = _infer_state(r)
    return rows


def _infer_state(entry: dict) -> str:
    pn = (entry.get("process_name") or "").lower()
    wt = (entry.get("window_title") or "").lower()
    intention = get_intention()
    if not intention:
        return "idle"
    cat = _categorize_process(pn, wt)
    if cat in _DISTRACTION_CATEGORIES:
        return "drifted"
    if cat in ("work", "utilities", "other"):
        return "on_track"
    return "neutral"
