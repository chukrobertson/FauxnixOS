from __future__ import annotations

import json
import os
import socket
import threading
import time
from pathlib import Path

SOCKET_DIR = "/run/nexus"
DISPATCH_SOCK = "/run/nexus/dispatch.sock"


def stream_event(thread_name: str, source: str, data: dict, duration: float | None = None) -> None:
    event = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "thread": thread_name,
        "src": source,
        "data": data,
    }
    if duration is not None:
        event["dur"] = duration

    _write_to_socket(thread_name, event)


def stream_window_event(thread_name: str, app: str, title: str, duration: float | None = None) -> None:
    stream_event(thread_name, "window", {"app": app, "title": title}, duration)


def stream_file_event(thread_name: str, path: str, action: str) -> None:
    stream_event(thread_name, "file", {"path": path, "action": action})


def stream_git_event(thread_name: str, repo: str, branch: str, message: str, action: str) -> None:
    stream_event(thread_name, "git", {
        "repo": repo, "branch": branch, "msg": message, "action": action,
    })


def stream_browser_event(thread_name: str, domain: str, title: str) -> None:
    stream_event(thread_name, "browser", {"domain": domain, "title": title})


def stream_terminal_event(thread_name: str, cmd: str, cwd: str) -> None:
    stream_event(thread_name, "terminal", {"cmd": cmd, "cwd": cwd})


def stream_idle_event(thread_name: str, state: str, seconds: float) -> None:
    stream_event(thread_name, "idle", {"state": state, "seconds": seconds})


def _write_to_socket(thread_name: str, event: dict) -> None:
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(2)
        sock.connect(DISPATCH_SOCK)
        sock.sendall((json.dumps(event) + "\n").encode())
        sock.close()
    except (FileNotFoundError, ConnectionRefusedError, OSError):
        pass


class ContextStreamer:
    def __init__(self, thread_name: str) -> None:
        self._thread_name = thread_name
        self._last_window: dict | None = None
        self._window_start: float | None = None

    def on_window_change(self, app: str, title: str) -> None:
        now = time.time()
        if self._last_window:
            duration = now - (self._window_start or now)
            stream_window_event(
                self._thread_name,
                self._last_window["app"],
                self._last_window["title"],
                round(duration, 1),
            )
        self._last_window = {"app": app, "title": title}
        self._window_start = now
        stream_window_event(self._thread_name, app, title)

    def on_file_change(self, path: str, action: str) -> None:
        stream_file_event(self._thread_name, path, action)

    def on_git_activity(self, repo: str, branch: str, message: str, action: str) -> None:
        stream_git_event(self._thread_name, repo, branch, message, action)

    def on_browser_activity(self, domain: str, title: str) -> None:
        stream_browser_event(self._thread_name, domain, title)

    def on_terminal_command(self, cmd: str, cwd: str) -> None:
        stream_terminal_event(self._thread_name, cmd, cwd)

    def on_idle_change(self, state: str, seconds: float) -> None:
        stream_idle_event(self._thread_name, state, seconds)
