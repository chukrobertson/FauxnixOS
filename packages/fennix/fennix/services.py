from __future__ import annotations

import hashlib
import json
import threading
import time

from pathlib import Path

from fauxnix_tools.db import get_conn as _get_fauxnix_conn
from fennix.config import config


class BaseService:
    name = "base"
    interval = 60

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self):
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.wait(self.interval):
            try:
                self.tick()
            except Exception:
                pass

    def tick(self):
        pass


class ClipboardContextWatcher(BaseService):
    name = "clipboard_watcher"
    interval = 2

    def __init__(self):
        super().__init__()
        self._last_hash = ""

    def tick(self):
        if not config.clipboard_watch:
            return
        try:
            import pyperclip
            content = pyperclip.paste()
            if not content or not content.strip():
                return
            content_hash = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
            if content_hash == self._last_hash:
                return
            self._last_hash = content_hash

            conn = _get_fauxnix_conn()
            cur = conn.cursor()
            now = time.time()

            source_app = ""
            try:
                fp = get_foreground_process()
                if fp:
                    source_app = fp.get("process_name", "")
            except Exception:
                pass

            cur.execute(
                """INSERT OR IGNORE INTO fennix_clipboard_snapshots
                   (content, content_hash, mime_type, source_app, captured_ts)
                   VALUES (?, ?, 'text/plain', ?, ?)""",
                (content[:5000], content_hash, source_app, now),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass


class OpenFilesTracker(BaseService):
    name = "open_files_tracker"
    interval = 10

    def tick(self):
        try:
            proc = get_foreground_process()
            if not proc:
                return
            pid = proc.get("pid")
            if not pid:
                return

            open_files: list[str] = []
            proc_fd = Path("/proc") / str(pid) / "fd"
            if proc_fd.exists():
                for entry in proc_fd.iterdir():
                    try:
                        target = entry.resolve()
                        if target.is_file():
                            open_files.append(str(target))
                    except OSError:
                        continue

            if not open_files:
                return

            now = time.time()
            conn = _get_fauxnix_conn()
            cur = conn.cursor()
            snapshot = json.dumps({
                "pid": pid,
                "process_name": proc.get("process_name", ""),
                "open_files": open_files[:50],
            })
            cur.execute(
                "INSERT INTO fennix_context_snapshots (snapshot_type, snapshot_data, captured_ts) VALUES (?, ?, ?)",
                ("open_files", snapshot, now),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass


class SystemStateLogger(BaseService):
    name = "system_state_logger"
    interval = 300

    def tick(self):
        if config.system_snapshot_interval <= 0:
            return
        try:
            import psutil
            now = time.time()

            cpu = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")

            processes: list[str] = []
            for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
                try:
                    info = proc.info
                    if info["cpu_percent"] and info["cpu_percent"] > 1.0:
                        processes.append(f"{info['name']}:cpu={info['cpu_percent']:.1f}")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            snapshot = json.dumps({
                "cpu_percent": cpu,
                "mem_percent": mem.percent,
                "mem_used_gb": round(mem.used / (1024**3), 2),
                "mem_total_gb": round(mem.total / (1024**3), 2),
                "disk_percent": disk.percent,
                "disk_free_gb": round(disk.free / (1024**3), 2),
                "top_processes": processes[:20],
            })

            conn = _get_fauxnix_conn()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO fennix_context_snapshots (snapshot_type, snapshot_data, captured_ts) VALUES (?, ?, ?)",
                ("system_state", snapshot, now),
            )
            conn.commit()
            conn.close()

            self._prune_old_snapshots()
        except ImportError:
            pass
        except Exception:
            pass

    def _prune_old_snapshots(self):
        try:
            cutoff = time.time() - (86400 * 7)
            conn = _get_fauxnix_conn()
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM fennix_context_snapshots WHERE captured_ts < ?",
                (cutoff,),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass


class AutoIngestionScanner(BaseService):
    name = "auto_ingestion_scanner"
    interval = 600

    def tick(self):
        if not config.auto_ingest:
            return
        for watch_dir in config.ingest_dirs:
            if not watch_dir.exists():
                continue
            try:
                self._scan_directory(watch_dir)
            except Exception:
                pass

    def _scan_directory(self, directory: Path):
        max_size = config.max_ingest_file_mb * 1024 * 1024
        exclude = {"node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build", ".cache"}

        for entry in directory.rglob("*"):
            if entry.is_dir():
                continue
            if any(part in exclude for part in entry.parts):
                continue
            if not entry.is_file():
                continue
            if entry.suffix not in {
                ".txt", ".md", ".py", ".js", ".ts", ".rs", ".go",
                ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini",
                ".sh", ".bash", ".zsh", ".fish",
                ".html", ".css", ".scss",
                ".csv", ".log",
            }:
                continue
            try:
                if entry.stat().st_size > max_size:
                    continue
            except OSError:
                continue

            try:
                file_hash = self._hash_file(entry)
            except OSError:
                continue

            if self._already_ingested(file_hash):
                continue

            try:
                content = entry.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            if len(content.strip()) < 20:
                continue

            from fennix.ingestion.pipeline import ingest_content
            ingest_content(
                file_path=str(entry),
                file_hash=file_hash,
                content=content,
                source="auto",
            )

    def _hash_file(self, path: Path) -> str:
        from fauxnix_tools.utils import sha256_file
        return sha256_file(path)

    def _already_ingested(self, file_hash: str) -> bool:
        conn = _get_fauxnix_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) AS c FROM fennix_ingested_files WHERE file_hash = ?",
            (file_hash,),
        )
        row = cur.fetchone()
        conn.close()
        return row is not None and row["c"] > 0


class FileChangeReconciler(BaseService):
    name = "file_change_reconciler"
    interval = 120

    def tick(self):
        conn = _get_fauxnix_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, file_path, file_hash FROM fennix_ingested_files ORDER BY updated_ts DESC LIMIT 200"
        )
        rows = cur.fetchall()
        conn.close()

        for row in rows:
            path = Path(row["file_path"])
            if not path.exists():
                continue
            try:
                new_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                continue
            if new_hash == row["file_hash"]:
                continue

            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            from fennix.ingestion.pipeline import reingest_content
            reingest_content(
                ingested_file_id=row["id"],
                file_path=str(path),
                file_hash=new_hash,
                content=content,
            )


class ServicesManager:
    def __init__(self, thread_name: str = "workspace"):
        self._services: list[BaseService] = [
            ClipboardContextWatcher(),
            OpenFilesTracker(),
            SystemStateLogger(),
            AutoIngestionScanner(),
            FileChangeReconciler(),
            ContextStreamService(thread_name),
            GitActivityWatcher(thread_name),
            TerminalHistoryWatcher(thread_name),
            BrowserActivityWatcher(thread_name),
            ClipboardBridge(thread_name),
        ]

    def start(self):
        for svc in self._services:
            svc.start()

    def stop(self):
        for svc in self._services:
            svc.stop()

    def status(self) -> dict:
        return {
            "running": sum(1 for s in self._services if s._thread and s._thread.is_alive()),
            "services": [s.name for s in self._services],
        }

    def get_service(self, name: str) -> BaseService | None:
        for s in self._services:
            if s.name == name:
                return s
        return None


class ContextStreamService(BaseService):
    name = "context_streamer"
    interval = 5

    def __init__(self, thread_name: str = "workspace"):
        super().__init__()
        self._thread_name = thread_name
        self._streamer = None

    def start(self):
        from fennix.stream import ContextStreamer
        self._streamer = ContextStreamer(self._thread_name)
        super().start()

    def tick(self):
        if not self._streamer:
            return
        _stream_system_heartbeat(self._streamer)
        fg = get_foreground_process()
        if fg:
            app_name = fg.get("process_name", "")
            title = fg.get("window_title", "")
            if app_name:
                self._streamer.on_window_change(app_name, title)
        else:
            from fennix.stream import stream_event
            stream_event(
                self._thread_name, "heartbeat",
                {"status": "alive"},
            )


def _stream_system_heartbeat(streamer) -> None:
    try:
        import psutil
        from fennix.stream import stream_event
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory().percent
        stream_event(
            streamer._thread_name, "system",
            {"cpu": round(cpu, 1), "mem": round(mem, 1)},
        )
    except Exception:
        pass


class GitActivityWatcher(BaseService):
    name = "git_watcher"
    interval = 15

    def __init__(self, thread_name: str = "workspace"):
        super().__init__()
        self._thread_name = thread_name
        self._last_heads: dict[str, str] = {}

    def tick(self):
        from fennix.stream import stream_git_event
        for repo_path in self._find_repos():
            try:
                head_path = repo_path / ".git" / "HEAD"
                if not head_path.exists():
                    continue
                ref = head_path.read_text().strip()
                if ref.startswith("ref: "):
                    branch = ref[5:].split("/")[-1]
                    branch_ref = repo_path / ".git" / ref[5:]
                    if branch_ref.exists():
                        ref = branch_ref.read_text().strip()
                else:
                    branch = "HEAD"

                cache_key = str(repo_path)
                if self._last_heads.get(cache_key) != ref:
                    self._last_heads[cache_key] = ref
                    msg = self._last_commit_message(repo_path)
                    stream_git_event(
                        self._thread_name,
                        str(repo_path), branch, msg, "commit",
                    )
            except Exception:
                pass

    def _find_repos(self) -> list[Path]:
        repos: list[Path] = []
        for base in [Path("/shared"), Path("/home/chxk")]:
            if not base.exists():
                continue
            for git_dir in base.rglob(".git"):
                if git_dir.is_dir():
                    repos.append(git_dir.parent)
                    if len(repos) >= 20:
                        return repos
        return repos

    def _last_commit_message(self, repo_path: Path) -> str:
        try:
            import subprocess
            result = subprocess.run(
                ["git", "-C", str(repo_path), "log", "-1", "--format=%s"],
                capture_output=True, text=True, timeout=3,
            )
            return result.stdout.strip()[:100] if result.returncode == 0 else ""
        except Exception:
            return ""


class TerminalHistoryWatcher(BaseService):
    name = "terminal_watcher"
    interval = 10

    def __init__(self, thread_name: str = "workspace"):
        super().__init__()
        self._thread_name = thread_name
        self._last_sizes: dict[Path, int] = {}

    def tick(self):
        from fennix.stream import stream_terminal_event
        history_files = [
            Path.home() / ".bash_history",
            Path.home() / ".zsh_history",
            Path.home() / ".local/share/fish/fish_history",
        ]
        for hf in history_files:
            if not hf.exists():
                continue
            try:
                size = hf.stat().st_size
                last = self._last_sizes.get(hf, 0)
                if size > last:
                    with open(hf, "rb") as f:
                        f.seek(max(0, size - 2048))
                        tail = f.read().decode("utf-8", errors="replace")
                    lines = tail.strip().split("\n")
                    new_cmds = lines[-3:] if len(lines) > max(0, (size - last) // 50) else []
                    for cmd in new_cmds:
                        cmd = cmd.strip()
                        if cmd and not cmd.startswith("#"):
                            stream_terminal_event(
                                self._thread_name, cmd, str(Path.cwd()),
                            )
                    self._last_sizes[hf] = size
            except Exception:
                pass


class BrowserActivityWatcher(BaseService):
    name = "browser_watcher"
    interval = 10

    BROWSER_APPS = {"firefox", "chromium", "chrome", "brave", "vivaldi", "edge", "opera"}

    def __init__(self, thread_name: str = "workspace"):
        super().__init__()
        self._thread_name = thread_name

    def tick(self):
        from fennix.stream import stream_browser_event
        fg = get_foreground_process()
        if not fg:
            return
        proc_name = fg.get("process_name", "").lower()
        title = fg.get("window_title", "")

        is_browser = any(b in proc_name for b in self.BROWSER_APPS)
        if not is_browser:
            return

        domain = self._extract_domain(title)
        if domain:
            stream_browser_event(self._thread_name, domain, title)

    def _extract_domain(self, title: str) -> str:
        for sep in [" — ", " - ", " | ", " :: "]:
            if sep in title:
                parts = title.rsplit(sep, 1)
                candidate = parts[-1].strip()
                if candidate and len(candidate) < 100:
                    title = parts[0].strip()
                    if any(b in candidate.lower() for b in self.BROWSER_APPS):
                        return title[:80]
                    return candidate[:80]
        return title.split(" - ")[0][:80] if " - " in title else title[:80]

    def service_running(self, name: str) -> bool:
        svc = self.get_service(name)
        return bool(svc and svc._thread and svc._thread.is_alive())

    def toggle_service(self, name: str, enabled: bool):
        svc = self.get_service(name)
        if not svc:
            return
        if enabled:
            svc.start()
        else:
            svc.stop()


class ClipboardBridge(BaseService):
    name = "clipboard_bridge"
    interval = 3

    CLIPBOARD_DIR = "/shared/.clipboard"

    def __init__(self, thread_name: str = "workspace"):
        super().__init__()
        self._thread_name = thread_name
        self._last_content: str = ""
        self._last_external: dict[str, float] = {}

    def tick(self):
        try:
            import pyperclip
            Path(self.CLIPBOARD_DIR).mkdir(parents=True, exist_ok=True)

            current = pyperclip.paste() or ""
            clip_file = Path(self.CLIPBOARD_DIR) / f"{self._thread_name}.txt"

            if current and current != self._last_content:
                clip_file.write_text(current)
                self._last_content = current

            self._check_external_clips()
        except Exception:
            pass

    def _check_external_clips(self):
        try:
            import pyperclip
            clip_dir = Path(self.CLIPBOARD_DIR)
            if not clip_dir.exists():
                return

            latest_file = None
            latest_mtime = 0
            for f in clip_dir.glob("*.txt"):
                if f.name == f"{self._thread_name}.txt":
                    continue
                mtime = f.stat().st_mtime
                if mtime > latest_mtime and mtime > self._last_external.get(str(f), 0):
                    latest_file = f
                    latest_mtime = mtime

            if latest_file:
                content = latest_file.read_text()
                if content and content != self._last_content:
                    pyperclip.copy(content)
                    self._last_content = content
                    self._last_external[str(latest_file)] = latest_mtime
        except Exception:
            pass


def get_foreground_process() -> dict | None:
    try:
        from membrie.awareness.process import get_foreground_process as _membrie_fg
        return _membrie_fg()
    except ImportError:
        pass
    try:
        import subprocess
        result = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowpid", "getwindowname"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split("\n")
            if len(parts) >= 2:
                pid = int(parts[0])
                title = parts[1]
                try:
                    proc_path = Path("/proc") / str(pid) / "comm"
                    proc_name = proc_path.read_text().strip() if proc_path.exists() else ""
                except Exception:
                    proc_name = ""
                return {"pid": pid, "window_title": title, "process_name": proc_name}
    except Exception:
        pass
    return None
