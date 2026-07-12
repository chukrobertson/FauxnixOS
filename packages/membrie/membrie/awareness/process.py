from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time

from fauxnix_tools.db import get_conn as _get_fauxnix_conn
from fauxnix_tools.utils import now_ts as _now_ts


_PROC_LOG_INTERVAL = 60
_IDLE_ACTIVE = 300
_IDLE_AWAY = 900


def _which(binary: str) -> str | None:
    try:
        result = subprocess.run(["which", binary], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return shutil.which(binary)


def _run(args: list[str], timeout: int = 10) -> tuple[int, str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return result.returncode, (result.stdout or "").strip()
    except Exception:
        return -1, ""


def list_running_processes() -> list[dict]:
    processes = []
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            pid = int(entry)
            try:
                cmdline = (Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").strip().decode("utf-8", errors="ignore"))
            except Exception:
                continue
            name = Path(cmdline.split()[0]).name if cmdline else ""
            if name:
                processes.append({"name": name, "pid": pid, "cmdline": cmdline[:200]})
    except Exception:
        pass
    return processes[:80]


def _xdotool_get_foreground() -> dict | None:
    xdotool = _which("xdotool")
    if not xdotool:
        return None
    code, window_id = _run([xdotool, "getactivewindow"])
    if code != 0 or not window_id:
        return None
    code, pid_str = _run([xdotool, "getwindowpid", window_id])
    pid = int(pid_str) if code == 0 and pid_str.isdigit() else None
    code, title = _run([xdotool, "getwindowname", window_id])
    if pid:
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").strip().decode("utf-8", errors="ignore")
            process_name = Path(cmdline.split()[0]).name if cmdline else ""
        except Exception:
            # fallback: read /proc/<pid>/comm
            try:
                process_name = Path(f"/proc/{pid}/comm").read_text(encoding="utf-8", errors="ignore").strip()
            except Exception:
                process_name = ""
    else:
        process_name = ""
    wmclass = ""
    wmctrl = _which("wmctrl")
    if wmctrl:
        code2, wmctrl_out = _run([wmctrl, "-lx"])
        if code2 == 0:
            for line in wmctrl_out.splitlines():
                if window_id in line:
                    parts = line.split(None, 3)
                    if len(parts) >= 4:
                        wmclass = parts[2] if len(parts) > 2 else ""
                    break

    return {
        "process_name": process_name or wmclass or "unknown",
        "window_title": title or "",
        "pid": pid,
        "window_id": window_id,
        "wm_class": wmclass,
    }


def get_foreground_process() -> dict | None:
    result = _xdotool_get_foreground()
    if result and result.get("process_name"):
        return result

    try:
        import Xlib.display
        display = Xlib.display.Display()
        root = display.screen().root
        window_id = root.get_full_property(display.intern_atom("_NET_ACTIVE_WINDOW"), Xlib.X.AnyPropertyType)
        if window_id:
            win_id = window_id.value[0]
            try:
                window = display.create_resource_object("window", win_id)
                title_prop = window.get_full_property(display.intern_atom("_NET_WM_NAME"), Xlib.X.AnyPropertyType)
                title = title_prop.value.decode("utf-8") if title_prop else ""
                pid_prop = window.get_full_property(display.intern_atom("_NET_WM_PID"), Xlib.X.AnyPropertyType)
                pid = pid_prop.value[0] if pid_prop else None
                class_prop = window.get_full_property(display.intern_atom("WM_CLASS"), Xlib.X.AnyPropertyType)
                wmclass = class_prop.value.decode("utf-8") if class_prop else ""
                if pid:
                    try:
                        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").strip().decode("utf-8", errors="ignore")
                        process_name = Path(cmdline.split()[0]).name if cmdline else ""
                    except Exception:
                        process_name = wmclass.split("\x00")[-1] if "\x00" in wmclass else wmclass
                else:
                    process_name = wmclass.split("\x00")[-1] if "\x00" in wmclass else wmclass
                return {"process_name": process_name or "unknown", "window_title": title or "", "pid": pid, "window_id": win_id, "wm_class": wmclass}
            except Exception:
                pass
    except ImportError:
        pass

    return None


def get_idle_seconds() -> float:
    xprintidle = _which("xprintidle")
    if xprintidle:
        code, out = _run([xprintidle])
        if code == 0 and out:
            try:
                return float(out) / 1000.0
            except ValueError:
                pass

    try:
        import Xlib.display
        import Xlib.ext.screensaver
        display = Xlib.display.Display()
        info = display.screensaver_query_info()
        return info.idle / 1000.0
    except ImportError:
        pass

    return 0.0


def get_idle_state() -> str:
    secs = get_idle_seconds()
    if secs < _IDLE_ACTIVE:
        return "active"
    if secs < _IDLE_AWAY:
        return "idle"
    if _screen_locked():
        return "locked"
    return "away"


def _screen_locked() -> bool:
    try:
        code, out = _run(["loginctl", "show-session", os.environ.get("XDG_SESSION_ID", ""), "-p", "LockedHint"], timeout=5)
        if code == 0 and "yes" in out.lower():
            return True
    except Exception:
        pass

    try:
        code, out = _run(["dbus-send", "--session", "--print-reply", "--dest=org.gnome.ScreenSaver",
                          "/org/gnome/ScreenSaver", "org.gnome.ScreenSaver.GetActive"], timeout=5)
        if code == 0 and "true" in out.lower():
            return True
    except Exception:
        pass

    try:
        code, out = _run(["qdbus", "org.kde.screensaver", "/ScreenSaver", "GetSessionIdleTime"], timeout=5)
        if code != 0:
            code2, out2 = _run(["qdbus", "org.freedesktop.ScreenSaver", "/ScreenSaver", "GetActive"], timeout=5)
            if code2 == 0 and "true" in out2.lower():
                return True
    except Exception:
        pass

    return False


def log_process_activity(duration_seconds: int = 300) -> dict:
    start = time.time()
    foreground = get_foreground_process()
    if not foreground:
        return {"logged": False, "reason": "no_foreground_process"}
    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO process_log (process_name, window_title, duration_seconds, start_ts, end_ts) VALUES (?, ?, ?, ?, ?)",
        (foreground["process_name"], foreground.get("window_title", "")[:200], duration_seconds, start, start + duration_seconds),
    )
    conn.commit()
    conn.close()
    return {"logged": True, "process": foreground["process_name"], "duration_seconds": duration_seconds}


def get_active_process_context() -> str:
    foreground = get_foreground_process()
    if not foreground:
        return ""

    conn = _get_fauxnix_conn()
    cur = conn.cursor()
    name = foreground["process_name"]
    cur.execute(
        "SELECT process_name, window_title, SUM(duration_seconds) as total_seconds FROM process_log WHERE process_name = ? AND start_ts > ? GROUP BY process_name ORDER BY total_seconds DESC LIMIT 3",
        (name, time.time() - 86400),
    )
    history = [dict(r) for r in cur.fetchall()]
    conn.close()

    parts = [f"Currently active: {name}"]
    if foreground.get("window_title"):
        parts.append(f"Window: {foreground['window_title'][:80]}")
    if history:
        total = sum(h.get("total_seconds", 0) for h in history)
        parts.append(f"Used {total:.0f}s in the past 24h")
    return " | ".join(parts)


def _categorize_process(process_name: str, window_title: str = "") -> str:
    from fauxnix_tools.utils.categories import file_category
    name = (process_name or "").lower()

    work_patterns = {
        "code", "vs code", "intellij", "pycharm", "vim", "nvim", "emacs",
        "terminal", "konsole", "gnome-terminal", "alacritty", "kitty",
        "docker", "postman", "libreoffice", "notion", "obsidian",
        "gimp", "blender", "inkscape", "krita", "figma",
        "gitkraken", "sublime", "gedit", "kate",
    }
    comm_patterns = {
        "teams", "slack", "discord", "zoom", "skype", "telegram",
        "whatsapp", "signal", "thunderbird", "evolution", "geary",
    }
    browsing_patterns = {
        "chrome", "chromium", "firefox", "brave", "opera", "vivaldi", "tor",
    }
    entertainment_patterns = {
        "spotify", "vlc", "mpv", "steam", "games", "rhythmbox",
    }

    for pattern in work_patterns:
        if pattern in name:
            return "work"
    for pattern in comm_patterns:
        if pattern in name:
            return "communication"
    for pattern in browsing_patterns:
        if pattern in name:
            return "browsing"
    for pattern in entertainment_patterns:
        if pattern in name:
            return "entertainment"
    return "other"


def category_color(category: str) -> str:
    colors = {
        "work": "#81c784",
        "communication": "#64b5f6",
        "browsing": "#ffd54f",
        "entertainment": "#ef5350",
        "utilities": "#ce93d8",
        "other": "#888",
    }
    return colors.get(category, "#888")


class WindowHook:
    def __init__(self):
        self._thread = None
        self._running = False
        self._ready = threading.Event()
        self._last_process = ""
        self._last_window = ""
        self._last_row_id: int | None = None
        self._last_start: float = 0.0
        self._current: dict | None = None
        self._lock = threading.Lock()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="window_hook")
        self._thread.start()
        self._ready.wait(timeout=5)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    @property
    def current(self) -> dict | None:
        with self._lock:
            return self._current

    @property
    def is_running(self) -> bool:
        return self._running

    def _run(self):
        self._ready.set()
        last_check = 0.0
        while self._running:
            now = time.time()
            if now - last_check < 2.0:
                time.sleep(0.5)
                continue
            last_check = now
            try:
                fg = get_foreground_process()
                if not fg:
                    continue
                pn = fg.get("process_name", "")
                wt = (fg.get("window_title") or "")[:200]

                if pn == self._last_process and wt == self._last_window:
                    continue

                conn = _get_fauxnix_conn()
                cur = conn.cursor()

                if self._last_row_id is not None and self._last_start > 0:
                    cur.execute(
                        "UPDATE process_log SET end_ts = ?, duration_seconds = ? WHERE id = ?",
                        (now, now - self._last_start, self._last_row_id),
                    )

                cur.execute(
                    "INSERT INTO process_log (process_name, window_title, duration_seconds, start_ts, end_ts) VALUES (?, ?, 0, ?, ?)",
                    (pn, wt, now, now),
                )
                self._last_row_id = cur.lastrowid
                self._last_start = now
                self._last_process = pn
                self._last_window = wt

                conn.commit()
                conn.close()

                with self._lock:
                    self._current = fg
            except Exception:
                pass

    def update_current_duration(self):
        if self._last_row_id is None or self._last_start <= 0:
            return
        now = time.time()
        try:
            conn = _get_fauxnix_conn()
            cur = conn.cursor()
            cur.execute(
                "UPDATE process_log SET end_ts = ?, duration_seconds = ? WHERE id = ?",
                (now, now - self._last_start, self._last_row_id),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass


from pathlib import Path
