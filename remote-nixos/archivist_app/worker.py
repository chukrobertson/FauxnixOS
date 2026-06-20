from pathlib import Path
import time
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver
from watchdog.events import FileSystemEventHandler
from app.indexer import index_file
from app.config import ARCHIVE_ROOT, ARCHIVE_INBOX


class ArchiveHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        try:
            index_file(Path(event.src_path))
        except Exception as e:
            print(f"[watcher] create error: {e}")

    def on_modified(self, event):
        if event.is_directory:
            return
        try:
            index_file(Path(event.src_path))
        except Exception as e:
            print(f"[watcher] modify error: {e}")


def run_watcher():
    if not ARCHIVE_ROOT.exists():
        print(f"[watcher] archive root not found: {ARCHIVE_ROOT}")
        return
    handler = ArchiveHandler()
    observer = None
    for observer_cls in (Observer, PollingObserver):
        candidate = observer_cls()
        candidate.schedule(handler, str(ARCHIVE_ROOT), recursive=True)
        if ARCHIVE_INBOX.exists() and ARCHIVE_INBOX.resolve(strict=False) != ARCHIVE_ROOT.resolve(strict=False):
            candidate.schedule(handler, str(ARCHIVE_INBOX), recursive=True)
        try:
            candidate.start()
            observer = candidate
            break
        except (PermissionError, OSError) as e:
            print(f"[watcher] {observer_cls.__name__} could not watch {ARCHIVE_ROOT}: {e}")
            try:
                candidate.stop()
                candidate.join(timeout=2)
            except RuntimeError:
                pass

    if observer is None:
        print("[watcher] live filesystem watching disabled; manual indexing and uploads still work.")
        return

    print(f"[watcher] watching: {ARCHIVE_ROOT}")
    try:
        while True:
            time.sleep(1)
    finally:
        observer.stop()
        observer.join()
