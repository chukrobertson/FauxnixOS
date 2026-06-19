"""Async HTTP client for the fauxd daemon API on localhost:8756."""

import json
import urllib.request
import urllib.error
from typing import Any

FAUXD_URL = "http://127.0.0.1:8756"


def _req(method: str, path: str, body: dict | None = None) -> dict | list | None:
    url = f"{FAUXD_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body else None
    try:
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError):
        return None


def get_summary() -> dict | None:
    return _req("GET", "/api/summary")


def get_telemetry() -> dict | None:
    return _req("GET", "/api/telemetry")


def get_weather() -> dict | None:
    return _req("GET", "/api/weather")


def get_threads() -> list | None:
    return _req("GET", "/api/threads")


def get_thread_cards() -> list | None:
    return _req("GET", "/api/thread-cards")


def get_notes() -> list | None:
    return _req("GET", "/api/notes")


def create_note(title: str, content: str) -> dict | None:
    return _req("POST", "/api/notes", {"title": title, "content": content})


def get_clipboard() -> list | None:
    return _req("GET", "/api/clipboard")


def set_clipboard(text: str) -> dict | None:
    return _req("POST", "/api/clipboard/text", {"text": text})


def clear_clipboard() -> dict | None:
    return _req("POST", "/api/clipboard/clear")


def get_files_recent(limit: int = 20) -> list | None:
    return _req("GET", f"/api/files/recent?limit={limit}")


def get_files_pins() -> list | None:
    return _req("GET", "/api/files/pins")


def search_files(query: str) -> list | None:
    return _req("GET", f"/api/files/search?q={query}")


def do_action(action: str) -> dict | None:
    return _req("POST", "/api/action", {"action": action})


def push_shell_event(event: str) -> dict | None:
    return _req("POST", "/api/shell-event", {"event": event})


def get_events(since: int = 0) -> list | None:
    return _req("GET", f"/api/events?since={since}")


def chat(prompt: str, route: str = "local") -> dict | None:
    return _req("POST", "/api/chat", {"prompt": prompt, "route": route})


def get_sessions() -> list | None:
    return _req("GET", "/api/sessions")


def get_continuity() -> list | None:
    return _req("GET", "/api/continuity")
