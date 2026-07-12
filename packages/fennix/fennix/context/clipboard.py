from __future__ import annotations

import time


def get_recent_clipboard(limit: int = 5) -> list[dict]:
    from fauxnix_tools.db import get_conn
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT content, source_app, captured_ts FROM fennix_clipboard_snapshots ORDER BY captured_ts DESC LIMIT ?",
            (limit,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def get_clipboard_context(max_items: int = 3, max_length: int = 500) -> str:
    items = get_recent_clipboard(max_items)
    if not items:
        return ""

    lines: list[str] = []
    for item in items:
        content = (item.get("content") or "")[:max_length]
        source = item.get("source_app") or ""
        ts = item.get("captured_ts") or 0
        age = ""
        if ts:
            seconds = time.time() - ts
            if seconds < 60:
                age = f"{int(seconds)}s ago"
            elif seconds < 3600:
                age = f"{int(seconds / 60)}m ago"
            else:
                age = f"{int(seconds / 3600)}h ago"

        label = f"Clipboard {age}" if age else "Clipboard"
        if source:
            label += f" (from {source})"
        lines.append(f"{label}:\n{content}")

    return "\n\n".join(lines)


def get_current_clipboard() -> str | None:
    try:
        import pyperclip
        content = pyperclip.paste()
        if content and content.strip():
            return content[:5000]
    except Exception:
        pass
    return None
